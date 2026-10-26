"""Stage 10: water demand, pump station siting and sizing.

Demand: ``deficit`` mode V = deficit_mm/1000 * A_served; ``specific_yield`` mode
V = dh * Sy * A_served; Q = V / (design_period_days * 86400).
Head: H = H_static + sum(h_f) with H_static = z_pool(target) - z_src and pool level
z_land - dA. Friction by Manning (Chow1959, canal) or Hazen-Williams (Mays2011, pipe).
Power P = rho g Q H / eta (Karassik2008). Shortfalls are reported, never capped silently.
"""
from __future__ import annotations

import math
import pickle

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import Point

from .config import NeedsHuman, require

RHO, G = 1000.0, 9.81


def pump_power_kw(q_m3s: float, h_m: float, eta: float) -> float:
    """P = rho g Q H / eta, in kW (Karassik2008)."""
    return RHO * G * q_m3s * h_m / eta / 1000.0


def manning_hf(length: float, q: float, n: float, width: float, depth: float) -> float:
    """Friction head over ``length`` of rectangular canal (Chow1959): L * (n Q / (A R^(2/3)))^2."""
    A = width * depth
    R = A / (width + 2 * depth)
    return length * (n * q / (A * R ** (2 / 3))) ** 2


def hazen_williams_hf(length: float, q: float, c: float, d: float) -> float:
    """Friction head in a pipe (Mays2011)."""
    return 10.67 * length * q ** 1.852 / (c ** 1.852 * d ** 4.87)


def site_stations(levels: list[float], fric: list[float], z_src: float, max_head: float, sekat: list[bool]) -> list[dict]:
    """Place pump stations along a route (nodes 0..n).

    ``levels[j]`` is the pool level required at node j, ``fric[j]`` the friction loss of the
    edge into node j (``fric[0]`` = 0). A station is placed at the source and then wherever
    the cumulative head since the last station would exceed ``max_head``; stations move back to
    the latest sekat node inside the stage when one exists (a lift station co-locates with a block).
    Returns dicts with idx, stage head h_m, h_static_m, h_fric_m, exceeds, snapped.
    """
    n = len(levels) - 1
    if n < 1:
        return []
    st, last, lv_last = [0], 0, z_src
    flags = {0: dict(exceeds=False, snapped=False)}
    j = 1
    while j <= n:
        acc = max(0.0, levels[j] - lv_last) + sum(fric[last + 1:j + 1])
        if acc > max_head + 1e-12:
            cand = j - 1
            exceeds = False
            if cand <= last:
                cand, exceeds = j, True            # a single edge already exceeds the limit
            snap_to = [k for k in range(last + 1, cand + 1) if sekat[k]]
            snapped = False
            if snap_to and not exceeds:
                cand, snapped = snap_to[-1], True
            st.append(cand); flags[cand] = dict(exceeds=exceeds, snapped=snapped)
            last, lv_last = cand, levels[cand]
            j = cand + 1
            continue
        j += 1
    out = []
    for a, k in enumerate(st):
        nxt = st[a + 1] if a + 1 < len(st) else n
        lv0 = z_src if k == 0 else levels[k]
        h_static = max(0.0, levels[nxt] - lv0)
        h_fric = sum(fric[k + 1:nxt + 1])
        out.append(dict(idx=k, h_m=h_static + h_fric, h_static_m=h_static, h_fric_m=h_fric, next_idx=nxt, **flags[k]))
    return out


def _area_served(ctx, seg_ids, segs, peat_union, sk, influence):
    """Peat area (m2) within the influence distance of served segments, per sub-KHG."""
    out = {}
    sel = segs[segs["seg_id"].isin(seg_ids)]
    for kid, g in sel.groupby("subkhg_id"):
        buf = g.geometry.union_all().buffer(influence)
        poly = sk[sk["subkhg_id"] == kid].geometry.iloc[0]
        out[kid] = (buf if peat_union is None else buf.intersection(peat_union)).intersection(poly).area
    return out


def run(ctx) -> None:
    if not ctx.cfg.pumping.enabled:
        ctx.log.info("Stage 10 skipped: pumping.enabled is false (sekat only)")
        return "skipped"
    cfg = ctx.cfg
    pc = cfg.pumping
    sk = ctx.read_layer("subkhg_selected")
    has_deficit = {"deficit_mm", "design_period_days"} <= set(sk.columns) and bool(sk[["deficit_mm", "design_period_days"]].notna().all().all())
    mode = pc.demand_mode
    if mode == "deficit" and not has_deficit:
        mode = "specific_yield"
        ctx.warn("Stage 10: no water deficit (neraca air) for the selected sub-KHGs; demand uses specific yield x water-table rise instead")
    has_period = "design_period_days" in sk.columns and bool(sk["design_period_days"].notna().all())
    need = ["conveyance", "pump_efficiency", "max_head_per_station_m", "pump_capacity_m3s", "influence_distance_m"]
    if pc.conveyance == "canal":
        need.append("manning_n")
    elif pc.conveyance == "pipe":
        need += ["hazen_williams_c", "pipe_diameter_m"]
    if mode == "specific_yield":
        need += ["specific_yield", "water_table_rise_m"]
    if not has_period:
        need.append("design_period_days")
    require(pc, need, "Stage 10", "pumping")
    dA = cfg.sekat.dA_m
    with open(ctx.work / "network.pkl", "rb") as fh:
        Gr = pickle.load(fh)
    with open(ctx.work / "routing.pkl", "rb") as fh:
        rt = pickle.load(fh)
    segs = ctx.read_layer("canal_segments")
    tgt = ctx.read_layer("pump_targets").set_index("target_id")
    src = ctx.read_layer("pump_sources").set_index("node_id")
    pe = ctx.read_layer("inputs_clipped_peat_depth")
    peat_union = pe.geometry.union_all() if ctx.cfg.inputs.peat_depth is not None else None
    routes_gdf = ctx.read_layer("pump_routes")

    # ---- demand per target
    dem = {}
    for tid in rt["routes"]:
        seg_ids = tgt.loc[tid, "seg_ids"].split(";")
        areas = _area_served(ctx, seg_ids, segs, peat_union, sk, pc.influence_distance_m)
        q = v_tot = a_tot = 0.0
        for kid, a in areas.items():
            r = sk[sk["subkhg_id"] == kid].iloc[0]
            V = (r["deficit_mm"] / 1000.0 * a) if mode == "deficit" else pc.water_table_rise_m * pc.specific_yield * a
            days = r["design_period_days"] if r["design_period_days"] == r["design_period_days"] else pc.design_period_days
            q += V / (days * 86400.0)
            v_tot += V; a_tot += a
        dem[tid] = dict(q=q, v=v_tot, a_ha=a_tot / 1e4)

    # ---- edge flows (shared edges of a Steiner tree carry the sum of downstream demand)
    def edge_q(tid, e):
        if rt["mode"] == "per_target":
            return dem[tid]["q"]
        return sum(dem[t2]["q"] for t2, p in rt["routes"].items() if e in set(zip(p[:-1], p[1:])))

    stations, route_upd, gates = {}, {}, {}
    for tid, nodes in rt["routes"].items():
        s_node = nodes[0]
        z_src = src.loc[s_node, "z_src_m"] if s_node in src.index else np.nan
        if not (z_src == z_src):
            raise NeedsHuman(f"Stage 10: water level of source node {s_node} is unknown (dry_season_wl_m missing); "
                             "pump head cannot be computed (spec section 11.2)")
        edges = list(zip(nodes[:-1], nodes[1:]))
        levels = [Gr.nodes[n].get("z_land_m", np.nan) - dA for n in nodes]
        fric = [0.0]
        for e in edges:
            d = Gr[e[0]][e[1]]
            q = edge_q(tid, e)
            if pc.conveyance == "canal":
                if not (d["width_m"] == d["width_m"] and d["depth_m"] == d["depth_m"]):
                    raise NeedsHuman(f"Stage 10: canal cross-section (width_m/depth_m) missing on segment {d['seg_id']}; needed for Manning friction")
                fric.append(manning_hf(d["length_m"], q, pc.manning_n, d["width_m"], d["depth_m"]))
            else:
                fric.append(hazen_williams_hf(d["length_m"], q, pc.hazen_williams_c, pc.pipe_diameter_m))
        is_sekat = [any(k.startswith("sekat") for k in Gr.nodes[n].get("kinds", [])) for n in nodes]
        h_static_total = max(0.0, levels[-1] - z_src)
        h_fric_total = float(sum(fric))
        sited = site_stations(levels, fric, float(z_src), pc.max_head_per_station_m, is_sekat) if (h_static_total + h_fric_total) > 0 else []
        for s in sited:
            n = nodes[s["idx"]]
            q_out = edge_q(tid, edges[s["idx"]]) if s["idx"] < len(edges) else dem[tid]["q"]
            cur = stations.get(n)
            row = dict(node_id=n, q_m3s=q_out, h_m=s["h_m"], h_static_m=s["h_static_m"], h_fric_m=s["h_fric_m"],
                       exceeds_max=s["exceeds"], snapped_to_sekat=s["snapped"], route_ids=[f"R_{tid}"], source_node=s_node)
            if cur is None:
                stations[n] = row
            else:
                cur["q_m3s"] = max(cur["q_m3s"], q_out); cur["h_m"] = max(cur["h_m"], s["h_m"])
                cur["h_static_m"] = max(cur["h_static_m"], s["h_static_m"]); cur["h_fric_m"] = max(cur["h_fric_m"], s["h_fric_m"])
                cur["route_ids"].append(f"R_{tid}")
        route_upd[f"R_{tid}"] = dict(q_required_m3s=dem[tid]["q"], v_m3=dem[tid]["v"], a_served_ha=dem[tid]["a_ha"], z_src_m=float(z_src),
                                     h_static_m=h_static_total, h_friction_m=h_fric_total, h_total_m=h_static_total + h_fric_total,
                                     n_stations=len(sited))
        for n, flag in zip(nodes, is_sekat):
            d = Gr.nodes[n]
            if flag and not d.get("has_gate", False):
                g = gates.setdefault(n, dict(node_id=n, sekat_id=d.get("sekat_id"), kind=",".join(k for k in d["kinds"] if k.startswith("sekat")),
                                             route_ids=[], geometry=Point(d["x"], d["y"])))
                g["route_ids"].append(f"R_{tid}")

    # ---- sizing
    rows, shortfalls = [], []
    for i, (n, r) in enumerate(sorted(stations.items()), start=1):
        units = max(1, math.ceil(r["q_m3s"] / pc.pump_capacity_m3s - 1e-12))
        short = 0.0
        if pc.max_units_per_station is not None and units > pc.max_units_per_station:
            short = r["q_m3s"] - pc.max_units_per_station * pc.pump_capacity_m3s
            shortfalls.append((n, short)); units = pc.max_units_per_station
        d = Gr.nodes[n]
        rows.append(dict(station_id=f"PS{i:03d}", node_id=n, source_node=r["source_node"], q_m3s=r["q_m3s"], h_m=r["h_m"], h_static_m=r["h_static_m"],
                         h_fric_m=r["h_fric_m"], p_kw=pump_power_kw(r["q_m3s"], r["h_m"], pc.pump_efficiency), units_needed=units,
                         shortfall_m3s=short, exceeds_max=r["exceeds_max"], snapped_to_sekat=r["snapped_to_sekat"],
                         route_ids=";".join(sorted(set(r["route_ids"]))), geometry=Point(d["x"], d["y"])))
    if shortfalls:
        ctx.warn(f"Stage 10: demand exceeds installed capacity at {len(shortfalls)} station(s); see shortfall_m3s")
    if any(r["exceeds_max"] for r in rows):
        ctx.warn("Stage 10: some single edges need more than max_head_per_station_m; see exceeds_max")
    empty = lambda k: gpd.GeoDataFrame({k: []}, geometry=[], crs=ctx.crs)
    ctx.write_layer("pump_stations", gpd.GeoDataFrame(rows, geometry="geometry", crs=ctx.crs) if rows else empty("station_id"), "10")
    upd = pd.DataFrame.from_dict(route_upd, orient="index").rename_axis("route_id").reset_index()
    ctx.write_layer("pump_routes", routes_gdf.drop(columns=[c for c in upd.columns if c != "route_id" and c in routes_gdf], errors="ignore").merge(upd, on="route_id", how="left"), "10")
    gl = [dict(g, route_ids=";".join(sorted(set(g["route_ids"])))) for g in gates.values()]
    ctx.write_layer("gates_required", gpd.GeoDataFrame(gl, geometry="geometry", crs=ctx.crs) if gl else empty("node_id"), "10")
    ctx.report["pumps"] = [{k: v for k, v in r.items() if k != "geometry"} for r in rows]
    ctx.set_counts("10", stations=len(rows), gates_required=len(gl), shortfalls=len(shortfalls))
