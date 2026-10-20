import geopandas as gpd
from shapely.geometry import LineString

from repeat_pump.core import io, segments, topology
from tests.conftest import make_ctx
from tests.fixtures.synthetic import CRS, X0, Y0


def _ctx_with_canals(world, geoms, classes=None):
    cfg, tmp = world
    ctx = make_ctx(cfg)
    gdf = gpd.GeoDataFrame({"canal_class": classes or ["primer"] * len(geoms), "depth_m": 2.0, "width_m": 4.0}, geometry=geoms, crs=CRS)
    ctx.write_layer("inputs_clipped_canals", gdf, "1")
    return ctx


def test_snap_break_dangles_and_duplicates(world):
    a = LineString([(X0, Y0 + 500), (X0 + 1000, Y0 + 500)])
    b = LineString([(X0 + 500, Y0 + 501), (X0 + 500, Y0 + 900)])  # 1 m gap below: snaps onto a
    dup = LineString([(X0 + 1000, Y0 + 500), (X0, Y0 + 500)])      # duplicate of a, reversed
    ctx = _ctx_with_canals(world, [a, b, dup])
    topology.run(ctx)
    clean = ctx.read_layer("canals_clean")
    assert len(clean) == 3                       # a broken at the junction (2) + b (1); duplicate removed
    assert abs(clean.length_m.sum() - (1000 + 400)) < 1e-6
    gaps = ctx.read_layer("qa_topology_gaps")
    assert len(gaps) == 1 and abs(gaps.gap_m.iloc[0] - 1.0) < 1e-6
    dang = ctx.read_layer("qa_topology_dangles")
    assert len(dang) == 3                        # three free ends; none deleted
    assert clean.canal_id.is_unique


def test_canal_id_independent_of_row_order(world):
    a = LineString([(X0, Y0 + 500), (X0 + 1000, Y0 + 500)])
    b = LineString([(X0 + 500, Y0 + 500), (X0 + 500, Y0 + 900)])
    c1 = _ctx_with_canals(world, [a, b]); topology.run(c1)
    c2 = _ctx_with_canals(world, [b, a]); topology.run(c2)
    g1 = c1.read_layer("canals_clean"); g2 = c2.read_layer("canals_clean")
    assert [(i, round(l, 3)) for i, l in zip(g1.canal_id, g1.length_m)] == [(i, round(l, 3)) for i, l in zip(g2.canal_id, g2.length_m)]


def test_segments_split_and_flag(world):
    ctx = _ctx_with_canals(world, [LineString([(X0, Y0 + 500), (X0 + 1210, Y0 + 500)])])
    topology.run(ctx); segments.run(ctx)
    seg = ctx.read_layer("canal_segments")
    assert list(seg.length_m.round(1)) == [500.0, 500.0, 210.0]
    assert list(seg.seg_id) == ["C00001_001", "C00001_002", "C00001_003"]
    ctx2 = _ctx_with_canals(world, [LineString([(X0, Y0 + 500), (X0 + 1010, Y0 + 500)])])
    topology.run(ctx2); segments.run(ctx2)
    s2 = ctx2.read_layer("canal_segments")
    assert list(s2.status_mcda) == [1, 1, 0]      # 10 m sliver flagged, kept
