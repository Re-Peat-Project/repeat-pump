"""An attribute named ``fid`` in an input layer must not break stage 1: the GeoPackage reserves ``fid`` for its row id."""
import geopandas as gpd
import pytest

from repeat_pump.core import io
from tests.conftest import make_ctx


@pytest.mark.parametrize("values", [[1.0, 2.0], [None, 2], [1, 1], [7, 8]], ids=["real", "null", "repeated", "unique"])
def test_canal_shapefile_with_a_fid_column(world, values):
    cfg, tmp = world
    c = gpd.read_file(tmp / "canals.gpkg")
    c["FID"] = values
    c.to_file(tmp / "canals.shp")                        # as a shapefile saved from QGIS: FID is a plain attribute
    cfg["inputs"]["canals"] = {"path": str(tmp / "canals.shp"), "columns": {"canal_class": "canal_clas"}}   # shapefile cuts names to 10 characters
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    out = ctx.read_layer("inputs_clipped_canals")
    assert "src_fid" in out and "fid" not in out
    assert any("'fid' renamed to 'src_fid'" in w for w in ctx.warnings)


def test_polygon_layer_with_a_repeated_fid_column(world):
    cfg, tmp = world
    p = gpd.read_file(tmp / "peat.gpkg")
    p["FID"] = 1                                          # e.g. two layers merged, each numbered from 1
    p.to_file(tmp / "peat.shp")
    cfg["inputs"]["peat_depth"]["path"] = str(tmp / "peat.shp")
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    assert "src_fid" in ctx.read_layer("inputs_clipped_peat_depth")


def test_an_existing_src_fid_column_is_kept(world):
    cfg, tmp = world
    c = gpd.read_file(tmp / "canals.gpkg")
    c["FID"], c["src_fid"] = [1.5, 2.5], ["a", "b"]
    c.to_file(tmp / "canals.shp")
    cfg["inputs"]["canals"] = {"path": str(tmp / "canals.shp"), "columns": {"canal_class": "canal_clas"}}
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    out = ctx.read_layer("inputs_clipped_canals")
    assert sorted(out["src_fid"]) == ["a", "b"] and "src_fid_x" in out
