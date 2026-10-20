"""Engine contract the QGIS wizard relies on: stale-stage invalidation, failed status, ``check`` JSON."""
import json
from pathlib import Path

import pytest

from repeat_pump import cli
from repeat_pump.core.config import MissingParameters, load_config
from repeat_pump.core.pipeline import ReviewRequired, run_pipeline
from repeat_pump.core.requirements import check, required_by_stage
from tests.fixtures.synthetic import write_cfg

EXAMPLE = Path(__file__).parents[1] / "configs" / "example_khg.yaml"


def _state(ctx):
    return {int(k): v["status"] for k, v in ctx.state["stages"].items()}


def test_rerunning_a_stage_invalidates_later_stages(world):
    cfg, tmp = world
    c = load_config(write_cfg(tmp / "c.yaml", cfg))
    with pytest.raises(ReviewRequired):
        run_pipeline(c)
    with pytest.raises(ReviewRequired):
        run_pipeline(c, accept=[2])                        # stages 3-5 done, 6 awaits review
    ctx = run_pipeline(c, stop_after=3, resume_from=3)    # re-run stage 3 only
    assert _state(ctx) == {1: "done", 2: "done", 3: "done"}, "stages 4-6 must be dropped, not left 'done'"
    with pytest.raises(ReviewRequired):                    # a normal run now recomputes 4, 5 and 6
        run_pipeline(c, accept=[2])


def test_completed_stage_stores_a_fingerprint_that_changes_with_its_settings(world):
    cfg, tmp = world
    c = load_config(write_cfg(tmp / "c.yaml", cfg))
    with pytest.raises(ReviewRequired):
        run_pipeline(c)
    state = json.loads(next(tmp.rglob("run_state.json")).read_text())["stages"]
    now = {s["id"]: s["fingerprint"] for s in check(c)["stages"]}
    assert state["1"]["fingerprint"] == now[1] and state["2"]["fingerprint"] == now[2]
    cfg["topology"]["snap_tolerance_m"] = 3.5                        # a decision changed after the stage ran
    changed = {s["id"]: s["fingerprint"] for s in check(load_config(write_cfg(tmp / "c2.yaml", cfg)))["stages"]}
    assert changed[2] != state["2"]["fingerprint"] and changed[3] == now[3] and changed[1]["run"]["name"] == now[1]["run"]["name"]


def test_a_stage_is_not_invalidated_by_settings_only_later_stages_read(world):
    """Filling in pump settings (stage 10) after routing (stage 9) ran must not mark routing out of date."""
    cfg, tmp = world
    fp = lambda c, i: {s["id"]: s["fingerprint"] for s in check(load_config(write_cfg(tmp / f"{i}.yaml", c)))["stages"]}
    base = fp(cfg, "a")
    cfg["pumping"]["manning_n"] = 0.05                               # a stage 10 setting
    pump = fp(cfg, "b")
    assert pump[9] == base[9] and pump[10] != base[10] and pump[7] == base[7]
    cfg["pumping"]["uphill_penalty_lambda"] = 99                     # read by stage 9 (and stage 10 reads all of pumping)
    lam = fp(cfg, "c")
    assert lam[9] != base[9] and lam[10] != base[10]
    cfg["sekat"]["dA_m"] = 0.5                                       # stage 7 and stage 10 read it
    da = fp(cfg, "d")
    assert da[7] != base[7] and da[10] != lam[10] and da[9] == lam[9]


def test_rerun_drops_warnings_of_the_stage_and_later_ones(world):
    cfg, tmp = world
    c = load_config(write_cfg(tmp / "c.yaml", cfg))
    with pytest.raises(ReviewRequired):
        run_pipeline(c)
    p = next(tmp.rglob("run_state.json"))
    data = json.loads(p.read_text())
    data["warnings"] += ["Stage 2: 9 endpoint(s) snapped (tolerance 2.0 m)", "Stage 5: old", "ACCURACY: kept (stage 1)", "dtm covers only 84%"]
    p.write_text(json.dumps(data))
    with pytest.raises(ReviewRequired):
        run_pipeline(c, resume_from=2, stop_after=2)
    kept = json.loads(p.read_text())["warnings"]
    assert "Stage 2: 9 endpoint(s) snapped (tolerance 2.0 m)" not in kept and "Stage 5: old" not in kept
    assert "ACCURACY: kept (stage 1)" in kept and "dtm covers only 84%" in kept


def test_failed_stage_is_recorded(world):
    cfg, tmp = world
    cfg["hydro"]["breach_max_dist_cells"] = None
    c = load_config(write_cfg(tmp / "c.yaml", cfg))
    with pytest.raises(ReviewRequired):
        run_pipeline(c)
    with pytest.raises(MissingParameters):
        run_pipeline(c, accept=[2])
    state = json.loads(next(tmp.rglob("run_state.json")).read_text())["stages"]
    assert state["3"]["status"] == "failed" and "breach_max_dist_cells" in state["3"]["error"]


def test_check_on_example_config_lists_the_todo_keys():
    out = check(load_config(EXAMPLE))
    by = {s["id"]: s for s in out["stages"]}
    assert len(out["stages"]) == 11 and [s["id"] for s in out["stages"] if s["review"]] == [2, 6, 9]
    assert {"run.clip_margin_m", "inputs.dtm.vertical_rmse_m", "inputs.moisture.higher_is_wetter"} <= set(by[1]["missing"])
    assert by[1]["recommended_missing"] == ["run.vertical_datum", "inputs.rivers.vertical_datum"]
    assert by[2]["missing"] == ["topology.snap_tolerance_m"]
    assert "prioritise.criteria.burn_freq.weight" in by[6]["missing"] and "prioritise.upstream_buffer_m" in by[6]["missing"]
    assert "pumping.conveyance" in by[10]["missing"] and "pumping.manning_n" not in by[10]["missing"]


def test_check_on_complete_world_is_empty(world):
    cfg, tmp = world
    cfg["pumping"]["allow_gate_addition"] = True
    req = required_by_stage(load_config(write_cfg(tmp / "c.yaml", cfg)))
    assert all(v == [] for v in req.values()), req


def test_check_follows_conveyance_and_demand_mode(world):
    cfg, tmp = world
    cfg["pumping"].update(conveyance="pipe", demand_mode="specific_yield", hazen_williams_c=None, pipe_diameter_m=None)
    req = required_by_stage(load_config(write_cfg(tmp / "c.yaml", cfg)))[10]
    assert "pumping.hazen_williams_c" in req and "pumping.pipe_diameter_m" in req and "pumping.manning_n" not in req


def test_check_cli_prints_json(capsys):
    assert cli.main(["check", "--config", str(EXAMPLE)]) == 0
    assert json.loads(capsys.readouterr().out)["stages"][1]["name"] == "topology"
