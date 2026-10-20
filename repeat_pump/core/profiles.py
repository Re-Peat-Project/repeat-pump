"""Stage 5: along-canal land profiles from the UNCONDITIONED DTM.

The canal centreline in a LiDAR DTM is canal bed, so land elevation is sampled on
lines offset by ``profiles.bank_offsets_m`` on both sides, median-combined, then
median-filtered along the canal (spec Stage 5). Slope is derived from this land
profile, never from the burned DTM (legacy rule). Flow direction of each canal
comes from the profile trend; flat canals (|dz| < RMSE) are resolved by network
distance to the nearest river point (Dijkstra1959).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from scipy.ndimage import map_coordinates, median_filter
from shapely.geometry import Point

from .network import endpoint_distance_to_rivers, river_canal_points


def stations(length: float, step: float) -> np.ndarray:
    s = np.arange(0.0, length, step)
    return np.append(s, length) if length - (s[-1] if len(s) else 0) > 1e-9 else s


def _tangent_normal(line, s: float, h: float):
    a, b = line.interpolate(max(s - h, 0.0)), line.interpolate(min(s + h, line.length))
    dx, dy = b.x - a.x, b.y - a.y
    n = float(np.hypot(dx, dy)) or 1.0
    return dx / n, dy / n


def sample_profile(src, line, step: float, offsets: list[float]) -> tuple[np.ndarray, np.ndarray]:
    """Median land elevation at each station across both banks (nan where no data)."""
    s = stations(line.length, step)
    pad = max(offsets) + 2 * src.res[0]
    minx, miny, maxx, maxy = line.bounds
    win = rasterio.windows.from_bounds(minx - pad, miny - pad, maxx + pad, maxy + pad, src.transform)
    win = win.round_offsets().round_lengths().intersection(rasterio.windows.Window(0, 0, src.width, src.height))
    arr = src.read(1, window=win).astype("float64")
    if src.nodata is not None:
        arr[arr == src.nodata] = np.nan
    tr = src.window_transform(win)
    cols_all, rows_all = [], []
    h = max(step, 1.0)
    for st in s:
        tx, ty = _tangent_normal(line, st, h)
        nx_, ny_ = -ty, tx
        p = line.interpolate(st)
        for off in offsets:
            for sg in (-1, 1):
                x, y = p.x + sg * off * nx_, p.y + sg * off * ny_
                cols_all.append((x - tr.c) / tr.a - 0.5)
                rows_all.append((y - tr.f) / tr.e - 0.5)
    vals = map_coordinates(arr, [np.array(rows_all), np.array(cols_all)], order=1, mode="nearest", cval=np.nan)
    vals = vals.reshape(len(s), 2 * len(offsets))
    with np.errstate(all="ignore"):
        z = np.nanmedian(vals, axis=1)
    return s, z


def smooth(z: np.ndarray, step: float, window_m: float) -> np.ndarray:
    ok = np.isfinite(z)
    if ok.sum() == 0:
        return z
    zi = np.interp(np.arange(len(z)), np.nonzero(ok)[0], z[ok])
    k = max(1, int(round(window_m / step)))
    k += 1 - k % 2
    return median_filter(zi, size=k, mode="nearest")


def run(ctx) -> None:
    cfg = ctx.cfg
    pc = cfg.profiles
    rmse = cfg.inputs.dtm.vertical_rmse_m
    canals = ctx.read_layer("canals_clean")
    segs = ctx.read_layer("canal_segments")
    dtm = ctx.report["inputs"]["dtm"]  # unconditioned DTM, never the burned one
    prof_rows, can_rows = [], {}
    with rasterio.open(dtm) as src:
        for cid, line in zip(canals["canal_id"], canals.geometry):
            s, zr = sample_profile(src, line, pc.sample_step_m, pc.bank_offsets_m)
            z = smooth(zr, pc.sample_step_m, pc.smoothing_window_m)
            slope = np.gradient(z, s) if len(s) > 1 else np.zeros(len(s))   # signed dz/ds along digitised direction
            dz = float(z[-1] - z[0])
            if not np.isfinite(dz):
                direction, method = "ambiguous", "no_data"
            elif abs(dz) < rmse:
                direction, method = "ambiguous", "flat"
            else:
                direction, method = ("forward" if dz < 0 else "reverse"), "profile"
            can_rows[cid] = dict(direction=direction, direction_method=method, z_start_m=float(z[0]), z_end_m=float(z[-1]), s=s, z=z, slope=slope)
            for st, zz, sl in zip(s, z, slope):
                p = line.interpolate(st)
                prof_rows.append(dict(canal_id=cid, station_m=float(st), z_land_m=float(zz), dzds_m_m=float(sl),
                                      i_lahan_m_m=float(abs(sl)), i_lahan_pct=float(abs(sl) * 100), geometry=p))

    # resolve ambiguous direction by network distance to the nearest river point
    rivers = ctx.read_layer("inputs_clipped_rivers") if ctx.has_layer("inputs_clipped_rivers") else None
    rpts = river_canal_points(canals, rivers) if rivers is not None else None
    dist = endpoint_distance_to_rivers(canals, rpts) if rpts is not None and len(rpts) else {}
    n_unres = 0
    for cid, line in zip(canals["canal_id"], canals.geometry):
        r = can_rows[cid]
        if r["direction"] != "ambiguous":
            continue
        k0 = (round(line.coords[0][0], 3), round(line.coords[0][1], 3))
        k1 = (round(line.coords[-1][0], 3), round(line.coords[-1][1], 3))
        d0, d1 = dist.get(k0, np.inf), dist.get(k1, np.inf)
        if np.isfinite(d0) or np.isfinite(d1):
            if d0 != d1:
                r["direction"], r["direction_method"] = ("reverse" if d0 < d1 else "forward"), "network"
                continue
        r["direction_method"] = "unresolved"
        n_unres += 1
    if n_unres:
        ctx.warn(f"Stage 5: {n_unres} canal(s) with ambiguous flow direction could not be resolved (no river connection); treated as forward")

    # canal-level attributes
    for c in ("direction", "direction_method", "z_start_m", "z_end_m"):
        canals[c] = [can_rows[cid][c] for cid in canals["canal_id"]]
    for cid in canals["canal_id"]:
        if can_rows[cid]["direction"] == "ambiguous":
            can_rows[cid]["direction"] = "forward"
    canals["direction"] = [can_rows[cid]["direction"] for cid in canals["canal_id"]]

    # segment-level attributes
    z0, z1, zu, zd, im = [], [], [], [], []
    for cid, a, b in zip(segs["canal_id"], segs["chain_start_m"], segs["chain_end_m"]):
        r = can_rows[cid]
        za, zb = float(np.interp(a, r["s"], r["z"])), float(np.interp(b, r["s"], r["z"]))
        m = (r["s"] >= a - 1e-9) & (r["s"] <= b + 1e-9)
        i_mean = float(np.abs(r["slope"][m]).mean()) if m.any() else abs(zb - za) / max(b - a, 1e-9)
        z0.append(za); z1.append(zb); im.append(i_mean)
        down_is_end = r["direction"] == "forward"
        zd.append(zb if down_is_end else za); zu.append(za if down_is_end else zb)
    segs["z_c0_m"], segs["z_c1_m"], segs["z_up_m"], segs["z_down_m"] = z0, z1, zu, zd
    segs["i_lahan_mean"] = im
    segs["i_lahan_pct"] = np.array(im) * 100
    segs["direction"] = [can_rows[c]["direction"] for c in segs["canal_id"]]

    ctx.write_layer("canal_profiles", gpd.GeoDataFrame(prof_rows, geometry="geometry", crs=ctx.crs), "5")
    ctx.write_layer("canals_clean", canals, "5")
    ctx.write_layer("canal_segments", segs, "5")
    ctx.set_counts("5", stations=len(prof_rows), ambiguous_unresolved=n_unres)
