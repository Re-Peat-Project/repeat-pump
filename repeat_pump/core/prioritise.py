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

``weights_mode: klh`` is an opt-in alternative that reproduces steps 7.1 and 7.2 of the KLH technical guide ([PanduanKLH]):
four ordinal criteria scored 1 to 3 and added (maximum 12), segments with a total of at least ``klh_min_score`` selected. The
class breaks are fixed numbers, not min-max normalised, and the moisture mean is read in the full ``upstream_buffer_m`` buffer
including the canal water. It deliberately keeps those two choices (AGENTS.md section 9, bugs 4 and 5) because the guide does;
the default method is unchanged and the report warns whenever the mode is used.
"""
from __future__ import annotations

import math

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import rasterio
from rasterio.errors import WindowError
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


def zonal_values(src, geom) -> tuple[np.ndarray, int]:
    """Valid cell values of ``src`` inside ``geom`` (nodata ignored) and the number of cells inside."""
    if geom.is_empty:
        return np.empty(0), 0
    win = from_bounds(*geom.bounds, transform=src.transform).round_offsets().round_lengths()
    try:
        win = win.intersection(Window(0, 0, src.width, src.height))
    except WindowError:
        return np.empty(0), 0
    if win.width <= 0 or win.height <= 0:
        return np.empty(0), 0
    arr = src.read(1, window=win).astype("float64")
    tr = src.window_transform(win)
    inside = ~geometry_mask([geom], out_shape=arr.shape, transform=tr, all_touched=False)
    if src.nodata is not None:
        arr[arr == src.nodata] = np.nan
    return arr[inside & np.isfinite(arr)], int(inside.sum())


def zonal(src, geom, stat: str = "mean"):
    """Statistic of ``src`` inside ``geom`` (nodata ignored): mean, max, median or min."""
    v, _ = zonal_values(src, geom)
    if v.size == 0:
        return np.nan
    return float({"mean": np.mean, "max": np.max, "median": np.median, "min": np.min}[stat](v))


def peat_from_raster(path: str, segs, progress=None) -> pd.DataFrame:
    """Peat depth along each segment from a depth raster in metres: the median of the cells within one cell width of the line scores
    the segment, the minimum feeds the KLH rule (shallowest depth, as the class minimum does for polygons; team decision 26 Oct 2026).
    ``peat_share_dom`` is the share of those cells that hold a depth. Segments without peat cells get 0, as with polygons."""
    rows = []
    with rasterio.open(path) as src:
        width = max(abs(src.res[0]), abs(src.res[1]))
        for k, g in enumerate(segs.geometry):
            if progress:
                progress(k, len(segs))
            v, n = zonal_values(src, g.buffer(width))
            rows.append((float(np.median(v)) if v.size else 0.0, float(v.min()) if v.size else 0.0, v.size / n if n else 0.0))
    return pd.DataFrame(rows, columns=["peat_depth_mid_m", "peat_depth_min_m", "peat_share_dom"], index=segs.index)


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


def klh_breaks(values, name: str) -> tuple[float, float]:
    if not isinstance(values, (list, tuple)) or len(values) != 2 or not values[0] < values[1]:
        raise ConfigError(f"prioritise.{name} must be two increasing numbers, for example [0.8, 1.5]; got {values!r}")
    return float(values[0]), float(values[1])


KLH_MAX_SCORE = 12


def klh_scores(burn: np.ndarray, peat_min_m: np.ndarray, moisture: np.ndarray, flow: np.ndarray, cpwi_breaks, flow_breaks,
               higher_is_wetter: bool) -> dict[str, np.ndarray]:
    """Step 7.1 of the KLH guide, each criterion 1 to 3 (a missing value scores 1, like ``ELSE 1`` in the guide's expression).

    * burn: 2 or more burn years 3, one year 2, none 1 (the guide's 2x, 3x, 4x -> 3, 1x -> 2, else 1, on the parsed count);
    * peat: shallowest depth of the class 3 m or more 3, 1 m or more 2, otherwise 1 (the guide lists the classes, this is the same rule);
    * dryness: the moisture mean below the first break 3, up to the second 2, above 1; mirrored when a higher value means drier;
    * flow: maximum flow accumulation above the second break 3, above the first 2, otherwise 1.
    """
    b0, b1 = cpwi_breaks
    f0, f1 = flow_breaks
    burn_s = np.where(burn >= 2, 3, np.where(burn >= 1, 2, 1))
    peat_s = np.where(peat_min_m >= 3, 3, np.where(peat_min_m >= 1, 2, 1))
    with np.errstate(invalid="ignore"):
        if higher_is_wetter:
            dry_s = np.where(moisture < b0, 3, np.where((moisture >= b0) & (moisture <= b1), 2, 1))
        else:
            dry_s = np.where(moisture > b1, 3, np.where((moisture >= b0) & (moisture <= b1), 2, 1))
        flow_s = np.where(flow > f1, 3, np.where(flow > f0, 2, 1))
    return {"klh_burn": burn_s, "klh_peat": peat_s, "klh_dryness": dry_s, "klh_flow": flow_s}


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
    klh = pc.weights_mode == "klh"
    missing = []
    if klh:
        missing += [f"prioritise.{k}" for k in ("klh_cpwi_breaks", "klh_flow_breaks", "klh_min_score") if getattr(pc, k) is None]
        if pc.upstream_method != "flow_acc":
            raise ConfigError("prioritise.weights_mode klh scores the flow accumulation maximum: set prioritise.upstream_method to flow_acc")
    elif pc.weights_mode == "ahp":
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
    if klh:
        cpwi_breaks, flow_breaks = klh_breaks(pc.klh_cpwi_breaks, "klh_cpwi_breaks"), klh_breaks(pc.klh_flow_breaks, "klh_flow_breaks")
        w = np.zeros(len(names))
        ctx.warn("Stage 6: KLH scoring (weights_mode klh) reproduces the guide: fixed class breaks instead of min-max normalisation and the "
                 "moisture read in the full buffer including the canal water. Use the default method for new analyses.")
        ctx.report["scoring"] = {"method": "klh", "cpwi_breaks": list(cpwi_breaks), "flow_breaks": list(flow_breaks),
                                 "min_score": pc.klh_min_score, "max_score": KLH_MAX_SCORE}
    elif pc.weights_mode == "ahp":
        w, cr = ahp_weights(pc.ahp_matrix)
        if len(w) != len(names):
            raise ConfigError("ahp_matrix size must equal the number of criteria")
        if cr > 0.10:
            raise ConfigError(f"AHP consistency ratio {cr:.3f} > 0.10; revise the pairwise matrix")
        ctx.report["ahp_cr"] = cr
    else:
        w = np.array([pc.criteria[k].weight for k in names], float)
        w = w / w.sum()
    ctx.report["weights"] = {} if klh else dict(zip(names, map(float, w)))

    # ---- categorical transfer (length-weighted)
    ba = ctx.read_layer("inputs_clipped_burn_area")
    pe = ctx.read_layer("inputs_clipped_peat_depth")
    d = dominant_by_length(segs, ba.assign(burn_freq_n=ba["burn_freq_n"].astype(float)).dropna(subset=["burn_freq_n"]), "burn_freq_n")
    segs["burn_freq_n"] = segs["seg_id"].map(d["burn_freq_n"]).fillna(0).astype(int)
    segs["burn_share_dom"] = segs["seg_id"].map(d["share_dominant"]).fillna(0.0)
    if "peat_depth" in ctx.report["inputs"]:          # a depth raster: values along the segment instead of the dominant class
        pr = peat_from_raster(ctx.report["inputs"]["peat_depth"], segs,
                              lambda k, n: ctx.progress(k / max(n, 1) * 0.1, f"peat depth, segment {k + 1} of {n}"))
        segs[["peat_depth_mid_m", "peat_depth_min_m", "peat_share_dom"]] = pr
        segs["peat_class"] = "raster"
    else:
        pe = pe.assign(_mid=(pe["depth_min_m"] + pe["depth_max_m"]) / 2)
        d = dominant_by_length(segs, pe, "peat_class", order_col="_mid")
        segs["peat_class"] = segs["seg_id"].map(d["peat_class"])
        segs["peat_share_dom"] = segs["seg_id"].map(d["share_dominant"]).fillna(0.0)
        cls = pe.drop_duplicates("peat_class").set_index("peat_class")
        segs["peat_depth_mid_m"] = segs["peat_class"].map(cls["_mid"]).fillna(0.0)
        segs["peat_depth_min_m"] = segs["peat_class"].map(cls["depth_min_m"]).fillna(0.0)
    sk = ctx.read_layer("subkhg_selected")
    d = dominant_by_length(segs, sk[["subkhg_id", "geometry"]], "subkhg_id")
    segs["subkhg_id"] = segs["seg_id"].map(d["subkhg_id"])

    # ---- raster criteria
    inner, outer = pc.ring_buffer_m
    with rasterio.open(ctx.report["inputs"]["moisture"]) as m:
        ring_mean = []
        for k, g in enumerate(segs.geometry):
            ctx.progress(k / max(len(segs), 1) * 0.5, f"moisture ring, segment {k + 1} of {len(segs)}")
            ring_mean.append(zonal(m, g.buffer(pc.upstream_buffer_m) if klh else ring(g, inner, outer), "mean"))
    sign = -1.0 if cfg.inputs.moisture.higher_is_wetter else 1.0
    segs["moisture_ring_mean"] = ring_mean
    segs["dryness_raw"] = sign * segs["moisture_ring_mean"]
    if pc.upstream_method == "flow_acc":
        with rasterio.open(ctx.report["inputs"]["flow_acc"]) as f:
            fa = []
            for k, g in enumerate(segs.geometry):
                ctx.progress(0.5 + k / max(len(segs), 1) * 0.4, f"flow accumulation, segment {k + 1} of {len(segs)}")
                fa.append(zonal(f, g.buffer(pc.upstream_buffer_m), "max"))
            segs["flow_acc_max"] = fa
        segs["upstream_contrib_raw"] = np.log1p(segs["flow_acc_max"])
    else:
        segs["upstream_contrib_raw"] = segs["seg_id"].map(upstream_length_graph(segs)).fillna(0.0)
    ctx.report["upstream_method"] = pc.upstream_method
    raw = {"burn_freq": segs["burn_freq_n"].astype(float), "peat_depth": segs["peat_depth_mid_m"], "dryness": segs["dryness_raw"],
           "upstream_contrib": segs["upstream_contrib_raw"]}

    # ---- scoring on segments with status_mcda == 1
    ok = (segs["status_mcda"] == 1) & segs["subkhg_id"].notna()   # margin canals outside the sub-KHGs are not scored
    norm = pd.DataFrame(index=segs.index[ok])
    if klh:
        parts = klh_scores(segs["burn_freq_n"].to_numpy(float), segs["peat_depth_min_m"].to_numpy(float), segs["moisture_ring_mean"].to_numpy(float),
                           segs["flow_acc_max"].to_numpy(float), cpwi_breaks, flow_breaks, bool(cfg.inputs.moisture.higher_is_wetter))
        for k, v in parts.items():
            segs[k] = np.where(ok, v, 0).astype(int)
        segs["klh_score"] = np.where(ok, sum(parts.values()), 0).astype(int)        # StatusMCDA = 0 scores 0, as in the guide
        nodata = int((ok & (segs["moisture_ring_mean"].isna() | segs["flow_acc_max"].isna())).sum())
        if nodata:
            ctx.warn(f"Stage 6: {nodata} segment(s) without moisture or flow data scored 1 for it (the guide's ELSE branch)")
        for k in names:
            segs[f"{k}_raw"] = raw[k]
        score = pd.Series((segs.loc[ok, "klh_score"] / KLH_MAX_SCORE).to_numpy(), index=segs.loc[ok, "seg_id"].to_numpy())
    else:
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
    segs["need_score"] = segs["seg_id"].map(score)             # KLH mode: total / 12, so maps and stage 12 keep working on 0-1
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
    if klh:
        segs.loc[cand.index[cand["klh_score"] >= pc.klh_min_score], "selected"] = True
    else:
        segs.loc[cand.index[:math.ceil(pc.top_fraction * len(cand))], "selected"] = True

    # ---- sensitivity
    norm.index = segs.loc[ok, "seg_id"].to_numpy()
    feas = pd.Series(segs.loc[ok, "feasible"].to_numpy(), index=norm.index)
    sens = sensitivity(norm, w, names, pc.top_fraction, feas) if not klh and len(norm) > 2 and feas.any() else pd.DataFrame(
        {"criterion": [], "delta_pct": [], "spearman_rho": [], "top_share_retained": []})
    ctx.write_layer("canal_segments", segs, "6")
    ctx.write_layer("qa_sensitivity", sens, "6")
    ctx.report["sensitivity"] = sens.to_dict("records")
    ctx.set_counts("6", scored=int(ok.sum()), selected=int(segs["selected"].sum()), infeasible=int((~segs["feasible"]).sum()))
