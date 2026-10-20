"""The priority table (neraca air + sub-KHG prioritisation) is optional: neutral fallbacks, nothing invented."""
import json

import pytest

from repeat_pump.core import io
from repeat_pump.core.config import MissingParameters, load_config
from repeat_pump.core.pipeline import ReviewRequired, run_pipeline
from repeat_pump.core.requirements import check
from tests.conftest import make_ctx
from tests.fixtures.synthetic import write_cfg


def _no_table(cfg, **selection):
    cfg["inputs"].pop("subkhg_priority")
    cfg["run"]["subkhg_selection"] = selection or {"mode": "top_n", "n": 1}
    return cfg


def _selected(ctx):
    return ctx.read_layer("subkhg_selected")


def test_without_a_table_top_n_falls_back_to_every_subkhg_with_equal_priority(world):
    cfg, _ = world
    ctx = make_ctx(_no_table(cfg))
    io.run_stage1(ctx)
    sel = _selected(ctx)
    assert sorted(sel["subkhg_id"]) == ["A", "B"]
    assert (sel["priority_rank"] == 1.0).all() and (sel["priority_weight"] == 0.5).all()      # equal distribution
    assert ctx.report["validation"]["priority_source"] == "equal" and ctx.report["validation"]["demand_source"] == "specific_yield"
    assert any("No priority ranking available" in w for w in ctx.warnings)


def test_without_a_table_ids_mode_selects_exactly_those(world):
    cfg, _ = world
    ctx = make_ctx(_no_table(cfg, mode="ids", ids=["A"]))
    io.run_stage1(ctx)
    sel = _selected(ctx)
    assert list(sel["subkhg_id"]) == ["A"] and sel["priority_weight"].iloc[0] == 1.0


def test_all_mode_selects_every_subkhg(world):
    cfg, _ = world
    cfg["run"]["subkhg_selection"] = {"mode": "all"}
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    assert sorted(_selected(ctx)["subkhg_id"]) == ["A", "B"] and ctx.report["validation"]["priority_source"] == "table"


def test_unknown_id_is_still_an_error_without_a_table(world):
    cfg, _ = world
    with pytest.raises(Exception, match="not in subkhg layer"):
        io.run_stage1(make_ctx(_no_table(cfg, mode="ids", ids=["Z"])))


def test_a_table_with_only_ids_degrades_column_by_column(world, tmp_path):
    cfg, tmp = world
    (tmp / "prio.csv").write_text("subkhg_id\nA\nB\n")
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    assert sorted(_selected(ctx)["subkhg_id"]) == ["A", "B"]
    for col in ("priority_rank", "deficit_mm", "design_period_days"):
        assert any(f"no '{col}' column" in w for w in ctx.warnings), col
    assert ctx.report["validation"]["demand_source"] == "specific_yield"


def test_a_full_table_behaves_as_before(world):
    cfg, _ = world
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    sel = _selected(ctx)
    assert list(sel["subkhg_id"]) == ["A"] and sel["priority_rank"].iloc[0] == 1
    assert ctx.report["validation"]["priority_source"] == "table" and ctx.report["validation"]["demand_source"] == "deficit_table"
    assert not any("No priority ranking" in w for w in ctx.warnings)


def test_check_asks_for_demand_decisions_only_when_there_is_no_deficit(world):
    cfg, tmp = world
    full = {s["id"]: s["missing"] for s in check(load_config(write_cfg(tmp / "a.yaml", dict(cfg))))["stages"]}
    assert "pumping.specific_yield" not in full[10] and "pumping.design_period_days" not in full[10]
    no = _no_table(json.loads(json.dumps(cfg)))
    for k in ("specific_yield", "water_table_rise_m", "design_period_days"):
        no["pumping"].pop(k, None)
    miss = {s["id"]: s["missing"] for s in check(load_config(write_cfg(tmp / "b.yaml", no)))["stages"]}
    assert {"pumping.specific_yield", "pumping.water_table_rise_m", "pumping.design_period_days"} <= set(miss[10])


def test_full_run_without_a_table_needs_specific_yield_and_a_design_period(world):
    cfg, tmp = world
    cfg["pumping"]["allow_gate_addition"] = True
    _no_table(cfg, mode="ids", ids=["A"])
    c = load_config(write_cfg(tmp / "c.yaml", cfg))
    with pytest.raises(ReviewRequired):
        run_pipeline(c)
    with pytest.raises(ReviewRequired):
        run_pipeline(c, accept=[2])
    with pytest.raises(ReviewRequired):
        run_pipeline(c, accept=[2, 6])
    with pytest.raises(MissingParameters, match="design_period_days") as e:              # nothing is invented for the human
        run_pipeline(c, accept=[2, 6, 9])
    assert "specific_yield" in str(e.value) and "water_table_rise_m" in str(e.value)

    cfg["pumping"].update(specific_yield=0.2, water_table_rise_m=0.3, design_period_days=90)
    c2 = load_config(write_cfg(tmp / "c.yaml", cfg))
    ctx = run_pipeline(c2, accept=[2, 6, 9])
    st = ctx.read_layer("pump_stations")
    assert len(st) >= 1 and (st["q_m3s"] > 0).all()
    assert any("no water deficit" in w for w in ctx.warnings)
    rep = json.loads((ctx.out_dir / "run_report.json").read_text())
    assert rep["validation"]["priority_source"] == "equal"


def test_unit_id_is_accepted_for_subkhg_id_in_the_layer_and_the_table(world):
    """The RE-PEAT delineation and prioritisation write `unit_id`; the module works on `subkhg_id` internally."""
    import geopandas as gpd
    import pandas as pd
    cfg, tmp = world
    gpd.read_file(tmp / "subkhg.gpkg").rename(columns={"subkhg_id": "unit_id"}).to_file(tmp / "subkhg.gpkg", driver="GPKG")
    pd.read_csv(tmp / "prio.csv").rename(columns={"subkhg_id": "unit_id"}).to_csv(tmp / "prio.csv", index=False)
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    sel = _selected(ctx)
    assert list(sel["subkhg_id"]) == ["A"] and sel["priority_rank"].iloc[0] == 1
    assert ctx.report["validation"]["priority_source"] == "table" and ctx.report["validation"]["demand_source"] == "deficit_table"
