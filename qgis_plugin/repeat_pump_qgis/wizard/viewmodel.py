"""Wizard view-model: pure Python, no qgis or Qt imports (tested in the engine venv).

Turns the engine's files (``run_state.json``, ``repeat-pump check`` JSON) into what the UI shows: stage
statuses, result tiles, callouts, the parameters a human must still fill, and the command each button runs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

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
        "Removes pits by least-cost breaching, burns the canals into a separate raster, and computes D-infinity flow accumulation.",
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
}

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
    7: [("existing", "Existing sekat", "", False), ("proposed", "Sekat proposed", "ready to review", False), ("unsnapped", "Unsnapped points", "listed in the log", True)],
    8: [("nodes", "Network nodes", "", False), ("edges", "Network edges", "", False)],
    9: [("sources", "Water sources", "", False), ("targets", "Targets", "", False), ("routes", "Routes", "", False),
        ("unreachable", "Unreachable targets", "see the QA layer", True)],
    10: [("stations", "Pump stations", "", False), ("gates_required", "Gates required", "", False), ("shortfalls", "Capacity shortfalls", "", True)],
    11: [("warnings", "Warnings", "", True), ("null_parameters", "Parameters still unset", "", True)],
}

# layers worth showing after a stage (all in the output GeoPackage)
STAGE_LAYERS: dict[int, list[str]] = {
    2: ["canals_clean", "qa_topology_dangles", "qa_topology_gaps"], 4: ["canal_segments"], 5: ["canal_profiles"],
    6: ["canal_segments", "qa_sensitivity"], 7: ["sekat_existing_assessed", "sekat_proposed"], 8: ["network_nodes", "network_edges"],
    9: ["pump_sources", "pump_targets", "pump_routes", "qa_unreachable_targets"], 10: ["pump_stations", "gates_required"],
}

REVIEW_HINT: dict[int, str] = {
    2: "Open the dangles and gaps layers. Snaps above the tolerance need your decision. Fix canals with a canal-edits layer, then re-run.",
    6: "Look at the ranking on the map and the sensitivity table. If the top segments change a lot when weights move, discuss the weights.",
    9: "Check that each target is connected to a source. Unreachable targets usually mean a block without a gate.",
}


@dataclass(frozen=True)
class Field_:
    """A parameter a human must decide. ``kind``: float | int | bool | text | enum."""
    key: str
    label: str
    kind: str
    unit: str = ""
    help: str = ""
    options: tuple = ()


FIELDS: dict[str, Field_] = {f.key: f for f in [
    Field_("run.clip_margin_m", "Clip margin around sub-KHGs", "float", "m", "Extra distance kept around the selected sub-KHGs."),
    Field_("inputs.dtm.vertical_rmse_m", "DTM vertical accuracy (RMSE)", "float", "m", "From the LiDAR provider. Needed to judge if a dA step is larger than the DTM noise."),
    Field_("inputs.moisture.higher_is_wetter", "Moisture index: higher means wetter", "bool", "", "Depends on the index used (check its definition)."),
    Field_("run.vertical_datum", "Vertical datum of the DTM", "text", "", "Must be the same as the river water levels. Needed if river levels are used."),
    Field_("inputs.rivers.vertical_datum", "Vertical datum of river water levels", "text", "", "Needed if the rivers layer has dry-season water levels."),
    Field_("topology.snap_tolerance_m", "Snap tolerance", "float", "m", "Canal ends closer than this are joined. Larger snaps are listed for your review."),
    Field_("hydro.breach_max_dist_cells", "Maximum breach distance", "int", "cells", "How far a pit may be breached before it is filled instead."),
    Field_("prioritise.upstream_buffer_m", "Upstream buffer", "float", "m", "Narrow buffer used to read flow accumulation along a segment."),
    Field_("prioritise.feasibility.concession_mode", "Concession handling", "enum", "", "Applied after scoring, never inside the need score.", ("exclude", "flag", "ignore")),
    Field_("sekat.max_spacing_m", "Maximum sekat spacing", "float", "m", "Upper bound on spacing between sekat."),
    Field_("sekat.snap_tolerance_m", "Snap tolerance for existing sekat", "float", "m", "How far an existing sekat may be from a canal and still be attached to it."),
    Field_("sekat.min_spacing_m", "Minimum sekat spacing", "float", "m", "No new sekat closer than this to an existing one."),
    Field_("pumping.uphill_penalty_lambda", "Uphill penalty (lambda)", "float", "m per m of lift", "Extra route cost per metre of lift: a proxy for pumping energy."),
    Field_("pumping.conveyance", "Conveyance", "enum", "", "Pump into the canals (open channel) or through pipes.", ("canal", "pipe")),
    Field_("pumping.manning_n", "Manning roughness n", "float", "", "Open-channel friction loss."),
    Field_("pumping.hazen_williams_c", "Hazen-Williams C", "float", "", "Pipe friction loss."),
    Field_("pumping.pipe_diameter_m", "Pipe diameter", "float", "m", ""),
    Field_("pumping.pump_efficiency", "Pump efficiency", "float", "0-1", ""),
    Field_("pumping.max_head_per_station_m", "Maximum head per station", "float", "m", "A new station is placed when this would be exceeded."),
    Field_("pumping.pump_capacity_m3s", "Capacity per pump unit", "float", "m3/s", ""),
    Field_("pumping.influence_distance_m", "Canal influence distance", "float", "m", "How far from a canal the peat is rewetted. Calibrate with water-table observations."),
    Field_("pumping.specific_yield", "Specific yield", "float", "", "Needed in specific-yield demand mode."),
    Field_("pumping.water_table_rise_m", "Required water-table rise", "float", "m", "Needed in specific-yield demand mode."),
]}


def field_for(key: str) -> Field_:
    """Metadata for a parameter key; criterion weights and unknown keys get sensible generic entries."""
    if key in FIELDS:
        return FIELDS[key]
    if key.startswith("prioritise.criteria.") and key.endswith(".weight"):
        name = key.split(".")[2]
        return Field_(key, f"Weight: {name.replace('_', ' ')}", "float", "", "Relative importance of this criterion. Decided with the team; weights are normalised.")
    if key == "prioritise.ahp_matrix":
        return Field_(key, "AHP pairwise matrix", "matrix", "", "Edit this in the YAML file (a matrix cannot be typed here).")
    return Field_(key, key, "text")


# ----------------------------------------------------------------------------- model
STATUSES = ("locked", "ready", "running", "needs_review", "done", "failed")


@dataclass
class Tile:
    label: str
    value: str
    note: str
    warn: bool


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
    tiles: list[Tile] = field(default_factory=list)
    error: str = ""
    review_hint: str = ""
    layers: list[str] = field(default_factory=list)
    can_run: bool = False
    can_accept: bool = False
    can_rerun: bool = False
    blocking: str = ""


@dataclass(frozen=True)
class RunPlan:
    """Arguments for ``runner.run_cli``."""
    first: Optional[int]
    last: int
    accept: tuple = ()
    rerun: bool = False


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
    def _status(self, sid: int, previous_ok: bool) -> tuple[str, str, str]:
        st = self.state.get("stages", {}).get(str(sid), {})
        raw = st.get("status")
        if raw == "running":
            if self.running == sid:
                return "running", "Running", ""
            return "failed", "Interrupted", "The last run was interrupted. Run it again."
        if raw == "failed":
            return "failed", "Failed", st.get("error", "")
        if raw == "awaiting_review":
            return "needs_review", "Needs your review", ""
        if raw == "done":
            return "done", "Done", ""
        return ("ready", "Ready to run", "") if previous_ok else ("locked", "Locked", "")

    def _build(self) -> list[StageView]:
        counts = self.state.get("report", {}).get("counts", {})
        views, prev_ok = [], True
        for s in self.check["stages"]:
            sid = s["id"]
            title, purpose, what, why, ref = STAGE_TEXT[sid]
            status, sub, err = self._status(sid, prev_ok)
            v = StageView(sid, title, purpose, what, why, ref, s["review"], status, sub, list(s["missing"]),
                          list(s.get("recommended_missing", [])), error=err)
            if status == "locked" and s["review"]:
                v.sub = "Locked, review stage"
            tcfg = STAGE_TILES.get(sid, [])
            c = counts.get(str(sid), {})
            if status in ("done", "needs_review"):
                v.tiles = [Tile(label, _fmt(c[k]), note, bool(warn and c[k]))
                           for k, label, note, warn in tcfg if k in c]
            v.review_hint = REVIEW_HINT.get(sid, "") if status == "needs_review" else ""
            v.layers = STAGE_LAYERS.get(sid, [])
            busy = self.running is not None
            if not self.engine_ready:
                v.blocking = "The engine environment is not set up yet."
            elif v.missing and status in ("ready", "failed", "done", "needs_review"):
                v.blocking = f"{len(v.missing)} required value{'s are' if len(v.missing) != 1 else ' is'} empty"
            v.can_run = status in ("ready",) and not v.blocking and not busy
            v.can_accept = status == "needs_review" and not busy
            v.can_rerun = status in ("done", "failed", "needs_review") and not v.blocking and not busy
            views.append(v)
            prev_ok = status == "done"
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
            if v.status != "done":
                return v.id
        return self.stages[-1].id

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
        raise ValueError(action)
