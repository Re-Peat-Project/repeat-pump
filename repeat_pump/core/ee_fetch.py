"""Exact CPWI v2 through the Earth Engine Python API: a line-by-line port of the team's script ``legacy/gee_code.txt``.

Needs the optional ``earthengine-api`` package and a registered Earth Engine account with a Cloud project (one-time sign-in:
``repeat-pump fetch-moisture --ee-authenticate``). Nothing here runs without them, and it has not been exercised against the
live service in this repository's tests (they cover the maths in ``cpwi.py`` and the tiling only).

Same inputs, clamps, weights, Cloud Score+ threshold and masking rules as the script, so the result is the CPWI the team
already produces. The raster is downloaded in tiles and mosaicked into one float32 GeoTIFF in the run CRS.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import cpwi
from .cloudfetch import NODATA, RESOLUTION_M, FetchError, Grid, _progress

TILE_PX = 1024          # download chunk edge; one float32 chunk is about 4 MB, well under the getDownloadURL limit


def _ee():
    try:
        import ee
    except ImportError as e:
        raise FetchError("the Earth Engine backend needs the earthengine-api package: install it in the engine environment "
                         "(python -m pip install earthengine-api) and sign in with `repeat-pump fetch-moisture --ee-authenticate`") from e
    return ee


def authenticate() -> None:
    """One-time browser sign-in (local redirect, no typing of codes)."""
    _ee().Authenticate(auth_mode="localhost")


def initialise(project: str):
    ee = _ee()
    try:
        ee.Initialize(project=project, opt_url="https://earthengine-highvolume.googleapis.com")
    except Exception as e:
        raise FetchError(f"could not start Earth Engine for project {project!r}: {e}. Sign in first with --ee-authenticate and check the project id") from e
    return ee


def build_cpwi(ee, region, primary: tuple[str, str], fallback: tuple[str, str], p: cpwi.CpwiParams = cpwi.LEGACY):
    """The ee.Image of the script's section 1 to 4 (continuous CPWI), without the 5-class step."""
    cs_plus = ee.ImageCollection("GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED")

    def mask(img):
        return img.updateMask(img.select("cs_cdf").gte(p.cloud_score_min)).select("B.*").multiply(0.0001).copyProperties(img, ["system:time_start"])

    def s2_collection(a, b):
        return (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(region).filterDate(a, b)
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", p.max_scene_cloud_pct)).linkCollection(cs_plus, ["cs_cdf"]).map(mask))

    s2 = s2_collection(*primary).median().clip(region).unmask(s2_collection(*fallback).median().clip(region)).clip(region)
    ndwi, ndmi, ndvi = (s2.normalizedDifference(["B3", "B8"]), s2.normalizedDifference(["B8", "B11"]), s2.normalizedDifference(["B8", "B4"]))
    s2_valid = s2.select("B3").mask()

    def norm(img, lo, hi):
        return img.clamp(lo, hi).subtract(lo).divide(hi - lo).clamp(0, 1)

    def s1(orbit):
        return (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(region).filterDate(*primary).filter(ee.Filter.eq("instrumentMode", "IW"))
                .filter(ee.Filter.eq("orbitProperties_pass", orbit)).filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")).select(["VV"]))

    s1c = s1("ASCENDING").merge(s1("DESCENDING")).median().clip(region)
    s1_valid = s1c.select("VV").mask()
    vv_lin = ee.Image(10).pow(s1c.divide(10))
    ndvi_safe = ndvi.unmask(p.ndvi_fallback).clamp(p.ndvi_floor, 1)
    sar = norm(vv_lin.divide(ndvi_safe), *p.sar_range)
    out = (norm(ndwi, *p.ndwi_range).unmask(p.neutral).multiply(p.w_ndwi).add(norm(ndmi, *p.ndmi_range).unmask(p.neutral).multiply(p.w_ndmi))
           .add(sar.unmask(p.neutral).multiply(p.w_sar)))
    return out.updateMask(s2_valid.Or(s1_valid)).rename("CPWI").toFloat()


def fetch_cpwi(bounds, crs: str, out: str | Path, primary: tuple[str, str], fallback: tuple[str, str], project: str) -> dict:
    """Download CPWI v2 for ``bounds`` (x0, y0, x1, y1 in ``crs``) into ``out`` (float32 GeoTIFF, nodata -9999)."""
    import numpy as np
    import rasterio
    from rasterio.windows import Window

    if not (fallback[0] <= primary[0] and primary[1] <= fallback[1]):
        raise FetchError(f"the fallback window {fallback} must contain the primary window {primary}")
    ee = initialise(project)
    grid = Grid.make(bounds, crs)
    x0, y0, x1, y1 = grid.bounds
    image = build_cpwi(ee, ee.Geometry.Rectangle([x0, y0, x1, y1], proj=crs, geodesic=False), primary, fallback)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    prof = dict(driver="GTiff", height=grid.height, width=grid.width, count=1, dtype="float32", crs=grid.crs, transform=grid.transform,
                nodata=NODATA, compress="deflate", tiled=True, blockxsize=256, blockysize=256)
    tiles = [Window(c, r, min(TILE_PX, grid.width - c), min(TILE_PX, grid.height - r)) for r in range(0, grid.height, TILE_PX) for c in range(0, grid.width, TILE_PX)]
    valid = 0
    with rasterio.open(out, "w", **prof) as dst:
        for n, w in enumerate(tiles):
            _progress(n / len(tiles), f"Earth Engine tile {n + 1} of {len(tiles)}")
            tx0, ty1 = x0 + w.col_off * grid.res, y1 - w.row_off * grid.res
            box = [tx0, ty1 - w.height * grid.res, tx0 + w.width * grid.res, ty1]
            url = image.getDownloadURL({"region": ee.Geometry.Rectangle(box, proj=crs, geodesic=False), "scale": RESOLUTION_M, "crs": crs,
                                        "format": "GEO_TIFF", "filePerBand": False})
            with urllib.request.urlopen(url, timeout=600) as r, rasterio.MemoryFile(r.read()) as mf, mf.open() as src:
                arr = src.read(1, masked=True).astype("float32").filled(np.nan)
            if arr.shape != (int(w.height), int(w.width)):          # EE may be a pixel off at tile edges
                fixed = np.full((int(w.height), int(w.width)), np.nan, "float32")
                h, wd = min(arr.shape[0], fixed.shape[0]), min(arr.shape[1], fixed.shape[1])
                fixed[:h, :wd] = arr[:h, :wd]
                arr = fixed
            valid += int(np.isfinite(arr).sum())
            dst.write(np.where(np.isfinite(arr), arr, NODATA).astype("float32"), 1, window=w)
    _progress(1.0, "done")
    prov = {"product": "CPWI v2 (continuous, Earth Engine)", "higher_is_wetter": True, "source": "Google Earth Engine, legacy/gee_code.txt",
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "crs": crs, "resolution_m": RESOLUTION_M, "bounds": list(grid.bounds),
            "primary_window": list(primary), "fallback_window": list(fallback), "ee_project": project,
            "valid_fraction": round(valid / (grid.width * grid.height), 4), "deviations": []}
    Path(str(out) + ".provenance.json").write_text(json.dumps(prov, indent=2))
    return prov
