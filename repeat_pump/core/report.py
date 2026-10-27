"""Stage 11: run report (``run_report.md`` and ``run_report.json``) and optional validation."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .io import find_col
from .requirements import get_value


def _nulls(obj, prefix="") -> list[str]:
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += _nulls(v, f"{prefix}{k}.")
    elif obj is None:
        out.append(prefix.rstrip("."))
    return out


def _tma_validation(ctx) -> list[dict] | str:
    """Observed vs modelled pool level (z_land - dA) at the nearest canal profile station. Validation only."""
    if not ctx.has_layer("inputs_clipped_tma_obs"):
        return "not provided"
    obs = ctx.read_layer("inputs_clipped_tma_obs")
    if obs.empty:
        return "no observations inside the extent"
    try:
        col = find_col(obs, ["tma_m", "water_level_m", "level_m", "wl_m", "tma"], "tma_obs")
    except Exception:
        return "tma_obs has no recognised level column (tma_m / water_level_m / level_m / wl_m)"
    prof = ctx.read_layer("canal_profiles")
    dA = ctx.cfg.sekat.dA_m
    rows = []
    for _, o in obs.iterrows():
        d = prof.geometry.distance(o.geometry)
        j = d.idxmin()
        rows.append(dict(obs=float(o[col]), modelled_pool_m=float(prof.z_land_m[j] - dA), distance_m=float(d[j])))
    return rows


def run(ctx) -> None:
    cfg = ctx.cfg
    rep = ctx.report
    todo = _nulls(cfg.model_dump())
    summary = {
        "run": cfg.run.name,
        "config": cfg.model_dump(),
        "validation": rep.get("validation", {}),
        "warnings": ctx.warnings,
        "counts": rep.get("counts", {}),
        "notes": rep.get("notes", []),
        "files": rep.get("inputs", {}),
        "hydro": rep.get("hydro", {}),
        "weights": rep.get("weights", {}),
        "sensitivity": rep.get("sensitivity", []),
        "routing": rep.get("routing", {}),
        "sekat_balance": rep.get("sekat_balance", {}),
        "pumps": rep.get("pumps", []),
        "null_parameters": todo,
        "preset": cfg.preset,
        "tma_validation": _tma_validation(ctx),
    }
    from . import interventions
    summary["interventions"] = interventions.run(ctx)
    summary["budget"] = ctx.report.get("budget")            # written by the interventions step
    canals = ctx.read_layer("canals_clean")
    ipg = []
    if "n_req" in canals:
        ipg = canals[["canal_id", "length_m", "direction", "n_req", "n_existing", "ipg"]].replace({np.nan: None}).to_dict("records")
    summary["ipg"] = ipg
    (ctx.out_dir / "run_report.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf8")

    L = [f"# Run report: {cfg.run.name}", ""]
    L += ["## Files (rasters kept outside the GeoPackage)", ""] + [f"- {k}: {v}" for k, v in summary["files"].items()] + [""]
    L += ["## Warnings", ""] + ([f"- {w}" for w in ctx.warnings] or ["- none"]) + [""]
    L += ["## Validation", "", "```json", json.dumps(summary["validation"], indent=2, default=str), "```", ""]
    L += ["## Stage counts", ""] + [f"- Stage {k}: {v}" for k, v in sorted(summary["counts"].items(), key=lambda kv: int(kv[0]))] + [""]
    L += ["## IPG per canal", "", "| canal | length_m | direction | n_req | n_existing | IPG |", "|---|---|---|---|---|---|"]
    L += [f"| {r['canal_id']} | {r['length_m']:.0f} | {r['direction']} | {r['n_req']} | {r['n_existing']} | {r['ipg']} |" for r in ipg] + [""]
    L += ["## Weights and sensitivity", "", f"Weights: {summary['weights']}", ""]
    if summary["sensitivity"]:
        s = pd.DataFrame(summary["sensitivity"])
        L += [f"Minimum Spearman rho: {s.spearman_rho.min():.3f}; minimum share of top-fraction segments retained: {s.top_share_retained.min():.2f}", ""]
    L += ["## Routing", "", json.dumps(summary["routing"], indent=2, default=str), ""]
    L += ["## Pump stations", "", "| station | node | Q m3/s | H m | P kW | units |", "|---|---|---|---|---|---|"]
    L += [f"| {p['station_id']} | {p['node_id']} | {p['q_m3s']:.4f} | {p['h_m']:.2f} | {p['p_kw']:.2f} | {p['units_needed']} |" for p in summary["pumps"]] + [""]
    iv = summary.get("interventions")
    if iv:
        L += ["## Interventions per sub-KHG", "", f"{iv['units']} sub-KHG; thresholds: {iv['thresholds']}. Layer `interventions`, table interventions.csv.", "",
              "| class | sub-KHG |", "|---|---|"] + [f"| {interventions.CLASSES[k]} | {n} |" for k, n in iv["counts"].items()] + [""]
        if iv.get("closed_otherwise"):
            L += ["Without the protected-peat rule, the units with canal closure would need: "
                  + ", ".join(f"{interventions.CLASSES[k]} {n}" for k, n in iv["closed_otherwise"].items()), ""]
        if iv["held_share_selected"]:
            L += ["Share of the deficit the kept sekat hold, selected sub-KHG: "
                  + ", ".join(f"{u} {100 * s:.1f} %" for u, s in iv["held_share_selected"].items()), ""]
    bd = summary.get("budget")
    if bd:
        fmt = lambda v: "-" if v is None else f"{v / 1e9:,.2f}"     # noqa: E731
        L += [f"## Budget estimate (billion rupiah, prices of {bd.get('price_year') or 'unknown year'}, proposed, not team decisions)", "",
              "| item | quantity | low | central | high |", "|---|---|---|---|---|"]
        L += [f"| {k} | {v['quantity']:,.1f} | {fmt(v['cost_low_idr'])} | {fmt(v['cost_idr'])} | {fmt(v['cost_high_idr'])} |" for k, v in bd["by_item"].items()]
        L += [f"| **total** | | {fmt(bd['total_low_idr'])} | {fmt(bd['total_idr'])} | {fmt(bd['total_high_idr'])} |", ""]
        if bd.get("idr_per_m3_held"):
            L += [f"Sekat in the selected sub-KHG: {bd['idr_per_m3_held']:,.0f} rupiah per m3 of water held.", ""]
        if bd.get("unpriced"):
            L += ["Not priced (quantity only): " + ", ".join(bd["unpriced"]), ""]
        L += ["Table per sub-KHG and item: budget.csv. Sources of the prices: docs/proposed_defaults.md.", ""]
    L += ["## Observed vs modelled levels (validation only)", "", json.dumps(summary["tma_validation"], indent=2, default=str), ""]
    if cfg.preset["keys"]:
        L += ["## Values from the proposed-defaults preset (not team decisions)", "", f"Preset: {cfg.preset['path']}", ""]
        L += [f"- {k} = {get_value(cfg, k)}" for k in cfg.preset["keys"]] + [""]
    L += ["## Parameters still null (TODO(human))", ""] + [f"- {t}" for t in todo] + [""]
    (ctx.out_dir / "run_report.md").write_text("\n".join(L), encoding="utf8")
    ctx.set_counts("11", warnings=len(ctx.warnings), null_parameters=len(todo))
