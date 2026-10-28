"""Stage 11 (optional canal blocking optimisation, before the report of stage 12) on the synthetic world."""
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
    """The synthetic world after every stage (stage 11 skipped because it is off by default)."""
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
    return run_pipeline(load_config(write_cfg(tmp / "o.yaml", cfg)), resume_from=11, stop_after=12)     # the optimisation, then the report


def test_off_by_default_the_stage_is_skipped_and_asks_for_nothing(world11):
    cfg, tmp, ctx = world11
    assert ctx.state["stages"]["11"]["status"] == "skipped" and ctx.state["stages"]["12"]["status"] == "done"
    chk = next(s for s in check(load_config(write_cfg(tmp / "d.yaml", cfg)))["stages"] if s["id"] == 11)
    assert chk["id"] == 11 and chk["missing"] == [] and [n["key"] for n in chk["needs"]] == ["optimise.enabled"]
    assert not ctx.has_layer("sekat_optimised")


def test_enabled_without_values_lists_every_missing_decision_once(world11):
    with pytest.raises(MissingParameters) as e:
        stage12(world11, enabled=True)
    for k in ("optimise.n_blocks", "optimise.max_evaluations", "optimise.canal_drawdown_m"):
        assert k in str(e.value)
    assert "grid_m" not in str(e.value)                                   # the cheap objective needs no groundwater parameters
    with pytest.raises(MissingParameters, match="grid_m"):          # the tropical peat tables need no multiplier
        stage12(world11, **{**CHEAP, "objective": "pde"})


def test_check_lists_the_pde_decisions_only_when_the_pde_objective_is_chosen(world11):
    cfg, tmp, _ = world11
    def needs(**opt):
        c = copy.deepcopy(cfg); c["optimise"] = opt
        return {n["key"] for n in next(s for s in check(load_config(write_cfg(tmp / "n.yaml", c)))["stages"] if s["id"] == 11)["needs"]}
    assert needs(enabled=True) == {"optimise.enabled", "optimise.objective", "optimise.n_blocks", "optimise.max_evaluations", "optimise.canal_drawdown_m"}
    assert {"optimise.grid_m", "optimise.dry_days", "optimise.et_mm_day"} <= needs(enabled=True, objective="pde")
    assert "optimise.transmissivity_multiplier" not in needs(enabled=True, objective="pde")          # default peat table: tropical-small
    assert "optimise.transmissivity_multiplier" in needs(enabled=True, objective="pde", peat_table="urzainki2020")


def test_canal_rise_run_writes_the_alternative_plan_and_extends_the_report(world11):
    ctx = stage12(world11, **CHEAP)
    assert ctx.state["stages"]["11"]["status"] == "done"
    out = ctx.read_layer("sekat_optimised")
    assert int(out["selected_best"].sum()) == 1 and {"selected_ga", "selected_sa", "selected_greedy"} <= set(out.columns)
    qa = ctx.read_layer("qa_optimisation")
    assert {"ga", "sa", "greedy", "random_mean"} <= set(qa["method"])
    best = qa[qa["method"].isin(["ga", "sa", "greedy"])]["benefit"].max()
    assert best >= qa[qa["method"] == "random_mean"]["benefit"].iloc[0] - 1e-9
    rep = json.loads((ctx.out_dir / "run_report.json").read_text())
    assert rep["optimisation"]["blocks"] == 1 and "alternative plan" in rep["optimisation"]["note"].lower()
    assert "Canal blocking optimisation (Stage 11)" in (ctx.out_dir / "run_report.md").read_text()
    # the routing and pump stages were not touched
    assert ctx.state["stages"]["10"]["status"] == "done" and ctx.has_layer("pump_stations")


def test_rerunning_the_stage_replaces_the_report_section(world11):
    stage12(world11, **CHEAP)
    ctx = stage12(world11, **{**CHEAP, "seed": 5})
    md = (ctx.out_dir / "run_report.md").read_text()
    assert md.count("## Canal blocking optimisation (Stage 11)") == 1


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


def test_stage_7_balance_keeps_the_fewest_sekat_for_the_target_share(world11):
    cfg, tmp, ctx = world11
    head_rule = len(ctx.read_layer("sekat_proposed"))
    cfg = copy.deepcopy(cfg)
    cfg["sekat"].update(target_rise_share=0.6, balance_drawdown_m=1.0)
    c = run_pipeline(load_config(write_cfg(tmp / "b.yaml", cfg)), resume_from=7, stop_after=7)
    kept, low = c.read_layer("sekat_proposed"), c.read_layer("sekat_low_benefit")
    assert len(kept) + len(low) == head_rule and len(kept) >= 1
    assert kept["cum_share"].max() >= 0.6 - 1e-9
    assert (kept["benefit_rank"].max() < low["benefit_rank"].min()) if len(low) else True
    assert len(kept) == 1 or kept.sort_values("benefit_rank")["cum_share"].iloc[-2] < 0.6     # one fewer would miss the share
    assert c.report["sekat_balance"]["kept"] == len(kept)
    cfg["sekat"].pop("balance_drawdown_m")
    with pytest.raises(MissingParameters, match="balance_drawdown_m"):
        run_pipeline(load_config(write_cfg(tmp / "b2.yaml", cfg)), resume_from=7, stop_after=7)


def test_stage_7_budget_cap_keeps_at_most_max_blocks_best_first(world11):
    cfg, tmp, _ = world11
    cfg = copy.deepcopy(cfg)
    cfg["sekat"].update(max_blocks=1, balance_drawdown_m=1.0)
    c = run_pipeline(load_config(write_cfg(tmp / "cap.yaml", cfg)), resume_from=7, stop_after=7)
    kept = c.read_layer("sekat_proposed")
    assert len(kept) == 1 and int(kept["benefit_rank"].iloc[0]) == 1
    assert c.report["sekat_balance"]["max_blocks"] == 1


def test_a_tropical_table_needs_no_multiplier_and_the_bracket_scores_every_table(world11):
    pde = {k: v for k, v in PDE.items() if k != "transmissivity_multiplier"}
    with pytest.raises(MissingParameters, match="transmissivity_multiplier"):       # the boreal table in the bracket still needs it
        stage12(world11, **{**CHEAP, "objective": "pde", **pde, "peat_table": "tropical-small", "bracket_tables": ["urzainki2020"]})
    ctx = stage12(world11, **{**CHEAP, "objective": "pde", **pde, "peat_table": "tropical-small", "bracket_tables": ["tropical-large"]})
    b = json.loads((ctx.out_dir / "run_report.json").read_text())["optimisation"]["bracket"]
    assert list(b) == ["tropical-small", "tropical-large"] and all(v["transmissivity_multiplier"] == 1.0 for v in b.values())
    ctx = stage12(world11, **{**CHEAP, "objective": "screen_then_pde", **PDE, "peat_table": "tropical-small", "bracket_tables": ["urzainki2020"]})
    rep = json.loads((ctx.out_dir / "run_report.json").read_text())
    b = rep["optimisation"]["bracket"]
    assert b["tropical-small"]["transmissivity_multiplier"] == 1.0 and b["urzainki2020"]["transmissivity_multiplier"] == PDE["transmissivity_multiplier"]
    assert rep["optimisation"]["unit"] == "ha m of dry peat avoided"            # re-scored values, and the random baseline in the same unit
    assert "scored with other peat tables" in (ctx.out_dir / "run_report.md").read_text()
