"""Stage 7: sekat (canal block) gap analysis and head-based placement.

Head-based design from KHG-SKSS-2021 with Ritzema2014 and Dohong2018; dA per PP57-2016:
 * required spacing  js = dA / i_lahan   (clipped to ``max_spacing_m``)
 * required count    n_req = ceil((z_up - z_down) / dA)
 * IPG = n_existing / n_req  (> 1 adequate, KHG-SKSS-2021 section 5.3.4)
 * new sekat where the land rises dA since the previous sekat, walking upstream
   (equivalent to crossing a dA contour without generating vector contours)
 * height  ts = dk + js * tan(alpha) - dA   (KHG-SKSS-2021 eq. 4.18)
"""
from __future__ import annotations

import math

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import STRtree
from shapely.geometry import Point

from .config import require


def place_sekat(d: np.ndarray, z: np.ndarray, dA: float, existing: list[float], min_spacing: float, fine: float,
                min_new: float | None = None) -> list[tuple[float, float]]:
    """Walk from the downstream end (d=0) upstream and return [(d_m, z_m)] of new sekat.

    ``d`` ascending distance from the downstream end, ``z`` land elevation. A sekat is
    placed when z has risen ``dA`` above the previous sekat (existing sekat reset the
    baseline). New sekat never lie within ``min_spacing`` of an existing one. With ``min_new`` the next new sekat is also at least
    that far along the canal from the previous new one (legacy JARAK_MIN); off by default because it overrides the head rule.
    """
    if len(d) < 2:
        return []
    dense = np.arange(0.0, d[-1] + 1e-9, fine)
    zz = np.interp(dense, d, z)
    ex = sorted(e for e in existing if 0 <= e <= d[-1])
    out, exi, i, n = [], 0, 0, len(dense)
    z_prev = zz[0]
    while i < n:
        nxt = ex[exi] if exi < len(ex) else None
        hit = np.nonzero(zz[i:] - z_prev >= dA - 1e-9)[0]
        j = i + int(hit[0]) if hit.size else None
        if nxt is not None and (j is None or dense[j] > nxt):
            i = int(round(nxt / fine))
            z_prev = float(np.interp(nxt, d, z))
            exi += 1
            continue
        if j is None:
            break
        p = float(dense[j])
        if any(abs(p - e) < min_spacing for e in ex):
            i = j + 1
            continue
        out.append((p, float(zz[j])))
        z_prev = float(zz[j])
        i = j + 1 if not min_new else max(j + 1, int(math.ceil((p + min_new) / fine - 1e-9)))
    return out


def dedup_proposed(rows: list[dict], existing: list, tol: float) -> tuple[list[dict], int]:
    """Drop proposals within ``tol`` of an existing sekat, or of an earlier proposal on a different canal (legacy DEDUP_TOL, which merged
    points that different routes put at the same junction). Rows are taken in ``sekat_pro_id`` order, so the result is deterministic."""
    cell = lambda g: (int(g.x // tol), int(g.y // tol))
    grid: dict = {}
    for g in existing:
        grid.setdefault(cell(g), []).append((None, g))
    kept = []
    for r in sorted(rows, key=lambda r: r["sekat_pro_id"]):
        g = r["geometry"]
        cx, cy = cell(g)
        near = [(c, q) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for c, q in grid.get((cx + dx, cy + dy), []) if g.distance(q) <= tol]
        if any(c is None or c != r["canal_id"] for c, _ in near):
            continue
        kept.append(r)
        grid.setdefault((cx, cy), []).append((r["canal_id"], g))
    return kept, len(rows) - len(kept)


def canal_arrays(prof: pd.DataFrame, direction: str, length: float):
    """Profile re-expressed as distance from the downstream end."""
    p = prof.sort_values("station_m")
    s, z, i = p["station_m"].to_numpy(), p["z_land_m"].to_numpy(), p["i_lahan_m_m"].to_numpy()
    if direction == "forward":          # downstream = end of the digitised line
        return (length - s)[::-1], z[::-1], i[::-1]
    return s, z, i


def run(ctx) -> None:
    cfg = ctx.cfg
    sk = cfg.sekat
    require(sk, ["max_spacing_m", "snap_tolerance_m", "min_spacing_m"], "Stage 7", "sekat")
    dA, fine = sk.dA_m, cfg.profiles.sample_step_m / 10.0
    canals = ctx.read_layer("canals_clean")
    segs = ctx.read_layer("canal_segments")
    prof = ctx.read_layer("canal_profiles")
    existing = ctx.read_layer("inputs_clipped_sekat_existing")
    rmse = cfg.inputs.dtm.vertical_rmse_m
    ctree = STRtree(list(canals.geometry))
    by_canal = {c: g for c, g in prof.groupby("canal_id")}

    # --- snap existing sekat onto canals
    ex_rows, ex_d = [], {}
    for _, r in (existing.iterrows() if len(existing) else []):
        pt = r.geometry
        near = [j for j in ctree.query(pt.buffer(sk.snap_tolerance_m))]
        best = min(near, key=lambda j: canals.geometry.iloc[j].distance(pt), default=None)
        row = {c: r[c] for c in ("sekat_id", "has_gate", "crest_elev_m") if c in existing.columns}
        if best is None or canals.geometry.iloc[best].distance(pt) > sk.snap_tolerance_m:
            row.update(snapped=False, canal_id=None, chainage_m=np.nan, snap_dist_m=np.nan, geometry=pt)
        else:
            ln = canals.geometry.iloc[best]
            ch = float(ln.project(pt))
            row.update(snapped=True, canal_id=canals["canal_id"].iloc[best], chainage_m=ch, snap_dist_m=float(ln.distance(pt)), geometry=ln.interpolate(ch))
        ex_rows.append(row)
    unsnapped = [r["sekat_id"] for r in ex_rows if not r["snapped"]]
    if unsnapped:
        ctx.warn(f"Stage 7: {len(unsnapped)} existing sekat could not be snapped to a canal within {sk.snap_tolerance_m} m: {unsnapped[:10]}")

    prop_rows, canal_upd = [], {}
    for k, (_, c) in enumerate(canals.iterrows()):
        ctx.progress(k / max(len(canals), 1), f"canal {k + 1} of {len(canals)}")
        cid, L, direction = c["canal_id"], c.geometry.length, c["direction"]
        if cid not in by_canal:
            continue
        d, z, i_loc = canal_arrays(by_canal[cid], direction, L)
        z_down, z_up = float(z[0]), float(z[-1])
        n_req = max(0, math.ceil((z_up - z_down) / dA - 1e-9)) if np.isfinite(z_up - z_down) else 0
        flag = "adverse_profile" if (z_up - z_down) < -rmse else ""
        e_here = [r for r in ex_rows if r["snapped"] and r["canal_id"] == cid]
        ex_pos = [(L - r["chainage_m"]) if direction == "forward" else r["chainage_m"] for r in e_here]
        new = place_sekat(d, z, dA, ex_pos, sk.min_spacing_m, fine, sk.min_new_spacing_m)
        canal_upd[cid] = dict(n_req=n_req, n_existing=len(e_here), ipg=(len(e_here) / n_req if n_req > 0 else np.nan), n_proposed=len(new), sekat_flag=flag)
        for r, dpos in zip(e_here, ex_pos):
            r["dist_down_m"] = float(dpos)
        prev = 0.0
        all_pos = sorted([p for p, _ in new] + ex_pos)
        dk = c.get("depth_m", np.nan)
        for k, (p, zp) in enumerate(new):
            before = [q for q in all_pos if q < p]
            prev = before[-1] if before else 0.0
            js = p - prev
            i_here = float(np.interp(p, d, i_loc))
            ts = (dk + js * i_here - dA) if (dk == dk and dk is not None) else np.nan
            ch = (L - p) if direction == "forward" else p
            sidx = segs[(segs.canal_id == cid) & (segs.chain_start_m <= ch + 1e-9) & (segs.chain_end_m >= ch - 1e-9)]
            js_req = min(dA / i_here, sk.max_spacing_m) if i_here > 1e-9 else sk.max_spacing_m
            prop_rows.append(dict(sekat_pro_id=f"P{cid}_{k + 1:03d}", canal_id=cid, seg_id=sidx["seg_id"].iloc[0] if len(sidx) else None,
                                  chainage_m=float(ch), dist_down_m=float(p), z_land_m=float(zp), i_lahan_pct=i_here * 100,
                                  js_m=float(js), js_req_m=float(js_req), ts_m=float(ts) if ts == ts else np.nan,
                                  ts_flag="" if ts == ts else "no_depth_dk",
                                  sekat_type="leaky/reinforced" if i_here * 100 >= sk.slope_reinforced_pct else "standard",
                                  geometry=c.geometry.interpolate(ch)))
    n_dedup = 0
    if sk.dedup_tol_m and prop_rows:
        prop_rows, n_dedup = dedup_proposed(prop_rows, [r["geometry"] for r in ex_rows if r["snapped"]], sk.dedup_tol_m)
        for cid, u in canal_upd.items():
            u["n_proposed"] = sum(1 for r in prop_rows if r["canal_id"] == cid)
        if n_dedup:
            ctx.warn(f"Stage 7: {n_dedup} proposed sekat dropped as duplicates within {sk.dedup_tol_m:g} m of an existing sekat or one on another canal")
    for cid, u in canal_upd.items():
        for k, v in u.items():
            canals.loc[canals["canal_id"] == cid, k] = v
    for r in ex_rows:
        u = canal_upd.get(r["canal_id"], {})
        r["ipg_canal"] = u.get("ipg", np.nan); r["n_req_canal"] = u.get("n_req", np.nan)
    ex_gdf = gpd.GeoDataFrame(ex_rows, geometry="geometry", crs=ctx.crs) if ex_rows else gpd.GeoDataFrame(
        {"sekat_id": []}, geometry=[], crs=ctx.crs)
    pr_gdf = gpd.GeoDataFrame(prop_rows, geometry="geometry", crs=ctx.crs) if prop_rows else gpd.GeoDataFrame(
        {"sekat_pro_id": []}, geometry=[], crs=ctx.crs)
    ctx.write_layer("sekat_existing_assessed", ex_gdf, "7")
    ctx.write_layer("sekat_proposed", pr_gdf, "7")
    ctx.write_layer("canals_clean", canals, "7")
    ctx.set_counts("7", existing=len(ex_rows), unsnapped=len(unsnapped), proposed=len(prop_rows))
