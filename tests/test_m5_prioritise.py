import numpy as np
import pandas as pd
import geopandas as gpd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

from repeat_pump.core import hydro, io, prioritise, profiles, segments, sekat, topology
from repeat_pump.core.config import ConfigError, MissingParameters
from tests.conftest import make_ctx
from tests.fixtures.synthetic import CRS, X0, Y0


def _seg(geom, sid="S1"):
    return gpd.GeoDataFrame({"seg_id": [sid]}, geometry=[geom], crs=CRS)


def test_length_weighted_dominance_two_polygons():
    """Test 2a: 500 m segment, 400 m class A and 100 m class B -> A (feature-count majority would tie)."""
    s = _seg(LineString([(0, 0), (500, 0)]))
    polys = gpd.GeoDataFrame({"v": ["A", "B"]}, geometry=[box(0, -5, 400, 5), box(400, -5, 500, 5)], crs=CRS)
    d = prioritise.dominant_by_length(s, polys, "v")
    assert d.loc["S1", "v"] == "A" and abs(d.loc["S1", "share_dominant"] - 0.8) < 1e-9


def test_length_weighted_dominance_three_pieces():
    """Test 2b: A 150, B 200, A 150 -> A (total 300 > 200); feature-count majority would also say A but B is the largest single piece."""
    s = _seg(LineString([(0, 0), (500, 0)]))
    polys = gpd.GeoDataFrame({"v": ["A", "B", "A"]}, geometry=[box(0, -5, 150, 5), box(150, -5, 350, 5), box(350, -5, 500, 5)], crs=CRS)
    d = prioritise.dominant_by_length(s, polys, "v")
    assert d.loc["S1", "v"] == "A" and abs(d.loc["S1", "share_dominant"] - 0.6) < 1e-9


def test_no_summed_values_after_split(tmp_path):
    """Test 3: raster values per segment are unchanged by splitting/aggregating (legacy summed means)."""
    p = tmp_path / "c.tif"
    with rasterio.open(p, "w", driver="GTiff", height=100, width=600, count=1, dtype="float64", crs=CRS,
                       transform=from_origin(0, 50, 1, 1), nodata=-9999) as d:
        d.write(np.full((100, 600), 1.7), 1)
    line = LineString([(0, 0), (500, 0)])
    with rasterio.open(p) as src:
        whole = prioritise.zonal(src, prioritise.ring(line, 15, 30), "mean")
        pieces = [prioritise.zonal(src, prioritise.ring(LineString([(a, 0), (b, 0)]), 15, 30), "mean") for a, b in ((0, 400), (400, 500))]
    assert abs(whole - 1.7) < 1e-9 and all(abs(x - 1.7) < 1e-9 for x in pieces)   # not 3.4


def test_ahp_consistency():
    """Test 8: consistent matrix -> CR ~ 0; inconsistent matrix -> CR > 0.10."""
    a = np.array([[1, 2, 4], [1 / 2, 1, 2], [1 / 4, 1 / 2, 1]])
    w, cr = prioritise.ahp_weights(a)
    assert cr < 1e-6 and abs(w.sum() - 1) < 1e-9 and w[0] > w[1] > w[2]
    bad = np.array([[1, 9, 1 / 9], [1 / 9, 1, 9], [9, 1 / 9, 1]])
    assert prioritise.ahp_weights(bad)[1] > 0.10


def _upto6(world, mutate=None):
    cfg, _ = world
    if mutate:
        mutate(cfg)
    ctx = make_ctx(cfg)
    for f in (io.run_stage1, topology.run, hydro.run, segments.run, profiles.run):
        f(ctx)
    return ctx


def test_stage6_end_to_end(world):
    ctx = _upto6(world)
    prioritise.run(ctx)
    s = ctx.read_layer("canal_segments")
    assert s.need_rank.notna().all() and s.selected.sum() >= 1
    # eastern, burned, deep-peat, drier segments must outrank the western ones
    c1 = s[s.canal_id == s.canal_id.iloc[0]].sort_values("chain_start_m")
    assert s.loc[s.need_score.idxmax(), "burn_freq_n"] == 2
    assert 0 <= s.need_score.min() and s.need_score.max() <= 1
    sens = ctx.read_layer("qa_sensitivity")
    assert len(sens) == 16 and sens.spearman_rho.between(-1, 1).all()


def test_weights_null_stops(world):
    def m(cfg):
        cfg["prioritise"]["criteria"]["dryness"]["weight"] = None
    ctx = _upto6(world, m)
    with pytest.raises(MissingParameters):
        prioritise.run(ctx)


def test_ahp_inconsistent_fails_in_stage(world):
    def m(cfg):
        cfg["prioritise"]["weights_mode"] = "ahp"
        cfg["prioritise"]["ahp_matrix"] = [[1, 9, 1 / 9, 1], [1 / 9, 1, 9, 1], [9, 1 / 9, 1, 1], [1, 1, 1, 1]]
    ctx = _upto6(world, m)
    with pytest.raises(ConfigError):
        prioritise.run(ctx)


def test_segments_outside_selected_subkhg_are_not_scored(world):
    """Stage 6 runs only inside the selected sub-KHGs: margin canals get no score and are never selected."""
    import geopandas as gpd
    cfg, _ = world
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    inside = LineString([(X0, Y0 + 500), (X0 + 1000, Y0 + 500)])
    margin = LineString([(X0 + 2050, Y0 + 300), (X0 + 2050, Y0 + 600)])    # in the 100 m margin, outside sub-KHG A
    ctx.write_layer("inputs_clipped_canals", gpd.GeoDataFrame({"canal_class": ["primer"] * 2, "depth_m": 2.0, "width_m": 4.0},
                                                              geometry=[inside, margin], crs=CRS), "1")
    for f in (topology.run, hydro.run, segments.run, profiles.run):
        f(ctx)
    prioritise.run(ctx)
    s = ctx.read_layer("canal_segments")
    out = s[s.subkhg_id.isna()]
    assert len(out) >= 1 and out.need_score.isna().all() and not out.selected.any()
    assert s[s.subkhg_id.notna()].need_score.notna().all()
