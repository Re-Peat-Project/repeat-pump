"""Which TODO(human) parameters each stage needs, without running it (for ``repeat-pump check``).

Mirrors the ``require(...)`` calls inside the stages (the stages stay the authority). Only config-decidable
requirements are listed. Data-dependent ones (e.g. vertical datums, needed only when ``rivers.dry_season_wl_m``
exists) are reported as ``recommended``.
"""
from __future__ import annotations

from typing import Any

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

        from .config import resolve
        return set(pd.read_csv(resolve(cfg, cfg.inputs.subkhg_priority.path), nrows=0).columns)
    except Exception:
        return set()


def needs_by_stage(cfg: Config) -> dict[int, list[str]]:
    """Every parameter each stage needs, filled or not (given the current conveyance / demand / weights modes)."""
    pc, pr = cfg.pumping, cfg.prioritise
    need: dict[int, list[str]] = {sid: [] for sid in SECTIONS}
    need[1] = ["run.clip_margin_m", "inputs.dtm.vertical_rmse_m", "inputs.moisture.higher_is_wetter"]
    need[2] = ["topology.snap_tolerance_m"]
    need[3] = ["hydro.breach_max_dist_cells"]
    need[6] = ["prioritise.ahp_matrix"] if pr.weights_mode == "ahp" else [f"prioritise.criteria.{k}.weight" for k in pr.criteria]
    if pr.upstream_method == "flow_acc":
        need[6].append("prioritise.upstream_buffer_m")
    if cfg.inputs.concession is not None:
        need[6].append("prioritise.feasibility.concession_mode")
    need[7] = ["sekat.max_spacing_m", "sekat.snap_tolerance_m", "sekat.min_spacing_m"]
    need[9] = ["pumping.uphill_penalty_lambda"]
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
    need[10] = [f"pumping.{k}" for k in p]
    oc = cfg.optimise
    need[12] = ["optimise.enabled"]
    if oc.enabled:
        o = ["objective", "n_blocks", "max_evaluations", "canal_drawdown_m"]
        if oc.objective != "canal_rise":
            o += ["grid_m", "dry_days", "et_mm_day", "transmissivity_multiplier"]
        need[12] += [f"optimise.{k}" for k in o]
    return need


# settings whose values change a stage's own results: whole sections (``topology``) or single keys (``pumping.routing``).
# A stage that is out of date makes every later one out of date, so each stage lists only what it reads itself.
FINGERPRINT_KEYS: dict[int, list[str]] = {
    1: ["run", "inputs"], 2: ["topology"], 3: ["hydro"], 4: ["segments"], 5: ["profiles"], 6: ["prioritise"], 7: ["sekat"], 8: [],
    9: ["pumping.uphill_penalty_lambda", "pumping.routing", "pumping.allow_gate_addition"],
    10: ["pumping", "sekat.dA_m"], 11: [], 12: ["optimise", "sekat.dA_m"],
}
SECTIONS = FINGERPRINT_KEYS          # kept for older imports


def fingerprint(cfg: Config, stage: int) -> dict:
    """JSON-ready snapshot of the settings that determine a stage's results. Stored when the stage completes; if the
    current fingerprint differs, the stage's outputs are out of date."""
    out = {}
    for key in FINGERPRINT_KEYS[stage]:
        v = get_value(cfg, key)
        out[key] = v.model_dump(mode="json") if hasattr(v, "model_dump") else v
    return out


def required_by_stage(cfg: Config) -> dict[int, list[str]]:
    """The subset of :func:`needs_by_stage` that is still null."""
    return {sid: [k for k in keys if get_value(cfg, k) is None] for sid, keys in needs_by_stage(cfg).items()}


def recommended_by_stage(cfg: Config) -> dict[int, list[str]]:
    rec: dict[int, list[str]] = {}
    if cfg.inputs.rivers is not None:
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
                       "fingerprint": fingerprint(cfg, sid)})
    return {"run_name": cfg.run.name, "output_gpkg": cfg.run.output_gpkg, "stages": stages}
