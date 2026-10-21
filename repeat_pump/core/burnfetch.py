"""Burn frequency polygons from the MODIS MCD64A1 burned-area product (Planetary Computer STAC, no login), for the wizard's
"Load burn scars from the cloud" button. Output follows the ``burn_area`` input contract: polygons with an integer ``burn_freq``.

Method [Giglio2018]: ``Burn_Date`` is the day of year a 500 m cell burned (0 unburned, -1 unmapped, -2 water). For every year in the
window a cell counts as burned if any monthly product maps it burned; ``burn_freq`` is the number of such years. Cells are warped
(nearest) to a 100 m grid in the run CRS and vectorised, so edges follow the native ~463 m cells to within one grid step.

Limits, all written to the provenance file next to the output: 500 m cells miss small fires; smouldering and understory peat fires are
often not detected; a year with several fires still counts once; areas never mapped burned are simply absent from the layer.
It is a coarse automatic fallback for the burn-scar layers KLH normally provides, not a replacement for them.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio.features
from rasterio.enums import Resampling
from shapely.geometry import shape

from .cloudfetch import BandReader, FetchError, Grid, Opener, _gdal_env, _post_json, _progress

PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
PC_TOKEN = "https://planetarycomputer.microsoft.com/api/sas/v1/token"
COLLECTION = "modis-64A1-061"
GRID_M = 100.0
LAYER = "burn_area"
LIMITS = ["MODIS cells are about 463 m: small fires are missed",
          "smouldering and understory peat fires are often not detected",
          "a year with several fires counts once, so burn_freq is the number of years with a detected fire",
          "areas never mapped as burned are absent from the layer (stage 6 treats them as burn_freq 0)"]


_TOKENS: dict[str, tuple[float, str]] = {}
_TOKEN_LOCK = threading.Lock()
BURN_WORKERS = 8                  # the signing service rate-limits (429); one token per storage container is reused for every product


def _sign(href: str) -> str:
    """Append a read-only SAS token. Planetary Computer issues one per container, valid about an hour, so fetch it once and reuse it."""
    u = urllib.parse.urlparse(href)
    account, container = u.hostname.split(".")[0], u.path.lstrip("/").split("/")[0]
    key = f"{account}/{container}"
    with _TOKEN_LOCK:
        cached = _TOKENS.get(key)
        if cached is None or cached[0] < time.time():
            for wait in (0, 2, 6, 15):
                time.sleep(wait)
                try:
                    with urllib.request.urlopen(f"{PC_TOKEN}/{account}/{container}", timeout=60) as r:
                        tok = json.loads(r.read())["token"]
                    break
                except urllib.error.HTTPError as e:
                    if e.code != 429:
                        raise
            else:
                raise FetchError("Planetary Computer is rate limiting the sign-in request: wait a minute and try again")
            cached = _TOKENS[key] = (time.time() + 1800, tok)
    return f"{href}?{cached[1]}"


def stac_search(grid: Grid, years: tuple[int, int], post: Callable = _post_json) -> list[dict]:
    body = {"collections": [COLLECTION], "bbox": grid.wgs84_bbox(), "datetime": f"{years[0]}-01-01T00:00:00Z/{years[1]}-12-31T23:59:59Z", "limit": 100}
    items: list[dict] = []
    for _ in range(200):
        page = post(f"{PC_STAC}/search", body)
        items += page.get("features", [])
        nxt = next((l for l in page.get("links", []) if l.get("rel") == "next"), None)
        if not nxt:
            break
        body = nxt.get("body") or body
    return sorted({i["id"]: i for i in items}.values(), key=lambda i: i["id"])


def item_year(item: dict) -> int:
    return int((item["properties"].get("start_datetime") or item["properties"]["datetime"])[:4])


def burn_frequency(read_burn_date: list, years: list[int], shape_hw: tuple[int, int]) -> np.ndarray:
    """``read_burn_date`` is a list of (year, array of Burn_Date). Number of distinct years with a burn (>0) in each cell."""
    burned = {y: np.zeros(shape_hw, bool) for y in years}
    for y, arr in read_burn_date:
        burned[y] |= arr > 0
    return sum(b.astype("int16") for b in burned.values())


def to_polygons(freq: np.ndarray, grid: Grid) -> gpd.GeoDataFrame:
    """One polygon per connected region of equal ``burn_freq`` (> 0)."""
    geoms, vals = [], []
    for g, v in rasterio.features.shapes(freq, mask=freq > 0, transform=grid.transform, connectivity=4):
        geoms.append(shape(g))
        vals.append(int(v))
    return gpd.GeoDataFrame({"burn_freq": pd.Series(vals, dtype="int64")}, geometry=geoms, crs=grid.crs)


def fetch_burn_frequency(bounds, crs: str, out: str | Path, years: tuple[int, int], search: Callable = stac_search,
                         opener: Opener = BandReader, sign: Callable = _sign, workers: int = BURN_WORKERS) -> dict:
    """Write the ``burn_area`` layer (GeoPackage) over ``bounds`` (x0, y0, x1, y1 in ``crs``) for the inclusive year window.

    The years are a required input: which period matters is the team's decision. Returns the provenance dict, also written to
    ``<out>.provenance.json``.
    """
    if years[1] < years[0]:
        raise FetchError(f"the last year {years[1]} is before the first year {years[0]}")
    grid = Grid.make(bounds, crs, GRID_M)
    out = Path(out)
    _progress(0.0, "searching MODIS burned-area products")
    items = search(grid, years)
    if not items:
        raise FetchError(f"no MODIS MCD64A1 products over the area for {years[0]} to {years[1]}")
    got_years = sorted({item_year(i) for i in items})
    missing = [y for y in range(years[0], years[1] + 1) if y not in got_years]

    def read(it):
        with _gdal_env(), ExitStack() as es:
            href = sign(it["assets"]["Burn_Date"]["href"])
            rd = opener(es, href, grid, Resampling.nearest, None)
            from rasterio.windows import Window
            return item_year(it), rd.read(Window(0, 0, grid.width, grid.height))

    with ThreadPoolExecutor(workers) as pool:
        reads = []
        for k, r in enumerate(pool.map(read, items)):
            reads.append(r)
            _progress(0.05 + 0.85 * (k + 1) / len(items), f"product {k + 1} of {len(items)}")
    freq = burn_frequency(reads, list(range(years[0], years[1] + 1)), (grid.height, grid.width))
    polys = to_polygons(freq, grid)
    polys["years_n"] = years[1] - years[0] + 1
    out.parent.mkdir(parents=True, exist_ok=True)
    if polys.empty:       # write an empty layer with the right columns so the file is still a valid burn_area input
        polys = gpd.GeoDataFrame({"burn_freq": pd.Series([], dtype="int64"), "years_n": pd.Series([], dtype="int64")}, geometry=[], crs=crs)
    polys.to_file(out, layer=LAYER, driver="GPKG")
    _progress(1.0, "done")
    prov = {"product": "Burn frequency from MODIS MCD64A1 (coarse, automatic)", "source": "Planetary Computer STAC, collection " + COLLECTION,
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "crs": crs, "grid_m": GRID_M, "bounds": list(grid.bounds),
            "years": list(years), "years_without_products": missing, "products": len(items), "polygons": int(len(polys)),
            "burned_fraction": round(float((freq > 0).mean()), 4), "max_burn_freq": int(freq.max()), "layer": LAYER, "deviations": LIMITS}
    Path(str(out) + ".provenance.json").write_text(json.dumps(prov, indent=2))
    return prov
