"""Stage 12 (optional): canal blocking optimisation after Urzainki et al. (2020) [Urzainki2020].

Chooses which ``optimise.n_blocks`` of the Stage 7 proposed sekat to build so that canal water levels (``canal_rise``) or
the dry peat volume from a 2D Boussinesq model (``pde``) improve most, using a genetic algorithm [Holland1975] and
simulated annealing [Kirkpatrick1983], with greedy, random and rule-based comparators.

This is an *alternative plan*: stages 8 to 10 still assume every proposed sekat is built, and nothing here changes them.
Off by default (``optimise.enabled: false``): the stage then records ``skipped`` and asks for nothing.
"""
from __future__ import annotations

import json
import math
import re

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio import features
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.windows import from_bounds
from scipy.ndimage import binary_erosion

from . import blockopt as bo
from .config import require
from .groundwater import PeatTable


def build_grid(ctx, net: bo.CanalNet, grid_m: float) -> bo.Grid:
    """Raster the sub-KHG, the (unconditioned) DTM, the peat depth and the canal stations on a ``grid_m`` grid."""
    sk = ctx.read_layer("subkhg_selected")
    minx, miny, maxx, maxy = sk.total_bounds
    nx, ny = max(3, math.ceil((maxx - minx) / grid_m)), max(3, math.ceil((maxy - miny) / grid_m))
    tr = from_origin(minx, maxy, grid_m, grid_m)
    domain = features.rasterize([(g, 1) for g in sk.geometry], out_shape=(ny, nx), transform=tr, fill=0).astype(bool)
    with rasterio.open(ctx.report["inputs"]["dtm"]) as src:
        win = from_bounds(minx, maxy - ny * grid_m, minx + nx * grid_m, maxy, src.transform)
        surface = src.read(1, window=win, out_shape=(ny, nx), resampling=Resampling.average, boundless=True,
                           fill_value=np.nan).astype("float64")
        if src.nodata is not None:
            surface[surface == src.nodata] = np.nan
    domain &= np.isfinite(surface)
    depth = np.zeros((ny, nx))
    if "peat_depth" in ctx.report["inputs"]:              # a depth raster (metres, from stage 1): averaged onto the grid
        with rasterio.open(ctx.report["inputs"]["peat_depth"]) as src:
            win = from_bounds(minx, maxy - ny * grid_m, minx + nx * grid_m, maxy, src.transform)
            depth = src.read(1, window=win, out_shape=(ny, nx), resampling=Resampling.average, boundless=True,
                             fill_value=np.nan).astype("float64")
        depth = np.where(np.isfinite(depth) & (depth > 0), depth, 0.0)
    elif ctx.has_layer("inputs_clipped_peat_depth"):
        pe = ctx.read_layer("inputs_clipped_peat_depth")
        mid = (pe["depth_min_m"] + pe["depth_max_m"]) / 2.0
        shapes = [(g, float(d)) for g, d in zip(pe.geometry, mid) if np.isfinite(d) and d > 0]
        if shapes:
            depth = features.rasterize(shapes, out_shape=(ny, nx), transform=tr, fill=0.0, dtype="float64")
    surface = np.where(domain, surface, 0.0)
    boundary = domain & ~binary_erosion(domain)
    cell = np.full(net.n, -1, dtype=int)
    owners: dict = {}
    for k in range(net.n):
        c, r = int((net.xy[k, 0] - minx) // grid_m), int((maxy - net.xy[k, 1]) // grid_m)
        if 0 <= r < ny and 0 <= c < nx and domain[r, c]:
            cell[k] = r * nx + c
            owners.setdefault(cell[k], set()).add(net.canal[k])
    shared = sum(1 for v in owners.values() if len(v) > 1)
    return bo.Grid(surface, domain, domain & (depth > 0), depth, boundary, cell, float(grid_m), shared)


def _fmt(sel, ids) -> str:
    return ";".join(str(ids[i]) for i in sel)


def run(ctx):
    cfg = ctx.cfg
    oc = cfg.optimise
    if not oc.enabled:
        ctx.log.info("Stage 12 skipped: optimise.enabled is false")
        return "skipped"
    need = ["n_blocks", "max_evaluations", "canal_drawdown_m"]
    if oc.objective != "canal_rise":
        need += ["grid_m", "dry_days", "et_mm_day", "transmissivity_multiplier"]
    require(oc, need, "Stage 12", "optimise")
    dA = cfg.sekat.dA_m
    canals = ctx.read_layer("canals_clean")
    prof = ctx.read_layer("canal_profiles")
    cand = ctx.read_layer("sekat_proposed")
    if cfg.pumping.enabled and cfg.pumping.sekat_scope == "selected" and ctx.has_layer("sekat_scope") and len(cand):
        sc = ctx.read_layer("sekat_scope")
        planned = set(sc.loc[sc["planned"].astype(bool), "sekat_pro_id"])
        cand = cand[cand["sekat_pro_id"].isin(planned)]
        ctx.log.info("Stage 12: pumping.sekat_scope is selected, so only the %d planned sekat are candidates", len(cand))
    if len(cand) == 0:
        ctx.warn("Stage 12: there are no proposed sekat to choose from; nothing to optimise")
        return "skipped"
    net = bo.CanalNet.from_profiles(canals, prof)
    base = net.z_land - oc.canal_drawdown_m

    # candidates: the Stage 7 proposed sekat (existing sekat are always in place and do not count towards n_blocks)
    cand = cand.reset_index(drop=True)
    nodes = [net.node_at(c, ch) for c, ch in zip(cand["canal_id"], cand["chainage_m"])]
    keep = [i for i, n in enumerate(nodes) if n is not None]
    if len(keep) < len(cand):
        ctx.warn(f"Stage 12: {len(cand) - len(keep)} proposed sekat are not on a profiled canal and were left out")
    cand, nodes = cand.iloc[keep].reset_index(drop=True), [nodes[i] for i in keep]
    crest = np.array([net.z_land[n] - dA for n in nodes])
    ineffective = int(np.sum(crest <= np.array([base[n] for n in nodes]) + 1e-9))
    if ineffective:
        ctx.warn(f"Stage 12: {ineffective} candidate(s) hold water no higher than the canal already stands "
                 f"(optimise.canal_drawdown_m is not larger than sekat.dA_m), so they cannot raise anything")
    fixed: dict = {}
    if ctx.has_layer("sekat_existing_assessed"):
        ex = ctx.read_layer("sekat_existing_assessed")
        for _, r in (ex[ex["snapped"].astype(bool)] if "snapped" in ex else ex.iloc[0:0]).iterrows():
            n = net.node_at(r["canal_id"], r["chainage_m"])
            if n is None:
                continue
            ce = r.get("crest_elev_m", np.nan)
            fixed[n] = max(fixed.get(n, -np.inf), float(ce) if ce == ce and ce is not None else float(net.z_land[n] - dA))

    n_cand = len(cand)
    k = min(int(oc.n_blocks), n_cand)
    if oc.n_blocks > n_cand:
        ctx.warn(f"Stage 12: optimise.n_blocks ({oc.n_blocks}) exceeds the {n_cand} candidate sites; all candidates are chosen")
    proxy = bo.CanalRiseObjective(net, base, nodes, crest, fixed)
    pde = None
    if oc.objective in ("pde", "screen_then_pde"):
        grid = build_grid(ctx, net, oc.grid_m)
        if grid.shared_cells:
            ctx.warn(f"Stage 12: {grid.shared_cells} grid cell(s) hold nodes of more than one canal; the cell takes their mean level "
                     f"(use a smaller optimise.grid_m if canals run closer than {oc.grid_m:g} m)")
        pde = bo.PdeObjective(net, base, nodes, crest, fixed, grid, PeatTable.urzainki2020(), oc.dry_days, oc.et_mm_day,
                              oc.transmissivity_multiplier)
    search_fn = pde.benefit if oc.objective == "pde" else proxy.benefit
    unit = "ha m of dry peat avoided" if oc.objective == "pde" else "m of canal level rise"
    if oc.max_evaluations < 2 * oc.ga.population:
        ctx.warn(f"Stage 12: optimise.max_evaluations ({oc.max_evaluations}) is below twice the GA population ({oc.ga.population}); "
                 "the genetic algorithm will barely leave its random start")
    ctx.log.info("Stage 12: %d candidates, choosing %d, objective %s, algorithms %s", n_cand, k, oc.objective, oc.algorithms)
    results = bo.optimise_subset(search_fn, n_cand, k, list(oc.algorithms), int(oc.max_evaluations), oc.seed, log=ctx.log.info,
                                 ga_kw=oc.ga.model_dump(), sa_kw=oc.sa.model_dump())

    # comparators scored with the same objective: random draws, and the highest need_score segments (rule-based)
    rng = np.random.default_rng(oc.seed + 1)
    rnd = bo.random_baseline(search_fn, n_cand, k, int(oc.random_baseline_draws), rng) if oc.random_baseline_draws > 0 else np.array([])
    rule = None
    segs = ctx.read_layer("canal_segments")
    if "need_score" in segs and "seg_id" in cand:
        score = dict(zip(segs["seg_id"], segs["need_score"]))
        order = sorted(range(n_cand), key=lambda i: -(score.get(cand["seg_id"].iloc[i], -np.inf) if score.get(cand["seg_id"].iloc[i], np.nan) == score.get(cand["seg_id"].iloc[i], np.nan) else -np.inf))
        rule = tuple(sorted(order[:k]))

    ids = list(cand["sekat_pro_id"])
    rows = []
    rnd_mean = float(rnd.mean()) if rnd.size else np.nan

    def add(method, sel, evals, value, proxy_value=None):
        rows.append(dict(method=method, blocks=len(sel), evaluations=evals, benefit=float(value), unit=unit,
                         benefit_vs_random=(float(value) / rnd_mean if rnd_mean and rnd_mean == rnd_mean and rnd_mean != 0 else np.nan),
                         sites=_fmt(sel, ids)))
    final = {}
    for r in results:
        sel_val = r.value
        if oc.objective == "screen_then_pde":                      # refine: re-score the screened winners with the full model
            sel_val = pde.benefit(r.best)
        final[r.algo] = (r.best, sel_val)
        add(r.algo, r.best, r.evaluations, sel_val)
    if rule is not None:
        v = pde.benefit(rule) if oc.objective == "screen_then_pde" else search_fn(rule)
        final["rule_based"] = (rule, v)
        add("rule_based", rule, 1, v)
    if rnd.size:
        rows.append(dict(method="random_mean", blocks=k, evaluations=int(rnd.size), benefit=rnd_mean, unit=unit, benefit_vs_random=1.0, sites=""))
    qa = pd.DataFrame(rows)
    best_algo = max((a for a in final if a in oc.algorithms), key=lambda a: final[a][1])
    best_sel, best_val = final[best_algo]

    out = cand.copy()
    out["crest_m"] = crest
    out["selected_best"] = [i in best_sel for i in range(n_cand)]
    for a, (sel, _) in final.items():
        out[f"selected_{a}"] = [i in sel for i in range(n_cand)]
    out["best_method"] = best_algo
    trace = pd.DataFrame([dict(method=r.algo, evaluations=int(e), best_so_far=float(v)) for r in results for e, v in r.trace])
    if not isinstance(out, gpd.GeoDataFrame):
        out = gpd.GeoDataFrame(out, geometry="geometry", crs=ctx.crs)
    ctx.write_layer("sekat_optimised", out, "12")
    ctx.write_layer("qa_optimisation", qa, "12")
    if len(trace):
        ctx.write_layer("qa_optimisation_trace", trace, "12")

    summary = dict(objective=oc.objective, unit=unit, candidates=n_cand, blocks=k, best_method=best_algo, best_benefit=float(best_val),
                   random_mean_benefit=rnd_mean, gain_vs_random=(float(best_val) / rnd_mean if rnd_mean and rnd_mean == rnd_mean and rnd_mean != 0 else None),
                   best_sites=[ids[i] for i in best_sel],
                   baseline_dry_volume_ha_m=(float(pde.dry_fixed) if pde is not None else None),
                   note="Alternative plan: stages 8-10 still assume every proposed sekat is built. Benefit is relative to the existing "
                        "structures only and is not a field-validated water table change.")
    ctx.report["optimisation"] = summary
    ctx.set_counts("12", candidates=n_cand, blocks=k, evaluations=int(sum(r.evaluations for r in results)),
                   best_method=best_algo, gain_vs_random=round(summary["gain_vs_random"], 2) if summary["gain_vs_random"] else 0)
    append_to_report(ctx, summary, qa)
    return None


def append_to_report(ctx, summary: dict, table: pd.DataFrame) -> None:
    """Stage 11 has already written the report: add (or replace) this stage's section in run_report.json and run_report.md."""
    js, md = ctx.out_dir / "run_report.json", ctx.out_dir / "run_report.md"
    if js.exists():
        data = json.loads(js.read_text(encoding="utf8"))
        data["optimisation"] = summary
        data["optimisation_table"] = table.replace({np.nan: None}).to_dict("records")
        js.write_text(json.dumps(data, indent=2, default=str), encoding="utf8")
    if md.exists():
        text = md.read_text(encoding="utf8")
        text = re.sub(r"\n## Canal blocking optimisation \(Stage 12\).*?(?=\n## |\Z)", "", text, flags=re.S)
        L = ["", "## Canal blocking optimisation (Stage 12)", "",
             f"Objective `{summary['objective']}`, {summary['blocks']} of {summary['candidates']} candidate sekat, best method **{summary['best_method']}**.",
             "", "This is an alternative plan. Stages 8 to 10 still assume every proposed sekat is built. The benefit is relative to the existing "
             "structures only and is not a field-validated water table change.", "", "| method | blocks | evaluations | benefit | vs random |", "|---|---|---|---|---|"]
        for r in table.itertuples():
            vr = "" if r.benefit_vs_random != r.benefit_vs_random else f"{r.benefit_vs_random:.2f}"
            L.append(f"| {r.method} | {r.blocks} | {r.evaluations} | {r.benefit:.4g} {r.unit} | {vr} |")
        md.write_text(text.rstrip("\n") + "\n" + "\n".join(L) + "\n", encoding="utf8")
