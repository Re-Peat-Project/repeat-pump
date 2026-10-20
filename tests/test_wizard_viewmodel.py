"""Wizard view-model and shared config builder: pure Python, no qgis (loaded by file path like test_plugin_runner)."""
import importlib.util
import json
import sys
from pathlib import Path


from repeat_pump.core.config import load_config
from repeat_pump.core.requirements import check
from tests.fixtures.synthetic import write_cfg

PLUGIN = Path(__file__).parents[1] / "qgis_plugin" / "repeat_pump_qgis"
EXAMPLE = Path(__file__).parents[1] / "configs" / "example_khg.yaml"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, PLUGIN / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


vm = _load("wizard_viewmodel", "wizard/viewmodel.py")
rc = _load("wizard_runconfig", "runconfig.py")
runner = _load("wizard_runner", "runner.py")


def model(state=None, running=None, cfg_path=EXAMPLE):
    return vm.WizardModel(check(load_config(cfg_path)), state or {"stages": {}, "warnings": [], "report": {}}, running)


def st(**by_stage):
    return {"stages": {k[1:]: {"status": v} for k, v in by_stage.items()}, "warnings": [], "report": {}}


# ---------------------------------------------------------------- statuses
def test_fresh_run_only_stage1_is_ready():
    m = model()
    assert [v.status for v in m.stages] == ["ready"] + ["locked"] * 10
    assert m.stage(2).sub == "Locked, review stage" and m.stage(3).sub == "Locked"


def test_stage_unlocks_only_after_previous_is_done():
    m = model(st(s1="done", s2="awaiting_review"))
    assert m.stage(2).status == "needs_review" and m.stage(3).status == "locked"
    m = model(st(s1="done", s2="done"))
    assert m.stage(3).status == "ready"


def test_running_stage_and_interrupted_run():
    s = {"stages": {"1": {"status": "done"}, "2": {"status": "running"}}, "warnings": [], "report": {}}
    assert model(s, running=2).stage(2).status == "running"
    interrupted = model(s, running=None).stage(2)
    assert interrupted.status == "failed" and "interrupted" in interrupted.error.lower()


def test_failed_stage_carries_the_engine_error():
    s = {"stages": {"1": {"status": "done"}, "2": {"status": "failed", "error": "boom"}}, "warnings": [], "report": {}}
    v = model(s).stage(2)
    assert v.status == "failed" and v.error == "boom"


def test_current_stage_prefers_review_then_first_unfinished():
    assert model().current == 1
    assert model(st(s1="done", s2="awaiting_review")).current == 2
    assert model(st(s1="done", s2="done", s3="done")).current == 4


# ---------------------------------------------------------------- required parameters
def test_run_is_blocked_while_required_values_are_empty():
    v = model().stage(1)                               # example config: clip margin, RMSE, moisture direction are null
    assert v.status == "ready" and not v.can_run and "empty" in v.blocking
    assert {"run.clip_margin_m", "inputs.dtm.vertical_rmse_m"} <= set(v.missing)


def test_run_enabled_when_nothing_is_missing(world):
    cfg, tmp = world
    cfg["pumping"]["allow_gate_addition"] = True
    m = model(cfg_path=write_cfg(tmp / "c.yaml", cfg))
    assert m.stage(1).can_run and m.stage(1).blocking == ""
    assert m.all_missing == []


def test_nothing_is_clickable_during_a_run():
    busy = model(st(s1="done", s2="awaiting_review"), running=3)
    assert not busy.stage(2).can_accept and not busy.stage(1).can_rerun and not busy.stage(1).can_run


def test_accept_and_rerun_available_on_complete_config(world):
    cfg, tmp = world
    cfg["pumping"]["allow_gate_addition"] = True
    p = write_cfg(tmp / "c.yaml", cfg)
    m = model(st(s1="done", s2="awaiting_review"), cfg_path=p)
    assert m.stage(2).can_accept and m.stage(2).can_rerun and not m.stage(2).can_run
    assert m.stage(1).can_rerun and not m.stage(1).can_accept


def test_fields_have_metadata_and_never_prefill():
    for key in ("pumping.pump_efficiency", "prioritise.criteria.burn_freq.weight", "prioritise.feasibility.concession_mode"):
        f = vm.field_for(key)
        assert f.label and f.kind in ("float", "enum")
    assert vm.field_for("pumping.conveyance").options == ("canal", "pipe")
    assert vm.field_for("prioritise.ahp_matrix").kind == "matrix"
    assert vm.field_for("some.unknown.key").kind == "text"


def test_every_key_the_engine_can_require_has_a_field():
    """Drift guard: a key listed by `repeat-pump check` must be editable (or explicitly a matrix)."""
    out = check(load_config(EXAMPLE))
    for s in out["stages"]:
        for key in s["missing"] + s["recommended_missing"]:
            assert vm.field_for(key).label != key or key.startswith("prioritise.criteria"), key


# ---------------------------------------------------------------- tiles and plans
def test_tiles_come_from_report_counts_and_flag_warnings():
    s = {"stages": {"1": {"status": "done"}, "2": {"status": "awaiting_review"}}, "warnings": ["w"],
         "report": {"counts": {"2": {"canals_in": 412, "canals_clean": 389, "dangles": 14, "snapped_gaps": 0}}}}
    v = model(s).stage(2)
    by = {t.label: t for t in v.tiles}
    assert by["Canal features in"].value == "412" and by["Dangles found"].warn and not by["Gaps snapped"].warn
    assert v.sub == "Needs your review" and v.review_hint


def test_tiles_empty_until_stage_has_run():
    assert model().stage(1).tiles == []


def test_plans_match_pipeline_semantics():
    assert vm.WizardModel.plan("run", 3) == vm.RunPlan(None, 3, (), False)
    assert vm.WizardModel.plan("accept", 2) == vm.RunPlan(None, 2, (2,), False)      # no resume: accept flips awaiting_review
    assert vm.WizardModel.plan("rerun", 1) == vm.RunPlan(1, 1, (), True)


def test_rerun_of_stage_one_passes_resume_flag(monkeypatch):
    seen = {}

    class P:
        stdout = iter(())
        def wait(self): return 0

    class Stream(list):
        def close(self): pass

    def popen(cmd, **kw):
        seen["cmd"] = cmd
        p = P(); p.stdout = Stream()
        return p
    monkeypatch.setattr(runner.subprocess, "Popen", popen)

    class Fb:
        def pushInfo(self, m): pass
        def isCanceled(self): return False
    runner.run_cli("py", "c.yaml", ".", 1, 1, [], Fb(), rerun=True)
    assert "--resume-from" in seen["cmd"] and seen["cmd"][seen["cmd"].index("--resume-from") + 1] == "1"
    runner.run_cli("py", "c.yaml", ".", 1, 11, [], Fb())
    assert "--resume-from" not in seen["cmd"]                       # provider behaviour unchanged


# ---------------------------------------------------------------- shared config builder
def test_build_run_config_overrides_and_params(tmp_path):
    cfg = tmp_path / "t.yaml"
    cfg.write_text(EXAMPLE.read_text(encoding="utf8"), encoding="utf8")
    out = rc.build_run_config(cfg, output_gpkg=str(tmp_path / "o.gpkg"), dtm="D:/x.tif", moisture="D:/m.tif", priority="D:/p.csv",
                              vectors={"canals": ("D:/c.gpkg", "kanal"), "burn_area": ("D:/b.shp", None)},
                              params={"topology.snap_tolerance_m": 2.5, "pumping.conveyance": "canal"})
    assert out["inputs"]["dtm"]["path"] == "D:/x.tif" and out["inputs"]["dtm"]["surface_type"] == "DTM"
    assert out["inputs"]["moisture"]["paths"] == ["D:/m.tif"] and out["inputs"]["subkhg_priority"] == {"path": "D:/p.csv"}
    assert out["inputs"]["canals"] == {"path": "D:/c.gpkg", "layer": "kanal"} and "layer" not in out["inputs"]["burn_area"]
    assert out["inputs"]["subkhg"]["path"].startswith(str(tmp_path))             # relative paths made absolute
    assert out["topology"]["snap_tolerance_m"] == 2.5 and out["pumping"]["conveyance"] == "canal"
    assert out["run"]["output_gpkg"] == str(tmp_path / "o.gpkg")
    load_config(rc.write_run_config(out, tmp_path / "run" / "run_config.yaml"))   # still a valid engine config


def test_dotted_helpers():
    d = {}
    rc.set_dotted(d, "prioritise.criteria.burn_freq.weight", 0.3)
    assert d == {"prioritise": {"criteria": {"burn_freq": {"weight": 0.3}}}} and rc.get_dotted(d, "prioritise.criteria.burn_freq.weight") == 0.3
    assert rc.get_dotted(d, "nope.x") is None


def test_load_state_missing_or_corrupt(tmp_path):
    g = tmp_path / "o.gpkg"
    assert vm.load_state(g)["stages"] == {}
    (tmp_path / "run_state.json").write_text("{not json")
    assert vm.load_state(g)["stages"] == {}
    (tmp_path / "run_state.json").write_text(json.dumps({"stages": {"1": {"status": "done"}}}))
    assert vm.load_state(g)["stages"]["1"]["status"] == "done"
