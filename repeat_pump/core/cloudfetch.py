"""Download-free build of a moisture raster from open cloud-optimised imagery (STAC), for the wizard's "Load from cloud" button.

Open backend: Sentinel-2 L2A from the Earth Search STAC API (AWS, no login). Windowed reads of the COGs are warped onto one
grid in the run CRS (10 m) and composited per tile, so memory stays bounded. The output is the *Sentinel-2 wetness index*
(NDWI and NDMI terms of CPWI, see ``cpwi.s2_wetness``), a 0 to 1 raster where higher means wetter.

It is an approximation of the team's Earth Engine CPWI v2 (``legacy/gee_code.txt``). Deviations, all recorded in the
provenance file written next to the raster:
* cloud masking uses the Scene Classification Layer (``SCL_CLEAR`` classes) instead of Google's Cloud Score+;
* there is no Sentinel-1 term (no open, calibrated, terrain-corrected Sentinel-1 is available over Kalimantan), so the
  NDWI and NDMI weights are renormalised;
* the median of an even number of scenes averages the middle two.
Reflectance is ``DN * scale + offset`` with the scale and offset read from each asset's ``raster:bands`` metadata, so the
processing-baseline offset (-0.1) is applied where the catalogue declares it; a scene without it is refused.

References: [McFeeters1996] NDWI, [Gao1996] NDMI. Method source: ``legacy/gee_code.txt``.
"""
from __future__ import annotations

import json
import math
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds
from rasterio.windows import Window

from . import cpwi

EARTH_SEARCH = "https://earth-search.aws.element84.com/v1"
S2_COLLECTION = "sentinel-2-c1-l2a"
RESOLUTION_M = 10.0
NODATA = -9999.0
SCL_CLEAR = (4, 5, 6, 7)          # vegetation, not vegetated, water, unclassified
WORKERS = 24                      # parallel HTTP reads: the COG reads are latency-bound, not CPU-bound
BANDS = {"b3": "green", "b4": "red", "b8": "nir", "b11": "swir16"}
OUTPUT_LABEL = "S2 wetness index (NDWI + NDMI of CPWI v2, open Sentinel-2 only)"


class FetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class Grid:
    bounds: tuple[float, float, float, float]    # snapped outwards to whole pixels
    crs: str
    res: float = RESOLUTION_M

    @classmethod
    def make(cls, bounds, crs: str, res: float = RESOLUTION_M) -> "Grid":
        x0, y0, x1, y1 = bounds
        if not (x1 > x0 and y1 > y0):
            raise FetchError(f"empty area: {bounds}")
        return cls((math.floor(x0 / res) * res, math.floor(y0 / res) * res, math.ceil(x1 / res) * res, math.ceil(y1 / res) * res), crs, res)

    @property
    def width(self) -> int:
        return int(round((self.bounds[2] - self.bounds[0]) / self.res))

    @property
    def height(self) -> int:
        return int(round((self.bounds[3] - self.bounds[1]) / self.res))

    @property
    def transform(self):
        return from_origin(self.bounds[0], self.bounds[3], self.res, self.res)

    def wgs84_bbox(self) -> list[float]:
        return list(transform_bounds(self.crs, "EPSG:4326", *self.bounds, densify_pts=21))


def tile_size(n_scenes: int, memory_budget_gb: float) -> int:
    """Square tile edge (pixels, multiple of 64, 128 to 1024): four float32 band stacks plus the mask and working copies for every scene."""
    per_px = max(n_scenes, 1) * (4 * 4 + 1) * 3
    t = int(math.sqrt(memory_budget_gb * 1e9 / per_px))
    return max(128, min(1024, t // 64 * 64))


# ----------------------------------------------------------------------------- STAC search
def _post_json(url: str, body: dict, timeout: float = 60) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Accept": "application/geo+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def stac_search(grid: Grid, start: str, end: str, max_cloud_pct: float, post: Callable = _post_json,
                api: str = EARTH_SEARCH, collection: str = S2_COLLECTION) -> list[dict]:
    """All Sentinel-2 items over the grid between two dates (inclusive, YYYY-MM-DD) below the cloud-cover limit, sorted by id."""
    body = {"collections": [collection], "bbox": grid.wgs84_bbox(), "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z", "limit": 100,
            "query": {"eo:cloud_cover": {"lt": max_cloud_pct}}}
    items: list[dict] = []
    for _ in range(200):                      # pages; 200 x 100 scenes is far beyond any real search
        page = post(f"{api}/search", body)
        items += page.get("features", [])
        nxt = next((l for l in page.get("links", []) if l.get("rel") == "next"), None)
        if not nxt:
            break
        body = nxt.get("body") or body
    return sorted({i["id"]: i for i in items}.values(), key=lambda i: i["id"])


def asset_scaling(item: dict, key: str) -> tuple[float, float]:
    """``(scale, offset)`` of an asset from its ``raster:bands`` metadata; refuses when the catalogue does not declare it."""
    rb = (item["assets"].get(key) or {}).get("raster:bands")
    if not rb or "scale" not in rb[0]:
        raise FetchError(f"{item['id']}: asset {key!r} has no raster:bands scale/offset, so the reflectance cannot be computed reliably")
    return float(rb[0]["scale"]), float(rb[0].get("offset", 0.0))


# ----------------------------------------------------------------------------- windowed reads
class BandReader:
    """One COG warped lazily onto the grid; ``read(window)`` returns raw values (0 = no data)."""

    def __init__(self, stack: ExitStack, href: str, grid: Grid, resampling: Resampling):
        src = stack.enter_context(rasterio.open(href))
        self._vrt = stack.enter_context(WarpedVRT(src, crs=grid.crs, transform=grid.transform, width=grid.width, height=grid.height,
                                                  resampling=resampling, src_nodata=0, nodata=0))

    def read(self, window: Window) -> np.ndarray:
        return self._vrt.read(1, window=window)


Opener = Callable[[ExitStack, str, Grid, Resampling], BandReader]


def _gdal_env():
    return rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff", GDAL_HTTP_MAX_RETRY="3",
                        GDAL_HTTP_RETRY_DELAY="2", GDAL_HTTP_MULTIPLEX="YES", VSI_CACHE="TRUE")


def _progress(fraction: float, text: str) -> None:
    if os.environ.get("REPEAT_PUMP_PROGRESS") == "1":
        print(f"@@progress|0|{min(max(fraction, 0.0), 1.0):.3f}|{text.replace('|', '/')}", flush=True)


# ----------------------------------------------------------------------------- composite
def scene_reflectance(readers: dict[str, BandReader], scaling: dict[str, tuple[float, float]], window: Window) -> Optional[dict[str, np.ndarray]]:
    """Cloud-masked reflectance of one scene on one window (NaN = masked), or ``None`` when nothing is clear."""
    scl = readers["scl"].read(window)
    clear = np.isin(scl, SCL_CLEAR)
    if not clear.any():
        return None
    out = {}
    for k in BANDS:
        dn = readers[k].read(window)
        scale, offset = scaling[k]
        refl = dn.astype("float32") * scale + offset
        out[k] = np.where(clear & (dn > 0), refl, np.nan).astype("float32")
    # every band must be valid together, as in the Earth Engine script where one mask is applied to the whole image
    ok = np.all([np.isfinite(v) for v in out.values()], axis=0)
    return {k: np.where(ok, v, np.nan) for k, v in out.items()} if ok.any() else None


def composite_tile(scenes: list[dict[str, np.ndarray]], primary: list[bool]) -> Optional[dict[str, np.ndarray]]:
    """Median reflectance per band: the primary-window median, with gaps filled from the median of all scenes (fallback window)."""
    if not scenes:
        return None
    out = {}
    for k in BANDS:
        everything = cpwi.median_composite([s[k] for s in scenes])
        prim = [s[k] for s, p in zip(scenes, primary) if p]
        if prim:
            first = cpwi.median_composite(prim)
            everything = np.where(np.isnan(first), everything, first)
        out[k] = everything
    return out


def fetch_s2_wetness(bounds, crs: str, out: str | Path, primary: tuple[str, str], fallback: tuple[str, str],
                     max_cloud_pct: Optional[float] = None, memory_budget_gb: float = 4.0,
                     search: Callable = stac_search, opener: Opener = BandReader, workers: int = WORKERS) -> dict:
    """Build the S2 wetness index over ``bounds`` (x0, y0, x1, y1 in ``crs``) and write it to ``out`` (float32 GeoTIFF, nodata -9999).

    ``primary`` and ``fallback`` are (start, end) dates; the fallback window must contain the primary one. They are required
    inputs: dates belong to the site and year, not to the method. Returns the provenance dict (also written to ``<out>.provenance.json``).
    """
    p = cpwi.LEGACY
    max_cloud = p.max_scene_cloud_pct if max_cloud_pct is None else max_cloud_pct
    if not (fallback[0] <= primary[0] and primary[1] <= fallback[1]):
        raise FetchError(f"the fallback window {fallback} must contain the primary window {primary}")
    grid = Grid.make(bounds, crs)
    out = Path(out)
    _progress(0.0, "searching Sentinel-2 scenes")
    items = search(grid, fallback[0], fallback[1], max_cloud)
    if not items:
        raise FetchError(f"no Sentinel-2 scenes over the area between {fallback[0]} and {fallback[1]} with cloud cover below {max_cloud:g} %")
    is_primary = [primary[0] <= i["properties"]["datetime"][:10] <= primary[1] for i in items]
    if not any(is_primary):
        raise FetchError(f"no Sentinel-2 scenes in the primary window {primary[0]} to {primary[1]} (the fallback window has {len(items)})")
    scalings = [{k: asset_scaling(i, a) for k, a in BANDS.items()} for i in items]
    for i in items:
        if "scl" not in i["assets"]:
            raise FetchError(f"{i['id']}: no scene classification (scl) asset")
    T = tile_size(len(items), memory_budget_gb)
    out.parent.mkdir(parents=True, exist_ok=True)
    prof = dict(driver="GTiff", height=grid.height, width=grid.width, count=1, dtype="float32", crs=grid.crs, transform=grid.transform,
                nodata=NODATA, compress="deflate", tiled=True, blockxsize=256, blockysize=256)
    tiles = [Window(c, r, min(T, grid.width - c), min(T, grid.height - r)) for r in range(0, grid.height, T) for c in range(0, grid.width, T)]
    valid_px = 0
    def open_scene(it):
        with _gdal_env():
            es = ExitStack()
            keys = {**BANDS, "scl": "scl"}
            try:
                return es, {k: opener(es, it["assets"][a]["href"], grid, Resampling.nearest if k == "scl" else Resampling.bilinear) for k, a in keys.items()}
            except BaseException:
                es.close()
                raise

    def read_scene(args):
        rd, sc, win = args
        with _gdal_env():
            return scene_reflectance(rd, sc, win)

    with ExitStack() as stack, ThreadPoolExecutor(workers) as pool, rasterio.open(out, "w", **prof) as dst:
        opened = []
        for k, (es, rd) in enumerate(pool.map(open_scene, items)):
            opened.append(rd)
            stack.enter_context(es)
            _progress(0.02 * (k + 1) / len(items), f"opening scene {k + 1} of {len(items)}")
        for n, win in enumerate(tiles):
            _progress(0.02 + 0.96 * n / len(tiles), f"tile {n + 1} of {len(tiles)}, {len(items)} scenes")
            refls = list(pool.map(read_scene, [(rd, sc, win) for rd, sc in zip(opened, scalings)]))
            got = [r for r in refls if r is not None]
            flags = [p_ for r, p_ in zip(refls, is_primary) if r is not None]
            comp = composite_tile(got, flags)
            if comp is None:
                arr = np.full((int(win.height), int(win.width)), np.nan, "float32")
            else:
                ndwi, ndmi, _ndvi = cpwi.s2_indices(comp["b3"], comp["b4"], comp["b8"], comp["b11"])
                arr = cpwi.s2_wetness(ndwi, ndmi, p)
            valid_px += int(np.isfinite(arr).sum())
            dst.write(np.where(np.isfinite(arr), arr, NODATA).astype("float32"), 1, window=win)
    _progress(1.0, "done")
    total = grid.width * grid.height
    prov = {
        "product": OUTPUT_LABEL, "higher_is_wetter": True, "source": "Earth Search STAC (Sentinel-2 L2A collection 1)", "stac_collection": S2_COLLECTION,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "crs": crs, "resolution_m": RESOLUTION_M,
        "bounds": list(grid.bounds), "primary_window": list(primary), "fallback_window": list(fallback), "max_scene_cloud_pct": max_cloud,
        "scenes_total": len(items), "scenes_primary": int(sum(is_primary)), "scene_ids": [i["id"] for i in items],
        "valid_fraction": round(valid_px / total, 4), "tile_px": T,
        "method": "legacy/gee_code.txt CPWI v2, NDWI and NDMI terms; weights renormalised to " f"{p.w_ndwi / (p.w_ndwi + p.w_ndmi):.2f}/{p.w_ndmi / (p.w_ndwi + p.w_ndmi):.2f}",
        "deviations": ["cloud mask: Scene Classification Layer classes " + ",".join(map(str, SCL_CLEAR)) + " instead of Cloud Score+ (cs_cdf >= 0.60)",
                       "no Sentinel-1 term (weight 0.35 of CPWI dropped, others renormalised)",
                       "median of an even scene count averages the two middle values"],
    }
    Path(str(out) + ".provenance.json").write_text(json.dumps(prov, indent=2))
    return prov
