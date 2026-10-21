"""Stage 8: directed network graph (helpers first; Stage 8 body added later in this file)."""
from __future__ import annotations

import pickle

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely import STRtree
from shapely.geometry import Point
from shapely.ops import nearest_points


def river_canal_points(canals: gpd.GeoDataFrame, rivers: gpd.GeoDataFrame, tol: float = 0.0) -> gpd.GeoDataFrame:
    """River-canal intersection points (candidate water sources, spec Stage 9).

    For polygon rivers the point is where the canal crosses the river boundary; a
    canal lying wholly inside a polygon contributes its end points. For line rivers
    the point is the line-line intersection. With ``tol`` > 0 a river that stops short of a canal but lies within ``tol``
    metres of it also counts (KLH guide step 8.2 buffers the canal by 30 m); the point is the nearest point on the canal
    and ``gap_m`` records the distance. ``tol`` = 0 keeps the exact-crossing behaviour.
    """
    rows = []
    if rivers is None or len(rivers) == 0:
        return gpd.GeoDataFrame({"canal_id": [], "chainage_m": [], "river_idx": []}, geometry=[], crs=canals.crs)
    rtree = STRtree(list(rivers.geometry))
    for cid, ln in zip(canals["canal_id"], canals.geometry):
        seen: list[Point] = []
        for ri in rtree.query(ln.buffer(tol) if tol > 0 else ln):
            r = rivers.geometry.iloc[ri]
            pts: list[Point] = []
            gap = 0.0
            if not r.intersects(ln):
                gap = float(r.distance(ln))
                if tol <= 0 or gap > tol:
                    continue
                pts = [nearest_points(ln, r)[0]]
            elif r.geom_type in ("Polygon", "MultiPolygon"):
                inter = ln.intersection(r.boundary)
                pts = [g for g in getattr(inter, "geoms", [inter]) if g.geom_type == "Point"]
                if not pts:
                    for e in (Point(ln.coords[0]), Point(ln.coords[-1])):
                        if r.contains(e):
                            pts.append(e)
            else:
                inter = ln.intersection(r)
                pts = [g for g in getattr(inter, "geoms", [inter]) if g.geom_type == "Point"]
            for p in pts:
                if any(p.distance(q) < 1e-3 for q in seen):
                    continue
                seen.append(p)
                row = {"canal_id": cid, "chainage_m": float(ln.project(p)), "river_idx": int(ri), "gap_m": gap, "geometry": p}
                for c in ("perennial", "dry_season_wl_m"):
                    if c in rivers:
                        row[c] = rivers[c].iloc[ri]
                rows.append(row)
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=canals.crs) if rows else gpd.GeoDataFrame(
        {"canal_id": [], "chainage_m": [], "river_idx": []}, geometry=[], crs=canals.crs)


def snap_points_to_canals(pts: gpd.GeoDataFrame, canals: gpd.GeoDataFrame, snap_m: float) -> tuple[gpd.GeoDataFrame, int]:
    """Move river points onto the nearest kept canal within ``snap_m`` (legacy SNAP_MUARA); returns the points and how many were dropped."""
    tol = max(snap_m, 1e-3)
    tree = STRtree(list(canals.geometry))
    rows, seen, dropped = [], set(), 0
    for _, r in pts.iterrows():
        near = [j for j in tree.query(r.geometry.buffer(tol)) if canals.geometry.iloc[j].distance(r.geometry) <= tol]
        if not near:
            dropped += 1
            continue
        j = min(near, key=lambda j: (canals.geometry.iloc[j].distance(r.geometry), j))
        ln = canals.geometry.iloc[j]
        ch = float(ln.project(r.geometry))
        key = (canals["canal_id"].iloc[j], round(ch), int(r["river_idx"]))
        if key in seen:
            continue
        seen.add(key)
        row = {c: r[c] for c in pts.columns if c not in ("geometry", "canal_id", "chainage_m")}
        row.update(canal_id=canals["canal_id"].iloc[j], chainage_m=ch, snap_dist_m=float(ln.distance(r.geometry)), geometry=ln.interpolate(ch))
        rows.append(row)
    return (gpd.GeoDataFrame(rows, geometry="geometry", crs=canals.crs) if rows else
            gpd.GeoDataFrame({"canal_id": [], "chainage_m": [], "river_idx": []}, geometry=[], crs=canals.crs)), dropped


def river_sources(ctx, canals: gpd.GeoDataFrame, rivers: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """River-canal points on the analysis canals, following the KLH guide when settings ask for it.

    Without ``topology.canal_classes``: river points on ``canals`` within ``topology.river_buffer_m`` (exact crossing when null).
    With it, as in step 8.2 the points are found on the FULL canal set (``inputs_clipped_canals``) and then moved onto the kept
    network within ``topology.source_snap_m``; points with no kept canal that close are dropped and counted in the report.
    """
    t = ctx.cfg.topology
    tol = t.river_buffer_m or 0.0
    if not t.canal_classes or not ctx.has_layer("inputs_clipped_canals"):
        return river_canal_points(canals, rivers, tol)
    full = ctx.read_layer("inputs_clipped_canals")
    full = gpd.GeoDataFrame(full[["geometry"]], geometry="geometry", crs=full.crs).explode(index_parts=False).reset_index(drop=True)
    full = full[full.geom_type == "LineString"].reset_index(drop=True)
    full["canal_id"] = range(len(full))
    found = river_canal_points(full, rivers, tol)
    kept, dropped = snap_points_to_canals(found, canals, t.source_snap_m or 0.0)
    ctx.report["river_sources"] = {"found_on_full_network": int(len(found)), "dropped_not_on_kept_network": int(dropped), "kept": int(len(kept))}
    if dropped:
        ctx.warn(f"{dropped} river point(s) found on canals left out by the class filter are more than {t.source_snap_m or 0:g} m from the kept network and were dropped")
    return kept


def endpoint_distance_to_rivers(canals: gpd.GeoDataFrame, river_pts: gpd.GeoDataFrame) -> dict:
    """Network distance from every canal end node to the nearest river point (Dijkstra, Dijkstra1959)."""
    import networkx as nx

    def nk(c):
        return (round(c[0], 3), round(c[1], 3))
    G = nx.Graph()
    L = dict(zip(canals["canal_id"], canals.geometry.length))
    for cid, g in zip(canals["canal_id"], canals.geometry):
        G.add_edge(nk(g.coords[0]), nk(g.coords[-1]), weight=float(g.length))
    geom = dict(zip(canals["canal_id"], canals.geometry))
    for i, r in river_pts.reset_index(drop=True).iterrows():
        g = geom[r["canal_id"]]
        v = ("river", i)
        G.add_edge(v, nk(g.coords[0]), weight=float(r["chainage_m"]))
        G.add_edge(v, nk(g.coords[-1]), weight=float(L[r["canal_id"]] - r["chainage_m"]))
    srcs = [("river", i) for i in range(len(river_pts))]
    if not srcs:
        return {}
    return dict(nx.multi_source_dijkstra_path_length(G, srcs, weight="weight"))


def _nk(c) -> tuple:
    return (round(c[0], 3), round(c[1], 3))


def build_graph(segs: gpd.GeoDataFrame, prof: pd.DataFrame, cuts: list[dict]) -> tuple[nx.DiGraph, dict]:
    """Directed graph from canal segments (both directions per piece).

    ``cuts`` are points to insert as nodes: dicts with canal_id, chainage_m, kind and
    node attributes. Segments are split at the cuts so sekat and river points become nodes.
    Edge fields: seg_id, length_m, z_from_m, z_to_m, dz_m (land elevation, Stage 5 profile).
    """
    z_of = {}
    for cid, g in prof.groupby("canal_id"):
        g = g.sort_values("station_m")
        z_of[cid] = (g["station_m"].to_numpy(), g["z_land_m"].to_numpy())

    def z_at(cid, ch):
        s, z = z_of[cid]
        return float(np.interp(ch, s, z))

    G = nx.DiGraph()
    node_attr: dict[tuple, dict] = {}
    by_canal: dict[str, list] = {}
    for c in cuts:
        by_canal.setdefault(c["canal_id"], []).append(c)

    def add_node(key, **kw):
        a = node_attr.setdefault(key, {"kinds": set(), "z_land_m": np.nan})
        for k, v in kw.items():
            if k == "kind":
                a["kinds"].add(v)
            elif v is not None and not (isinstance(v, float) and np.isnan(v)):
                a[k] = v

    for _, sg in segs.iterrows():
        cid, c0, c1, g = sg["canal_id"], sg["chain_start_m"], sg["chain_end_m"], sg.geometry
        pts = [(c0, None)]
        for c in sorted(by_canal.get(cid, []), key=lambda x: x["chainage_m"]):
            if c0 + 1e-6 < c["chainage_m"] < c1 - 1e-6:
                pts.append((c["chainage_m"], c))
        pts.append((c1, None))
        from shapely.ops import substring
        for (a, ca), (b, cb) in zip(pts[:-1], pts[1:]):
            geom = substring(g, a - c0, b - c0)
            ka, kb = _nk(geom.coords[0]), _nk(geom.coords[-1])
            za, zb = z_at(cid, a), z_at(cid, b)
            add_node(ka, kind="endpoint", z_land_m=za)
            add_node(kb, kind="endpoint", z_land_m=zb)
            for cc, key in ((ca, ka), (cb, kb)):
                if cc is not None:
                    add_node(key, kind=cc["kind"], **cc.get("attrs", {}))
            L = float(geom.length)
            base = dict(seg_id=sg["seg_id"], canal_id=cid, length_m=L, width_m=sg.get("width_m", np.nan), depth_m=sg.get("depth_m", np.nan),
                        selected=bool(sg.get("selected", False)))
            for u, v, gm, zu, zv in ((ka, kb, geom, za, zb), (kb, ka, geom.reverse(), zb, za)):
                if G.has_edge(u, v) and G[u][v]["length_m"] <= L:
                    continue
                G.add_edge(u, v, geom=gm, z_from_m=zu, z_to_m=zv, dz_m=zv - zu, **base)
    # cuts at segment ends (chainage equal to a segment end) become attributes of that end node
    seg_idx = {}
    for _, sg in segs.iterrows():
        seg_idx.setdefault(sg["canal_id"], []).append((sg["chain_start_m"], sg["chain_end_m"], sg.geometry))
    for cid, cl in by_canal.items():
        for c in cl:
            for a, b, g in seg_idx.get(cid, []):
                for end, idx in ((a, 0), (b, -1)):
                    if abs(c["chainage_m"] - end) <= 1e-6:
                        key = _nk(g.coords[idx])
                        add_node(key, kind=c["kind"], **c.get("attrs", {}))
    ids = {k: i + 1 for i, k in enumerate(sorted(node_attr))}
    H = nx.DiGraph()
    for k, a in node_attr.items():
        H.add_node(ids[k], x=k[0], y=k[1], **{kk: vv for kk, vv in a.items() if kk != "kinds"}, kinds=sorted(a["kinds"]))
    for u, v, d in G.edges(data=True):
        H.add_edge(ids[u], ids[v], **d, from_node=ids[u], to_node=ids[v])
    return H, ids


def run(ctx):
    segs = ctx.read_layer("canal_segments").sort_values("seg_id").reset_index(drop=True)
    canals = ctx.read_layer("canals_clean")
    prof = ctx.read_layer("canal_profiles")
    cuts = []
    ex = ctx.read_layer("sekat_existing_assessed")
    for _, r in (ex.iterrows() if len(ex) and "snapped" in ex else []):
        if r["snapped"]:
            cuts.append(dict(canal_id=r["canal_id"], chainage_m=float(r["chainage_m"]), kind="sekat_existing",
                             attrs=dict(sekat_id=str(r["sekat_id"]), has_gate=bool(r["has_gate"]))))
    pr = ctx.read_layer("sekat_proposed")
    for _, r in (pr.iterrows() if len(pr) and "canal_id" in pr else []):
        cuts.append(dict(canal_id=r["canal_id"], chainage_m=float(r["chainage_m"]), kind="sekat_proposed",
                         attrs=dict(sekat_id=str(r["sekat_pro_id"]), has_gate=False)))
    if ctx.has_layer("inputs_clipped_rivers"):
        rp = river_sources(ctx, canals, ctx.read_layer("inputs_clipped_rivers"))
        for k, r in rp.reset_index(drop=True).iterrows():
            cuts.append(dict(canal_id=r["canal_id"], chainage_m=float(r["chainage_m"]), kind="river",
                             attrs=dict(river_idx=int(r["river_idx"]), perennial=bool(r.get("perennial", False)),
                                        dry_season_wl_m=float(r["dry_season_wl_m"]) if "dry_season_wl_m" in r and r["dry_season_wl_m"] == r["dry_season_wl_m"] else np.nan)))
    G, ids = build_graph(segs, prof, cuts)
    # nodes of the graph keep a boolean has_gate only for sekat nodes
    with open(ctx.work / "network.pkl", "wb") as fh:
        pickle.dump(G, fh)
    nodes = gpd.GeoDataFrame(
        [dict(node_id=n, kinds=",".join(d["kinds"]), z_land_m=d.get("z_land_m", np.nan), sekat_id=d.get("sekat_id"),
              has_gate=d.get("has_gate"), perennial=d.get("perennial"), dry_season_wl_m=d.get("dry_season_wl_m", np.nan),
              geometry=Point(d["x"], d["y"])) for n, d in G.nodes(data=True)], geometry="geometry", crs=ctx.crs)
    edges = gpd.GeoDataFrame(
        [dict(from_node=u, to_node=v, seg_id=d["seg_id"], length_m=d["length_m"], z_from_m=d["z_from_m"], z_to_m=d["z_to_m"], dz_m=d["dz_m"],
              selected=d["selected"], geometry=d["geom"]) for u, v, d in G.edges(data=True)], geometry="geometry", crs=ctx.crs)
    ctx.write_layer("network_nodes", nodes, "8")
    ctx.write_layer("network_edges", edges, "8")
    ctx.set_counts("8", nodes=G.number_of_nodes(), edges=G.number_of_edges())
