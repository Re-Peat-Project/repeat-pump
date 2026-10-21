"""Moisture rasters from cloud imagery: CPWI maths (hand-computed from legacy/gee_code.txt), STAC compositing with a fake catalogue."""
import json

import numpy as np
import pytest
import rasterio

from repeat_pump.core import cloudfetch as cf
from repeat_pump.core import cpwi

nan = np.nan


def a(*v):
    return np.array(v, dtype="float32")


# ----------------------------------------------------------------------------- maths
def test_cpwi_all_components_present():
    # ndwi 0.05 -> 0.5, ndmi 0.15 -> 0.5, vv 0.04 / ndvi 0.5 = 0.08 -> 0.5, so every weight sees 0.5
    out = cpwi.cpwi(a(0.05), a(0.15), a(0.5), a(0.04))
    assert out[0] == pytest.approx(0.5)


def test_cpwi_missing_radar_is_neutral():
    # ndwi 0.4 -> 1, ndmi -0.2 -> 0, no radar -> 0.5:  0.30*1 + 0.35*0 + 0.35*0.5
    assert cpwi.cpwi(a(0.4), a(-0.2), a(0.6), a(nan))[0] == pytest.approx(0.475)


def test_cpwi_radar_only_uses_ndvi_fallback_and_is_not_masked():
    # no Sentinel-2: ndvi falls back to 0.1; vv 0.0115 / 0.1 = 0.115 -> (0.115-0.01)/0.14 = 0.75; optical terms neutral 0.5
    assert cpwi.cpwi(a(nan), a(nan), a(nan), a(0.0115))[0] == pytest.approx(0.30 * 0.5 + 0.35 * 0.5 + 0.35 * 0.75)


def test_cpwi_masked_only_where_neither_sensor_has_data():
    assert np.isnan(cpwi.cpwi(a(nan), a(nan), a(nan), a(nan))[0])


def test_cpwi_clamps_before_scaling():
    assert cpwi.cpwi(a(5.0), a(5.0), a(1.0), a(10.0))[0] == pytest.approx(1.0)
    assert cpwi.cpwi(a(-5.0), a(-5.0), a(0.1), a(1e-6))[0] == pytest.approx(0.0)


def test_ndvi_is_floored_for_the_radar_term():
    # ndvi -0.3 is floored at 0.01: vv 0.0005 / 0.01 = 0.05 -> (0.05-0.01)/0.14
    assert cpwi.sar_wetness(a(0.0005), a(-0.3))[0] == pytest.approx(0.04 / 0.14, rel=1e-5)


def test_s2_wetness_renormalises_the_weights():
    out = cpwi.s2_wetness(a(0.4), a(-0.2))              # terms 1 and 0
    assert out[0] == pytest.approx(0.30 / 0.65)
    assert cpwi.s2_wetness(a(0.4), a(nan))[0] != cpwi.s2_wetness(a(0.4), a(nan))[0]    # masked stays masked


def test_median_composite_ignores_masked_and_keeps_all_masked():
    m = cpwi.median_composite([a(1, nan, nan), a(3, 5, nan), a(5, 7, nan)])
    assert m[0] == 3 and m[1] == 6 and np.isnan(m[2])
    with pytest.raises(ValueError):
        cpwi.median_composite([])


def test_tile_size_follows_the_memory_budget():
    assert cf.tile_size(60, 8) == 1024 and cf.tile_size(60, 0.5) < cf.tile_size(60, 2) and cf.tile_size(10_000, 0.1) == 128
    assert cf.tile_size(40, 1) % 64 == 0


def test_reflectance_scaling_comes_from_the_catalogue():
    item = {"id": "x", "assets": {"nir": {"raster:bands": [{"scale": 0.0001, "offset": -0.1}]}, "red": {}}}
    assert cf.asset_scaling(item, "nir") == (0.0001, -0.1)
    with pytest.raises(cf.FetchError, match="raster:bands"):
        cf.asset_scaling(item, "red")


# ----------------------------------------------------------------------------- fake catalogue
BOUNDS = (500000.0, 9700000.0, 500200.0, 9700100.0)      # 20 x 10 pixels at 10 m, EPSG:32749


def dn(refl):                                            # scale 0.0001, offset -0.1
    return round((refl + 0.1) / 0.0001)


def item(i, date, **refl):
    assets = {a_: {"href": f"{i}/{a_}", "raster:bands": [{"scale": 0.0001, "offset": -0.1}]} for a_ in ("green", "red", "nir", "swir16")}
    assets["scl"] = {"href": f"{i}/scl"}
    return {"id": i, "properties": {"datetime": f"{date}T02:00:00Z"}, "assets": assets, "refl": refl}


class FakeReader:
    def __init__(self, arr):
        self.arr = arr

    def read(self, window):
        r, c = int(window.row_off), int(window.col_off)
        return self.arr[r:r + int(window.height), c:c + int(window.width)]


def make_opener(items, scl_by_id):
    data = {}
    for it in items:
        shape = (10, 20)
        for key, band in (("b3", "green"), ("b4", "red"), ("b8", "nir"), ("b11", "swir16")):
            data[f"{it['id']}/{band}"] = np.full(shape, dn(it["refl"][key]), "uint16")
        data[f"{it['id']}/scl"] = scl_by_id.get(it["id"], np.full(shape, 4, "uint8"))
    return lambda stack, href, grid, resampling: FakeReader(data[href])


def expected(r):
    nd, nm, _ = cpwi.s2_indices(a(r["b3"]), a(r["b4"]), a(r["b8"]), a(r["b11"]))
    return float(cpwi.s2_wetness(nd, nm)[0])


WET = dict(b3=0.08, b4=0.05, b8=0.30, b11=0.15)
DRY = dict(b3=0.06, b4=0.08, b8=0.25, b11=0.30)
FALL = dict(b3=0.07, b4=0.06, b8=0.28, b11=0.22)


def run(tmp_path, items, scl):
    out = tmp_path / "w.tif"
    prov = cf.fetch_s2_wetness(BOUNDS, "EPSG:32749", out, ("2023-07-01", "2023-10-31"), ("2023-04-01", "2023-11-30"),
                               search=lambda g, s, e, c: items, opener=make_opener(items, scl))
    with rasterio.open(out) as s:
        return prov, s.read(1), s.nodata, s.crs.to_string(), s.transform


def test_primary_median_fills_gaps_from_the_fallback_window(tmp_path):
    items = [item("A", "2023-08-01", **WET), item("B", "2023-09-01", **DRY), item("C", "2023-05-01", **FALL)]
    left_cloud = np.full((10, 20), 4, "uint8")
    left_cloud[:, :10] = 9                                   # high-probability cloud on the left half
    prov, arr, nodata, crs, tr = run(tmp_path, items, {"A": left_cloud, "B": left_cloud})
    # right half: median of A and B reflectance (averaged), left half: only the fallback scene C is clear
    mid = {k: (WET[k] + DRY[k]) / 2 for k in WET}
    assert arr[:, 15] == pytest.approx(expected(mid), abs=2e-3)
    assert arr[:, 5] == pytest.approx(expected(FALL), abs=2e-3)
    assert crs == "EPSG:32749" and (tr.a, tr.e) == (10.0, -10.0) and nodata == cf.NODATA
    assert prov["scenes_total"] == 3 and prov["scenes_primary"] == 2 and prov["valid_fraction"] == 1.0
    sidecar = json.loads((tmp_path / "w.tif.provenance.json").read_text())
    assert sidecar["higher_is_wetter"] is True and any("Cloud Score+" in d for d in sidecar["deviations"])


def test_pixels_clear_in_no_scene_are_nodata(tmp_path):
    items = [item("A", "2023-08-01", **WET)]
    cloud = np.full((10, 20), 9, "uint8")
    cloud[:, 10:] = 4
    prov, arr, nodata, _, _ = run(tmp_path, items, {"A": cloud})
    assert (arr[:, :10] == nodata).all() and (arr[:, 10:] != nodata).all() and prov["valid_fraction"] == 0.5


def test_wetter_scene_gives_higher_index(tmp_path):
    _, wet, *_ = run(tmp_path, [item("A", "2023-08-01", **WET)], {})
    _, dry, *_ = run(tmp_path, [item("A", "2023-08-01", **DRY)], {})
    assert wet.mean() > dry.mean()


def test_no_scenes_or_bad_windows_are_clear_errors(tmp_path):
    with pytest.raises(cf.FetchError, match="no Sentinel-2 scenes"):
        cf.fetch_s2_wetness(BOUNDS, "EPSG:32749", tmp_path / "x.tif", ("2023-07-01", "2023-10-31"), ("2023-04-01", "2023-11-30"), search=lambda *a: [])
    with pytest.raises(cf.FetchError, match="primary window"):
        cf.fetch_s2_wetness(BOUNDS, "EPSG:32749", tmp_path / "x.tif", ("2023-01-01", "2023-02-01"), ("2023-04-01", "2023-11-30"),
                            search=lambda *a: [item("A", "2023-08-01", **WET)], opener=make_opener([item("A", "2023-08-01", **WET)], {}))
    with pytest.raises(cf.FetchError, match="must contain"):
        cf.fetch_s2_wetness(BOUNDS, "EPSG:32749", tmp_path / "x.tif", ("2023-01-01", "2023-12-01"), ("2023-04-01", "2023-11-30"), search=lambda *a: [])


def test_stac_search_follows_pages_and_dedups():
    pages = [{"features": [{"id": "b"}, {"id": "a"}], "links": [{"rel": "next", "body": {"page": 2}}]}, {"features": [{"id": "a"}, {"id": "c"}], "links": []}]
    seen = []

    def post(url, body):
        seen.append(body)
        return pages[len(seen) - 1]

    out = cf.stac_search(cf.Grid.make(BOUNDS, "EPSG:32749"), "2023-07-01", "2023-10-31", 80, post=post)
    assert [i["id"] for i in out] == ["a", "b", "c"] and seen[0]["query"] == {"eo:cloud_cover": {"lt": 80}} and seen[1] == {"page": 2}
    assert seen[0]["datetime"] == "2023-07-01T00:00:00Z/2023-10-31T23:59:59Z" and -3 < seen[0]["bbox"][1] < 0


def test_grid_snaps_outwards_to_whole_pixels():
    g = cf.Grid.make((500003.0, 9700004.0, 500197.0, 9700096.0), "EPSG:32749")
    assert g.bounds == (500000.0, 9700000.0, 500200.0, 9700100.0) and (g.width, g.height) == (20, 10)


# ----------------------------------------------------------------------------- stage 1 reads the provenance
def test_stage1_reports_cloud_moisture_provenance_and_deviations(world):
    from repeat_pump.core import io
    from tests.conftest import make_ctx
    cfg, _ = world
    moisture = cfg["inputs"]["moisture"]["paths"][0]
    prov = {"product": cf.OUTPUT_LABEL, "higher_is_wetter": True, "deviations": ["no Sentinel-1 term"], "scenes_total": 3}
    from pathlib import Path
    Path(moisture + ".provenance.json").write_text(json.dumps(prov))
    cfg["inputs"]["moisture"]["higher_is_wetter"] = False        # contradicts what the engine built
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    assert ctx.report["moisture_provenance"][0]["scenes_total"] == 3
    assert any("no Sentinel-1 term" in w for w in ctx.warnings)
    assert any("higher_is_wetter=True" in w for w in ctx.warnings)


def test_cli_fetch_moisture_needs_dates_and_area(capsys):
    from repeat_pump.cli import main
    with pytest.raises(SystemExit):
        main(["fetch-moisture", "--bounds", "0", "0", "100", "100", "--crs", "EPSG:32749", "--out", "x.tif"])
    assert "--primary" in capsys.readouterr().err
