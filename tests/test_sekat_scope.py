"""Sekat scope (A3): every proposed sekat is labelled target / route / other once the routes are known, and pumping.sekat_scope
decides which are in the plan. The gates on the pump routes stay in the plan with either setting."""
import pytest

from repeat_pump.core import hydro, io, network, prioritise, profiles, routing, segments, sekat, topology
from repeat_pump.core.config import Config
from repeat_pump.core.requirements import fingerprint
from tests.conftest import make_ctx

STAGES = (io.run_stage1, topology.run, hydro.run, segments.run, profiles.run, prioritise.run, sekat.run, network.run, routing.run)


def _run(cfg):
    ctx = make_ctx(cfg)
    for f in STAGES:
        f(ctx)
    return ctx


@pytest.fixture
def dense(world):
    """Small head step, so the synthetic canals carry several sekat; the existing sekat get gates so the routes are not blocked."""
    import geopandas as gpd
    from tests.fixtures.synthetic import CRS, X0, Y0
    cfg, tmp = world
    gpd.GeoDataFrame({"sekat_id": ["E1", "E2"], "has_gate": [True, True]}, geometry=gpd.points_from_xy([X0 + 300, X0 + 1000], [Y0 + 503, Y0 + 497]),
                     crs=CRS).to_file(tmp / "sekat.gpkg", driver="GPKG")
    cfg["sekat"]["dA_m"] = 0.1
    return cfg


def test_every_proposed_sekat_gets_one_label_and_all_are_planned_by_default(dense):
    ctx = _run(dense)
    pr, sc = ctx.read_layer("sekat_proposed"), ctx.read_layer("sekat_scope")
    assert len(pr) > 0 and sorted(sc["sekat_pro_id"]) == sorted(pr["sekat_pro_id"])
    assert set(sc["scope"]) <= {"target", "route", "other"} and sc["planned"].astype(bool).all()
    c = ctx.report["counts"]["9"]
    assert c["sekat_target"] + c["sekat_route"] + c["sekat_other"] == len(pr) == c["sekat_planned"]


def test_labels_follow_the_selected_segments_and_the_routes(dense):
    ctx = _run(dense)
    sc = ctx.read_layer("sekat_scope")
    served = {s for t in ctx.read_layer("pump_targets")["seg_ids"] for s in str(t).split(";") if s}
    routes = ctx.read_layer("pump_routes").geometry.union_all()
    assert {"target", "route"} <= set(sc["scope"])            # the fixture exercises both labels
    for _, r in sc.iterrows():
        if r["scope"] == "target":
            assert str(r["seg_id"]) in served
        elif r["scope"] == "route":
            assert str(r["seg_id"]) not in served and r.geometry.distance(routes) <= routing.SCOPE_TOL_M
        else:
            assert str(r["seg_id"]) not in served and r.geometry.distance(routes) > routing.SCOPE_TOL_M


def test_selected_scope_keeps_targets_and_route_gates_only(dense):
    dense["pumping"]["sekat_scope"] = "selected"
    ctx = _run(dense)
    sc = ctx.read_layer("sekat_scope")
    assert (sc["planned"].astype(bool) == (sc["scope"] != "other")).all()
    assert ctx.report["sekat_scope"]["planned"] == ctx.report["counts"]["9"]["sekat_planned"] == int((sc["scope"] != "other").sum())


def test_a_target_without_sekat_is_warned_about(world):
    cfg, _ = world
    cfg["sekat"]["dA_m"] = 50.0                          # the land never rises this much: no sekat anywhere
    ctx = _run(cfg)
    assert len(ctx.read_layer("pump_targets")) >= 1
    assert any("have no proposed sekat on their selected canals" in w for w in ctx.warnings)
    assert ctx.report["counts"]["9"]["sekat_planned"] == 0


def test_the_scope_setting_makes_stage_9_out_of_date_not_stage_7(world):
    cfg, _ = world
    before = {s: fingerprint(Config.model_validate(cfg), s) for s in (7, 9)}
    cfg["pumping"]["sekat_scope"] = "selected"
    after = {s: fingerprint(Config.model_validate(cfg), s) for s in (7, 9)}
    assert before[7] == after[7] and before[9] != after[9]
