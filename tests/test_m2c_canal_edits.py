import geopandas as gpd
import pytest
from shapely.geometry import LineString

from repeat_pump.core import io, topology
from repeat_pump.core.config import InputError
from tests.conftest import make_ctx
from tests.fixtures.synthetic import CRS, X0, Y0


def _edits(tmp, rows):
    gpd.GeoDataFrame({"action": [a for a, _ in rows]}, geometry=[g for _, g in rows], crs=CRS).to_file(tmp / "edits.gpkg", driver="GPKG")


def _run(cfg, tmp, canals, rows, name="edits.gpkg"):
    _edits(tmp, rows)
    cfg["inputs"]["canal_edits"] = {"path": str(tmp / name)}
    gpd.GeoDataFrame({"canal_class": ["primer"] * len(canals), "depth_m": 2.0, "width_m": 4.0}, geometry=canals, crs=CRS).to_file(tmp / "canals.gpkg", driver="GPKG")
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    topology.run(ctx)
    return ctx


A = LineString([(X0, Y0 + 500), (X0 + 400, Y0 + 500)])            # reaches the river
B = LineString([(X0 + 410, Y0 + 500), (X0 + 800, Y0 + 500)])      # 10 m gap, tolerance is 2 m


def test_add_edit_bridges_gap_and_is_reproducible(world):
    cfg, tmp = world
    ctx0 = _run(cfg, tmp, [A, B], [("delete", LineString([(X0 + 5000, Y0), (X0 + 5001, Y0)]))])
    c0 = ctx0.read_layer("canals_clean")
    assert not c0.reaches_river.all()                                # gap leaves B disconnected
    bridge = LineString([(X0 + 400, Y0 + 500), (X0 + 410, Y0 + 500)])
    ctx1 = _run(cfg, tmp, [A, B], [("add", bridge)])
    c1 = ctx1.read_layer("canals_clean")
    assert c1.reaches_river.all() and c1.component_id.nunique() == 1
    ctx2 = _run(cfg, tmp, [A, B], [("add", bridge)])                 # same inputs and edits -> identical result
    c2 = ctx2.read_layer("canals_clean")
    assert list(c1.canal_id) == list(c2.canal_id) and [g.wkt for g in c1.geometry] == [g.wkt for g in c2.geometry]
    assert ctx1.report["validation"]["canal_edits"]["sha256"] == ctx2.report["validation"]["canal_edits"]["sha256"]
    assert len(ctx1.read_layer("qa_topology_edits")) == 1


def test_delete_edit_removes_canal_and_unmatched_warns(world):
    cfg, tmp = world
    spur = LineString([(X0 + 200, Y0 + 500), (X0 + 200, Y0 + 700)])
    ctx = _run(cfg, tmp, [A, spur], [("delete", LineString([(X0 + 200, Y0 + 500), (X0 + 200, Y0 + 700)]))])
    c = ctx.read_layer("canals_clean")
    assert round(c.length_m.sum()) == 400                             # spur gone, A intact
    assert ctx.read_layer("qa_topology_edits").n_affected.iloc[0] == 1
    ctx2 = _run(cfg, tmp, [A], [("delete", LineString([(X0 + 3000, Y0 + 100), (X0 + 3000, Y0 + 200)]))])
    assert not any("matched no canal" in w for w in ctx2.warnings)    # outside the extent: clipped away, nothing to warn about
    ctx3 = _run(cfg, tmp, [A], [("delete", LineString([(X0 + 100, Y0 + 800), (X0 + 100, Y0 + 850)]))])
    assert any("matched no canal" in w for w in ctx3.warnings)


def test_bad_action_rejected(world):
    cfg, tmp = world
    with pytest.raises(InputError, match="unknown action"):
        _run(cfg, tmp, [A], [("move", A)])
