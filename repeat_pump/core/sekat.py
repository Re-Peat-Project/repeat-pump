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

from .config import InputError, require


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


def respace(rows: list[dict], existing_pos: dict, canals: gpd.GeoDataFrame, dA: float) -> None:
    """Recompute ``js_m`` (distance to the previous sekat downstream, new or existing) and the height ``ts_m`` after sekat were dropped or
    added, so every proposal's spacing and height describe the final layout."""
    depth = dict(zip(canals["canal_id"], canals["depth_m"] if "depth_m" in canals else [np.nan] * len(canals)))
    by_canal: dict = {}
    for r in rows:
        by_canal.setdefault(r["canal_id"], []).append(r)
    for cid, rs in by_canal.items():
        positions = sorted([r["dist_down_m"] for r in rs] + list(existing_pos.get(cid, [])))
        dk = depth.get(cid, np.nan)
        for r in rs:
            before = [q for q in positions if q < r["dist_down_m"] - 1e-9]
            js = r["dist_down_m"] - (before[-1] if before else 0.0)
            ts = dk + js * r["i_lahan_pct"] / 100 - dA if dk == dk and dk is not None else np.nan
            r["js_m"] = float(js)
            r["ts_m"] = float(ts) if ts == ts else np.nan
            r["ts_flag"] = "" if ts == ts else "no_depth_dk"


def apply_sekat_edits(ctx, rows: list[dict], canals: gpd.GeoDataFrame, segs: gpd.GeoDataFrame, by_canal: dict, dA: float) -> tuple[list[dict], dict]:
    """Apply ``sekat.edits`` (points with ``action`` add or delete) to the proposals.

    * delete: the proposal nearest to the point, if one lies within ``sekat.snap_tolerance_m``, is dropped;
    * add: the point is snapped onto the nearest canal within the same distance; the sekat gets its chainage, land height and slope from
      the profile, is marked ``manual`` and is never refused for spacing (the person decided).
    Deletes are matched before adds are made, so an edits file can never delete its own additions. Unmatched edits are warned about.
    """
    from .io import read_vector
    cfg, sk = ctx.cfg, ctx.cfg.sekat
    ed = read_vector(cfg, sk.edits.path, "sekat_edits", ctx, sk.edits.layer)
    if "action" not in ed:
        raise InputError("sekat_edits: needs an 'action' column with values add or delete")
    ed["action"] = ed["action"].astype(str).str.strip().str.lower()
    bad = sorted(set(ed["action"]) - {"add", "delete"})
    if bad:
        raise InputError(f"sekat_edits: unknown action value(s) {bad}; use add or delete")
    if not ed.geom_type.isin(["Point"]).all():
        raise InputError("sekat_edits: all features must be points")
    tol = sk.snap_tolerance_m
    rows = list(rows)
    stats = {"deleted": 0, "added": 0, "unmatched_deletes": 0, "unsnapped_adds": 0}
    for g in ed[ed["action"] == "delete"].geometry:
        near = [(r["geometry"].distance(g), r["sekat_pro_id"], i) for i, r in enumerate(rows) if r["geometry"].distance(g) <= tol]
        if near:
            rows.pop(min(near)[2])
            stats["deleted"] += 1
        else:
            stats["unmatched_deletes"] += 1
    canal_geom = dict(zip(canals["canal_id"], canals.geometry))
    canal_row = {c["canal_id"]: c for _, c in canals.iterrows()}
    tree = STRtree(list(canals.geometry))
    manual_k: dict = {}
    for g in sorted(ed[ed["action"] == "add"].geometry, key=lambda p: (round(p.x, 3), round(p.y, 3))):
        near = [j for j in tree.query(g.buffer(tol)) if canals.geometry.iloc[j].distance(g) <= tol]
        if not near:
            stats["unsnapped_adds"] += 1
            continue
        j = min(near, key=lambda j: (canals.geometry.iloc[j].distance(g), j))
        cid = canals["canal_id"].iloc[j]
        if cid not in by_canal:
            stats["unsnapped_adds"] += 1
            continue
        ln, L, direction = canal_geom[cid], canal_geom[cid].length, canals["direction"].iloc[j]
        d, z, i_loc = canal_arrays(by_canal[cid], direction, L)
        ch = float(ln.project(g))
        p = (L - ch) if direction == "forward" else ch
        i_here = float(np.interp(p, d, i_loc))
        sidx = segs[(segs.canal_id == cid) & (segs.chain_start_m <= ch + 1e-9) & (segs.chain_end_m >= ch - 1e-9)]
        manual_k[cid] = manual_k.get(cid, 0) + 1
        rows.append(dict(sekat_pro_id=f"M{cid}_{manual_k[cid]:03d}", canal_id=cid, seg_id=sidx["seg_id"].iloc[0] if len(sidx) else None,
                         chainage_m=ch, dist_down_m=float(p), z_land_m=float(np.interp(p, d, z)), i_lahan_pct=i_here * 100,
                         js_m=np.nan, js_req_m=float(min(dA / i_here, sk.max_spacing_m) if i_here > 1e-9 else sk.max_spacing_m),
                         ts_m=np.nan, ts_flag="no_depth_dk",
                         sekat_type="leaky/reinforced" if i_here * 100 >= sk.slope_reinforced_pct else "standard", manual=True,
                         geometry=ln.interpolate(ch)))
        stats["added"] += 1
    if stats["unmatched_deletes"]:
        ctx.warn(f"Stage 7: {stats['unmatched_deletes']} sekat edit(s) to delete matched no proposed sekat within {tol:g} m")
    if stats["unsnapped_adds"]:
        ctx.warn(f"Stage 7: {stats['unsnapped_adds']} sekat edit(s) to add are more than {tol:g} m from any canal and were skipped")
    return rows, stats


def canal_arrays(prof: pd.DataFrame, direction: str, length: float):
    """Profile re-expressed as distance from the downstream end."""
    p = prof.sort_values("station_m")
    s, z, i = p["station_m"].to_numpy(), p["z_land_m"].to_numpy(), p["i_lahan_m_m"].to_numpy()
    if direction == "forward":          # downstream = end of the digitised line
        return (length - s)[::-1], z[::-1], i[::-1]
    return s, z, i


def balance(ctx, pr: gpd.GeoDataFrame, canals: gpd.GeoDataFrame, prof: pd.DataFrame, ex_rows: list):
    """Keep the fewest proposed sekat that give ``sekat.target_rise_share`` of the canal rewetting all of them give.

    Rewetting is the canal-rise objective of Stage 12 [Urzainki2020]: a block holds water at its land level minus ``dA`` and
    raises every canal station upstream of it up to that level, from a dry-season level ``balance_drawdown_m`` below the land.
    Blocks are ranked by the extra rise each adds (existing sekat already in place), and the ranked list is cut where the
    share is reached. Returns (kept, low benefit); both carry benefit_rank, gain_m2 (rise x canal length) and cum_share."""
    from . import blockopt as bo
    sk = ctx.cfg.sekat
    require(sk, ["balance_drawdown_m"], "Stage 7", "sekat")
    share = 1.0 if sk.target_rise_share is None else sk.target_rise_share
    if not 0 < share <= 1:
        raise InputError(f"Stage 7: sekat.target_rise_share must be between 0 and 1, not {sk.target_rise_share}")
    dA, step = sk.dA_m, ctx.cfg.profiles.sample_step_m
    net = bo.CanalNet.from_profiles(canals, prof)
    base = net.z_land - sk.balance_drawdown_m
    fixed: dict = {}
    for r in ex_rows:
        n = net.node_at(r["canal_id"], r["chainage_m"]) if r.get("snapped") else None
        if n is not None:
            fixed[n] = max(fixed.get(n, -np.inf), float(net.z_land[n] - dA))
    pr = pr.reset_index(drop=True)
    nodes = [net.node_at(c, ch) for c, ch in zip(pr["canal_id"], pr["chainage_m"])]
    ok = [i for i, n in enumerate(nodes) if n is not None]
    order = bo.greedy_rank(net, base, [nodes[i] for i in ok], np.array([net.z_land[nodes[i]] - dA for i in ok]), fixed)
    total = sum(g for _, g in order)
    pr["benefit_rank"], pr["gain_m2"], pr["cum_share"] = len(pr) + 1, 0.0, 1.0
    cum = 0.0
    for rank, (j, g) in enumerate(order, 1):
        cum += g
        i = ok[j]
        pr.loc[i, ["benefit_rank", "gain_m2", "cum_share"]] = [rank, g * step, cum / total if total > 0 else 1.0]
    # keep every block up to and including the one that reaches the share
    reach = pr.loc[pr["cum_share"] >= share - 1e-9, "benefit_rank"].min()
    if sk.max_blocks is not None:                       # the budget cap wins over the share
        reach = min(reach, int(sk.max_blocks))
    keep = pr["benefit_rank"] <= reach
    kept, low = pr[keep].copy(), pr[~keep].copy()
    if total <= 0:
        ctx.warn("Stage 7: the proposed sekat raise no canal water (sekat.balance_drawdown_m is not larger than sekat.dA_m); all are kept")
        return pr, pr.iloc[0:0]
    ctx.report["sekat_balance"] = dict(head_rule=len(pr), kept=len(kept), low_benefit=len(low), target_rise_share=sk.target_rise_share,
                                       max_blocks=sk.max_blocks, share_kept=round(float(kept["gain_m2"].sum()) / (total * step), 3) if total > 0 else None,
                                       rise_m2_all=round(total * step), rise_m2_kept=round(float(kept["gain_m2"].sum())))
    ctx.log.info("Stage 7: %d of %d head-rule sekat give %.0f %% of the canal rewetting%s; %d moved to sekat_low_benefit",
                 len(kept), len(pr), 100 * float(kept["gain_m2"].sum()) / (total * step) if total > 0 else 100,
                 f" (budget cap {sk.max_blocks})" if sk.max_blocks is not None and len(kept) == sk.max_blocks else "", len(low))
    rows = kept.to_dict("records")
    respace(rows, {c: [r["dist_down_m"] for r in ex_rows if r.get("snapped") and r["canal_id"] == c and "dist_down_m" in r]
                   for c in kept["canal_id"].unique()}, canals, dA)
    kept = gpd.GeoDataFrame(rows, geometry="geometry", crs=pr.crs)
    ctx.write_layer("sekat_reach", reach_lines(ctx, net, base, [(nodes[i], float(net.z_land[nodes[i]] - dA), pid) for i, pid in
                                                          sorted(((i, r["sekat_pro_id"]) for i, r in pr[keep].iterrows() if nodes[i] is not None),
                                                                 key=lambda t: pr.loc[t[0], "benefit_rank"])], fixed, canals, pr.loc[keep]), "7")
    return kept.sort_values("benefit_rank").reset_index(drop=True), low.sort_values("benefit_rank").reset_index(drop=True)


def reach_lines(ctx, net, base: np.ndarray, blocks: list, fixed: dict, canals: gpd.GeoDataFrame, kept: pd.DataFrame) -> gpd.GeoDataFrame:
    """The canal stretch in which each kept sekat holds the water: the stations whose final level that block sets (existing sekat
    built first, then the kept ones in order of benefit), as lines drawn from the block upstream, the way the water backs up.

    Columns: sekat_pro_id, benefit_rank, canal_id, length_m, rise_m (mean rise over the dry-season level), depth_m (mean water level
    below the land), burnt_frac (share of the length inside the burn-area layer; null without one)."""
    from shapely.ops import substring
    wt, owner = net.owners(base, [(n, c, "existing") for n, c in fixed.items()] + blocks)
    rank = dict(zip(kept["sekat_pro_id"], kept["benefit_rank"]))
    rows = []
    for cid, line, direction in zip(canals["canal_id"], canals.geometry, canals["direction"]):
        if cid not in net.lookup:
            continue
        s, idx = net.lookup[cid]
        i = 0
        while i < len(s) - 1:
            lab = owner[idx[i]]
            j = i
            while j < len(s) - 1 and lab not in (None, "existing") and owner[idx[j + 1]] == lab:
                j += 1
            if j > i:
                seg = substring(line, float(s[i]), float(s[j]))
                if direction == "forward":                  # digitised downstream: the water backs up against the digitising
                    seg = seg.reverse()
                k = idx[i:j + 1]
                rows.append(dict(sekat_pro_id=lab, benefit_rank=int(rank.get(lab, 0)), canal_id=cid, length_m=float(seg.length),
                                 rise_m=float(np.nanmean(wt[k] - base[k])), depth_m=float(np.nanmean(net.z_land[k] - wt[k])), geometry=seg))
            i = max(j, i + 1)
    out = gpd.GeoDataFrame(rows, geometry="geometry", crs=ctx.crs) if rows else gpd.GeoDataFrame(
        {"sekat_pro_id": [], "benefit_rank": [], "length_m": []}, geometry=[], crs=ctx.crs)
    out["burnt_frac"] = np.nan
    if len(out) and ctx.has_layer("inputs_clipped_burn_area"):
        ba = ctx.read_layer("inputs_clipped_burn_area")
        if len(ba):
            burn = ba.geometry.make_valid().union_all()
            out["burnt_frac"] = [g.intersection(burn).length / g.length if g.length else np.nan for g in out.geometry]
    return out


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
        excl = 0
        if cfg.topology.canal_classes and ctx.has_layer("inputs_clipped_canals"):   # on a canal the class filter left out?
            allc = ctx.read_layer("inputs_clipped_canals")
            tree = STRtree(list(allc.geometry))
            for r in ex_rows:
                if not r["snapped"] and len(tree.query(r["geometry"].buffer(sk.snap_tolerance_m))):
                    excl += 1
        ctx.warn(f"Stage 7: {len(unsnapped)} existing sekat could not be snapped to a canal within {sk.snap_tolerance_m} m"
                 + (f"; {excl} of them lie on canal classes left out by topology.canal_classes" if excl else "") + f": {unsnapped[:10]}")

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
    edit_stats = None
    if sk.edits is not None:
        prop_rows, edit_stats = apply_sekat_edits(ctx, prop_rows, canals, segs, by_canal, dA)
        ctx.report["sekat_edits"] = edit_stats
        for cid, u in canal_upd.items():
            u["n_proposed"] = sum(1 for r in prop_rows if r["canal_id"] == cid)
    if sk.dedup_tol_m or sk.edits is not None:           # spacing and height of what is left, not of what was first proposed
        respace(prop_rows, {c: [r["dist_down_m"] for r in ex_rows if r["snapped"] and r["canal_id"] == c and "dist_down_m" in r] for c in canal_upd}, canals, dA)
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
    low = None
    if (sk.target_rise_share is not None or sk.max_blocks is not None) and len(pr_gdf):
        pr_gdf, low = balance(ctx, pr_gdf, canals, prof, ex_rows)
    ctx.write_layer("sekat_existing_assessed", ex_gdf, "7")
    if len(pr_gdf) and "manual" in pr_gdf:
        pr_gdf["manual"] = pr_gdf["manual"].fillna(False).astype(bool)
    elif len(pr_gdf):
        pr_gdf["manual"] = False
    ctx.write_layer("sekat_proposed", pr_gdf, "7")
    if low is not None:
        ctx.write_layer("sekat_low_benefit", low, "7")
    elif ctx.has_layer("sekat_low_benefit"):                # balance switched off since the last run: no stale leftovers
        ctx.write_layer("sekat_low_benefit", pr_gdf.iloc[0:0], "7")
    if low is None and ctx.has_layer("sekat_reach"):
        ctx.write_layer("sekat_reach", ctx.read_layer("sekat_reach").iloc[0:0], "7")
    ctx.write_layer("canals_clean", canals, "7")
    ctx.set_counts("7", existing=len(ex_rows), unsnapped=len(unsnapped), proposed=len(pr_gdf),
                   **({"head_rule": len(prop_rows), "low_benefit": len(low)} if low is not None else {}),
                   **({"edits_added": edit_stats["added"], "edits_deleted": edit_stats["deleted"]} if edit_stats else {}))
