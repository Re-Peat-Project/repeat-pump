"""Stage 2: canal topology cleaning.

Equivalent of GRASS ``v.clean tool=snap,break,rmdupl`` (Neteler2008) implemented with
shapely noding (``unary_union``), without GRASS. Nothing is deleted silently:
snapped gaps go to ``qa_topology_gaps`` and remaining dangles to ``qa_topology_dangles``.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely import STRtree
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points

import networkx as nx

from .config import InputError, require
from .network import river_sources


def explode_lines(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    g = gdf.copy()
    g["geometry"] = shapely.force_2d(g.geometry.values)
    g = g.explode(index_parts=False, ignore_index=True)
    g = g[g.geom_type == "LineString"]
    g = g[(~g.geometry.is_empty) & (g.geometry.length > 0)].reset_index(drop=True)
    return g


def snap_endpoints(lines: list[LineString], tol: float) -> tuple[list[LineString], list[dict]]:
    """Snap each endpoint onto the nearest *other* line within ``tol`` (Neteler2008)."""
    tree = STRtree(lines)
    out, gaps = [], []
    for i, ln in enumerate(lines):
        coords = list(ln.coords)
        for pos in (0, -1):
            p = Point(coords[pos])
            best = None
            for j in tree.query(p.buffer(tol)):
                if j == i:
                    continue
                d = lines[j].distance(p)
                if d <= tol and (best is None or d < best[0]):
                    best = (d, j)
            if best is not None and best[0] > 1e-9:
                q = nearest_points(lines[best[1]], p)[0]
                gaps.append({"canal_idx": i, "gap_m": float(best[0]), "geometry": LineString([p, q])})
                coords[pos] = (q.x, q.y)
        out.append(LineString(coords) if len(set(coords)) > 1 else ln)
    return out, gaps


def filter_canal_classes(raw: gpd.GeoDataFrame, classes: list[str], ctx) -> gpd.GeoDataFrame:
    """Keep the canals whose ``canal_class`` is listed (case and spaces ignored), as step 1.2 of the KLH guide does for primary and
    secondary canals. What is left out is counted per class in the report; the full set stays in ``inputs_clipped_canals`` because
    river mouths are found on it (step 8.2). Canals added by ``canal_edits`` are not filtered."""
    want = {c.strip().lower() for c in classes}
    cmap = {str(k).strip().lower(): str(v).strip().lower() for k, v in (ctx.cfg.topology.canal_class_map or {}).items()}
    cls = raw["canal_class"].astype(str).str.strip().str.lower()
    cls = cls.map(lambda v: cmap.get(v, cmap.get(v.removesuffix(".0"), v)))      # 1 and 1.0 are the same code
    keep = cls.isin(want) | cls.apply(lambda v: bool(want & set(v.split())))     # "Kanal Primer" counts as primer
    found = {k: int(v) for k, v in cls.value_counts().items()}
    dropped = {k: v for k, v in found.items() if k not in want}
    if not keep.any():
        raise InputError(f"Stage 2: no canal has a class in {sorted(want)}; the layer has {sorted(found)}")
    ctx.report["canal_class_filter"] = {"kept_classes": sorted(want), "kept": int(keep.sum()), "dropped": dropped}
    if dropped:
        ctx.warn(f"Stage 2: {sum(dropped.values())} canal piece(s) left out by the class filter ({', '.join(f'{k}: {v}' for k, v in sorted(dropped.items()))}); kept: {', '.join(sorted(want))}")
    absent = sorted(want - set(found))
    if absent:
        ctx.warn(f"Stage 2: canal class(es) {absent} are listed in topology.canal_classes but do not occur in the canal layer")
    return raw[keep].reset_index(drop=True)


def run(ctx) -> None:
    cfg = ctx.cfg
    require(cfg.topology, ["snap_tolerance_m"], "Stage 2", "topology")
    tol = cfg.topology.snap_tolerance_m
    raw = explode_lines(ctx.read_layer("inputs_clipped_canals"))
    if cfg.topology.canal_classes:
        raw = filter_canal_classes(raw, cfg.topology.canal_classes, ctx)
    attrs = [c for c in raw.columns if c != "geometry" and c not in ("run_name", "stage")]
    edit_rows = []
    if ctx.has_layer("inputs_clipped_canal_edits"):
        ed = explode_lines(ctx.read_layer("inputs_clipped_canal_edits")) if len(ctx.read_layer("inputs_clipped_canal_edits")) else None
        if ed is not None:
            keep = [True] * len(raw)
            for _, e in ed[ed["action"] == "delete"].iterrows():
                zone = e.geometry.buffer(tol)
                hit = [i for i, g in enumerate(raw.geometry) if keep[i] and g.within(zone)]
                for i in hit:
                    keep[i] = False
                edit_rows.append({"action": "delete", "n_affected": len(hit), "geometry": e.geometry})
                if not hit:
                    ctx.warn("Stage 2: a canal_edits 'delete' line matched no canal (it must lie along the canal, within the snap tolerance)")
            raw = raw[keep]
            adds = ed[ed["action"] == "add"]
            for _, e in adds.iterrows():
                edit_rows.append({"action": "add", "n_affected": 1, "geometry": e.geometry})
            if len(adds):
                cols = [c for c in raw.columns if c != "geometry"]
                add_df = adds.reindex(columns=cols + ["geometry"])
                raw = gpd.GeoDataFrame(pd.concat([raw, add_df], ignore_index=True), geometry="geometry", crs=ctx.crs)
            raw = raw.reset_index(drop=True)
    issues = []   # lines needing human attention; reported, never altered
    for g in raw.geometry:
        if not g.is_simple:
            issues.append({"issue": "self_intersection", "geometry": g.representative_point()})
        if g.is_closed:
            issues.append({"issue": "closed_loop", "geometry": Point(g.coords[0])})
    lines, gaps = snap_endpoints(list(raw.geometry), tol)

    # noding + duplicate removal: unary_union nodes at every intersection and dissolves overlaps
    noded = shapely.get_parts(shapely.unary_union(lines))
    noded = [g for g in noded if g.geom_type == "LineString" and g.length > 0]

    # carry attributes: each noded piece takes the attributes of the original line that covers it
    tree = STRtree(lines)
    rows = []
    for g in noded:
        mid = g.interpolate(0.5, normalized=True)
        cands = [j for j in tree.query(mid.buffer(1e-3)) if lines[j].distance(mid) < 1e-3]
        j = min(cands) if cands else int(tree.nearest(mid))
        rows.append({**{c: raw.iloc[j][c] for c in attrs}, "geometry": g})
    clean = gpd.GeoDataFrame(rows, geometry="geometry", crs=ctx.crs)

    # overshoot trimming: a short piece with one free end whose other end is a junction (degree >= 3)
    trimmed = []
    omax = cfg.topology.overshoot_max_m
    if omax is not None:
        deg = {}
        for g in clean.geometry:
            for c in (g.coords[0], g.coords[-1]):
                k = (round(c[0], 3), round(c[1], 3))
                deg[k] = deg.get(k, 0) + 1
        drop = []
        for idx, g in enumerate(clean.geometry):
            a, b = [(round(c[0], 3), round(c[1], 3)) for c in (g.coords[0], g.coords[-1])]
            lo, hi = sorted([deg[a], deg[b]])
            if g.length <= omax and lo == 1 and hi >= 3:
                drop.append(idx)
                trimmed.append({"length_m": float(g.length), "geometry": g})
        clean = clean.drop(index=drop).reset_index(drop=True)

    # stable canal_id: deterministic order from geometry, not row order
    def key(g):
        a, b = g.coords[0], g.coords[-1]
        lo, hi = sorted([a, b])
        return (round(lo[0], 3), round(lo[1], 3), round(hi[0], 3), round(hi[1], 3), round(g.length, 3))
    clean["_k"] = [key(g) for g in clean.geometry]
    clean = clean.sort_values("_k").drop(columns="_k").reset_index(drop=True)
    clean["canal_id"] = [f"C{i + 1:05d}" for i in range(len(clean))]
    clean["length_m"] = clean.geometry.length

    # dangles: degree-1 endpoints of the cleaned network (never removed)
    ends = {}
    for cid, g in zip(clean["canal_id"], clean.geometry):
        for c in (g.coords[0], g.coords[-1]):
            ends.setdefault((round(c[0], 3), round(c[1], 3)), []).append(cid)
    ctree = STRtree(list(clean.geometry))
    dang = []
    for (x, y), cids in ends.items():
        if len(cids) != 1:
            continue
        p = Point(x, y)
        others = [j for j in ctree.query(p.buffer(max(tol, 1.0) * 50)) if clean.canal_id[j] != cids[0]]
        d = min((clean.geometry[j].distance(p) for j in others), default=np.nan)
        dang.append({"canal_id": cids[0], "dist_nearest_m": float(d), "geometry": p})
    gdf_d = gpd.GeoDataFrame(dang, geometry="geometry", crs=ctx.crs) if dang else gpd.GeoDataFrame(
        {"canal_id": [], "dist_nearest_m": []}, geometry=[], crs=ctx.crs)
    gdf_g = gpd.GeoDataFrame(gaps, geometry="geometry", crs=ctx.crs) if gaps else gpd.GeoDataFrame(
        {"canal_idx": [], "gap_m": []}, geometry=[], crs=ctx.crs)
    # connectivity: components with no river connection can never be a pump route
    nk = lambda c: (round(c[0], 3), round(c[1], 3))
    NG = nx.Graph()
    for g in clean.geometry:
        NG.add_edge(nk(g.coords[0]), nk(g.coords[-1]))
    comp_of = {}
    for i, comp in enumerate(sorted(nx.connected_components(NG), key=lambda c: min(c)), start=1):
        for n in comp:
            comp_of[n] = i
    clean["component_id"] = [comp_of[nk(g.coords[0])] for g in clean.geometry]
    n_disc = 0
    empty = lambda k: gpd.GeoDataFrame({k: []}, geometry=[], crs=ctx.crs)
    qa = empty("canal_id")
    if ctx.has_layer("inputs_clipped_rivers") and len(clean):
        rp = river_sources(ctx, clean, ctx.read_layer("inputs_clipped_rivers"))
        with_river = {int(clean.loc[clean.canal_id == c, "component_id"].iloc[0]) for c in rp["canal_id"]} if len(rp) else set()
        clean["reaches_river"] = clean["component_id"].isin(with_river)
        disc = clean[~clean["reaches_river"]]
        n_disc = int(disc["component_id"].nunique())
        if n_disc:
            qa = disc[["canal_id", "component_id", "length_m", "geometry"]]
            ctx.warn(f"Stage 2: {n_disc} canal component(s) ({len(disc)} canals) have no connection to a river and can never be pump routes (qa_topology_disconnected)")
    else:
        ctx.report.setdefault("notes", []).append("Stage 2: no river layer, connectivity to rivers not checked")
    ctx.write_layer("qa_topology_disconnected", qa, "2")
    ctx.write_layer("qa_topology_issues", gpd.GeoDataFrame(issues, geometry="geometry", crs=ctx.crs) if issues else empty("issue"), "2")
    ctx.write_layer("qa_topology_edits", gpd.GeoDataFrame(edit_rows, geometry="geometry", crs=ctx.crs) if edit_rows else empty("action"), "2")
    ctx.write_layer("qa_topology_trimmed", gpd.GeoDataFrame(trimmed, geometry="geometry", crs=ctx.crs) if trimmed else empty("length_m"), "2")
    if issues:
        ctx.warn(f"Stage 2: {len(issues)} self-intersection/closed-loop line(s) found; see qa_topology_issues")
    ctx.write_layer("canals_clean", clean, "2")
    ctx.write_layer("qa_topology_dangles", gdf_d, "2")
    ctx.write_layer("qa_topology_gaps", gdf_g, "2")
    ctx.set_counts("2", canals_in=int(len(raw)), canals_clean=int(len(clean)), dangles=int(len(dang)), snapped_gaps=int(len(gaps)), trimmed=len(trimmed), disconnected_components=n_disc, issues=len(issues), edits_applied=len(edit_rows))
    if gaps:
        ctx.warn(f"Stage 2: {len(gaps)} endpoint(s) snapped (tolerance {tol} m); review qa_topology_gaps")
