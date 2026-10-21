"""Burn frequency from MODIS MCD64A1: counting years, polygons, provenance, with a fake catalogue."""
import json

import geopandas as gpd
import numpy as np
import pytest

from repeat_pump.core import burnfetch as bf
from repeat_pump.core.cloudfetch import FetchError, Grid

BOUNDS = (500000.0, 9700000.0, 500600.0, 9700400.0)       # 6 x 4 cells at 100 m


def item(i, year, month):
    return {"id": i, "properties": {"start_datetime": f"{year}-{month:02d}-01T00:00:00Z"}, "assets": {"Burn_Date": {"href": f"{i}"}}}


class Reader:
    def __init__(self, arr):
        self.arr = arr

    def read(self, window):
        return self.arr


def opener_for(data):
    return lambda stack, href, grid, resampling, nodata=None: Reader(data[href])


def run(tmp_path, items, data, years=(2019, 2021)):
    out = tmp_path / "b.gpkg"
    prov = bf.fetch_burn_frequency(BOUNDS, "EPSG:32749", out, years, search=lambda g, y: items, opener=opener_for(data), sign=lambda h: h)
    return prov, gpd.read_file(out, layer="burn_area")


def grid_arr(**cells):
    a = np.zeros((4, 6), "int16")
    for k, v in cells.items():
        r, c = map(int, k[1:].split("_"))
        a[r, c] = v
    return a


def test_burn_frequency_counts_years_not_months():
    f = bf.burn_frequency([(2019, grid_arr(c0_0=150)), (2019, grid_arr(c0_0=200)), (2020, grid_arr(c0_0=10, c1_1=-1, c2_2=-2)), (2021, grid_arr())],
                          [2019, 2020, 2021], (4, 6))
    assert f[0, 0] == 2 and f[1, 1] == 0 and f[2, 2] == 0           # two fires in 2019 count once; unmapped and water never count


def test_polygons_carry_integer_burn_freq_in_the_run_crs(tmp_path):
    items = [item("a", 2019, 8), item("b", 2020, 9), item("c", 2021, 9)]
    data = {"a": grid_arr(r0_0=100, r0_1=100, r3_5=250), "b": grid_arr(r0_0=270), "c": np.zeros((4, 6), "int16")}
    prov, gdf = run(tmp_path, items, data)
    assert gdf.crs.to_epsg() == 32749 and gdf["burn_freq"].dtype.kind == "i"
    assert gdf.loc[gdf.burn_freq == 2].geometry.area.sum() == pytest.approx(1e4) and gdf.loc[gdf.burn_freq == 1].geometry.area.sum() == pytest.approx(2e4)
    assert prov["max_burn_freq"] == 2 and prov["years_without_products"] == [] and prov["polygons"] == 3
    side = json.loads((tmp_path / "b.gpkg.provenance.json").read_text())
    assert any("small fires" in d for d in side["deviations"])


def test_nothing_burned_gives_an_empty_valid_layer_and_missing_years_are_reported(tmp_path):
    prov, gdf = run(tmp_path, [item("a", 2019, 8)], {"a": np.zeros((4, 6), "int16")})
    assert len(gdf) == 0 and "burn_freq" in gdf.columns and prov["years_without_products"] == [2020, 2021]


def test_errors_are_clear(tmp_path):
    with pytest.raises(FetchError, match="before the first"):
        bf.fetch_burn_frequency(BOUNDS, "EPSG:32749", tmp_path / "x.gpkg", (2021, 2019), search=lambda *a: [])
    with pytest.raises(FetchError, match="no MODIS"):
        bf.fetch_burn_frequency(BOUNDS, "EPSG:32749", tmp_path / "x.gpkg", (2019, 2020), search=lambda *a: [])


def test_search_follows_pages_and_year_comes_from_the_item():
    pages = [{"features": [{"id": "b"}], "links": [{"rel": "next", "body": {"p": 2}}]}, {"features": [{"id": "a"}, {"id": "b"}], "links": []}]
    seen = []

    def post(url, body):
        seen.append(body)
        return pages[len(seen) - 1]

    out = bf.stac_search(Grid.make(BOUNDS, "EPSG:32749", 100.0), (2019, 2020), post=post)
    assert [i["id"] for i in out] == ["a", "b"] and seen[0]["collections"] == ["modis-64A1-061"] and seen[0]["datetime"].startswith("2019-01-01")
    assert bf.item_year({"properties": {"start_datetime": "2019-09-01T00:00:00Z"}}) == 2019


def test_stage1_reports_burn_provenance(world, tmp_path):
    from pathlib import Path

    from repeat_pump.core import io
    from tests.conftest import make_ctx
    cfg, _ = world
    path = cfg["inputs"]["burn_area"]["path"]
    Path(path + ".provenance.json").write_text(json.dumps({"product": "MODIS", "deviations": ["MODIS cells are about 463 m"]}))
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    assert ctx.report["burn_area_provenance"] and any("463 m" in w for w in ctx.warnings)
