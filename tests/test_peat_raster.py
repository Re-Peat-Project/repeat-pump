"""Peat depth as a raster (A1): the same input key takes thickness-class polygons or a depth raster in m or cm."""
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from repeat_pump.core import hydro, io, prioritise, profiles, segments, topology
from repeat_pump.core.config import Config, NeedsHuman
from repeat_pump.core.requirements import needs_by_stage
from tests.conftest import make_ctx
from tests.fixtures.synthetic import CRS, X0, Y0


def peat_raster(path, scale=1.0, nodata_block=None, res=10.0):
    """The synthetic peat polygons as a raster of their class midpoints: 1.25 m west of X0 + 1200, 3.5 m east of it (to X0 + 2000)."""
    x0, y1 = X0 - 100, Y0 + 1000
    w, h = int(2200 / res), int(1000 / res)
    xs = x0 + (np.arange(w) + 0.5) * res
    arr = np.tile(np.where(xs < X0 + 1200, 1.25, np.where(xs < X0 + 2000, 3.5, np.nan)), (h, 1)) * scale
    if nodata_block is not None:
        arr[:10, :10] = nodata_block
    with rasterio.open(path, "w", driver="GTiff", height=h, width=w, count=1, dtype="float32", crs=CRS,
                       transform=from_origin(x0, y1, res, res), nodata=np.nan) as d:
        d.write(arr.astype("float32"), 1)
    return str(path)


def test_a_raster_needs_its_unit(world):
    cfg, tmp = world
    cfg["inputs"]["peat_depth"] = {"path": peat_raster(tmp / "peat.tif")}
    assert "inputs.peat_depth.units" in needs_by_stage(Config.model_validate(cfg))[1]
    with pytest.raises(NeedsHuman, match="units"):
        io.run_stage1(make_ctx(cfg))


def test_polygons_do_not_ask_for_a_unit(world):
    cfg, _ = world
    assert "inputs.peat_depth.units" not in needs_by_stage(Config.model_validate(cfg))[1]


def test_centimetres_and_extra_nodata_become_metres(world):
    cfg, tmp = world
    cfg["inputs"]["peat_depth"] = {"path": peat_raster(tmp / "peat_cm.tif", scale=100.0, nodata_block=-8888.0), "units": "cm",
                                   "nodata": [-8888]}
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    with rasterio.open(ctx.report["inputs"]["peat_depth"]) as r:
        v = r.read(1)
    v = v[np.isfinite(v)]
    assert set(np.round(np.unique(v), 3)) == {1.25, 3.5}
    assert any("extra no-data value" in w for w in ctx.warnings)
    assert not any("do not look like" in w for w in ctx.warnings)          # cm values that fit cm are not questioned
    pe = ctx.read_layer("inputs_clipped_peat_depth")
    assert len(pe) > 0 and set(pe["peat_class"]) == {"raster"}


def test_a_unit_that_does_not_fit_the_values_is_warned_about(world):
    cfg, tmp = world
    cfg["inputs"]["peat_depth"] = {"path": peat_raster(tmp / "peat_cm.tif", scale=100.0), "units": "m"}
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    assert any("do not look like m" in w for w in ctx.warnings)


def _stage6(cfg):
    ctx = make_ctx(cfg)
    for f in (io.run_stage1, topology.run, hydro.run, segments.run, profiles.run, prioritise.run):
        f(ctx)
    return ctx.read_layer("canal_segments").set_index("seg_id")


def test_raster_and_polygons_of_the_same_peat_give_the_same_segments(world):
    cfg, tmp = world
    poly = _stage6(cfg)
    cfg["inputs"]["peat_depth"] = {"path": peat_raster(tmp / "peat.tif"), "units": "m"}
    cfg["run"]["output_gpkg"] = str(tmp / "out_raster" / "run.gpkg")
    ras = _stage6(cfg)
    assert set(ras["peat_class"]) == {"raster"}
    inside = poly.index[poly["peat_share_dom"] >= 0.999]               # segments wholly inside one class polygon
    assert len(inside) >= 0.7 * len(poly)
    assert np.allclose(ras.loc[inside, "peat_depth_mid_m"], poly.loc[inside, "peat_depth_mid_m"])
    assert (ras["peat_depth_min_m"] <= ras["peat_depth_mid_m"] + 1e-9).all()
    assert (ras["selected"].astype(bool) == poly["selected"].astype(bool)).mean() >= 0.9
