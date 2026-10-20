"""Stage 6: segment prioritisation (need score) inside the selected sub-KHGs.

* categorical polygon attributes are transferred by LARGEST TOTAL LENGTH, never by
  feature-count majority (legacy bug); ``share_dominant`` records the dominance.
* dryness = moisture mean in a ring buffer excluding the canal water surface.
* upstream contribution = log of max flow accumulation in a narrow buffer, or the
  upstream canal length from the segment graph (config ``upstream_method``).
* need = weighted linear combination of min-max normalised criteria (Malczewski2006),
  weights direct or AHP (Saaty1980, CR must be <= 0.10), sensitivity analysis by
  one-at-a-time weight perturbation (Chen2010).
* feasibility (concession) is applied AFTER scoring, never inside the need score.
"""
from __future__ import annotations

import math

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds
from scipy.stats import spearmanr

from .config import ConfigError, MissingParameters, require

RI = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}  # Saaty1980


def ahp_weights(m) -> tuple[np.ndarray, float]:
    """Principal-eigenvector weights and consistency ratio (Saaty1980)."""
    a = np.asarray(m, float)
    n = a.shape[0]
    if a.shape != (n, n) or n < 1:
        raise ConfigError("ahp_matrix must be square")
    vals, vecs = np.linalg.eig(a)
    k = int(np.argmax(vals.real))
    w = np.abs(vecs[:, k].real)
    w = w / w.sum()
    ci = (vals[k].real - n) / (n - 1) if n > 1 else 0.0
    cr = ci / RI[n] if RI.get(n, 0) > 0 else 0.0
    return w, float(cr)


def dominant_by_length(segments: gpd.GeoDataFrame, polygons: gpd.GeoDataFrame, value_col: str, order_col: str | None = None,
                       id_col: str = "seg_id") -> pd.DataFrame:
    """Value covering the largest total length of each segment (+ ``share_dominant``).

    Intersect, sum piece lengths per (segment, value), take the argmax per segment. Ties
    go to the larger ``order_col`` (default the value itself), which is deterministic.
    """
    order_col = order_col or value_col
    pol = polygons[[value_col, order_col, "geometry"]] if order_col != value_col else polygons[[value_col, "geometry"]]
    ov = gpd.overlay(segments[[id_col, "geometry"]], pol, how="intersection", keep_geom_type=True)
    if ov.empty:
        return pd.DataFrame({value_col: pd.Series(dtype=object), "share_dominant": pd.Series(dtype=float)})
    ov["_len"] = ov.geometry.length
    ov["_o"] = ov[order_col]
    g = ov.groupby([id_col, value_col], dropna=True).agg(_len=("_len", "sum"), _o=("_o", "max")).reset_index()
    g["_lr"] = g["_len"].round(6)
    g = g.sort_values([id_col, "_lr", "_o"], ascending=[True, False, False]).drop_duplicates(id_col)
    total = segments.set_index(id_col).geometry.length
    g["share_dominant"] = g["_len"].to_numpy() / total.reindex(g[id_col]).to_numpy()
    return g.set_index(id_col)[[value_col, "share_dominant"]]


def zonal(src, geom, stat: str = "mean"):
    """Statistic of ``src`` inside ``geom`` (nodata ignored)."""
    if geom.is_empty:
        return np.nan
    win = from_bounds(*geom.bounds, transform=src.transform).round_offsets().round_lengths()
    win = win.intersection(Window(0, 0, src.width, src.height))
    if win.width <= 0 or win.height <= 0:
        return np.nan
    arr = src.read(1, window=win).astype("float64")
    tr = src.window_transform(win)
    inside = ~geometry_mask([geom], out_shape=arr.shape, transform=tr, all_touched=False)
    if src.nodata is not None:
        arr[arr == src.nodata] = np.nan
    v = arr[inside & np.isfinite(arr)]
    if v.size == 0:
        return np.nan
    return float(v.mean() if stat == "mean" else v.max())


def ring(geom, inner: float, outer: float):
    """Both-sides ring around a segment, excluding the canal water surface (inner)."""
    return geom.buffer(outer).difference(geom.buffer(inner))


def upstream_length_graph(segs: gpd.GeoDataFrame) -> pd.Series:
    """Total length of canal segments upstream of each segment (segment digraph)."""
    def k(c):
        return (round(c[0], 3), round(c[1], 3))
    up, down = {}, {}
    for sid, g, d in zip(segs["seg_id"], segs.geometry, segs["direction"]):
        a, b = k(g.coords[0]), k(g.coords[-1])
        # note: segment geometry is oriented like the canal; downstream end depends on direction
        down[sid], up[sid] = (b, a) if d == "forward" else (a, b)
    by_up: dict = {}
    for sid, n in up.items():
        by_up.setdefault(n, []).append(sid)
    D = nx.DiGraph()
    D.add_nodes_from(segs["seg_id"])
    for sid, n in down.items():          # edge upstream -> downstream
        for t in by_up.get(n, []):
            if t != sid:
                D.add_edge(sid, t)
    L = dict(zip(segs["seg_id"], segs.geometry.length))
    return pd.Series({s: sum(L[a] for a in nx.ancestors(D, s)) for s in D.nodes})


def minmax(x: np.ndarray, higher_is_worse: bool) -> np.ndarray:
    lo, hi = np.nanmin(x), np.nanmax(x)
    n = np.zeros_like(x, float) if hi - lo < 1e-12 else (x - lo) / (hi - lo)
    return n if higher_is_worse else 1 - n


def rank_scores(score: pd.Series) -> pd.Series:
    """Unique rank (1 = highest need), ties broken by seg_id for determinism."""
    order = sorted(score.index, key=lambda i: (-score[i], i))
    return pd.Series({s: r + 1 for r, s in enumerate(order)})


def sensitivity(norm: pd.DataFrame, w: np.ndarray, names: list[str], top_fraction: float, feasible: pd.Series) -> pd.DataFrame:
    """One-at-a-time +/-10% and +/-20% weight perturbation (Chen2010)."""
    base = norm.to_numpy() @ w
    base_s = pd.Series(base, index=norm.index)
    n_top = max(1, math.ceil(top_fraction * int(feasible.sum())))
    def top(s):
        r = rank_scores(s[feasible[feasible].index])
        return set(r[r <= n_top].index)
    t0 = top(base_s)
    rows = []
    for i, nm in enumerate(names):
        for dpct in (-20, -10, 10, 20):
            w2 = w.copy(); w2[i] *= 1 + dpct / 100.0; w2 = w2 / w2.sum()
            s2 = pd.Series(norm.to_numpy() @ w2, index=norm.index)
            rho = spearmanr(base, s2.to_numpy())[0] if len(norm) > 2 else np.nan
            rows.append(dict(criterion=nm, delta_pct=dpct, spearman_rho=float(rho), top_share_retained=len(t0 & top(s2)) / len(t0)))
    return pd.DataFrame(rows)


def run(ctx) -> None:
    cfg = ctx.cfg
    pc = cfg.prioritise
    segs = ctx.read_layer("canal_segments").sort_values("seg_id").reset_index(drop=True)
    names = list(pc.criteria.keys())
    # ---- null parameters, reported together (weights, buffer, concession mode)
    missing = []
    if pc.weights_mode == "ahp":
        if pc.ahp_matrix is None:
            missing.append("prioritise.ahp_matrix")
    else:
        missing += [f"prioritise.criteria.{k}.weight" for k in names if pc.criteria[k].weight is None]
    if pc.upstream_method == "flow_acc" and pc.upstream_buffer_m is None:
        missing.append("prioritise.upstream_buffer_m")
    if ctx.has_layer("inputs_clipped_concession") and pc.feasibility.concession_mode is None:
        missing.append("prioritise.feasibility.concession_mode")
    if missing:
        raise MissingParameters("Stage 6 needs these parameters (TODO(human), see spec section 11): " + ", ".join(missing))
    if pc.weights_mode == "ahp":
        w, cr = ahp_weights(pc.ahp_matrix)
        if len(w) != len(names):
            raise ConfigError("ahp_matrix size must equal the number of criteria")
        if cr > 0.10:
            raise ConfigError(f"AHP consistency ratio {cr:.3f} > 0.10; revise the pairwise matrix")
        ctx.report["ahp_cr"] = cr
    else:
        w = np.array([pc.criteria[k].weight for k in names], float)
        w = w / w.sum()
    ctx.report["weights"] = dict(zip(names, map(float, w)))

    # ---- categorical transfer (length-weighted)
    ba = ctx.read_layer("inputs_clipped_burn_area")
    pe = ctx.read_layer("inputs_clipped_peat_depth")
    d = dominant_by_length(segs, ba.assign(burn_freq_n=ba["burn_freq_n"].astype(float)).dropna(subset=["burn_freq_n"]), "burn_freq_n")
    segs["burn_freq_n"] = segs["seg_id"].map(d["burn_freq_n"]).fillna(0).astype(int)
    segs["burn_share_dom"] = segs["seg_id"].map(d["share_dominant"]).fillna(0.0)
    pe = pe.assign(_mid=(pe["depth_min_m"] + pe["depth_max_m"]) / 2)
    d = dominant_by_length(segs, pe, "peat_class", order_col="_mid")
    segs["peat_class"] = segs["seg_id"].map(d["peat_class"])
    segs["peat_share_dom"] = segs["seg_id"].map(d["share_dominant"]).fillna(0.0)
    cls = pe.drop_duplicates("peat_class").set_index("peat_class")
    segs["peat_depth_mid_m"] = segs["peat_class"].map(cls["_mid"]).fillna(0.0)
    sk = ctx.read_layer("subkhg_selected")
    d = dominant_by_length(segs, sk[["subkhg_id", "geometry"]], "subkhg_id")
    segs["subkhg_id"] = segs["seg_id"].map(d["subkhg_id"])

    # ---- raster criteria
    inner, outer = pc.ring_buffer_m
    with rasterio.open(ctx.report["inputs"]["moisture"]) as m:
        ring_mean = [zonal(m, ring(g, inner, outer), "mean") for g in segs.geometry]
    sign = -1.0 if cfg.inputs.moisture.higher_is_wetter else 1.0
    segs["moisture_ring_mean"] = ring_mean
    segs["dryness_raw"] = sign * segs["moisture_ring_mean"]
    if pc.upstream_method == "flow_acc":
        with rasterio.open(ctx.report["inputs"]["flow_acc"]) as f:
            segs["flow_acc_max"] = [zonal(f, g.buffer(pc.upstream_buffer_m), "max") for g in segs.geometry]
        segs["upstream_contrib_raw"] = np.log1p(segs["flow_acc_max"])
    else:
        segs["upstream_contrib_raw"] = segs["seg_id"].map(upstream_length_graph(segs)).fillna(0.0)
    ctx.report["upstream_method"] = pc.upstream_method
    raw = {"burn_freq": segs["burn_freq_n"].astype(float), "peat_depth": segs["peat_depth_mid_m"], "dryness": segs["dryness_raw"],
           "upstream_contrib": segs["upstream_contrib_raw"]}

    # ---- scoring on segments with status_mcda == 1
    ok = (segs["status_mcda"] == 1) & segs["subkhg_id"].notna()   # margin canals outside the sub-KHGs are not scored
    norm = pd.DataFrame(index=segs.index[ok])
    for k in names:
        x = raw[k][ok].astype(float)
        nan = int(x.isna().sum())
        if nan:
            ctx.warn(f"Stage 6: {nan} segment(s) without {k} data; filled with the median")
            x = x.fillna(x.median())
        n = minmax(x.to_numpy(), pc.criteria[k].direction == "higher_is_worse")
        norm[k] = n
        segs.loc[ok, f"{k}_norm"] = n
        segs[f"{k}_raw"] = raw[k]
    score = pd.Series(norm.to_numpy() @ w, index=segs.loc[ok, "seg_id"].to_numpy())
    segs["need_score"] = segs["seg_id"].map(score)
    segs["need_rank"] = segs["seg_id"].map(rank_scores(score)).astype("Int64")

    # ---- feasibility, after scoring
    segs["concession_share"] = 0.0
    segs["feasible"] = True
    if ctx.has_layer("inputs_clipped_concession"):
        mode = pc.feasibility.concession_mode
        con = ctx.read_layer("inputs_clipped_concession")
        if len(con):
            u = gpd.GeoDataFrame({"_c": [1]}, geometry=[con.geometry.union_all()], crs=ctx.crs)
            d = dominant_by_length(segs, u, "_c")
            share = segs["seg_id"].map(d["share_dominant"]).fillna(0.0)
            segs["concession_share"] = share
            inside = share > 0.5     # dominant by length
            segs["concession_flag"] = inside
            if mode == "exclude":
                segs["feasible"] = ~inside
    segs["selected"] = False
    cand = segs[ok & segs["feasible"]].sort_values("need_rank")
    n_sel = math.ceil(pc.top_fraction * len(cand))
    segs.loc[cand.index[:n_sel], "selected"] = True

    # ---- sensitivity
    norm.index = segs.loc[ok, "seg_id"].to_numpy()
    feas = pd.Series(segs.loc[ok, "feasible"].to_numpy(), index=norm.index)
    sens = sensitivity(norm, w, names, pc.top_fraction, feas) if len(norm) > 2 and feas.any() else pd.DataFrame(
        {"criterion": [], "delta_pct": [], "spearman_rho": [], "top_share_retained": []})
    ctx.write_layer("canal_segments", segs, "6")
    ctx.write_layer("qa_sensitivity", sens, "6")
    ctx.report["sensitivity"] = sens.to_dict("records")
    ctx.set_counts("6", scored=int(ok.sum()), selected=int(segs["selected"].sum()), infeasible=int((~segs["feasible"]).sum()))
