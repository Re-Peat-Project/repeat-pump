"""Why did this canal segment get its score? Plain-language breakdown of one row of ``canal_segments`` (stage 6).

Pure Python (no QGIS): ``explain`` takes the segment's attributes, the weights recorded when stage 6 ran (``run_state.json``,
not the config: a weight changed since would be applied to old normalised values) and a few totals over all segments, and
returns what to show. ``to_html`` renders it. The map tool that supplies the click is ``explain_tool``.

Two methods are explained: the default weighted sum of min-max normalised criteria (weight x score, which adds up to
``need_score``) and the opt-in KLH scoring (a class 1 to 3 per criterion, which adds up to ``klh_score`` of 12).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from html import escape
from typing import Any, Optional

from .i18n import tr

CRITERIA = {"burn_freq": "Burn frequency", "peat_depth": "Peat depth", "dryness": "Dryness", "upstream_contrib": "Upstream contribution"}
KLH_FIELDS = {"burn_freq": "klh_burn", "peat_depth": "klh_peat", "dryness": "klh_dryness", "upstream_contrib": "klh_flow"}


@dataclass
class Row:
    criterion: str          # readable name
    value: str              # what the data says for this segment
    score: Optional[float]  # 0-1 (weighted) or the class 1-3 (KLH)
    weight: Optional[float] = None
    adds: Optional[float] = None


@dataclass
class Explanation:
    seg_id: str
    method: str = "weighted"                  # weighted | klh | none
    scored: bool = True
    headline: str = ""                        # one sentence: the answer
    rows: list[Row] = field(default_factory=list)
    total_text: str = ""
    notes: list[str] = field(default_factory=list)
    stale: bool = False


def _num(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _pct(x: Any) -> str:
    v = _num(x)
    return "" if v is None else f"{v:.0%}"


def describe(key: str, a: dict, upstream_method: str = "flow_acc") -> str:
    """The segment's own value for a criterion, in words."""
    if key == "burn_freq":
        n = _num(a.get("burn_freq_n"))
        if n is None:
            return tr("no burn data")
        share = _pct(a.get("burn_share_dom"))
        return tr("{n} burn year(s)").format(n=int(n)) + (tr(", over {share} of the segment").format(share=share) if share and n else "")
    if key == "peat_depth":
        cls = a.get("peat_class")
        if cls in (None, "") or (isinstance(cls, float) and math.isnan(cls)):
            return tr("no peat-depth polygon")
        share = _pct(a.get("peat_share_dom"))
        return f"{cls}" + (tr(", over {share} of the segment").format(share=share) if share else "")
    if key == "dryness":
        m = _num(a.get("moisture_ring_mean"))
        return tr("moisture index {v}").format(v=f"{m:.2f}") if m is not None else tr("no moisture data")
    if upstream_method == "graph":
        v = _num(a.get("upstream_contrib_raw"))
        return tr("{v} m of canal upstream").format(v=f"{v:,.0f}") if v is not None else tr("no data")
    v = _num(a.get("flow_acc_max"))
    return tr("largest flow accumulation {v}").format(v=f"{v:,.1f}") if v is not None else tr("no flow data")


def explain(attrs: dict, report: dict, stats: Optional[dict] = None, stale: bool = False) -> Explanation:
    """``attrs``: the segment's fields. ``report``: ``run_state.json``'s ``report`` (weights, scoring). ``stats``: totals over all
    segments: ``n_scored``, ``n_selected``, ``lowest_selected`` (the lowest ``need_score`` that was selected), ``top_fraction`` (optional)."""
    stats = stats or {}
    seg = str(attrs.get("seg_id", ""))
    ex = Explanation(seg_id=seg, stale=stale)
    method = (report.get("scoring") or {}).get("method", "weighted")
    upstream = report.get("upstream_method", "flow_acc")

    # ---- not scored at all
    status = attrs.get("status_mcda")
    if status is not None and int(status) == 0:
        ex.scored, ex.method = False, "none"
        ex.headline = tr("This segment is too short to be scored (a sliver left over when canals were cut). It stays in the network, so water can still pass it, but it is never selected.")
        return ex
    sub = attrs.get("subkhg_id")
    if sub is None or (isinstance(sub, float) and math.isnan(sub)) or sub == "":
        ex.scored, ex.method = False, "none"
        ex.headline = tr("This segment lies outside the selected sub-KHGs (it is in the margin around them), so it is not scored.")
        return ex

    score = _num(attrs.get("need_score"))
    ex.method = method
    # ---- the criteria
    if method == "klh":
        sc = report.get("scoring") or {}
        for key, name in CRITERIA.items():
            cls = _num(attrs.get(KLH_FIELDS[key]))
            ex.rows.append(Row(tr(name), describe(key, attrs, upstream), cls))
        total = _num(attrs.get("klh_score"))
        top = sc.get("max_score", 12)
        ex.total_text = tr("Total {total} of {top}").format(total=int(total) if total is not None else "n/a", top=top)
        ms = sc.get("min_score")
        sel = bool(attrs.get("selected"))
        if total is not None and ms is not None:
            ex.headline = (tr("Selected: the total of {total} reaches the minimum of {ms}.") if sel else
                           tr("Not selected: the total of {total} is below the minimum of {ms}, or the segment was left out for another reason (see below).")).format(
                total=int(total), ms=f"{float(ms):g}")
    else:
        weights = report.get("weights") or {}
        total = 0.0
        for key, name in CRITERIA.items():
            n = _num(attrs.get(f"{key}_norm"))
            w = _num(weights.get(key))
            adds = (w * n) if (w is not None and n is not None) else None
            total += adds or 0.0
            ex.rows.append(Row(tr(name), describe(key, attrs, upstream), n, w, adds))
        ex.total_text = tr("Need score {score} (the sum of the last column)").format(score=f"{score:.3f}" if score is not None else f"{total:.3f}")
        rank = attrs.get("need_rank")
        n_scored = stats.get("n_scored")
        sel = bool(attrs.get("selected"))
        where = tr("rank {rank} of {n}").format(rank=int(rank), n=n_scored) if rank is not None and n_scored else ""
        low = stats.get("lowest_selected")
        if sel:
            ex.headline = tr("Selected as a target ({where}).").format(where=where) if where else tr("Selected as a target.")
        elif low is not None and score is not None:
            ex.headline = tr("Not selected ({where}): the lowest selected score is {low}, this one is {score}.").format(
                where=where, low=f"{low:.3f}", score=f"{score:.3f}")
        else:
            ex.headline = tr("Not selected ({where}).").format(where=where) if where else tr("Not selected.")
        if score is not None and abs(total - score) > 1e-6 and all(r.adds is not None for r in ex.rows):
            ex.notes.append(tr("The rows add up to {total}, not the stored score {score}: the weights in the run report may differ from the ones used. Re-run stage 6.").format(
                total=f"{total:.3f}", score=f"{score:.3f}"))

    # ---- feasibility (after scoring, never part of the score)
    share = _num(attrs.get("concession_share"))
    if attrs.get("feasible") is False or attrs.get("feasible") == 0:
        ex.notes.append(tr("Left out of the selection because {share} of it lies inside a concession (concession handling is set to exclude).").format(share=_pct(share) or "most"))
    elif attrs.get("concession_flag"):
        ex.notes.append(tr("Flagged: {share} of it lies inside a concession. This does not change the score or the selection.").format(share=_pct(share) or "most"))
    if stale:
        ex.notes.append(tr("Stage 6 is out of date (a setting changed since it ran). This explains the results as they were."))
    return ex


def to_html(ex: Explanation) -> str:
    """Rich text for a QLabel (inline styles only)."""
    out = [f"<h3 style='margin:0 0 6px 0'>{escape(tr('Segment {id}').format(id=ex.seg_id))}</h3>", f"<p>{escape(ex.headline)}</p>"]
    if ex.rows:
        klh = ex.method == "klh"
        head = ([tr("Criterion"), tr("Your data"), tr("Class (1 to 3)")] if klh else
                [tr("Criterion"), tr("Your data"), tr("Score 0-1"), tr("Weight"), tr("Adds")])
        out.append("<table cellspacing='0' cellpadding='4'><tr>" + "".join(f"<th align='left'>{escape(h)}</th>" for h in head) + "</tr>")
        for r in ex.rows:
            cells = [r.criterion, r.value, "" if r.score is None else (f"{int(r.score)}" if klh else f"{r.score:.2f}")]
            if not klh:
                cells += ["" if r.weight is None else f"{r.weight:.2f}", "" if r.adds is None else f"{r.adds:.3f}"]
            out.append("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in cells) + "</tr>")
        out.append("</table>")
        out.append(f"<p><b>{escape(ex.total_text)}</b></p>")
    for n in ex.notes:
        out.append(f"<p>{escape(n)}</p>")
    return "".join(out)


def stats_from_rows(rows: list[dict]) -> dict:
    """Totals over every segment's attributes, for ``explain``."""
    scored = [r for r in rows if _num(r.get("need_score")) is not None]
    chosen = [_num(r.get("need_score")) for r in scored if r.get("selected")]
    return {"n_scored": len(scored), "n_selected": len(chosen), "lowest_selected": min(chosen) if chosen else None}
