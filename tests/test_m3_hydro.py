import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
import geopandas as gpd
from shapely.geometry import LineString

from repeat_pump.core import hydro, io, topology

try:
    from whitebox import WhiteboxTools
    WhiteboxTools().version()
    HAVE_WBT = True
except Exception:  # pragma: no cover
    HAVE_WBT = False

pytestmark = pytest.mark.skipif(not HAVE_WBT, reason="WhiteboxTools binary unavailable")


def _write(path, z):
    with rasterio.open(path, "w", driver="GTiff", height=z.shape[0], width=z.shape[1], count=1, dtype="float64",
                       crs="EPSG:32749", transform=from_origin(0, 100, 1, 1), nodata=-9999.0) as d:
        d.write(z, 1)


def test_pit_is_breached_and_flow_reaches_outlet(tmp_path):
    n = 100
    z = np.tile((n - np.arange(n))[:, None].astype(float), (1, n)) * 0.1   # slopes towards the last row
    z[50, 50] -= 1.0                                                       # pit
    _write(tmp_path / "dem.tif", z)
    hydro.condition_dem(tmp_path / "dem.tif", tmp_path / "c.tif", 10, tmp_path)
    hydro.flow_accumulation(tmp_path / "c.tif", tmp_path / "a.tif", "dinf", tmp_path)
    with rasterio.open(tmp_path / "a.tif") as d:
        a = d.read(1)
    assert a[-2:, :].sum() >= 0.9 * n * n          # almost all cells drain to the outlet edge: pit is resolved


def test_burn_does_not_touch_unconditioned_dtm(world):
    cfg, tmp = world
    from tests.conftest import make_ctx
    ctx = make_ctx(cfg)
    io.run_stage1(ctx); topology.run(ctx); hydro.run(ctx)
    dtm = ctx.report["inputs"]["dtm"]
    cond = ctx.report["inputs"]["dtm_conditioned"]
    with rasterio.open(dtm) as a, rasterio.open(cond) as b:
        za, zb = a.read(1), b.read(1)
    assert za.shape == zb.shape

    assert not np.allclose(za, zb)                  # the canal trench was burned in the copy only
    with rasterio.open(ctx.report["inputs"]["flow_acc"]) as f:
        assert f.read(1).max() > 100


def test_memory_budget_guard(world):
    cfg, _ = world
    from tests.conftest import make_ctx
    cfg["run"]["memory_budget_gb"] = 1e-9
    with pytest.raises(io.MemoryBudgetExceeded):
        io.check_memory(make_ctx(cfg).cfg, 10_000, 8, 5, "x")
