"""The final screen's "results at a glance", built from ``run_report.json``. Pure Python, no Qt: tested in the engine venv.

It only re-states what the engine already wrote (counts, routing, pumps, warnings). It never recomputes anything.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .i18n import tr


@dataclass
class Section:
    title: str
    rows: list[tuple[str, str]] = field(default_factory=list)       # (label, value)


@dataclass
class Summary:
    sections: list[Section] = field(default_factory=list)
    pump_table: list[list[str]] = field(default_factory=list)        # first row is the header
    files: list[tuple[str, str]] = field(default_factory=list)       # (what, path) of the outputs that exist outside the GeoPackage
    notes: list[str] = field(default_factory=list)


def load_report(output_gpkg: str | Path) -> Optional[dict]:
    """``run_report.json`` next to the GeoPackage, or None when it is not there (yet) or cannot be read."""
    p = Path(output_gpkg).parent / "run_report.json"
    try:
        return json.loads(p.read_text(encoding="utf8"))
    except (OSError, ValueError):
        return None


def _n(x: Any, digits: int = 0) -> str:
    try:
        return f"{float(x):,.{digits}f}"
    except (TypeError, ValueError):
        return "-"


BUDGET_ITEMS = {"canal_closure_km": "Canal closure or backfill", "sekat_standard": "Sekat, wooden", "sekat_reinforced": "Sekat, concrete",
                "sekat_ipg_estimate": "Sekat, KLH IPG estimate", "revegetation_ha": "Revegetation", "deep_wells": "Deep wells (sumur bor)",
                "pump_units": "Pump units", "pump_fuel_l": "Pump fuel"}


def summarise(report: dict) -> Summary:
    """Sections for the segments, sekat, routes and pumps, a pump table, the output files and a few honest notes."""
    c = report.get("counts", {})
    out = Summary()
    seg = Section(tr("Canal segments"))
    if "6" in c:
        seg.rows += [(tr("Scored"), _n(c["6"].get("scored"))), (tr("Selected as targets"), _n(c["6"].get("selected")))]
    if "4" in c:
        seg.rows.append((tr("Too short to score"), _n(c["4"].get("short_flagged"))))
    sek = Section(tr("Sekat"))
    if "7" in c:
        sek.rows += [(tr("Existing"), _n(c["7"].get("existing"))), (tr("Proposed"), _n(c["7"].get("proposed")))]
        if c["7"].get("low_benefit") is not None:
            sek.rows.append((tr("Left out, low benefit"), _n(c["7"].get("low_benefit"))))
    bal = report.get("sekat_balance") or {}
    if bal.get("rise_m2_all"):
        sek.rows.append((tr("Share of the canal rewetting kept"), f"{_n(100 * bal['rise_m2_kept'] / bal['rise_m2_all'])} %"))
    ipg = [r for r in report.get("ipg", []) if r.get("ipg") is not None]
    if ipg:
        short = sum(1 for r in ipg if r["ipg"] < 1)
        sek.rows.append((tr("Canals with too few sekat (IPG below 1)"), f"{short} / {len(ipg)}"))
    route = Section(tr("Routes"))
    r = report.get("routing", {})
    if r:
        route.rows += [(tr("Targets"), _n(r.get("n_targets"))), (tr("Unreachable targets"), _n(r.get("n_unreachable"))),
                       (tr("Total length"), f"{_n(r.get('total_length_m'))} m"), (tr("Total lift"), f"{_n(r.get('total_lift_m'), 2)} m")]
    pumps = report.get("pumps", [])
    pump = Section(tr("Pumps"))
    if pumps:
        pump.rows += [(tr("Stations"), _n(len(pumps))), (tr("Total power"), f"{_n(sum(p.get('p_kw', 0) for p in pumps), 2)} kW"),
                      (tr("Total flow"), f"{_n(sum(p.get('q_m3s', 0) for p in pumps) * 1000, 1)} L/s")]
    if "10" in c:
        pump.rows.append((tr("Gates to add or check"), _n(c["10"].get("gates_required"))))
    iv = report.get("interventions") or {}
    inter = Section(tr("Interventions per sub-KHG"))
    if iv:
        from ..intervention_labels import LABELS
        inter.rows += [(tr(LABELS[k]), _n(n)) for k, n in iv.get("counts", {}).items() if n]
    water = Section(tr("Water and budget"))
    if iv.get("deficit_m3_selected"):
        held = iv.get("held_m3_selected") or 0
        water.rows += [(tr("Water held by the sekat"), f"{_n(held / 1e6, 2)} {tr('million m³')}"),
                       (tr("Deficit of the analysed sub-KHG"), f"{_n(iv['deficit_m3_selected'] / 1e6, 1)} {tr('million m³')}"),
                       (tr("Share of the deficit held"), f"{_n(100 * held / iv['deficit_m3_selected'], 1)} %")]
    bd = report.get("budget") or {}
    if bd.get("total_idr") is not None:
        water.rows.append((tr("Budget estimate"), f"{_n(bd['total_idr'] / 1e9, 1)} {tr('billion Rp')}"))
        water.rows.append((tr("Low to high"), f"{_n(bd['total_low_idr'] / 1e9, 1)} - {_n(bd['total_high_idr'] / 1e9, 1)}"))
    if bd.get("unpriced"):
        water.rows.append((tr("Not priced"), ", ".join(tr(BUDGET_ITEMS.get(i, i)) for i in bd["unpriced"])))
    opt = report.get("optimisation") or {}
    alt = Section(tr("Stage 11, alternative plan"))
    if opt:
        alt.rows += [(tr("Sekat chosen"), f"{_n(opt.get('blocks'))} / {_n(opt.get('candidates'))}"), (tr("Best method"), str(opt.get("best_method", "-")))]
        if opt.get("gain_vs_random"):
            alt.rows.append((tr("Better than random choice"), f"{_n(opt['gain_vs_random'], 2)} x"))
    out.sections = [s for s in (seg, sek, route, pump, inter, water, alt) if s.rows]
    if pumps:
        out.pump_table = [[tr("Station"), tr("Flow (L/s)"), tr("Head (m)"), tr("Power (kW)"), tr("Units")]] + [
            [str(p.get("station_id", "")), _n(p.get("q_m3s", 0) * 1000, 1), _n(p.get("h_m"), 2), _n(p.get("p_kw"), 2), _n(p.get("units_needed"))]
            for p in pumps]
    files = report.get("files", {})
    out.files = [(tr(label), files[key]) for key, label in (("dtm_conditioned", "Conditioned DTM"), ("flow_acc", "Flow accumulation")) if files.get(key)]
    if any(p.get("shortfall_m3s", 0) > 0 for p in pumps):
        out.notes.append(tr("Some stations cannot deliver the required flow with the installed capacity (see the run report)."))
    if r.get("n_unreachable"):
        out.notes.append(tr("Some targets cannot be reached, usually because of a sekat without a gate."))
    preset = (report.get("preset") or {}).get("keys") or []
    if preset:
        out.notes.append(tr("{n} values are proposed defaults.").format(n=len(preset)))
    if report.get("warnings"):
        out.notes.append(tr("{n} warnings are listed in the run report.").format(n=len(report["warnings"])))
    out.notes.append(tr("The plan assumes every proposed sekat is built (after the balance, when it is on). Stage 11, if used, is an alternative plan and does not change it."))
    return out
