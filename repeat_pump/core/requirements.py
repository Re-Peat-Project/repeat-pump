"""Which TODO(human) parameters each stage needs, without running it (for ``repeat-pump check``).

Mirrors the ``require(...)`` calls inside the stages (the stages stay the authority). Only config-decidable
requirements are listed. Data-dependent ones (e.g. vertical datums, needed only when ``rivers.dry_season_wl_m``
exists) are reported as ``recommended``.
"""
from __future__ import annotations

from typing import Any, Optional

from .config import Config


def get_value(cfg: Config, key: str) -> Any:
    """Value of a dotted config key such as ``prioritise.criteria.burn_freq.weight``."""
    node: Any = cfg
    for part in key.split("."):
        node = node[part] if isinstance(node, dict) else getattr(node, part)
    return node


def _priority_columns(cfg: Config) -> set:
    """Columns of the optional priority table (empty set if there is none or it cannot be read)."""
    if cfg.inputs.subkhg_priority is None:
        return set()
    try:
        import pandas as pd

        from .config import resolve, snake_name
        cols = list(pd.read_csv(resolve(cfg, cfg.inputs.subkhg_priority.path), nrows=0).columns)
        mapped = {snake_name(src): want for want, src in (cfg.inputs.subkhg_priority.columns or {}).items()}
        return {mapped.get(snake_name(c), c) for c in cols}      # the names stage 1 will see after the user's column mapping
    except Exception:
        return set()


def rivers_have_levels(cfg: Config) -> bool:
    """True if the rivers layer carries ``dry_season_wl_m`` values: Stage 1 then needs both vertical datums (spec section 3)."""
    if cfg.inputs.rivers is None:
        return False
    try:
        import pyogrio

        from .config import resolve, snake_name
        r = cfg.inputs.rivers
        path = resolve(cfg, r.path)
        want = snake_name((r.columns or {}).get("dry_season_wl_m", "dry_season_wl_m"))
        actual = next((f for f in pyogrio.read_info(path, layer=r.layer)["fields"] if snake_name(f) == want), None)
        if actual is None:
            return False
        df = pyogrio.read_dataframe(path, layer=r.layer, columns=[actual], read_geometry=False)
        return bool(df[actual].notna().any())
    except Exception:       # no such column, unreadable file: the stage itself reports it
        return False


def needs_by_stage(cfg: Config) -> dict[int, list[str]]:
    """Every parameter each stage needs, filled or not (given the current conveyance / demand / weights modes)."""
    pc, pr = cfg.pumping, cfg.prioritise
    need: dict[int, list[str]] = {sid: [] for sid in SECTIONS}
    need[1] = ["run.clip_margin_m", "inputs.dtm.vertical_rmse_m", "inputs.moisture.higher_is_wetter"]
    if rivers_have_levels(cfg):
        need[1] += ["run.vertical_datum", "inputs.rivers.vertical_datum"]
    if cfg.inputs.peat_depth is not None and cfg.inputs.peat_depth.is_raster:
        need[1].append("inputs.peat_depth.units")          # BRGM rasters are in cm, the neraca raster in m: never guessed
    need[2] = ["topology.snap_tolerance_m"]
    need[3] = ["hydro.breach_max_dist_cells"]
    if pr.weights_mode == "klh":
        need[6] = ["prioritise.weights_mode", "prioritise.klh_cpwi_breaks", "prioritise.klh_flow_breaks", "prioritise.klh_min_score"]
    else:
        need[6] = ["prioritise.weights_mode"] + (["prioritise.ahp_matrix"] if pr.weights_mode == "ahp" else [f"prioritise.criteria.{k}.weight" for k in pr.criteria])
    if pr.upstream_method == "flow_acc":
        need[6].append("prioritise.upstream_buffer_m")
    if cfg.inputs.concession is not None:
        need[6].append("prioritise.feasibility.concession_mode")
    need[7] = ["sekat.max_spacing_m", "sekat.snap_tolerance_m", "sekat.min_spacing_m"]
    if cfg.sekat.target_rise_share is not None or cfg.sekat.max_blocks is not None:
        need[7].append("sekat.balance_drawdown_m")
    for sid in (8, 9, 10):
        need[sid] = ["pumping.enabled"]
    if pc.enabled:                                       # sekat only (false): the pump stages ask for nothing else
        if cfg.pumping.route_edits is not None:
            need[8] += ["sekat.snap_tolerance_m"] + (["run.vertical_datum"] if route_edits_have_levels(cfg) else [])
        need[9] += ["pumping.uphill_penalty_lambda"]
        p = ["conveyance", "pump_efficiency", "max_head_per_station_m", "pump_capacity_m3s", "influence_distance_m"]
        if pc.conveyance == "canal":
            p.append("manning_n")
        elif pc.conveyance == "pipe":
            p += ["hazen_williams_c", "pipe_diameter_m"]
        cols = _priority_columns(cfg)
        if pc.demand_mode == "specific_yield" or not {"deficit_mm", "design_period_days"} <= cols:
            p += ["specific_yield", "water_table_rise_m"]      # no water deficit available: demand comes from specific yield
        if "design_period_days" not in cols:
            p.append("design_period_days")
        need[10] += [f"pumping.{k}" for k in p]
    if cfg.inputs.subkhg_indicators is not None and cfg.interventions.enabled:
        from .interventions import NEEDED
        need[11] = ["interventions.enabled"] + [f"interventions.{k}" for k in NEEDED]
    oc = cfg.optimise
    need[12] = ["optimise.enabled"]
    if oc.enabled:
        o = ["objective", "n_blocks", "max_evaluations", "canal_drawdown_m"]
        if oc.objective != "canal_rise":
            o += ["grid_m", "dry_days", "et_mm_day"] + (["transmissivity_multiplier"] if "urzainki2020" in [oc.peat_table, *oc.bracket_tables] else [])
        need[12] += [f"optimise.{k}" for k in o]
    return need


# Settings with a default that a person may still change, per stage. Never "missing": ``check`` lists them with their
# current value so a front end can offer them. ``review.auto_accept`` is left out on purpose (it skips the review stops).
OPTIONS_BY_STAGE: dict[int, list[str]] = {
    1: ["inputs.dtm.source", "run.crs", "run.auto_reproject", "run.memory_budget_gb", "run.subkhg_selection.mode", "run.subkhg_selection.n",
        "run.subkhg_selection.ids"],
    2: ["topology.overshoot_max_m", "topology.canal_classes", "topology.river_buffer_m", "topology.source_snap_m"],
    3: ["hydro.burn_depth_default_m", "hydro.flow_algorithm"],
    4: ["segments.max_length_m", "segments.min_length_m"],
    5: ["profiles.bank_offsets_m", "profiles.sample_step_m", "profiles.smoothing_window_m"],
    6: ["prioritise.ring_buffer_m", "prioritise.top_fraction", "prioritise.upstream_method"],
    7: ["sekat.dA_m", "sekat.slope_reinforced_pct", "sekat.min_new_spacing_m", "sekat.dedup_tol_m", "sekat.target_rise_share", "sekat.max_blocks"],
    8: [],
    9: ["pumping.routing", "pumping.allow_gate_addition", "pumping.sekat_scope"],
    10: ["pumping.demand_mode", "pumping.max_units_per_station"],
    11: ["budget.enabled", "budget.price_year", "budget.sekat_standard_idr", "budget.sekat_reinforced_idr", "budget.canal_closure_idr_per_km", "budget.revegetation_idr_per_ha", "budget.well_idr", "budget.well_radius_m", "budget.pump_idr", "budget.fuel_idr_per_l", "budget.fuel_l_per_kwh", "budget.pump_hours_per_day"],
    12: ["optimise.peat_table", "optimise.bracket_tables", "optimise.algorithms", "optimise.seed", "optimise.random_baseline_draws", "optimise.ga.population", "optimise.ga.mutation",
         "optimise.ga.elite", "optimise.ga.tournament", "optimise.sa.t0_fraction", "optimise.sa.cooling"],
}


# settings whose values change a stage's own results: whole sections (``topology``) or single keys (``pumping.routing``).
# A stage that is out of date makes every later one out of date, so each stage lists only what it reads itself.
FINGERPRINT_KEYS: dict[int, list[str]] = {
    1: ["run", "inputs"], 2: ["topology"], 3: ["hydro"], 4: ["segments"], 5: ["profiles"], 6: ["prioritise"], 7: ["sekat"], 8: ["pumping.enabled", "pumping.route_edits"],
    9: ["pumping.uphill_penalty_lambda", "pumping.routing", "pumping.allow_gate_addition", "pumping.sekat_scope"],
    10: ["pumping", "sekat.dA_m"], 11: ["interventions", "budget"], 12: ["optimise", "sekat.dA_m"],
}
SECTIONS = FINGERPRINT_KEYS          # kept for older imports


def canal_edits_digest(cfg: Config) -> Optional[str]:
    """Content hash of the canal edits layer (actions and geometries as stored), or None without one.

    The edits file can change while its path stays the same, so stage 1's fingerprint carries this: editing it in QGIS marks
    stage 1 and every later stage out of date, however it was edited.
    """
    return _edits_digest(cfg, cfg.inputs.canal_edits)


def route_edits_digest(cfg: Config) -> Optional[str]:
    """The same for the manual water sources and targets (``pumping.route_edits``), carried by stage 8's fingerprint."""
    return _edits_digest(cfg, cfg.pumping.route_edits)


def route_edits_have_levels(cfg: Config) -> bool:
    """True if the route edits add a water source with a ``z_src_m`` level: stage 8 then needs the vertical datum, like river levels."""
    sec = cfg.pumping.route_edits
    if sec is None:
        return False
    try:
        import pyogrio

        from .config import resolve
        df = pyogrio.read_dataframe(resolve(cfg, sec.path), layer=sec.layer, read_geometry=False)
        low = {c.strip().lower(): c for c in df.columns}
        if not {"z_src_m", "action", "kind"} <= set(low):
            return False
        add_src = df[(df[low["action"]].astype(str).str.strip().str.lower() == "add") & (df[low["kind"]].astype(str).str.strip().str.lower() == "source")]
        return bool(add_src[low["z_src_m"]].notna().any())
    except Exception:
        return False


def sekat_edits_digest(cfg: Config) -> Optional[str]:
    """The same for the sekat edits (``sekat.edits``), carried by stage 7's fingerprint."""
    return _edits_digest(cfg, cfg.sekat.edits)


def _edits_digest(cfg: Config, sec) -> Optional[str]:
    if sec is None:
        return None
    try:
        import hashlib

        import pyogrio

        from .config import resolve
        ed = pyogrio.read_dataframe(resolve(cfg, sec.path), layer=sec.layer)
        if not any(c.strip().lower() == "action" for c in ed.columns):
            return "unreadable"
        cols = sorted(c for c in ed.columns if c != ed.geometry.name)           # every attribute counts: a water level or a kind changes the result too
        rows = ["|".join([str(ed[c].iloc[i]).strip().lower() if ed[c].iloc[i] == ed[c].iloc[i] else "" for c in cols] + [g.wkb_hex]) for i, g in enumerate(ed.geometry)]
        return hashlib.sha256("|".join(sorted(rows)).encode()).hexdigest()
    except Exception:
        return "unreadable"             # the stage itself reports what is wrong with the file


def fingerprint(cfg: Config, stage: int) -> dict:
    """JSON-ready snapshot of the settings that determine a stage's results. Stored when the stage completes; if the
    current fingerprint differs, the stage's outputs are out of date."""
    out = {}
    for key in FINGERPRINT_KEYS[stage]:
        v = get_value(cfg, key)
        out[key] = v.model_dump(mode="json") if hasattr(v, "model_dump") else v
    if stage == 1:
        out["canal_edits_digest"] = canal_edits_digest(cfg)
    if stage == 7:
        out["sekat_edits_digest"] = sekat_edits_digest(cfg)
    if stage == 8:
        out["route_edits_digest"] = route_edits_digest(cfg)
    return out


def required_by_stage(cfg: Config) -> dict[int, list[str]]:
    """The subset of :func:`needs_by_stage` that is still null."""
    return {sid: [k for k in keys if get_value(cfg, k) is None] for sid, keys in needs_by_stage(cfg).items()}


def recommended_by_stage(cfg: Config) -> dict[int, list[str]]:
    rec: dict[int, list[str]] = {}
    if cfg.inputs.rivers is not None and not rivers_have_levels(cfg):     # with levels present they are required (needs_by_stage)
        rec[1] = ["run.vertical_datum", "inputs.rivers.vertical_datum"]
    return rec


def check(cfg: Config) -> dict:
    """JSON-ready summary: stage list, review flags, the parameters each stage needs (with current values) and which are null."""
    from .pipeline import STAGES          # lazy: pipeline imports this module
    needs, rec = needs_by_stage(cfg), recommended_by_stage(cfg)
    def entries(keys):
        return [{"key": k, "value": get_value(cfg, k)} for k in keys]
    stages = []
    for sid, name, _, review in STAGES:
        stages.append({"id": sid, "name": name, "review": review,
                       "needs": entries(needs[sid]), "missing": [k for k in needs[sid] if get_value(cfg, k) is None],
                       "recommended": entries(rec.get(sid, [])),
                       "recommended_missing": [k for k in rec.get(sid, []) if get_value(cfg, k) is None],
                       "options": entries(OPTIONS_BY_STAGE.get(sid, [])),
                       "fingerprint": fingerprint(cfg, sid)})
    return {"run_name": cfg.run.name, "output_gpkg": cfg.run.output_gpkg, "stages": stages, "preset": cfg.preset}
