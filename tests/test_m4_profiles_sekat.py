import math

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString

from repeat_pump.core import io, profiles, segments, sekat, topology
from tests.conftest import make_ctx
from tests.fixtures.synthetic import CRS, SLOPE, X0, Y0


def _run(world, canal_geoms, with_existing=True):
    cfg, tmp = world
    if not with_existing:
        cfg["inputs"]["sekat_existing"] = None
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    gdf = gpd.GeoDataFrame({"canal_class": ["primer"] * len(canal_geoms), "depth_m": 2.0, "width_m": 4.0}, geometry=canal_geoms, crs=CRS)
    ctx.write_layer("inputs_clipped_canals", gdf, "1")
    topology.run(ctx); segments.run(ctx); profiles.run(ctx); sekat.run(ctx)
    return ctx


def test_tilted_plane_spacing_and_count(world):
    """Test 1: spacing = dA/s within one sample step; n_req analytic. Canal runs straight down the gradient."""
    c1 = LineString([(X0, Y0 + 500), (X0 + 1800, Y0 + 500)])
    ctx = _run(world, [c1], with_existing=False)
    dA, step = 0.4, 5.0
    prop = ctx.read_layer("sekat_proposed").sort_values("dist_down_m")
    expected = dA / SLOPE
    gaps = np.diff(np.r_[0.0, prop.dist_down_m.to_numpy()])
    assert len(prop) == 4 and np.all(np.abs(gaps - expected) <= step)
    canal = ctx.read_layer("canals_clean").iloc[0]
    assert canal["direction"] == "reverse"                      # digitised upstream
    assert canal["n_req"] == math.ceil(1.8 / dA)                # analytic: ceil(dz/dA) = 5
    assert (prop.js_m - expected).abs().max() <= step


def test_gap_analysis_and_existing(world):
    c1 = LineString([(X0, Y0 + 500), (X0 + 1800, Y0 + 500)])
    ctx = _run(world, [c1])
    ex = ctx.read_layer("sekat_existing_assessed")
    assert ex.snapped.all() and len(ex) == 2
    assert abs(ex.ipg_canal.iloc[0] - 2 / 5) < 1e-9
    prop = ctx.read_layer("sekat_proposed")
    ex_d = sorted(ex.dist_down_m)
    # never within min_spacing (50 m) of an existing sekat
    assert all(abs(p - e) >= 50 for p in prop.dist_down_m for e in ex_d)
    # ts = dk + js*tan(alpha) - dA  with dk = 2.0
    r = prop.iloc[0]
    assert abs(r.ts_m - (2.0 + r.js_m * r.i_lahan_pct / 100 - 0.4)) < 1e-6


def test_profile_ignores_canal_trench(world):
    c1 = LineString([(X0, Y0 + 500), (X0 + 1800, Y0 + 500)])
    ctx = _run(world, [c1], with_existing=False)
    p = ctx.read_layer("canal_profiles")
    expect = 2.0 + SLOPE * (p.station_m)       # plane, not the -2 m trench
    assert np.abs(p.z_land_m - expect).max() < 0.02


def test_flat_canal_direction_from_network(world):
    cfg, _ = world
    c1 = LineString([(X0, Y0 + 500), (X0 + 900, Y0 + 500)])
    c2 = LineString([(X0 + 900, Y0 + 500), (X0 + 900, Y0 + 900)])   # flat (constant x)
    ctx = _run(world, [c1, c2], with_existing=False)
    c = ctx.read_layer("canals_clean")
    flat = c[c.length_m.round() == 400].iloc[0]
    assert flat.direction_method == "network" and flat.direction == "reverse"   # river is at its start node's side


def test_place_sekat_function_resets_on_existing():
    d = np.arange(0, 1801, 5.0)
    z = 2.0 + 0.001 * d
    out = sekat.place_sekat(d, z, 0.4, [300.0], 50.0, 0.5)
    ds = [p for p, _ in out]
    assert abs(ds[0] - 700) < 1.0                     # baseline reset at the existing sekat (z=2.3 -> +0.4)
    assert not any(abs(p - 300) < 50 for p in ds)
