"""Manual changes to the proposed sekat (``sekat.edits``): delete a proposal, add one the head rule did not."""
import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from repeat_pump.core import io, profiles, segments, sekat, topology
from repeat_pump.core.config import Config, InputError
from repeat_pump.core.requirements import fingerprint, sekat_edits_digest
from tests.conftest import make_ctx
from tests.fixtures.synthetic import CRS, X0, Y0

CANAL = LineString([(X0, Y0 + 500), (X0 + 1800, Y0 + 500)])


def run(world, rows=None, **extra):
    cfg, tmp = world
    cfg["inputs"]["sekat_existing"] = None
    cfg["sekat"].update(extra)
    if rows is not None:
        gpd.GeoDataFrame({"action": [a for a, _ in rows]}, geometry=[g for _, g in rows], crs=CRS).to_file(tmp / "sekat_edits.gpkg", layer="sekat_edits", driver="GPKG")
        cfg["sekat"]["edits"] = {"path": str(tmp / "sekat_edits.gpkg"), "layer": "sekat_edits"}
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    ctx.write_layer("inputs_clipped_canals", gpd.GeoDataFrame({"canal_class": ["primer"], "depth_m": 2.0, "width_m": 4.0}, geometry=[CANAL], crs=CRS), "1")
    topology.run(ctx); segments.run(ctx); profiles.run(ctx); sekat.run(ctx)
    return ctx


def test_without_edits_nothing_changes_and_no_sekat_is_manual(world):
    ctx = run(world)
    p = ctx.read_layer("sekat_proposed")
    assert len(p) == 4 and not p.manual.any() and "sekat_edits" not in ctx.report


def test_delete_drops_the_nearest_proposal_and_respaces_the_rest(world):
    base = run(world).read_layer("sekat_proposed").sort_values("dist_down_m")
    victim = base.iloc[1].geometry
    ctx = run(world, [("delete", Point(victim.x + 3, victim.y + 4))])               # 5 m off, within the 10 m snap tolerance
    p = ctx.read_layer("sekat_proposed").sort_values("dist_down_m")
    assert len(p) == 3 and ctx.report["sekat_edits"] == {"deleted": 1, "added": 0, "unmatched_deletes": 0, "unsnapped_adds": 0}
    assert all(abs(g.distance(victim)) > 1 for g in p.geometry)
    gaps = p.dist_down_m.diff().fillna(p.dist_down_m)
    assert (p.js_m.round(6) == gaps.round(6)).all()                                 # spacing describes the final layout: the next one now spans two steps
    assert p.js_m.iloc[1] > base.js_m.iloc[1] * 1.9


def test_add_snaps_to_the_canal_and_is_marked_manual(world):
    ctx = run(world, [("add", Point(X0 + 650, Y0 + 507))])                         # 7 m north of the canal
    p = ctx.read_layer("sekat_proposed")
    m = p[p.manual]
    assert len(p) == 5 and len(m) == 1 and m.sekat_pro_id.iloc[0].startswith("M") and abs(m.geometry.iloc[0].y - (Y0 + 500)) < 1e-6
    assert abs(m.geometry.iloc[0].x - (X0 + 650)) < 1e-6 and m.z_land_m.notna().all() and m.ts_m.iloc[0] == m.ts_m.iloc[0]
    assert ctx.report["sekat_edits"]["added"] == 1 and ctx.read_layer("canals_clean").n_proposed.iloc[0] == 5
    assert abs(m.js_m.iloc[0] - (m.dist_down_m.iloc[0] - p[~p.manual & (p.dist_down_m < m.dist_down_m.iloc[0] - 1e-6)].dist_down_m.max())) < 1e-6


def test_unmatched_edits_are_warned_about_not_silently_dropped(world):
    ctx = run(world, [("delete", Point(X0 + 5000, Y0)), ("add", Point(X0 + 650, Y0 + 900))])
    assert ctx.report["sekat_edits"] == {"deleted": 0, "added": 0, "unmatched_deletes": 1, "unsnapped_adds": 1}
    assert len(ctx.read_layer("sekat_proposed")) == 4
    assert any("matched no proposed sekat" in w for w in ctx.warnings) and any("more than" in w and "skipped" in w for w in ctx.warnings)


def test_a_delete_never_removes_a_sekat_the_same_file_adds(world):
    spot = Point(X0 + 650, Y0 + 500)
    ctx = run(world, [("add", spot), ("delete", spot)])                             # deletes are matched to the computed proposals first
    assert ctx.read_layer("sekat_proposed").manual.sum() == 1 and ctx.report["sekat_edits"]["unmatched_deletes"] == 1


def test_bad_edits_files_fail_clearly(world):
    with pytest.raises(InputError, match="unknown action"):
        run(world, [("move", Point(X0, Y0))])
    cfg, tmp = world
    gpd.GeoDataFrame({"action": ["add"]}, geometry=[LineString([(X0, Y0), (X0 + 5, Y0)])], crs=CRS).to_file(tmp / "bad.gpkg", driver="GPKG")
    cfg["sekat"]["edits"] = {"path": str(tmp / "bad.gpkg")}
    cfg["inputs"]["sekat_existing"] = None
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    ctx.write_layer("inputs_clipped_canals", gpd.GeoDataFrame({"canal_class": ["primer"], "depth_m": 2.0, "width_m": 4.0}, geometry=[CANAL], crs=CRS), "1")
    topology.run(ctx); segments.run(ctx); profiles.run(ctx)
    with pytest.raises(InputError, match="points"):
        sekat.run(ctx)


def test_fingerprint_of_stage_7_follows_the_edits_content_and_stage_1_does_not(world, tmp_path):
    cfg, tmp = world
    assert sekat_edits_digest(Config.model_validate(cfg)) is None
    gpd.GeoDataFrame({"action": ["add"]}, geometry=[Point(X0, Y0)], crs=CRS).to_file(tmp / "e.gpkg", layer="sekat_edits", driver="GPKG")
    cfg["sekat"]["edits"] = {"path": str(tmp / "e.gpkg"), "layer": "sekat_edits"}
    one = fingerprint(Config.model_validate(cfg), 7)
    assert one["sekat_edits_digest"] and "sekat_edits_digest" not in fingerprint(Config.model_validate(cfg), 1)
    gpd.GeoDataFrame({"action": ["add", "delete"]}, geometry=[Point(X0, Y0), Point(X0 + 5, Y0)], crs=CRS).to_file(tmp / "e.gpkg", layer="sekat_edits", driver="GPKG")
    assert fingerprint(Config.model_validate(cfg), 7) != one
    assert fingerprint(Config.model_validate(cfg), 1) == fingerprint(Config.model_validate({**cfg, "sekat": {**cfg["sekat"], "edits": None}}), 1)   # stage 1 is untouched
