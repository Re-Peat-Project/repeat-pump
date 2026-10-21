"""Manual water sources and routing targets (``pumping.route_edits``): graph cuts, deletes, replacement of computed targets."""
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString

from repeat_pump.core import network
from tests.fixtures.synthetic import CRS


def tiny():
    """One canal of 1000 m cut into two 500 m segments, land rising 0.1 m per 100 m."""
    g1, g2 = LineString([(0, 0), (500, 0)]), LineString([(500, 0), (1000, 0)])
    segs = gpd.GeoDataFrame({"seg_id": ["S1", "S2"], "canal_id": ["C", "C"], "chain_start_m": [0.0, 500.0], "chain_end_m": [500.0, 1000.0],
                             "selected": [False, True], "width_m": 4.0, "depth_m": 2.0}, geometry=[g1, g2], crs=CRS)
    st = np.arange(0, 1001, 50.0)
    prof = pd.DataFrame({"canal_id": "C", "station_m": st, "z_land_m": 2 + st * 0.001})
    return segs, prof


@pytest.mark.parametrize("chainage", [0.0, 500.0, 1000.0, 250.0])
def test_a_cut_keeps_its_kind_and_attributes_at_canal_ends_segment_boundaries_and_inside(chainage):
    """Manual points often snap exactly to an end or a boundary: the node must still carry what the cut says."""
    segs, prof = tiny()
    G, _ids = network.build_graph(segs, prof, [dict(canal_id="C", chainage_m=chainage, kind="manual_target", attrs=dict(manual=True))])
    nodes = [d for _, d in G.nodes(data=True) if "manual_target" in d["kinds"]]
    assert len(nodes) == 1 and nodes[0]["manual"] is True and abs(nodes[0]["x"] - chainage) < 1e-3


def test_two_cuts_at_one_place_merge_into_one_node():
    segs, prof = tiny()
    cuts = [dict(canal_id="C", chainage_m=500.0, kind="river", attrs=dict(perennial=True)), dict(canal_id="C", chainage_m=500.0, kind="manual_target", attrs={})]
    G, _ = network.build_graph(segs, prof, cuts)
    both = [d for _, d in G.nodes(data=True) if {"river", "manual_target"} <= set(d["kinds"])]
    assert len(both) == 1


# ----------------------------------------------------------------------------- the stages, on the synthetic world
from shapely.geometry import Point  # noqa: E402

from repeat_pump.core import hydro, io, prioritise, profiles, pumps, routing, segments, sekat, topology  # noqa: E402
from repeat_pump.core.config import Config, NeedsHuman  # noqa: E402
from repeat_pump.core.requirements import fingerprint, needs_by_stage, route_edits_digest  # noqa: E402
from tests.conftest import make_ctx  # noqa: E402
from tests.fixtures.synthetic import X0, Y0  # noqa: E402

STAGES = (io.run_stage1, topology.run, hydro.run, segments.run, profiles.run, prioritise.run, sekat.run, network.run, routing.run, pumps.run)


def write_edits(tmp, rows):
    """rows: (action, kind, x, y[, z_src_m])"""
    gpd.GeoDataFrame({"action": [r[0] for r in rows], "kind": [r[1] for r in rows], "z_src_m": [r[4] if len(r) > 4 else np.nan for r in rows]},
                     geometry=[Point(r[2], r[3]) for r in rows], crs=CRS).to_file(tmp / "route_edits.gpkg", layer="route_edits", driver="GPKG")
    return {"path": str(tmp / "route_edits.gpkg"), "layer": "route_edits"}


def run_to(world, rows=None, last=10, mutate=None):
    cfg, tmp = world
    cfg["pumping"]["allow_gate_addition"] = True
    if rows is not None:
        cfg["pumping"]["route_edits"] = write_edits(tmp, rows)
    if mutate:
        mutate(cfg)
    ctx = make_ctx(cfg)
    for f in STAGES[:last]:
        f(ctx)
    return ctx


EAST_SELECTED = (X0 + 1200, Y0 + 500)          # on C00003_001, a selected segment
WEST_UNSELECTED = (X0 + 450, Y0 + 500)         # on C00001_001, not selected
RIVER_POINT = (X0 + 20, Y0 + 500)              # where the river meets the canal


def test_without_edits_nothing_changes(world):
    ctx = run_to(world)
    t, s = ctx.read_layer("pump_targets"), ctx.read_layer("pump_sources")
    assert list(t.target_id) == ["T001"] and not t.manual.any() and list(s.status) == ["ok"] and "route_edits" not in ctx.report


def test_a_manual_source_makes_routes_possible_where_there_is_no_river(world):
    no_river = lambda cfg: cfg["inputs"].pop("rivers", None)
    with pytest.raises(RuntimeError, match="no usable water source"):
        run_to(world, None, 9, no_river)
    ctx = run_to(world, [("add", "source", X0 + 100, Y0 + 507, 2.0)], 10, no_river)         # 7 m off the canal: snapped onto it
    s = ctx.read_layer("pump_sources")
    assert list(s.status) == ["manual"] and s.manual.all() and s.z_src_m.iloc[0] == 2.0 and abs(s.geometry.iloc[0].y - (Y0 + 500)) < 1e-6
    assert len(ctx.read_layer("pump_routes")) == 1 and ctx.report["route_edits"]["sources_added"] == 1


def test_a_manual_source_without_a_level_stops_stage_10_not_before(world):
    no_river = lambda cfg: cfg["inputs"].pop("rivers", None)
    ctx = run_to(world, [("add", "source", X0 + 100, Y0 + 500)], 9, no_river)               # routing works, the level is simply unknown
    assert len(ctx.read_layer("pump_routes")) == 1
    with pytest.raises(NeedsHuman, match="water level of source"):
        pumps.run(ctx)


def test_a_source_level_without_a_datum_stops_stage_8(world):
    def m(cfg):
        cfg["inputs"].pop("rivers", None)
        cfg["run"]["vertical_datum"] = None
    with pytest.raises(NeedsHuman, match="vertical datum"):
        run_to(world, [("add", "source", X0 + 100, Y0 + 500, 2.0)], 8, m)


def test_excluding_the_only_source_is_a_clear_error_and_stays_visible(world):
    with pytest.raises(RuntimeError, match="route edits excluded 1 source"):
        run_to(world, [("delete", "source", *RIVER_POINT)], 9)
    cfg, _ = world
    ctx = make_ctx(cfg)                                                                      # the layer was written before the error
    assert list(ctx.read_layer("pump_sources").status) == ["excluded_by_user"]


def test_excluding_the_river_source_leaves_the_manual_one(world):
    ctx = run_to(world, [("delete", "source", *RIVER_POINT), ("add", "source", X0 + 100, Y0 + 500, 2.0)], 9)
    s = ctx.read_layer("pump_sources").sort_values("status")
    assert list(s.status) == ["excluded_by_user", "manual"] and ctx.report["route_edits"]["sources_excluded_nodes"] == 1
    assert len(ctx.read_layer("pump_routes")) == 1


def test_a_manual_target_on_a_selected_cluster_replaces_the_computed_one_without_doubling_demand(world):
    base = run_to(world)
    ctx = run_to(world, [("add", "target", *EAST_SELECTED)])
    t = ctx.read_layer("pump_targets")
    assert list(t.target_id) == ["M001"] and t.manual.all() and t.seg_ids.iloc[0] == base.read_layer("pump_targets").seg_ids.iloc[0]
    assert abs(ctx.read_layer("pump_targets").geometry.iloc[0].x - EAST_SELECTED[0]) < 1e-6
    a_base, a_new = base.read_layer("pump_routes").a_served_ha.sum(), ctx.read_layer("pump_routes").a_served_ha.sum()
    assert abs(a_base - a_new) < 1e-9                                                       # the same segments are served once, not twice


def test_a_manual_target_on_an_unselected_segment_serves_only_that_segment_and_warns(world):
    ctx = run_to(world, [("add", "target", *WEST_UNSELECTED), ("delete", "target", X0 + 1800, Y0 + 500)])
    t = ctx.read_layer("pump_targets")
    assert list(t.target_id) == ["M001"] and t.seg_ids.iloc[0] == "C00001_001"
    rep = ctx.report["route_edits"]
    assert rep["targets_removed"] == 1 and rep["selected_segments_no_longer_served"] == 2
    assert any("no longer served" in w for w in ctx.warnings) and any("not on a selected segment" in w for w in ctx.warnings)


def test_removing_every_target_is_a_clear_error_and_an_unmatched_delete_warns(world):
    with pytest.raises(RuntimeError, match="removed every computed target"):
        run_to(world, [("delete", "target", X0 + 1800, Y0 + 500)], 9)
    ctx = run_to(world, [("delete", "target", X0 + 5, Y0 + 5)], 9)
    assert any("no computed target lies within" in w for w in ctx.warnings) and list(ctx.read_layer("pump_targets").target_id) == ["T001"]


def test_adds_far_from_every_canal_are_skipped_with_a_warning(world):
    ctx = run_to(world, [("add", "target", X0 + 1200, Y0 + 900), ("add", "source", X0 + 100, Y0 + 900, 2.0)], 9)
    assert ctx.report["route_edits"]["adds_skipped"] == 2 and any("were skipped" in w for w in ctx.warnings)


def test_bad_files_fail_clearly(world):
    cfg, tmp = world
    gpd.GeoDataFrame({"action": ["add"], "kind": ["pond"]}, geometry=[Point(X0, Y0)], crs=CRS).to_file(tmp / "bad.gpkg", driver="GPKG")
    with pytest.raises(Exception, match="unknown kind"):
        run_to(world, None, 8, lambda c: c["pumping"].update(route_edits={"path": str(tmp / "bad.gpkg")}))


def test_stage_8_fingerprint_and_requirements_follow_the_edits(world):
    cfg, tmp = world
    c0 = Config.model_validate(cfg)
    assert route_edits_digest(c0) is None and needs_by_stage(c0)[8] == []
    cfg["pumping"]["route_edits"] = write_edits(tmp, [("add", "source", X0 + 100, Y0 + 500, 2.0)])
    c1 = Config.model_validate(cfg)
    assert needs_by_stage(c1)[8] == ["sekat.snap_tolerance_m", "run.vertical_datum"]          # a level needs the DTM's datum
    one = fingerprint(c1, 8)
    assert one["route_edits_digest"] and "route_edits_digest" not in fingerprint(c1, 7)
    cfg["pumping"]["route_edits"] = write_edits(tmp, [("add", "source", X0 + 100, Y0 + 500)])
    c2 = Config.model_validate(cfg)
    assert needs_by_stage(c2)[8] == ["sekat.snap_tolerance_m"] and fingerprint(c2, 8) != one


def test_deleting_and_replacing_the_same_target_is_not_reported_as_unmatched(world):
    ctx = run_to(world, [("add", "target", *EAST_SELECTED), ("delete", "target", X0 + 1800, Y0 + 500)], 9)
    assert list(ctx.read_layer("pump_targets").target_id) == ["M001"] and not any("no computed target lies within" in w for w in ctx.warnings)
