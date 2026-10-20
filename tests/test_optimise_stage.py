"""Stage 12 (optional canal blocking optimisation) on the synthetic world."""
import copy
import json

import pytest

from repeat_pump.core.config import MissingParameters, load_config
from repeat_pump.core.pipeline import ReviewRequired, run_pipeline
from repeat_pump.core.requirements import check
from tests.fixtures.synthetic import build_world, write_cfg

CHEAP = dict(enabled=True, n_blocks=1, max_evaluations=40, canal_drawdown_m=1.0, algorithms=["ga", "sa", "greedy"], random_baseline_draws=4)
PDE = dict(grid_m=100, dry_days=3, et_mm_day=3.0, transmissivity_multiplier=150.0)


@pytest.fixture(scope="module")
def world11(tmp_path_factory):
    """The synthetic world after stages 1 to 11 (stage 12 skipped because it is off by default)."""
    tmp = tmp_path_factory.mktemp("opt")
    _, cfg = build_world(tmp)
    cfg["pumping"]["allow_gate_addition"] = True
    c = load_config(write_cfg(tmp / "c.yaml", cfg))
    for acc in ([], [2], [2, 6]):
        with pytest.raises(ReviewRequired):
            run_pipeline(c, accept=acc)
    ctx = run_pipeline(c, accept=[2, 6, 9])
    return cfg, tmp, ctx


def stage12(world11, **opt):
    cfg, tmp, _ = world11
    cfg = copy.deepcopy(cfg)
    cfg["optimise"] = opt
    return run_pipeline(load_config(write_cfg(tmp / "o.yaml", cfg)), resume_from=12, stop_after=12)


def test_off_by_default_the_stage_is_skipped_and_asks_for_nothing(world11):
    cfg, tmp, ctx = world11
    assert ctx.state["stages"]["12"]["status"] == "skipped"
    chk = check(load_config(write_cfg(tmp / "d.yaml", cfg)))["stages"][-1]
    assert chk["id"] == 12 and chk["missing"] == [] and [n["key"] for n in chk["needs"]] == ["optimise.enabled"]
    assert not ctx.has_layer("sekat_optimised")


def test_enabled_without_values_lists_every_missing_decision_once(world11):
    with pytest.raises(MissingParameters) as e:
        stage12(world11, enabled=True)
    for k in ("optimise.n_blocks", "optimise.max_evaluations", "optimise.canal_drawdown_m"):
        assert k in str(e.value)
    assert "grid_m" not in str(e.value)                                   # the cheap objective needs no groundwater parameters
    with pytest.raises(MissingParameters, match="transmissivity_multiplier"):
        stage12(world11, **{**CHEAP, "objective": "pde"})


def test_check_lists_the_pde_decisions_only_when_the_pde_objective_is_chosen(world11):
    cfg, tmp, _ = world11
    def needs(**opt):
        c = copy.deepcopy(cfg); c["optimise"] = opt
        return {n["key"] for n in check(load_config(write_cfg(tmp / "n.yaml", c)))["stages"][-1]["needs"]}
    assert needs(enabled=True) == {"optimise.enabled", "optimise.objective", "optimise.n_blocks", "optimise.max_evaluations", "optimise.canal_drawdown_m"}
    assert {"optimise.grid_m", "optimise.dry_days", "optimise.et_mm_day", "optimise.transmissivity_multiplier"} <= needs(enabled=True, objective="pde")


def test_canal_rise_run_writes_the_alternative_plan_and_extends_the_report(world11):
    ctx = stage12(world11, **CHEAP)
    assert ctx.state["stages"]["12"]["status"] == "done"
    out = ctx.read_layer("sekat_optimised")
    assert int(out["selected_best"].sum()) == 1 and {"selected_ga", "selected_sa", "selected_greedy"} <= set(out.columns)
    qa = ctx.read_layer("qa_optimisation")
    assert {"ga", "sa", "greedy", "random_mean"} <= set(qa["method"])
    best = qa[qa["method"].isin(["ga", "sa", "greedy"])]["benefit"].max()
    assert best >= qa[qa["method"] == "random_mean"]["benefit"].iloc[0] - 1e-9
    rep = json.loads((ctx.out_dir / "run_report.json").read_text())
    assert rep["optimisation"]["blocks"] == 1 and "alternative plan" in rep["optimisation"]["note"].lower()
    assert "Canal blocking optimisation (Stage 12)" in (ctx.out_dir / "run_report.md").read_text()
    # the routing and pump stages were not touched
    assert ctx.state["stages"]["10"]["status"] == "done" and ctx.has_layer("pump_stations")


def test_rerunning_the_stage_replaces_the_report_section(world11):
    stage12(world11, **CHEAP)
    ctx = stage12(world11, **{**CHEAP, "seed": 5})
    md = (ctx.out_dir / "run_report.md").read_text()
    assert md.count("## Canal blocking optimisation (Stage 12)") == 1


def test_pde_objective_gives_a_non_negative_benefit_and_a_baseline_volume(world11):
    ctx = stage12(world11, **{**CHEAP, **PDE, "objective": "pde", "algorithms": ["ga"], "max_evaluations": 6})
    rep = json.loads((ctx.out_dir / "run_report.json").read_text())["optimisation"]
    assert rep["baseline_dry_volume_ha_m"] > 0 and rep["best_benefit"] >= -1e-9 and "ha m" in rep["unit"]


def test_screen_then_pde_rescoring_runs(world11):
    ctx = stage12(world11, **{**CHEAP, **PDE, "objective": "screen_then_pde", "algorithms": ["sa"], "max_evaluations": 6, "random_baseline_draws": 2})
    qa = ctx.read_layer("qa_optimisation")
    assert "sa" in set(qa["method"]) and (qa["benefit"] >= -1e-9).all()


def test_candidates_that_cannot_raise_the_water_are_reported(world11):
    ctx = stage12(world11, **{**CHEAP, "canal_drawdown_m": 0.2})              # canal already within dA of the land
    assert any("cannot raise anything" in w for w in ctx.warnings)
