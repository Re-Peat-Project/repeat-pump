"""Stage 9: sources, targets and head-aware routing of pumped water.

Edge cost ``cost(u->v) = length + lambda * max(0, z_to - z_from)`` is a proxy for
pumping energy (P ~ H, Karassik2008). ``per_target`` routes each target with its own
multi-source Dijkstra (Dijkstra1959; legacy-equivalent baseline). ``steiner`` builds a
directed Steiner arborescence with the shortest-path heuristic (Takahashi1980) from a
virtual super-source joined to all sources at zero cost; the undirected networkx
Steiner tree (Kou1981, Mehlhorn1988) is reported only as a secondary comparison.
"""
from __future__ import annotations

import pickle

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge

from .config import require

SUPER = "SUPER"


def edge_cost(length: float, dz: float, lam: float) -> float:
    return length + lam * max(0.0, dz)


def routing_graph(G: nx.DiGraph, lam: float, allow_gate_addition: bool) -> nx.DiGraph:
    """Costed copy of ``G``. Existing ungated sekat become dead ends unless gates may be added.

    Proposed sekat do not block: they are designed with a gate and listed in ``gates_required`` (Stage 10)."""
    R = nx.DiGraph()
    R.add_nodes_from(G.nodes(data=True))
    for u, v, d in G.edges(data=True):
        R.add_edge(u, v, **d, cost=edge_cost(d["length_m"], d["dz_m"], lam))
    if not allow_gate_addition:
        for n, d in G.nodes(data=True):
            if "sekat_existing" in d.get("kinds", []) and not d.get("has_gate", False):
                R.remove_edges_from(list(R.out_edges(n)))   # reachable, but flow cannot pass through
    return R


def route_per_target(R: nx.DiGraph, sources: list, targets: list) -> tuple[dict, list]:
    """Independent Dijkstra from the super-source to each target (Dijkstra1959)."""
    Rs = R.copy()
    for s in sources:
        Rs.add_edge(SUPER, s, cost=0.0, length_m=0.0, dz_m=0.0)
    routes, bad = {}, []
    for t in targets:
        try:
            _, path = nx.single_source_dijkstra(Rs, SUPER, target=t, weight="cost")
            routes[t] = path
        except nx.NetworkXNoPath:
            bad.append(t)
    return routes, bad


def route_steiner(R: nx.DiGraph, sources: list, targets: list) -> tuple[dict, list, set]:
    """Shortest-path heuristic for the directed Steiner arborescence (Takahashi1980).

    Returns (route per target as node path from SUPER, unreachable targets, tree edge set).
    """
    Rs = R.copy()
    for s in sources:
        Rs.add_edge(SUPER, s, cost=0.0, length_m=0.0, dz_m=0.0)
    tree_nodes, parent, tree_edges = {SUPER}, {SUPER: None}, set()
    remaining, bad = list(targets), []
    while remaining:
        dist, paths = nx.multi_source_dijkstra(Rs, list(tree_nodes), weight="cost")
        reach = [(dist[t], str(t), t) for t in remaining if t in dist]
        if not reach:
            bad.extend(remaining)
            break
        _, _, t = min(reach, key=lambda x: (x[0], x[1]))
        path = paths[t]
        for a, b in zip(path[:-1], path[1:]):
            if b not in tree_nodes:
                parent[b] = a
                tree_nodes.add(b)
            tree_edges.add((a, b))
        remaining.remove(t)
    routes = {}
    for t in targets:
        if t in parent:
            p, n = [], t
            while n is not None:
                p.append(n); n = parent[n]
            routes[t] = p[::-1]
    return routes, bad, tree_edges


def path_geometry(G: nx.DiGraph, nodes: list):
    """The route as one line drawn from the source to the target (edge geometries keep their digitised direction, so each is
    turned to start at its upstream node of the route); a MultiLineString only if the edges do not touch."""
    parts = []
    for u, v in zip(nodes[:-1], nodes[1:]):
        if u == SUPER or not G.has_edge(u, v):
            continue
        c = list(G[u][v]["geom"].coords)
        ux, uy = G.nodes[u]["x"], G.nodes[u]["y"]
        if (c[-1][0] - ux) ** 2 + (c[-1][1] - uy) ** 2 < (c[0][0] - ux) ** 2 + (c[0][1] - uy) ** 2:
            c.reverse()
        parts.append(c)
    if not parts:
        return None
    coords = parts[0]
    for c in parts[1:]:
        if c[0] != coords[-1] and Point(c[0]).distance(Point(coords[-1])) > 1e-6:
            return linemerge(MultiLineString(parts))
        coords = coords + c[1:]
    return LineString(coords)


def run(ctx) -> None:
    if not ctx.cfg.pumping.enabled:
        ctx.log.info("Stage 9 skipped: pumping.enabled is false (sekat only)")
        return "skipped"
    cfg = ctx.cfg
    pc = cfg.pumping
    require(pc, ["uphill_penalty_lambda"], "Stage 9", "pumping")
    with open(ctx.work / "network.pkl", "rb") as fh:
        G = pickle.load(fh)
    # ---- sources: river-canal nodes on perennial rivers or with a known dry-season level
    edits = G.graph.get("route_edits")             # manual sources and targets, read once by stage 8
    src_rows, sources, n_excluded = [], [], 0
    for n, d in G.nodes(data=True):
        if "river" not in d.get("kinds", []):
            continue
        wl = d.get("dry_season_wl_m", np.nan)
        manual = bool(d.get("manual", False))
        ok = bool(d.get("perennial", False)) or (wl == wl and wl is not None)
        if d.get("excluded"):
            status, ok = "excluded_by_user", False
            n_excluded += 1
        else:
            status = ("manual" if manual else "ok") if ok else "flagged_not_perennial_no_wl"
        src_rows.append(dict(node_id=n, status=status, manual=manual, z_src_m=wl if wl == wl else np.nan,
                             z_land_m=d.get("z_land_m", np.nan), geometry=Point(d["x"], d["y"])))
        if ok:
            sources.append(n)
    if not sources:
        ctx.write_layer("pump_sources", gpd.GeoDataFrame(src_rows, geometry="geometry", crs=ctx.crs) if src_rows else
                        gpd.GeoDataFrame({"node_id": []}, geometry=[], crs=ctx.crs), "9")
        raise RuntimeError("Stage 9: no usable water source (river-canal intersection on a perennial river or with dry_season_wl_m)"
                           + (f"; your route edits excluded {n_excluded} source(s), remove an exclusion or add a source" if n_excluded else ""))
    ctx.write_layer("pump_sources", gpd.GeoDataFrame(src_rows, geometry="geometry", crs=ctx.crs), "9")

    # ---- targets: highest node of each connected cluster of selected segments
    E = nx.Graph()
    for u, v, d in G.edges(data=True):
        if d["selected"]:
            E.add_edge(u, v)
    tgt_rows, targets = [], {}
    manual_nodes = sorted(n for n, d in G.nodes(data=True) if "manual_target" in d.get("kinds", []))
    del_pts = [Point(p) for p in (edits or {}).get("deletes", {}).get("target", [])]
    tol = (edits or {}).get("tolerance", 0.0)
    used_manual, removed, served_after, deleted_and_replaced = set(), [], set(), 0
    m_serial = 0
    for k, comp in enumerate(sorted(nx.connected_components(E), key=lambda c: min(c)), start=1):
        node = max(sorted(comp), key=lambda n: (G.nodes[n].get("z_land_m", -np.inf), -n))
        segs = sorted({d["seg_id"] for u, v, d in G.edges(data=True) if d["selected"] and u in comp and v in comp})
        here = [m for m in manual_nodes if m in comp]
        if here:                                   # a manual target on a selected cluster replaces that cluster's computed target and serves its segments
            if len(here) > 1:
                ctx.warn(f"Stage 9: {len(here)} manual targets lie in one selected cluster; only the first is used, the others are ignored")
            used_manual.update(here)
            if del_pts and any(Point(G.nodes[node]["x"], G.nodes[node]["y"]).distance(p) <= tol for p in del_pts):
                deleted_and_replaced += 1              # removed and replaced in one go: the manual target stands for it
            m_serial += 1
            tid, node, manual = f"M{m_serial:03d}", here[0], True
        elif del_pts and any(Point(G.nodes[node]["x"], G.nodes[node]["y"]).distance(p) <= tol for p in del_pts):
            removed.append((f"T{k:03d}", segs))    # the person removed this target: its segments are no longer served
            continue
        else:
            tid, manual = f"T{k:03d}", False
        served_after.update(segs)
        targets[tid] = node
        tgt_rows.append(dict(target_id=tid, node_id=node, z_land_m=G.nodes[node].get("z_land_m", np.nan), n_segments=len(segs),
                             seg_ids=";".join(segs), manual=manual, geometry=Point(G.nodes[node]["x"], G.nodes[node]["y"])))
    for m in manual_nodes:                         # manual targets on unselected segments serve only the segment(s) they sit on
        if m in used_manual:
            continue
        segs = sorted({d["seg_id"] for _, _, d in G.edges(m, data=True)})
        m_serial += 1
        tid = f"M{m_serial:03d}"
        targets[tid] = m
        served_after.update(segs)
        tgt_rows.append(dict(target_id=tid, node_id=m, z_land_m=G.nodes[m].get("z_land_m", np.nan), n_segments=len(segs), seg_ids=";".join(segs),
                             manual=True, geometry=Point(G.nodes[m]["x"], G.nodes[m]["y"])))
        ctx.warn(f"Stage 9: manual target {tid} is not on a selected segment, so it serves only the segment(s) it sits on ({', '.join(segs)})")
    if edits is not None:
        unserved = sorted({s for _, ss in removed for s in ss} - served_after)
        ctx.report["route_edits"] = {**edits["stats"], "sources_excluded_nodes": n_excluded, "targets_removed": len(removed),
                                     "selected_segments_no_longer_served": len(unserved)}
        if removed:
            ctx.warn(f"Stage 9: {len(removed)} computed target(s) removed by your route edits; {len(unserved)} selected segment(s) are no longer served")
        if edits["stats"].get("target_deletes", 0) and not removed and not deleted_and_replaced:
            ctx.warn(f"Stage 9: the route edits remove a target, but no computed target lies within {tol:g} m of it")
    if not targets and removed:
        raise RuntimeError("Stage 9: no target left; your route edits removed every computed target")
    ctx.write_layer("pump_targets", gpd.GeoDataFrame(tgt_rows, geometry="geometry", crs=ctx.crs), "9")

    R = routing_graph(G, pc.uphill_penalty_lambda, pc.allow_gate_addition)
    tnodes = list(targets.values())
    if pc.routing == "per_target":
        paths_by_node, bad_nodes = route_per_target(R, sources, tnodes)
        tree = set()
        for p in paths_by_node.values():
            tree |= set(zip(p[:-1], p[1:]))
    else:
        paths_by_node, bad_nodes, tree = route_steiner(R, sources, tnodes)

    cc = ctx.read_layer("canals_clean")
    disc_canals = set(cc.loc[~cc["reaches_river"].astype(bool), "canal_id"]) if "reaches_river" in cc else set()
    route_rows, routes, unreachable = [], {}, []
    for k, (tid, node) in enumerate(targets.items()):
        ctx.progress(k / max(len(targets), 1), f"target {k + 1} of {len(targets)}")
        if node not in paths_by_node:
            Rf = routing_graph(G, pc.uphill_penalty_lambda, True)
            Rf.add_edges_from((SUPER, s, dict(cost=0.0, length_m=0.0, dz_m=0.0)) for s in sources)
            reason = "blocked_by_ungated_sekat" if nx.has_path(Rf, SUPER, node) else "no_path"
            if reason == "no_path" and disc_canals and any(d.get("canal_id") in disc_canals for _, _, d in G.edges(node, data=True)):
                reason = "disconnected_from_river"   # topology gap, see qa_topology_disconnected
            unreachable.append(dict(target_id=tid, node_id=node, reason=reason, geometry=Point(G.nodes[node]["x"], G.nodes[node]["y"])))
            continue
        p = paths_by_node[node]
        real = [n for n in p if n != SUPER]
        edges = list(zip(p[1:-1], p[2:]))
        cost = sum(R[u][v]["cost"] for u, v in edges)
        route_rows.append(dict(route_id=f"R_{tid}", target_id=tid, mode=pc.routing, source_node=real[0], cost=float(cost),
                               length_m=float(sum(G[u][v]["length_m"] for u, v in edges)),
                               lift_m=float(sum(max(0.0, G[u][v]["dz_m"]) for u, v in edges)), n_edges=len(edges),
                               canal_ids=";".join(sorted({str(G[u][v].get("canal_id")) for u, v in edges if G[u][v].get("canal_id") is not None})),
                               geometry=path_geometry(G, p)))
        routes[tid] = real
    tree_real = {(u, v) for u, v in tree if u != SUPER}
    summary = dict(mode=pc.routing, n_targets=len(targets), n_unreachable=len(unreachable),
                   total_length_m=float(sum(G[u][v]["length_m"] for u, v in tree_real)),
                   total_lift_m=float(sum(max(0.0, G[u][v]["dz_m"]) for u, v in tree_real)),
                   total_cost=float(sum(R[u][v]["cost"] for u, v in tree_real)))
    # secondary, undirected comparison only (Kou1981, Mehlhorn1988)
    try:
        U = nx.Graph()
        for u, v, d in R.edges(data=True):
            w = d["cost"]
            if not U.has_edge(u, v) or U[u][v]["w"] > w:
                U.add_edge(u, v, w=w)
        U.add_edges_from((SUPER, s, dict(w=0.0)) for s in sources)
        term = [SUPER] + [n for n in tnodes if n in U]
        st = nx.algorithms.approximation.steiner_tree(U, term, weight="w")
        summary["secondary_undirected_steiner_cost"] = float(sum(d["w"] for _, _, d in st.edges(data=True)))
    except Exception as e:  # pragma: no cover
        summary["secondary_undirected_steiner_cost"] = None
    ctx.report["routing"] = summary
    empty_r = gpd.GeoDataFrame({"route_id": []}, geometry=[], crs=ctx.crs)
    ctx.write_layer("pump_routes", gpd.GeoDataFrame(route_rows, geometry="geometry", crs=ctx.crs) if route_rows else empty_r, "9")
    ctx.write_layer("qa_unreachable_targets", gpd.GeoDataFrame(unreachable, geometry="geometry", crs=ctx.crs) if unreachable else gpd.GeoDataFrame(
        {"target_id": []}, geometry=[], crs=ctx.crs), "9")
    with open(ctx.work / "routing.pkl", "wb") as fh:
        pickle.dump(dict(mode=pc.routing, routes=routes, targets=targets, tree=tree_real, sources=sources), fh)
    if unreachable:
        ctx.warn(f"Stage 9: {len(unreachable)} target(s) unreachable (see qa_unreachable_targets)")
    scope_counts = sekat_scope(ctx, route_rows, served_after, tgt_rows)
    ctx.set_counts("9", sources=len(sources), targets=len(targets), routes=len(route_rows), unreachable=len(unreachable), **scope_counts)


SCOPE_TOL_M = 0.5        # a proposed sekat lies on the canal line, so on a route through that canal it is within rounding of it


def sekat_scope(ctx, route_rows: list[dict], served: set, tgt_rows: list[dict]) -> dict:
    """Label every proposed sekat ``target`` (on a served selected segment), ``route`` (on a pump route) or ``other``, and mark the ones
    in the plan (``pumping.sekat_scope``). Stage 7 places sekat on every kept canal by the head rule; the guide's order is the other way
    round (choose the area, route the water, block the canals on the way), so the scope is applied once the routes are known. The gates on
    the routes stay in the plan with either setting: pumped water is held behind them. Writes ``sekat_scope``; returns stage counts."""
    pr = ctx.read_layer("sekat_proposed")
    if not len(pr) or "sekat_pro_id" not in pr:
        pr = gpd.GeoDataFrame({"sekat_pro_id": [], "seg_id": []}, geometry=[], crs=ctx.crs)
    seg = pr["seg_id"].astype(str) if "seg_id" in pr else pd.Series([""] * len(pr), index=pr.index)
    on_target = seg.isin({str(s) for s in served})
    routes = gpd.GeoSeries([r["geometry"] for r in route_rows], crs=ctx.crs).union_all() if route_rows else None
    on_route = pr.geometry.distance(routes) <= SCOPE_TOL_M if routes is not None and len(pr) else pd.Series(False, index=pr.index)
    route_canals = {c for r in route_rows for c in str(r.get("canal_ids") or "").split(";") if c}
    if route_canals and "canal_id" in pr:              # a sekat on a crossing canal at a junction is near the route but not on it
        on_route = on_route & pr["canal_id"].astype(str).isin(route_canals)
    scope = np.where(on_target, "target", np.where(on_route, "route", "other")).astype(object)
    planned = np.ones(len(pr), bool) if ctx.cfg.pumping.sekat_scope == "all" else scope != "other"
    cols = [c for c in ("sekat_pro_id", "canal_id", "seg_id", "sekat_type", "manual") if c in pr]
    out = gpd.GeoDataFrame(pr[cols].assign(scope=scope, planned=planned), geometry=pr.geometry, crs=ctx.crs)
    ctx.write_layer("sekat_scope", out, "9")
    n = {k: int((scope == k).sum()) for k in ("target", "route", "other")}
    ctx.report["sekat_scope"] = dict(setting=ctx.cfg.pumping.sekat_scope, **n, planned=int(planned.sum()))
    # a selected area whose canals rise less than dA gets no sekat of its own: say so (team decision: a warning is enough)
    with_sekat = set(seg[on_target])
    bare = [t["target_id"] for t in tgt_rows if t["seg_ids"] and not with_sekat & set(t["seg_ids"].split(";"))]
    if bare:
        ctx.warn(f"Stage 9: {len(bare)} of {len(tgt_rows)} target(s) have no proposed sekat on their selected canals (the land rises less than "
                 f"sekat.dA_m along them), so only the gates on their pump routes hold the water: {', '.join(bare[:10])}")
    return dict(sekat_target=n["target"], sekat_route=n["route"], sekat_other=n["other"], sekat_planned=int(planned.sum()))
