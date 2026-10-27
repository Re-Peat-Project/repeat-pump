#!/usr/bin/env python3
"""Write docs/figures/pump_method.drawio, the method diagram of docs/pump-method.md (plain mxGraph XML; open in draw.io).

  python docs/figures/make_pump_method.py

Edit the boxes here and rerun, or edit the .drawio in draw.io (then this script no longer matches it).
"""
from pathlib import Path
from xml.sax.saxutils import escape

cells, n = [], [1]


def _id():
    n[0] += 1
    return f"c{n[0]}"


def box(x, y, w, h, text, style):
    i = _id()
    cells.append(f'<mxCell id="{i}" value="{escape(text, {chr(34): "&quot;"})}" style="{style}" vertex="1" parent="1">'
                 f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    return i


def edge(a, b, label="", dashed=False, side=False):
    st = "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;endFill=1;strokeColor=#5f6b7a;fontSize=10;" + ("dashed=1;" if dashed else "")
    if side:                                       # leave on the right, enter on the left: keeps the line in the gap between columns
        st += "exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;"
    cells.append(f'<mxCell id="{_id()}" value="{escape(label)}" style="{st}" edge="1" parent="1" source="{a}" target="{b}"><mxGeometry relative="1" as="geometry"/></mxCell>')


B = "rounded=1;whiteSpace=wrap;html=1;align=left;verticalAlign=top;spacingLeft=6;spacingTop=2;fontSize=11;"
INP, PRO = B + "fillColor=#eef3fb;strokeColor=#5b7db8;", B + "fillColor=#fff4e0;strokeColor=#c98a1b;"
PAR, OUT = B + "fillColor=#f3f3f3;strokeColor=#888888;dashed=1;", B + "fillColor=#e8f5ea;strokeColor=#3f8f50;"
REV, OPT = B + "fillColor=#fdecea;strokeColor=#c0392b;", B + "fillColor=#f7f7f7;strokeColor=#aaaaaa;fontColor=#666666;dashed=1;"
USE = B + "fillColor=#f5ecf7;strokeColor=#8a5a9c;"
HDR = "text;html=1;fontSize=14;fontStyle=1;align=left;verticalAlign=middle;"
BAND = "rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#cccccc;dashed=1;align=left;verticalAlign=top;spacingLeft=8;fontSize=13;fontStyle=1;fontColor=#444444;"

box(20, 10, 1500, 30, "Rewetting interventions, RE-PEAT: repeat-pump method (2026-10-27)", "text;html=1;fontSize=18;fontStyle=1;align=left;")
box(20, 42, 1500, 40, "<b>Any KHG from its code:</b> scripts/khg_run_config.py &lt;KHG folder&gt; | --all &lt;_khg&gt; writes _khg/&lt;code&gt;_&lt;name&gt;/05_pump/run_config.yaml from the KHG folder; "
    "repeat-pump run --config … (CLI) or the QGIS wizard (same engine). Stages 1-12 below; review stops after 2, 6 and 9. Proposed defaults come from configs/proposed_defaults.yaml and are marked as such.", PRO)
for x, t in [(30, "INPUTS"), (420, "STAGES (repeat_pump/core)"), (900, "OUTPUTS  (_khg/&lt;khg&gt;/05_pump/)")]:
    box(x, 88, 340, 24, t, HDR)
box(1260, 88, 250, 24, "READ BY", HDR)

# A. canal network and terrain
box(15, 115, 1510, 330, "A. Canal network and terrain (stages 1-5)", BAND)
dtm = box(30, 145, 340, 62, "<b>DTM</b> 01_dem (LiDAR first; DeltaDTM, DEMNAS)<br>inputs.dtm.source sets the suggested vertical error (lidar 0.3 m, deltadtm 0.49, demnas 4.97)", INP)
can = box(30, 215, 340, 52, "<b>Canals</b> 00_inputs/canals.gpkg (KODE_KANAL 1 primer, 2 sekunder, 3 tersier)<br>existing sekat 00_inputs/blocks.gpkg, rivers", INP)
sub = box(30, 275, 340, 52, "<b>Sub-KHG units and ranking</b> 02_delineation, 04_prioritisation (subkhg_priority.csv, unit_prioritas.gpkg)", INP)
oth = box(30, 335, 340, 52, "<b>Moisture</b> (latest NDMI), <b>burn area</b>, <b>peat depth</b> (optional: a criterion without its layer gets weight 0)", INP)
s1 = box(420, 145, 400, 52, "<b>1. Load and validate</b>: clip to the selected sub-KHG (top n by rank), CRS, DTM type (DSM refused), accuracy warning", PRO)
s2 = box(420, 205, 400, 52, "<b>2. Topology</b>: class filter (primer, sekunder; tersier optional), snap gaps, dangles, canal edits", REV)
s3 = box(420, 265, 400, 42, "<b>3. Hydro</b>: burn canals into the DTM, fill, flow accumulation (WhiteboxTools)", PRO)
s4 = box(420, 315, 400, 52, "<b>4-5. Segments and profiles</b>: 500 m segments; land profile every sample step; flow direction from slope, rivers, else flow accumulation", PRO)
o1 = box(900, 175, 330, 62, "<b>&lt;name&gt;.gpkg</b>: inputs_clipped_*, canals_clean, qa_topology_dangles, qa_topology_gaps, canal_segments, canal_profiles", OUT)
o1b = box(900, 245, 330, 42, "<b>&lt;name&gt;_work/</b> dtm_conditioned.tif, flow_acc.tif", OUT)
for a in (dtm, can, sub, oth):
    edge(a, s1, side=True)
edge(s1, s2); edge(s2, s3); edge(s3, s4); edge(s2, o1); edge(s3, o1b)

box(1260, 145, 250, 26, "Key", HDR)
for i, (t, st) in enumerate([("input", INP), ("stage", PRO), ("stage with a review stop", REV), ("optional stage", OPT), ("parameters", PAR), ("output", OUT)]):
    box(1260, 175 + 32 * i, 250, 26, t, st)

# B. sekat
box(15, 460, 1510, 300, "B. Where the sekat go (stages 6-7)", BAND)
s6 = box(420, 490, 400, 62, "<b>6. Prioritise</b>: need score per segment (dryness in a ring buffer, upstream flow, burn, peat depth), min-max, direct or AHP weights, sensitivity; or the KLH 1-3 scoring", REV)
s7 = box(420, 562, 400, 90, "<b>7. Sekat</b>: head rule, a block where the land rises dA = 0.40 m (PP 57/2016), spacing js = dA / slope, at most 500 m; existing sekat snapped; type reinforced from 5 % slope", PRO)
bal = box(420, 662, 400, 88, "<b>Balance</b> (canal-rise objective, Urzainki 2020): rank blocks by the extra canal water each adds, from a dry level 1.0 m below the land, capped at the surface; keep the fewest giving <b>90 %</b> (target_rise_share) or max_blocks", PRO)
p7 = box(30, 600, 340, 70, "<b>Parameters</b>: dA 0.40 m · max spacing 500 m · min spacing 100 m · target share 0.9 (POLICY) · balance drawdown 1.0 m · reinforced from 5 %", PAR)
o2 = box(900, 490, 330, 42, "canal_segments (need_score, rank), qa_sensitivity", OUT)
o3 = box(900, 562, 330, 100, "<b>sekat_proposed</b> (kept; benefit_rank, gain_m2, cum_share, js_m, sekat_type) · <b>sekat_low_benefit</b> · sekat_existing_assessed · <b>sekat_reach</b>: canal stretch each kept block holds, drawn upstream (rise_m, depth_m, burnt_frac)", OUT)
edge(s4, s6); edge(s6, s7); edge(s7, bal); edge(p7, s7, dashed=True); edge(s6, o2); edge(bal, o3)

# C. pumping, optional
box(15, 775, 1510, 150, "C. Pumping (stages 8-10, pumping.enabled; off when no river has a perennial flag or dry-season level)", BAND)
s8 = box(420, 805, 400, 110, "<b>8. Network</b> of canals, rivers and sekat · <b>9. Routing</b>: head-aware least cost from river intakes to the highest node of each target cluster (Steiner or per target), gates where routes cross sekat · <b>10. Pumps</b>: demand from deficit and specific yield, units per station", OPT)
o4 = box(900, 805, 330, 90, "network_nodes, network_edges, pump_sources, pump_targets, <b>pump_routes</b> (drawn intake to target), sekat_scope, pump_stations, gates_required", OUT)
edge(bal, s8, dashed=True); edge(s8, o4)

# D. interventions, budget, report
box(15, 1060, 1510, 330, "E. Interventions, budget and report (stage 12, always last)", BAND)
ind = box(30, 1090, 340, 62, "<b>Sub-KHG indicators</b> unit_prioritas.gpkg: i_protected, u_ndmi, burned_ever_frac, f_reach, f_water_dist, canal density", INP)
ner = box(30, 1160, 340, 62, "<b>Neraca air</b> 03_neraca/runs/balance/neraca_map.gpkg (repeat-neraca-map): KHG deficit, monthly balance, SiTMAT stations", INP)
prc = box(30, 1230, 340, 62, "<b>Unit prices</b> budget.* [low, central, high] Rp, sources in repeat_pump/data/budget_sources.csv (to verify)", INP)
s11 = box(420, 1090, 400, 132, "<b>12a. Interventions</b> per sub-KHG (held water from stage 7), first rule that holds: protected peat ≥ 0.5 → close or backfill canals · dry (NDMI &lt; 0.3) or burnt (≥ 0.25) and canal reach &lt; 0.4 → revegetation and fire readiness · sekat fall short (held &lt; 0.5 of deficit) with water ≤ 5 km → sekat and water supply · else, dry or burnt → sekat and deep wells · reach ≥ 0.4 → sekat · else maintain. Held = rise × Sy 0.15 × 600 m", PRO)
s11b = box(420, 1230, 400, 70, "<b>12b. Budget</b>: kept sekat by type (or the KLH IPG estimate where none were placed), km of canal to close, ha to revegetate, wells (burnt ha / π 200²), pumps and fuel × prices", PRO)
s11c = box(420, 1310, 400, 62, "<b>12c. Report</b>: run_report.md/json; repeat-pump report-html (map with animation, charts, tables); KLH print layouts A0-A4", PRO)
o5 = box(900, 1090, 330, 62, "<b>interventions</b> layer, interventions.csv (class, reasons, class without the protected rule, held_m3, deficit_m3)", OUT)
o6 = box(900, 1160, 330, 62, "<b>budget</b> layer, budget.csv, <b>budget_sources.csv</b> (register with status and run value)", OUT)
o7 = box(900, 1230, 330, 90, "<b>run_report.md</b>, run_report.json, <b>report.html</b> (one file, EN/ID, light/dark), layout PNG/PDF and .qpt templates", OUT)
u1 = box(1260, 1160, 250, 90, "<b>KLH</b>: plan, budget request, field check of sekat sites and prices", USE)
edge(ind, s11, side=True); edge(ner, s11, side=True); edge(s11, s11b); edge(prc, s11b, side=True); edge(s11b, s11c)
edge(s11, o5, side=True); edge(s11b, o6, side=True); edge(s11c, o7, side=True); edge(o6, u1, side=True); edge(o7, u1, side=True)

# E. optional optimisation
box(15, 940, 1510, 105, "D. Optional (stage 11, optimise.enabled)", BAND)
s12 = box(420, 970, 400, 65, "<b>11. Optimise</b>: choose n of the kept sekat by GA, SA or greedy; canal rise or 2D groundwater (Boussinesq) with peat_table urzainki2020, tropical-small or tropical-large; bracket_tables re-score as a range", OPT)
o8 = box(900, 970, 330, 55, "sekat_optimised, qa_optimisation (benefit per method, vs random, per peat table)", OUT)
edge(s12, o8)

xml = ('<mxfile host="repeat-pump"><diagram id="pump" name="repeat-pump method"><mxGraphModel dx="1600" dy="1420" grid="1" gridSize="10" guides="1" '
       'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1560" pageHeight="1420" background="#ffffff" math="0" shadow="0">'
       '<root><mxCell id="0"/><mxCell id="1" parent="0"/>' + "".join(cells) + "</root></mxGraphModel></diagram></mxfile>\n")
out = Path(__file__).with_name("pump_method.drawio")
out.write_text(xml, encoding="utf-8")
print(f"wrote {out} ({len(cells)} cells)")
