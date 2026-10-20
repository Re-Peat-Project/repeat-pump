"""Which TODO(human) parameters each stage needs, without running it (for ``repeat-pump check``).

Mirrors the ``require(...)`` calls inside the stages (the stages stay the authority; a test compares both).
Only config-decidable requirements are listed. Data-dependent ones (e.g. vertical datums, needed only when
``rivers.dry_season_wl_m`` exists) are reported as ``recommended``.
"""
from __future__ import annotations

from .config import Config
from .pipeline import STAGES


def _null(section, keys: list[str], prefix: str) -> list[str]:
    return [f"{prefix}.{k}" for k in keys if getattr(section, k) is None]


def required_by_stage(cfg: Config) -> dict[int, list[str]]:
    pc, pr = cfg.pumping, cfg.prioritise
    req: dict[int, list[str]] = {sid: [] for sid, *_ in STAGES}
    req[1] = _null(cfg.run, ["clip_margin_m"], "run") + _null(cfg.inputs.dtm, ["vertical_rmse_m"], "inputs.dtm") \
        + _null(cfg.inputs.moisture, ["higher_is_wetter"], "inputs.moisture")
    req[2] = _null(cfg.topology, ["snap_tolerance_m"], "topology")
    req[3] = _null(cfg.hydro, ["breach_max_dist_cells"], "hydro")
    if pr.weights_mode == "ahp":
        req[6] += _null(pr, ["ahp_matrix"], "prioritise")
    else:
        req[6] += [f"prioritise.criteria.{k}.weight" for k, c in pr.criteria.items() if c.weight is None]
    if pr.upstream_method == "flow_acc":
        req[6] += _null(pr, ["upstream_buffer_m"], "prioritise")
    if cfg.inputs.concession is not None:
        req[6] += _null(pr.feasibility, ["concession_mode"], "prioritise.feasibility")
    req[7] = _null(cfg.sekat, ["max_spacing_m", "snap_tolerance_m", "min_spacing_m"], "sekat")
    req[9] = _null(pc, ["uphill_penalty_lambda"], "pumping")
    need = ["conveyance", "pump_efficiency", "max_head_per_station_m", "pump_capacity_m3s", "influence_distance_m"]
    if pc.conveyance == "canal":
        need.append("manning_n")
    elif pc.conveyance == "pipe":
        need += ["hazen_williams_c", "pipe_diameter_m"]
    if pc.demand_mode == "specific_yield":
        need += ["specific_yield", "water_table_rise_m"]
    req[10] = _null(pc, need, "pumping")
    return req


def recommended(cfg: Config) -> dict[int, list[str]]:
    rec: dict[int, list[str]] = {}
    if cfg.inputs.rivers is not None:
        rec[1] = _null(cfg.run, ["vertical_datum"], "run") + _null(cfg.inputs.rivers, ["vertical_datum"], "inputs.rivers")
    return rec


def check(cfg: Config) -> dict:
    """JSON-ready summary: stage list, review flags and missing parameters per stage."""
    req, rec = required_by_stage(cfg), recommended(cfg)
    return {
        "run_name": cfg.run.name,
        "output_gpkg": cfg.run.output_gpkg,
        "stages": [{"id": sid, "name": name, "review": review, "missing": req[sid], "recommended_missing": rec.get(sid, [])}
                   for sid, name, _, review in STAGES],
    }
