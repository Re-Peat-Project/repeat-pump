"""Wizard view-model: pure Python, no qgis or Qt imports (tested in the engine venv).

Turns the engine's files (``run_state.json``, ``repeat-pump check`` JSON) into what the UI shows: stage
statuses, result tiles, callouts, the parameters a human must still fill, and the command each button runs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .i18n import tr

# ----------------------------------------------------------------------------- static content
# id -> (title, one-line purpose, what, why, reference)
STAGE_TEXT: dict[int, tuple[str, str, str, str, str]] = {
    1: ("Load and validate",
        "Tell the module where your data is. It checks projections, extents and the DTM type before anything is processed.",
        "Reads every layer you point to, checks projection, extent and that the elevation is a bare-earth DTM, selects the priority sub-KHGs and clips the data to them.",
        "A silent projection mismatch or a surface model (DSM) would make every later height and slope wrong.",
        "PP 57/2016 (dA); input contract in the spec, section 3"),
    2: ("Canal topology",
        "Canals are snapped, noded and de-duplicated. Nothing is deleted silently: you check the loose ends.",
        "Joins canal ends that nearly touch, splits lines at crossings and removes duplicates. Loose ends (dangles) are kept and flagged.",
        "A canal that looks connected on screen but is not would stop pumped water in the routing stage.",
        "Neteler and Mitasova (2008)"),
    3: ("Hydro-conditioning",
        "Prepares a copy of the elevation model for flow routing only, then computes flow accumulation.",
        "Removes pits by least-cost breaching, burns the canals into a separate raster, and computes flow accumulation (D-infinity by default).",
        "Water must be able to flow along canals in the model. The unmodified DTM is still used for heights and slopes.",
        "Lindsay (2016a, 2016b); Tarboton (1997); Garbrecht and Martz (1997)"),
    4: ("Segmentation",
        "Splits canals into pieces of at most the configured length, with stable IDs.",
        "Cuts each cleaned canal into segments and numbers them in a fixed order, so results are repeatable.",
        "Scoring and sekat design work per segment, so segments must be comparable in length.",
        "Spec section 5, Stage 4"),
    5: ("Land profiles",
        "Measures how the land rises along each canal, beside the canal rather than in it.",
        "Samples the DTM on both banks every few metres, takes the median and smooths it, then works out which way each canal drains.",
        "A canal bed is not the land surface. The bank profile gives the slope that sets sekat spacing.",
        "Spec section 5, Stage 5"),
    6: ("Prioritisation",
        "Scores each canal segment by need. Feasibility is kept separate from need.",
        "Transfers burn and peat attributes by length, extracts dryness from a ring around the canal, combines criteria with your weights, and tests how stable the ranking is.",
        "Pumping water everywhere is not possible. The ranking decides where rewetting is worth the effort.",
        "Malczewski (2006); Saaty (1980); Chen et al. (2010)"),
    7: ("Sekat placement",
        "Compares existing blocks with what the terrain needs and proposes new sekat by hydraulic head.",
        "Counts how many sekat each canal needs from the land rise, then places new ones so each step in water level is dA.",
        "Each sekat holds water about dA above the next pool downstream, keeping the peat wet without flooding it.",
        "PP 57/2016; Ritzema et al. (2014); Dohong et al. (2018); KHG Kahayan-Sebangau report (2021)"),
    8: ("Network graph",
        "Builds the canal network as a directed graph with heights, sekat and river intersections.",
        "Creates nodes at segment ends, sekat and river crossings, and edges that remember length and height change.",
        "Routing needs to know which way is uphill and where blocks stop the water.",
        "Spec section 5, Stage 8"),
    9: ("Sources and routes",
        "Finds water sources and routes pumped water to the highest pool of each target reach.",
        "Takes river-canal intersections as sources, then finds the cheapest tree of routes where uphill costs extra.",
        "Lift costs energy. One shared tree of routes needs fewer pumps than separate routes per target.",
        "Dijkstra (1959); Takahashi and Matsuyama (1980); Karassik et al. (2008)"),
    10: ("Pumps and sizing",
         "Works out water demand, the head along each route, where stations go and how much power they need.",
         "Converts the water deficit to a flow rate, adds friction loss to the static lift, places stations and sizes them.",
         "Shows what the pumps would have to do, and where the plan falls short.",
         "Chow (1959); Mays (2011); Karassik et al. (2008)"),
    11: ("Report",
         "Collects everything into one report, including warnings and parameters still unset.",
         "Writes run_report.md and run_report.json with counts, warnings, tables and the list of open parameters.",
         "The report is what you share and what the dashboard reads.",
         "Spec section 5, Stage 11"),
    12: ("Block optimisation",
         "Optional. Compares which of the proposed sekat to build first when you can only build some of them.",
         "Scores layouts of new sekat with a canal-level model (or a 2D groundwater model) and searches for the best layout with a genetic algorithm and simulated annealing, next to greedy, random and rule-based comparators.",
         "Money and access limit how many sekat you can build. This shows which layout of the proposed sekat gives the most benefit. It is an alternative plan: the pump stages still assume every proposed sekat is built.",
         "Urzainki et al. (2020); Holland (1975); Kirkpatrick et al. (1983)"),
}

OPTIONAL_STAGES = {8, 9, 10, 12}      # can be switched off (pumping.enabled, optimise.enabled); then shown as "Optional, switched off" and counted as done
SWITCH = {8: "pumping.enabled", 9: "pumping.enabled", 10: "pumping.enabled", 12: "optimise.enabled"}
REPORT_STAGE = 11           # the stage whose card lists every warning

# stage -> list of (counts key, label, note, warn-if-positive)
STAGE_TILES: dict[int, list[tuple[str, str, str, bool]]] = {
    1: [("subkhg_selected", "Sub-KHGs selected", "inside the analysis", False), ("canals", "Canals in scope", "after clipping", False)],
    2: [("canals_in", "Canal features in", "before cleaning", False), ("canals_clean", "Canal features out", "after snap and node", False),
        ("dangles", "Dangles found", "written to the QA layer", True), ("snapped_gaps", "Gaps snapped", "within tolerance", False),
        ("trimmed", "Overshoots trimmed", "", False), ("disconnected_components", "Disconnected parts", "of the network", True),
        ("issues", "Issues", "see the QA layers", True), ("edits_applied", "Manual edits applied", "", False)],
    3: [("canals_burned", "Canals burned in", "flow-routing raster only", False)],
    4: [("segments", "Segments", "", False), ("short_flagged", "Short pieces flagged", "kept, not scored", False)],
    5: [("stations", "Profile stations", "", False), ("ambiguous_unresolved", "Unresolved directions", "flat canals", True)],
    6: [("scored", "Segments scored", "", False), ("selected", "Selected as targets", "", False), ("infeasible", "Not feasible", "filtered after scoring", False)],
    7: [("existing", "Existing sekat", "", False), ("proposed", "Sekat proposed", "ready to review", False), ("low_benefit", "Left out, low benefit", "", False), ("unsnapped", "Unsnapped points", "listed in the log", True)],
    8: [("nodes", "Network nodes", "", False), ("edges", "Network edges", "", False)],
    9: [("sources", "Water sources", "", False), ("targets", "Targets", "", False), ("routes", "Routes", "", False),
        ("unreachable", "Unreachable targets", "see the QA layer", True), ("sekat_planned", "Sekat in the plan", "see sekat_scope", False),
        ("sekat_target", "Sekat on selected canals", "", False), ("sekat_route", "Sekat on pump routes", "gates", False)],
    10: [("stations", "Pump stations", "", False), ("gates_required", "Gates required", "", False), ("shortfalls", "Capacity shortfalls", "", True)],
    11: [("warnings", "Warnings", "", True), ("null_parameters", "Parameters still unset", "", True)],
    12: [("candidates", "Candidate sites", "proposed sekat", False), ("blocks", "Blocks to build", "", False),
         ("evaluations", "Layouts scored", "all algorithms", False), ("best_method", "Best method", "", False),
         ("gain_vs_random", "Gain over random", "times the random mean", False)],
}

# layers worth showing after a stage (all in the output GeoPackage)
STAGE_LAYERS: dict[int, list[str]] = {
    2: ["canals_clean", "qa_topology_dangles", "qa_topology_gaps"], 4: ["canal_segments"], 5: ["canal_profiles"],
    6: ["canal_segments", "qa_sensitivity"], 7: ["canals_clean", "sekat_existing_assessed", "sekat_low_benefit", "sekat_proposed"], 8: ["network_nodes", "network_edges"],
    9: ["pump_sources", "pump_targets", "pump_routes", "qa_unreachable_targets", "sekat_scope"], 10: ["pump_stations", "gates_required"],
    12: ["sekat_optimised", "qa_optimisation"],
}

# GeoTIFFs outside the GeoPackage, loaded from the run report
STAGE_RASTERS: dict[int, list[str]] = {3: ["dtm_conditioned", "flow_acc"]}

REVIEW_HINT: dict[int, str] = {
    2: "Open the dangles and gaps layers. Snaps above the tolerance need your decision. To fix canals, add a canal-edits layer in the run setup (stage 1) and re-run from stage 1, or change the snap tolerance below and re-run this stage.",
    6: "Look at the ranking on the map and the sensitivity table. If the top segments change a lot when weights move, discuss the weights.",
    9: "Check that each target is connected to a source. Unreachable targets usually mean a block without a gate.",
}


@dataclass(frozen=True)
class Field_:
    """A parameter a human may set. ``kind``: float | int | bool | text | enum | multi | floatlist | idlist | matrix.
    ``options`` are the stored codes of an enum or multi field, ``labels`` their readable names (same order, may be empty)."""
    key: str
    label: str
    kind: str
    unit: str = ""
    help: str = ""
    options: tuple = ()
    labels: tuple = ()


EMPTY_OK = {"topology.canal_classes"}      # multi fields where "nothing ticked" is a real choice (no filter) and removes the key

FIELDS: dict[str, Field_] = {f.key: f for f in [
    Field_("prioritise.weights_mode", "Weighting method", "enum", "",
           "Direct: type a weight per criterion. AHP: compare the criteria in pairs and the weights follow from the comparisons. KLH guide: the 1 to 3 class scores of the KLH technical guide, added up (to reproduce the guide, not the module's default).", ("direct", "ahp", "klh"),
           ("Direct weights", "AHP pairwise comparisons", "KLH guide scoring (1 to 3 per criterion)")),
    Field_("prioritise.klh_cpwi_breaks", "Moisture class breaks (KLH scoring)", "floatlist", "", "Two values of the moisture index, for example 0.8; 1.5: below the first is the driest class (3), up to the second 2, above 1. The guide says to fit them to the quartiles of your KHG."),
    Field_("prioritise.klh_flow_breaks", "Flow accumulation class breaks (KLH scoring)", "floatlist", "", "Two values, for example 1.5; 3.0: above the second scores 3, above the first 2, otherwise 1. Use values in the units of your flow accumulation raster."),
    Field_("prioritise.klh_min_score", "Minimum score to select (KLH scoring)", "float", "of 12", "Segments with at least this total become targets. The guide uses 10 and calls it temporary."),
    Field_("run.clip_margin_m", "Clip margin around sub-KHGs", "float", "m", "Extra distance kept around the selected sub-KHGs."),
    Field_("inputs.dtm.vertical_rmse_m", "DTM vertical accuracy (RMSE)", "float", "m", "From the LiDAR provider. Needed to judge if a dA step is larger than the DTM noise."),
    Field_("inputs.dtm.source", "What the DTM is", "enum", "", "Lets the proposed defaults suggest the DTM accuracy: LiDAR about 0.3 m, DeltaDTM 0.49 m, DEMNAS about 5 m.",
           ("lidar", "deltadtm", "demnas", "other"), ("Airborne LiDAR", "DeltaDTM", "DEMNAS", "Other")),
    Field_("inputs.moisture.higher_is_wetter", "Moisture index: higher means wetter", "bool", "", "Depends on the index used (check its definition)."),
    Field_("inputs.peat_depth.units", "Unit of the peat depth raster", "enum", "", "Check the raster's metadata: the BRGM peat depth models are in centimetres, the class-midpoint raster of the neraca module in metres.", ("m", "cm"),
           ("Metres", "Centimetres")),
    Field_("run.vertical_datum", "Vertical datum of the DTM", "text", "", "Must be the same as the river water levels. Needed if river levels are used."),
    Field_("inputs.rivers.vertical_datum", "Vertical datum of river water levels", "text", "", "Needed if the rivers layer has dry-season water levels."),
    Field_("topology.snap_tolerance_m", "Snap tolerance", "float", "m", "Canal ends closer than this are joined. Larger snaps are listed for your review."),
    Field_("hydro.breach_max_dist_cells", "Maximum breach distance", "int", "cells", "How far a pit may be breached before it is filled instead."),
    Field_("prioritise.upstream_buffer_m", "Upstream buffer", "float", "m", "Narrow buffer used to read flow accumulation along a segment."),
    Field_("prioritise.feasibility.concession_mode", "Concession handling", "enum", "", "Applied after scoring, never inside the need score.", ("exclude", "flag", "ignore"),
           ("Exclude from the selection", "Flag only", "Ignore")),
    Field_("sekat.max_spacing_m", "Maximum sekat spacing", "float", "m", "Upper bound on spacing between sekat."),
    Field_("sekat.snap_tolerance_m", "Snap tolerance for existing sekat", "float", "m", "How far an existing sekat may be from a canal and still be attached to it."),
    Field_("sekat.min_spacing_m", "Minimum sekat spacing", "float", "m", "No new sekat closer than this to an existing one."),
    Field_("pumping.uphill_penalty_lambda", "Uphill penalty (lambda)", "float", "m per m of lift", "Extra route cost per metre of lift: a proxy for pumping energy."),
    Field_("pumping.conveyance", "Conveyance", "enum", "", "Pump into the canals (open channel) or through pipes.", ("canal", "pipe"), ("Open canal", "Pipe or hose")),
    Field_("pumping.manning_n", "Manning roughness n", "float", "", "Open-channel friction loss."),
    Field_("pumping.hazen_williams_c", "Hazen-Williams C", "float", "", "Pipe friction loss."),
    Field_("pumping.pipe_diameter_m", "Pipe diameter", "float", "m", ""),
    Field_("pumping.pump_efficiency", "Pump efficiency", "float", "0-1", ""),
    Field_("pumping.max_head_per_station_m", "Maximum head per station", "float", "m", "A new station is placed when this would be exceeded."),
    Field_("pumping.pump_capacity_m3s", "Capacity per pump unit", "float", "m3/s", ""),
    Field_("pumping.influence_distance_m", "Canal influence distance", "float", "m", "How far from a canal the peat is rewetted. Calibrate with water-table observations."),
    Field_("pumping.enabled", "Plan pumps", "bool", "", "Switch off for a sekat-only plan: stages 8 to 10 are skipped. Needed when no river in the area can serve as a water source."),
    Field_("optimise.enabled", "Run the canal blocking optimisation", "bool", "", "Optional. Chooses which proposed sekat to build first when you cannot build them all. It is an alternative plan and does not change the pump stages."),
    Field_("optimise.objective", "How layouts are scored", "enum", "", "canal_rise is quick and needs few inputs. pde uses a groundwater model and needs the physical inputs below. screen_then_pde searches with canal rise and re-scores the winners with the groundwater model.", ("canal_rise", "pde", "screen_then_pde"),
           ("Canal level rise (quick)", "Groundwater model (slow)", "Quick search, then groundwater model")),
    Field_("optimise.n_blocks", "Number of new blocks", "int", "blocks", "How many of the proposed sekat you can build."),
    Field_("optimise.max_evaluations", "Search budget per algorithm", "int", "layouts", "How many different layouts each algorithm may score. More is better but slower."),
    Field_("optimise.canal_drawdown_m", "Canal water level below the land", "float", "m", "Dry-season level of the canal water below the surrounding land."),
    Field_("optimise.grid_m", "Groundwater grid cell size", "float", "m", "Cell size of the groundwater model. Smaller is more detailed and slower."),
    Field_("optimise.dry_days", "Length of the dry spell", "int", "days", "Days of drying simulated from a saturated start."),
    Field_("optimise.et_mm_day", "Net water loss without rain", "float", "mm/day", "Evapotranspiration the peat loses each dry day."),
    Field_("optimise.transmissivity_multiplier", "Peat transmissivity multiplier", "float", "", "Scales the transmissivity of the built-in peat tables. Results depend strongly on it, so set it for your site."),
    Field_("pumping.specific_yield", "Specific yield", "float", "", "Needed in specific-yield demand mode, and when there is no water deficit (neraca air)."),
    Field_("pumping.design_period_days", "Design period", "float", "days", "The days over which the water must be delivered. Needed when the priority table does not give it."),
    Field_("pumping.water_table_rise_m", "Required water-table rise", "float", "m", "Needed in specific-yield demand mode, and when there is no water deficit (neraca air)."),
    # ---- settings with a default (listed under "Advanced settings"; empty means the engine default applies)
    Field_("run.crs", "Coordinate system", "text", "", "Taken from the DTM when the run is created. Every layer must use it, or be reprojected."),
    Field_("run.auto_reproject", "Reproject layers that use another coordinate system", "bool", "", "Off: a layer in another system stops the run. On: the engine reprojects it and logs that it did."),
    Field_("run.memory_budget_gb", "Memory budget", "float", "GB", "Large rasters are read in windows so the run stays within this budget."),
    Field_("run.subkhg_selection.mode", "Which sub-KHGs to analyse", "enum", "", "Highest priority needs the priority table; without it every sub-KHG is analysed.", ("top_n", "ids", "all"),
           ("Highest-priority sub-KHGs", "Chosen sub-KHGs", "All sub-KHGs")),
    Field_("run.subkhg_selection.n", "How many sub-KHGs", "int", "", "Used by the highest-priority choice."),
    Field_("run.subkhg_selection.ids", "Chosen sub-KHG ids", "idlist", "", "Separate the ids with commas. Used by the chosen-sub-KHGs choice."),
    Field_("topology.canal_classes", "Canal classes to analyse", "multi", "", "Only these classes are analysed; leave none ticked to use every class. The KLH guide uses primary and secondary canals.", ("primer", "sekunder", "tersier"),
           ("Primary (primer)", "Secondary (sekunder)", "Tertiary (tersier)")),
    Field_("topology.river_buffer_m", "River reaches a canal within", "float", "m", "A river that stops this close to a canal still counts as meeting it, and becomes a water source. The KLH guide uses 30 m. Empty: the river must cross the canal."),
    Field_("topology.source_snap_m", "Move river points onto the kept canals within", "float", "m", "Used with the class filter: river points found on a left-out canal are moved onto the nearest kept canal within this distance, or dropped. The KLH guide uses 50 m."),
    Field_("topology.overshoot_max_m", "Trim canal overshoots up to", "float", "m", "Leave empty to keep overshoots."),
    Field_("hydro.burn_depth_default_m", "Default canal burn depth", "float", "m", "Used only where a canal has no depth of its own."),
    Field_("hydro.flow_algorithm", "Flow direction method", "enum", "", "How water is routed across the DTM.", ("dinf", "mfd", "d8"),
           ("D-infinity (default)", "Multiple flow direction", "D8 (single direction)")),
    Field_("segments.max_length_m", "Longest segment", "float", "m", "Canals are cut into pieces no longer than this."),
    Field_("segments.min_length_m", "Shortest scored segment", "float", "m", "Shorter pieces stay in the network but are not scored."),
    Field_("profiles.bank_offsets_m", "Bank sampling distances", "floatlist", "m", "Distances beyond the canal edge where land height is read, on both sides. Separate them with a semicolon, for example 6; 10."),
    Field_("profiles.sample_step_m", "Profile step", "float", "m", "Distance between height samples along a canal."),
    Field_("profiles.smoothing_window_m", "Smoothing window", "float", "m", "Median filter length along the profile."),
    Field_("prioritise.ring_buffer_m", "Moisture ring (inner, outer)", "floatlist", "m", "Two distances: the ring around a segment where dryness is read, without the canal water. For example 15; 100."),
    Field_("prioritise.top_fraction", "Share of segments selected", "float", "0-1", "The highest-scoring share of feasible segments becomes the target."),
    Field_("prioritise.upstream_method", "Upstream contribution from", "enum", "", "Flow accumulation reads the conditioned DTM; the network method adds up canal length upstream.", ("flow_acc", "graph"),
           ("Flow accumulation raster", "Canal network (upstream length)")),
    Field_("sekat.dA_m", "Head step between sekat (dA)", "float", "m", "Maximum water-table depth below the surface. PP 57/2016 uses 0.4 m."),
    Field_("sekat.min_new_spacing_m", "Minimum distance between new sekat", "float", "m", "Empty: the head rule alone decides. The KLH guide uses 500 m, which overrides the head rule on steep land and gives fewer sekat there."),
    Field_("sekat.dedup_tol_m", "Merge proposed sekat closer than", "float", "m", "A proposal this close to an existing sekat, or to one on another canal, is dropped. The KLH guide uses 50 m. Empty: keep all."),
    Field_("sekat.target_rise_share", "Balance: share of the rewetting to keep", "float", "0-1",
           "Keeps the fewest proposed sekat that give this share of the canal rewetting of all of them; the others go to the low-benefit layer. Empty: keep all."),
    Field_("sekat.max_blocks", "Budget: most new sekat", "int", "", "At most this many new sekat, those that rewet the most canal first. Empty: no cap."),
    Field_("sekat.balance_drawdown_m", "Dry-season canal level below the land", "float", "m", "Only used to rank the proposed sekat by how much canal they rewet."),
    Field_("sekat.slope_reinforced_pct", "Slope for reinforced blocks", "float", "%", "From this land slope a block is flagged leaky or reinforced instead of standard."),
    Field_("pumping.routing", "How routes are built", "enum", "", "One shared network connects all targets to the sources at the least cost; the other mode routes each target alone (the old method, for comparison).", ("steiner", "per_target"),
           ("One shared network (Steiner tree)", "Each target on its own (old method)")),
    Field_("pumping.sekat_scope", "Sekat in the plan", "enum", "", "Every sekat the head rule proposes, or only those on the selected canals plus the gates on the pump routes that feed them (cheaper; the others stay listed as 'other').", ("all", "selected"),
           ("Every proposed sekat", "Selected canals and their pump routes")),
    Field_("pumping.allow_gate_addition", "Allow adding gates to ungated sekat", "bool", "", "Off: a sekat without a gate blocks pumped water. On: the engine lists the gates that would have to be added."),
    Field_("pumping.demand_mode", "Water demand from", "enum", "", "The water-deficit table (neraca air), or specific yield and the water-table rise you give.", ("deficit", "specific_yield"),
           ("Water deficit table", "Specific yield and water-table rise")),
    Field_("pumping.max_units_per_station", "Most pump units per station", "int", "units", "Leave empty for no limit."),
    Field_("optimise.algorithms", "Search methods", "multi", "", "Each method gets the same budget of layouts.", ("ga", "sa", "greedy"),
           ("Genetic algorithm", "Simulated annealing", "Greedy")),
    Field_("optimise.seed", "Random seed", "int", "", "The same seed gives the same result."),
    Field_("optimise.random_baseline_draws", "Random layouts for comparison", "int", "", "The result is compared with the mean of this many random layouts."),
    Field_("optimise.ga.population", "Genetic algorithm: population", "int", "", "Layouts kept per generation."),
    Field_("optimise.ga.mutation", "Genetic algorithm: mutation rate", "float", "0-1", ""),
    Field_("optimise.ga.elite", "Genetic algorithm: elite layouts", "int", "", "Best layouts copied unchanged into the next generation."),
    Field_("optimise.ga.tournament", "Genetic algorithm: tournament size", "int", "", ""),
    Field_("optimise.sa.t0_fraction", "Simulated annealing: start temperature", "float", "", "As a fraction of the first layout's score."),
    Field_("optimise.sa.cooling", "Simulated annealing: cooling factor", "float", "", "Closer to 1 cools more slowly."),
]}


CRITERIA = {"burn_freq": "burn frequency", "peat_depth": "peat depth", "dryness": "dryness", "upstream_contrib": "upstream contribution"}


def field_for(key: str) -> Field_:
    """Metadata for a parameter key; criterion weights and unknown keys get sensible generic entries."""
    f = _field_en(key)
    label = tr(f.label)
    if key.startswith("prioritise.criteria.") and key.endswith(".weight"):
        name = key.split(".")[2]
        label = tr("Weight: {name}").format(name=tr(CRITERIA.get(name, name.replace("_", " "))))
    return Field_(f.key, label, f.kind, tr(f.unit) if f.unit else "", tr(f.help) if f.help else "", f.options,
                  tuple(tr(x) for x in f.labels))


def _field_en(key: str) -> Field_:
    if key in FIELDS:
        return FIELDS[key]
    if key.startswith("prioritise.criteria.") and key.endswith(".weight"):
        name = key.split(".")[2]
        return Field_(key, f"Weight: {CRITERIA.get(name, name.replace('_', ' '))}", "float", "",
                      "Relative importance of this criterion. Decided with the team; weights are normalised.")
    if key == "prioritise.ahp_matrix":
        return Field_(key, "AHP pairwise matrix", "matrix", "", "Row against column: how much more important the row criterion is (1 = equal, 9 = extremely). Fill the cells above the diagonal.")
    return Field_(key, key, "text")


# ----------------------------------------------------------------------------- model
STATUSES = ("locked", "ready", "running", "needs_review", "done", "failed", "stale", "skipped")


# ----------------------------------------------------------------------------- list-valued settings (pure Python)
def parse_floatlist(text: str, count: Optional[int] = None) -> Optional[list[float]]:
    """``"6, 10"`` or ``"6;10"`` -> [6.0, 10.0]; None when empty or not numbers, or when ``count`` is given and does not match."""
    parts = [p.strip().replace(",", ".") for p in text.replace(";", " ").replace("  ", " ").split()] if ";" in text or " " in text.strip() \
        else [p.strip().replace(",", ".") for p in text.split(",")]
    if not text.strip():
        return None
    try:
        out = [float(p) for p in parts if p]
    except ValueError:
        return None
    return out if out and (count is None or len(out) == count) else None


def format_list(values) -> str:
    """[6.0, 10.0] -> ``6, 10``."""
    return ", ".join(str(int(v)) if isinstance(v, float) and v == int(v) else str(v) for v in (values or []))


def parse_idlist(text: str) -> list:
    """``"1, 4, KHG-7"`` -> [1, 4, "KHG-7"]: whole numbers become numbers so they match numeric id columns."""
    out = []
    for p in text.replace(";", ",").split(","):
        p = p.strip()
        if p:
            out.append(int(p) if p.lstrip("-").isdigit() else p)
    return out


def option_labels(fld: "Field_") -> list[str]:
    """Readable names for an enum or multi field's codes (the code itself when there is no label)."""
    return list(fld.labels) if len(fld.labels) == len(fld.options) else list(fld.options)


# ----------------------------------------------------------------------------- AHP pairwise matrix (pure Python)
# The engine computes the weights itself (core/prioritise.py); this mirrors it only to give live feedback while typing.
AHP_RI = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}    # Saaty (1980)
AHP_MAX_CR = 0.10


def parse_ratio(text: str) -> Optional[float]:
    """Saaty-scale entry such as ``3``, ``1/3`` or ``0,5``; None when empty, not a number or outside 1/9..9."""
    t = text.strip().replace(",", ".")
    if not t:
        return None
    try:
        a, _, b = t.partition("/")
        x = float(a) / float(b) if b else float(a)
    except (ValueError, ZeroDivisionError):
        return None
    return x if 1 / 9 - 1e-9 <= x <= 9 + 1e-9 else None


def format_ratio(x: float) -> str:
    """``3``, ``1/3``: what a reciprocal cell shows."""
    if x >= 1 - 1e-9:
        return str(int(round(x))) if abs(x - round(x)) < 1e-6 else f"{x:.2f}"
    inv = 1 / x
    return f"1/{int(round(inv))}" if abs(inv - round(inv)) < 1e-6 else f"{x:.2f}"


def ahp_matrix(n: int, upper: dict[tuple[int, int], float]) -> Optional[list[list[float]]]:
    """Full reciprocal matrix from the cells above the diagonal; None until every one of them is filled."""
    if any((i, j) not in upper for i in range(n) for j in range(i + 1, n)):
        return None
    m = [[1.0] * n for _ in range(n)]
    for (i, j), x in upper.items():
        m[i][j], m[j][i] = x, 1 / x
    return m


def ahp_weights_cr(m: list[list[float]]) -> tuple[list[float], float]:
    """Normalised principal-eigenvector weights and the consistency ratio (power iteration, no numpy)."""
    n = len(m)
    w = [1.0 / n] * n
    for _ in range(500):
        v = [sum(m[i][j] * w[j] for j in range(n)) for i in range(n)]
        s = sum(v)
        nw = [x / s for x in v]
        done = max(abs(a - b) for a, b in zip(nw, w)) < 1e-12
        w = nw
        if done:
            break
    lam = sum(sum(m[i][j] * w[j] for j in range(n)) / w[i] for i in range(n)) / n
    ri = AHP_RI.get(n, 0.0)
    cr = ((lam - n) / (n - 1)) / ri if n > 2 and ri else 0.0
    return w, max(cr, 0.0)


def ahp_blocking(matrix) -> str:
    """Why stage 6 cannot run with this matrix (empty string when it can, or when there is no matrix yet)."""
    try:
        m = [[float(x) for x in row] for row in matrix]
        if not m or any(len(r) != len(m) for r in m):
            return tr("The AHP matrix is not square.")
        cr = ahp_weights_cr(m)[1]
    except (TypeError, ValueError):
        return ""
    return tr("The AHP comparisons are not consistent enough (ratio {cr}, must be 0.10 or less). Revise the matrix.").format(cr=f"{cr:.2f}") if cr > AHP_MAX_CR else ""


def layers_after(stage: int) -> list[str]:
    """Output layers that only stages after ``stage`` produce (their results disappear when ``stage`` is re-run)."""
    keep = {n for s, names in STAGE_LAYERS.items() if s <= stage for n in names}
    out: list[str] = []
    for s, names in sorted(STAGE_LAYERS.items()):
        out += [n for n in names if s > stage and n not in keep and n not in out]
    return out


@dataclass
class Tile:
    label: str
    value: str
    note: str
    warn: bool


@dataclass
class Param:
    """One decision on a stage card: its current value (None = still to be decided by a human)."""
    key: str
    value: Any
    recommended: bool = False
    from_preset: bool = False     # value comes from the proposed-defaults preset, not from a team decision
    option: bool = False          # a setting with a default (advanced), not a decision the stage waits for

    @property
    def missing(self) -> bool:
        return self.value is None


@dataclass
class StageView:
    id: int
    title: str
    purpose: str
    what: str
    why: str
    reference: str
    review: bool
    status: str
    sub: str
    missing: list[str] = field(default_factory=list)
    recommended: list[str] = field(default_factory=list)
    params: list[Param] = field(default_factory=list)
    options: list[Param] = field(default_factory=list)
    tiles: list[Tile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    stale_reason: str = ""
    optional: bool = False
    review_hint: str = ""
    layers: list[str] = field(default_factory=list)
    can_run: bool = False
    can_accept: bool = False
    can_rerun: bool = False
    blocking: str = ""


LAST_STAGE = 12


@dataclass(frozen=True)
class RunPlan:
    """Arguments for ``runner.run_cli``."""
    first: Optional[int]
    last: int
    accept: tuple = ()
    rerun: bool = False


def placeholder_check() -> dict:
    """Stage list shown before any run is set up (all locked, nothing to decide yet)."""
    return {"run_name": "", "output_gpkg": "", "stages": [
        {"id": sid, "name": "", "review": sid in (2, 6, 9), "needs": [], "missing": [], "recommended": [], "recommended_missing": []}
        for sid in STAGE_TEXT]}


def warnings_for(stage: int, warnings: list[str], n_stages: int = 11) -> list[str]:
    """Engine warnings relevant to a stage. Stage-specific ones start with ``Stage N:``; unprefixed ones come from
    input validation (stage 1); the DTM accuracy warning also matters for sekat placement (stage 7); the report shows all."""
    if stage == REPORT_STAGE:
        return list(warnings)
    out = []
    for w in warnings:
        if w.startswith("Stage "):
            if w.startswith(f"Stage {stage}:"):
                out.append(w)
        elif stage == 1 or (stage == 7 and w.startswith("ACCURACY")):
            out.append(w)
    return out


def load_state(output_gpkg: str | Path) -> dict:
    p = Path(output_gpkg).parent / "run_state.json"
    if not p.exists():
        return {"stages": {}, "warnings": [], "report": {}}
    try:
        return json.loads(p.read_text(encoding="utf8"))
    except (OSError, ValueError):
        return {"stages": {}, "warnings": [], "report": {}}


def stage_log_path(output_gpkg: str | Path, stage: int, name: str) -> Path:
    gp = Path(output_gpkg)
    return gp.parent / (gp.stem + "_work") / "logs" / f"stage_{stage:02d}_{name}.log"


def _fmt(v: Any) -> str:
    return f"{v:,}".replace(",", " ") if isinstance(v, int) else str(v)


class WizardModel:
    """State of one run. ``check`` is the ``repeat-pump check`` JSON, ``state`` is ``run_state.json``."""

    def __init__(self, check: dict, state: dict, running: Optional[int] = None, engine_ready: bool = True):
        self.check, self.state, self.running, self.engine_ready = check, state, running, engine_ready
        self.stages = self._build()

    # ---- derivation
    def _status(self, sid: int, previous_ok: bool, enabled: bool = True) -> tuple[str, str, str]:
        st = self.state.get("stages", {}).get(str(sid), {})
        raw = st.get("status")
        if raw == "running":
            if self.running == sid:
                return "running", tr("Running"), ""
            return "failed", tr("Interrupted"), tr("The last run was interrupted. Run it again.")
        if raw == "failed":
            err = st.get("error", "")
            if sid == 9 and "no usable water source" in err:
                err += "\n" + tr("For a sekat-only plan, choose No for Plan pumps on the stage 8 card, then run again.")
            return "failed", tr("Failed"), err
        if raw == "awaiting_review":
            return "needs_review", tr("Needs your review"), ""
        if raw == "done":
            return "done", tr("Done"), ""
        if sid in OPTIONAL_STAGES and not enabled and previous_ok:
            return "skipped", tr("Optional, switched off"), ""
        return ("ready", tr("Ready to run"), "") if previous_ok else ("locked", tr("Locked"), "")

    def _build(self) -> list[StageView]:
        counts = self.state.get("report", {}).get("counts", {})
        views, prev_ok, first_stale = [], True, None
        for s in self.check["stages"]:
            sid = s["id"]
            title, purpose, what, why, ref = STAGE_TEXT[sid]
            enabled = next((bool(e["value"]) for e in s.get("needs", []) if e["key"] == SWITCH.get(sid)), True)
            status, sub, err = self._status(sid, prev_ok, enabled)
            stale_reason = ""
            if status in ("done", "needs_review"):
                stored = self.state.get("stages", {}).get(str(sid), {}).get("fingerprint")
                if first_stale is not None:
                    status, sub, stale_reason = "stale", tr("Out of date"), tr("Stage {n} changed, so this stage is out of date.").format(n=first_stale)
                elif stored is not None and s.get("fingerprint") is not None and stored != s["fingerprint"]:
                    first_stale = sid
                    status, sub = "stale", tr("Out of date")
                    stale_reason = tr("A setting changed after this stage ran. Re-run it to apply the change.")
            v = StageView(sid, tr(title), tr(purpose), tr(what), tr(why), ref, s["review"], status, sub, list(s["missing"]),
                          list(s.get("recommended_missing", [])), error=err, stale_reason=stale_reason)
            preset_keys = set((self.check.get("preset") or {}).get("keys", []))
            v.params = [Param(e["key"], e["value"], from_preset=e["key"] in preset_keys) for e in s.get("needs", [])] + \
                       [Param(e["key"], e["value"], True) for e in s.get("recommended", [])]
            v.options = [Param(e["key"], e["value"], from_preset=e["key"] in preset_keys, option=True) for e in s.get("options", [])]
            keys = {p.key for p in v.params}
            if "run.vertical_datum" in keys and "inputs.rivers.vertical_datum" in keys:
                # the engine needs the two to be equal, so the person types one datum and the wizard writes both
                v.params = [p for p in v.params if p.key != "inputs.rivers.vertical_datum"]
                v.missing = [k for k in v.missing if k != "inputs.rivers.vertical_datum" or "run.vertical_datum" not in v.missing]
                if "run.vertical_datum" in v.missing and "inputs.rivers.vertical_datum" in v.missing:
                    v.missing.remove("inputs.rivers.vertical_datum")
            if status == "locked" and s["review"]:
                v.sub = tr("Locked, review stage")
            tcfg = STAGE_TILES.get(sid, [])
            c = counts.get(str(sid), {})
            if status in ("done", "needs_review", "stale"):
                v.tiles = [Tile(tr(label), _fmt(c[k]), tr(note) if note else "", bool(warn and c[k]))
                           for k, label, note, warn in tcfg if k in c]
            if status in ("done", "needs_review", "failed", "stale"):
                v.warnings = warnings_for(sid, self.warnings, len(self.check["stages"]))
            v.review_hint = tr(REVIEW_HINT.get(sid, "")) if status == "needs_review" else ""
            v.layers = STAGE_LAYERS.get(sid, [])
            busy = self.running is not None
            if not self.engine_ready:
                v.blocking = tr("The engine environment is not set up yet.")
            elif status == "stale" and sid != first_stale:
                v.blocking = tr("Re-run stage {n} first.").format(n=first_stale)
            elif sid == 6 and (ahp := next((p.value for p in v.params if p.key == "prioritise.ahp_matrix" and p.value is not None), None))                     and ahp_blocking(ahp):
                v.blocking = ahp_blocking(ahp)
            elif v.missing and status in ("ready", "failed", "done", "needs_review", "stale"):
                v.blocking = tr("1 required value is empty") if len(v.missing) == 1 else tr("{n} required values are empty").format(n=len(v.missing))
            v.can_run = status in ("ready",) and not v.blocking and not busy
            v.can_accept = status == "needs_review" and not busy       # never for a stale stage: its results are out of date
            v.can_rerun = status in ("done", "failed", "needs_review", "stale") and not v.blocking and not busy
            v.optional = sid in OPTIONAL_STAGES
            views.append(v)
            prev_ok = status in ("done", "skipped")
        return views

    # ---- queries
    def stage(self, sid: int) -> StageView:
        return next(v for v in self.stages if v.id == sid)

    @property
    def current(self) -> int:
        """Stage to show first: the review stage waiting for you, else the first stage not done."""
        for v in self.stages:
            if v.status in ("needs_review", "failed", "running"):
                return v.id
        for v in self.stages:
            if v.status not in ("done", "skipped"):
                return v.id
        return self.stages[-1].id

    @property
    def preset_path(self) -> str:
        """Proposed-defaults file the run opted into, or an empty string."""
        return (self.check.get("preset") or {}).get("path") or ""

    @property
    def warnings(self) -> list[str]:
        return list(self.state.get("warnings", []))

    @property
    def all_missing(self) -> list[str]:
        out: list[str] = []
        for v in self.stages:
            out += [k for k in v.missing if k not in out]
        return out

    # ---- what each button runs
    @staticmethod
    def plan(action: str, sid: int) -> RunPlan:
        """``run``: run stage ``sid`` (earlier done stages are skipped). ``accept``: accept a review stage.
        ``rerun``: run ``sid`` again, which also invalidates every later stage."""
        if action == "run":
            return RunPlan(None, sid)
        if action == "accept":
            return RunPlan(None, sid, (sid,))
        if action == "rerun":
            return RunPlan(sid, sid, (), True)
        if action == "run_on":                       # on until the engine stops at the next review stage (or the end)
            return RunPlan(None, LAST_STAGE)
        if action == "accept_on":
            return RunPlan(None, LAST_STAGE, (sid,))
        raise ValueError(action)
