"""Pydantic models for the YAML run config (spec section 4) and error types.

Null-valued policy parameters (``# TODO(human)`` in the spec) are accepted at load
time. Each stage calls :func:`require` for the keys it needs and fails with one
message listing every missing key, so ``--stop-after`` works before all of
section 11 is answered.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ConfigError(ValueError):
    """Invalid or inconsistent configuration."""


class MissingParameters(ConfigError):
    """One or more required (TODO(human)) parameters are null."""


class InputError(ValueError):
    """An input dataset violates the input contract (spec section 3)."""


class CRSMismatchError(InputError):
    pass


class SurfaceTypeError(InputError):
    pass


class NeedsHuman(InputError):
    """A decision the module must not guess (spec section 11)."""


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Columns an input may carry under another name, per input (``inputs.<role>.columns`` maps expected name -> your name).
# Value: True when the stage cannot run without it. The wizard keeps a copy (wizard/preflight.py); a test keeps them equal.
CANONICAL_COLUMNS: dict[str, dict[str, bool]] = {
    "subkhg": {"subkhg_id": True},
    "subkhg_priority": {"subkhg_id": True, "priority_rank": False, "deficit_mm": False, "design_period_days": False},
    "canals": {"canal_class": True, "depth_m": False, "width_m": False},
    "sekat_existing": {"sekat_id": True, "has_gate": False, "crest_elev_m": False},
    "rivers": {"dry_season_wl_m": False, "perennial": False},
    "burn_area": {"burn_freq": True},
    "peat_depth": {"peat_thick": True},
    "subkhg_indicators": {"subkhg_id": True},
}


def snake_name(c: str) -> str:
    """The name the engine gives a column when it reads a vector layer: lower case, letters and digits only, at most 30 characters."""
    import re
    n = re.sub(r"[^a-z0-9]+", "_", str(c).strip().lower()).strip("_")[:30] or "col"
    return "f_" + n if not n[0].isalpha() else n


class SubKhgSelection(_M):
    """``top_n``: the N highest-ranked sub-KHGs of the priority table; ``ids``: the listed ones; ``all``: every sub-KHG in the layer.
    Without a priority ranking, ``top_n`` falls back to ``all`` (equal priority) and says so in the report."""
    mode: Literal["top_n", "ids", "all"] = "top_n"
    n: Optional[int] = None
    ids: Optional[list[Any]] = None


class RunCfg(_M):
    name: str
    output_gpkg: str
    crs: str
    auto_reproject: bool = False
    vertical_datum: Optional[str] = None  # TODO(human)
    memory_budget_gb: Optional[float] = 8
    subkhg_selection: SubKhgSelection = Field(default_factory=SubKhgSelection)
    clip_margin_m: Optional[float] = None  # TODO(human): Stage 1 clip margin


class DtmCfg(_M):
    path: str
    surface_type: str
    vertical_rmse_m: Optional[float] = None  # TODO(human)
    source: Optional[Literal["lidar", "deltadtm", "demnas", "other"]] = None   # what the DTM is; lets a preset suggest vertical_rmse_m


class MoistureCfg(_M):
    paths: list[str]
    higher_is_wetter: Optional[bool] = None


class RiversCfg(_M):
    path: str
    layer: Optional[str] = None
    columns: Optional[dict[str, str]] = None   # {expected column: column in your layer}, see PathCfg
    vertical_datum: Optional[str] = None  # TODO(human): datum of dry_season_wl_m


class PathCfg(_M):
    path: str
    layer: Optional[str] = None   # layer name inside a multi-layer file (e.g. GeoPackage)
    columns: Optional[dict[str, str]] = None   # {expected column: column in your layer} when your data names it differently (CANONICAL_COLUMNS)


RASTER_SUFFIXES = (".tif", ".tiff", ".img", ".vrt", ".asc")


class PeatCfg(PathCfg):
    """Peat depth as thickness-class polygons (PEAT_THICK text) or as a depth raster (e.g. the BRGM model, or the class-midpoint raster
    the neraca module reads). A raster needs its unit stated: the BRGM rasters are in centimetres, the neraca raster in metres."""
    units: Optional[Literal["m", "cm"]] = None       # TODO(human) for a raster: m | cm
    nodata: Optional[list[float]] = None             # extra no-data values besides the file's own, e.g. [-8888]

    @property
    def is_raster(self) -> bool:
        return Path(self.path).suffix.lower() in RASTER_SUFFIXES


class InputsCfg(_M):
    dtm: DtmCfg
    subkhg: PathCfg
    subkhg_priority: Optional[PathCfg] = None   # optional: without it all selected sub-KHGs get equal priority and demand comes from specific yield
    canals: PathCfg
    canal_edits: Optional[PathCfg] = None   # lines with an "action" column: add | delete (reproducible manual fixes)
    sekat_existing: Optional[PathCfg] = None
    rivers: Optional[RiversCfg] = None
    burn_area: Optional[PathCfg] = None      # optional: without it the burn_freq criterion gets weight 0
    peat_depth: Optional[PeatCfg] = None     # optional: without it the peat_depth criterion gets weight 0 (the KLH scoring needs it)
    moisture: MoistureCfg
    concession: Optional[PathCfg] = None
    tma_obs: Optional[PathCfg] = None
    subkhg_indicators: Optional[PathCfg] = None   # optional: the sub-KHG prioritisation's unit_prioritas (csv or gpkg); turns on the interventions in stage 11


class TopologyCfg(_M):
    snap_tolerance_m: Optional[float] = None  # TODO(human)
    overshoot_max_m: Optional[float] = None   # TODO(human): null = overshoot trimming off
    canal_class_map: Optional[dict[str, str]] = None   # {value in your canal_class column: primer | sekunder | tersier}, e.g. {"1": primer}; unmapped values keep their own text
    canal_classes: Optional[list[str]] = None  # canal_class values kept for the analysis (Panduan 1.2: primer, sekunder); null = every class
    river_buffer_m: Optional[float] = None    # a river within this distance of a canal counts as meeting it (Panduan 8.2: 30 m); null = exact crossing only
    source_snap_m: Optional[float] = None     # with canal_classes: river points found on the full canal set are moved onto the kept network within this distance (SNAP_MUARA, 50 m)


class HydroCfg(_M):
    breach_max_dist_cells: Optional[int] = None  # TODO(human)
    burn_depth_default_m: float = 2.0
    flow_algorithm: Literal["dinf", "mfd", "d8"] = "dinf"


class SegmentsCfg(_M):
    max_length_m: float = 500
    min_length_m: float = 25


class ProfilesCfg(_M):
    bank_offsets_m: list[float] = [6, 10]
    sample_step_m: float = 5
    smoothing_window_m: float = 50
    direction_fallback: Literal["flow_acc", "forward"] = "flow_acc"   # canals neither the profile nor a river connection can orient:
                                                                      # downstream = the end with more flow accumulation (stage 3), or the digitised direction


class SekatCfg(_M):
    dA_m: float = 0.40
    max_spacing_m: Optional[float] = None  # TODO(human)
    slope_reinforced_pct: float = 5.0
    snap_tolerance_m: Optional[float] = None  # TODO(human)
    min_spacing_m: Optional[float] = None  # TODO(human)
    min_new_spacing_m: Optional[float] = None  # no two NEW sekat closer than this along a canal (legacy JARAK_MIN, 500 m); null = off. Overrides the head rule on steep land
    edits: Optional[PathCfg] = None        # manual changes to the proposals: points with an action column, add | delete (see core/sekat.py)
    dedup_tol_m: Optional[float] = None    # a proposed sekat within this distance of an existing one, or of one proposed on another canal, is dropped (legacy DEDUP_TOL, 50 m); null = off
    target_rise_share: Optional[float] = None   # balance: keep the fewest proposals that give this share (0-1) of the canal rewetting all of them give; null = keep all
    balance_drawdown_m: Optional[float] = None  # dry-season canal level below the land used to score the rewetting (needed with target_rise_share or max_blocks)
    max_blocks: Optional[int] = None            # budget: at most this many new sekat, the ones that rewet the most canal first; null = no cap


class CriterionCfg(_M):
    weight: Optional[float] = None  # TODO(human)
    direction: Literal["higher_is_worse", "lower_is_worse"] = "higher_is_worse"


class FeasibilityCfg(_M):
    concession_mode: Optional[Literal["exclude", "flag", "ignore"]] = None  # TODO(human)


def _criteria() -> dict[str, CriterionCfg]:
    return {k: CriterionCfg() for k in ("burn_freq", "peat_depth", "dryness", "upstream_contrib")}


class PrioritiseCfg(_M):
    ring_buffer_m: list[float] = [15, 100]
    criteria: dict[str, CriterionCfg] = Field(default_factory=_criteria)
    weights_mode: Literal["direct", "ahp", "klh"] = "direct"
    ahp_matrix: Optional[list[list[float]]] = None
    klh_cpwi_breaks: Optional[list[float]] = None   # TODO(human), klh mode: [wet, dry-edge] break values of the moisture index, scored 3 / 2 / 1
    klh_flow_breaks: Optional[list[float]] = None   # TODO(human), klh mode: [low, high] breaks of the flow accumulation maximum, scored 1 / 2 / 3
    klh_min_score: Optional[float] = None           # TODO(human), klh mode: segments scoring at least this (of 12) become targets
    feasibility: FeasibilityCfg = Field(default_factory=FeasibilityCfg)
    top_fraction: float = 0.2
    upstream_method: Literal["flow_acc", "graph"] = "flow_acc"
    upstream_buffer_m: Optional[float] = None  # TODO(human): narrow buffer for flow_acc


class PumpingCfg(_M):
    enabled: bool = True     # false: sekat only. Stages 8-10 are skipped, e.g. when the KHG has no usable river source yet
    conveyance: Optional[Literal["canal", "pipe"]] = None  # TODO(human)
    manning_n: Optional[float] = None
    hazen_williams_c: Optional[float] = None
    pipe_diameter_m: Optional[float] = None
    pump_efficiency: Optional[float] = None
    max_head_per_station_m: Optional[float] = None
    pump_capacity_m3s: Optional[float] = None
    max_units_per_station: Optional[int] = None  # None = unbounded
    uphill_penalty_lambda: Optional[float] = None
    demand_mode: Literal["deficit", "specific_yield"] = "deficit"
    specific_yield: Optional[float] = None
    water_table_rise_m: Optional[float] = None  # TODO(human): delta h, specific_yield mode
    design_period_days: Optional[float] = None  # TODO(human): needed only where the priority table gives no design_period_days
    influence_distance_m: Optional[float] = None
    route_edits: Optional[PathCfg] = None   # manual water sources and targets: points with action add|delete and kind source|target (core/network.py)
    routing: Literal["steiner", "per_target"] = "steiner"
    allow_gate_addition: bool = False
    sekat_scope: Literal["all", "selected"] = "all"   # sekat in the plan: every proposal, or those on the served selected canals plus the gates on their pump routes


class GaCfg(_M):
    """Genetic algorithm settings. Implementation defaults, not values taken from the paper."""
    population: int = 30
    mutation: float = 0.1
    elite: int = 2
    tournament: int = 3


class SaCfg(_M):
    """Simulated annealing settings. Implementation defaults, not values taken from the paper."""
    t0_fraction: float = 0.01
    cooling: float = 0.995


class OptimiseCfg(_M):
    """Optional Stage 12: canal blocking optimisation after Urzainki et al. (2020). Every physical input is a human decision."""
    enabled: bool = False
    objective: Literal["canal_rise", "pde", "screen_then_pde"] = "canal_rise"
    algorithms: list[Literal["ga", "sa", "greedy"]] = ["ga", "sa"]
    n_blocks: Optional[int] = None                    # TODO(human): number of new blocks to choose
    max_evaluations: Optional[int] = None             # TODO(human): cap on distinct layouts scored per algorithm
    canal_drawdown_m: Optional[float] = None          # TODO(human): dry-season canal water level below the surrounding land
    grid_m: Optional[float] = None                    # TODO(human): grid cell size of the groundwater model (pde objectives)
    dry_days: Optional[int] = None                    # TODO(human): length of the drying spell (pde objectives)
    et_mm_day: Optional[float] = None                 # TODO(human): net evapotranspiration loss without rain, mm/day (pde objectives)
    transmissivity_multiplier: Optional[float] = None  # TODO(human): scales the peat transmissivity table (pde objectives)
    seed: int = 0
    random_baseline_draws: int = 10
    ga: GaCfg = Field(default_factory=GaCfg)
    sa: SaCfg = Field(default_factory=SaCfg)


class ReviewCfg(_M):
    auto_accept: list[int] = []


class InterventionsCfg(_M):
    """Treatment class per sub-KHG in stage 11 (core/interventions.py). Thresholds are policy values; the preset proposes them."""
    enabled: bool = True
    protected_share: Optional[float] = None    # FEG protected function share from which canals are closed or backfilled
    reach_min: Optional[float] = None          # share of the unit within reach of a canal (f_reach) below which blocks cannot help it
    ndmi_dry: Optional[float] = None           # NDMI below this is dry
    burned_min: Optional[float] = None         # share of the unit ever burnt from which it counts as burnt
    water_max_dist_m: Optional[float] = None   # mean distance to permanent water (f_water_dist) up to which water counts as nearby
    held_target: Optional[float] = None        # share of the deficit the sekat must hold to count as enough
    deficit_min_mm: Optional[float] = None     # KHG deficit from which blocks are taken to fall short where they were not analysed
    specific_yield: Optional[float] = None     # water held = canal rise x specific_yield x lateral_reach_m (neraca: 0.15)
    lateral_reach_m: Optional[float] = None


class Config(_M):
    run: RunCfg
    inputs: InputsCfg
    topology: TopologyCfg = Field(default_factory=TopologyCfg)
    hydro: HydroCfg = Field(default_factory=HydroCfg)
    segments: SegmentsCfg = Field(default_factory=SegmentsCfg)
    profiles: ProfilesCfg = Field(default_factory=ProfilesCfg)
    sekat: SekatCfg = Field(default_factory=SekatCfg)
    prioritise: PrioritiseCfg = Field(default_factory=PrioritiseCfg)
    pumping: PumpingCfg = Field(default_factory=PumpingCfg)
    optimise: OptimiseCfg = Field(default_factory=OptimiseCfg)
    interventions: InterventionsCfg = Field(default_factory=InterventionsCfg)
    review: ReviewCfg = Field(default_factory=ReviewCfg)

    @property
    def base_dir(self) -> Path:
        return Path(getattr(self, "_base", "."))

    @property
    def preset(self) -> dict:
        """``{"path": ..., "keys": [...]}``: the proposed-defaults preset the run opted into and the keys it filled."""
        return getattr(self, "_preset", {"path": None, "keys": []})


# What a proposed-defaults preset may fill: policy and engineering values. Input paths and datums stay with the user. Two facts
# about the data may be suggested through ``suggested_facts`` (DTM error by DTM type, moisture direction), flagged like the rest.
PRESET_SECTIONS = {"topology", "hydro", "sekat", "prioritise", "pumping", "optimise", "interventions"}
PRESET_RUN_KEYS = {"clip_margin_m"}


def _fill_nulls(target: dict, source: dict, prefix: str, applied: list[str]) -> None:
    """Copy ``source`` values into ``target`` where ``target`` has no value (missing or null). Never overwrites."""
    for k, v in source.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            _fill_nulls(target[k], v, key, applied)
        elif isinstance(v, dict) and k not in target:
            target[k] = {}
            _fill_nulls(target[k], v, key, applied)
        elif v is not None and target.get(k) is None:
            target[k] = v
            applied.append(key)


def _suggest_facts(data: dict, facts: dict, applied: list[str]) -> None:
    """``suggested_facts`` of a preset: a typical DTM error for the declared ``inputs.dtm.source`` and the usual direction of the
    moisture index. Filled only where the run config leaves them null, and listed like every other preset value."""
    inputs = data.get("inputs") or {}
    dtm, moist = inputs.get("dtm") or {}, inputs.get("moisture") or {}
    table = facts.get("dtm_rmse_by_source") or {}
    if dtm.get("vertical_rmse_m") is None and dtm.get("source") in table:
        dtm["vertical_rmse_m"] = float(table[dtm["source"]])
        applied.append("inputs.dtm.vertical_rmse_m")
    if moist and moist.get("higher_is_wetter") is None and facts.get("moisture_higher_is_wetter") is not None:
        moist["higher_is_wetter"] = bool(facts["moisture_higher_is_wetter"])
        applied.append("inputs.moisture.higher_is_wetter")


def apply_preset(data: dict, base: Path) -> tuple[list[str], Optional[str]]:
    """Fill the null policy/engineering parameters of a run config from the preset file named by its top-level ``preset`` key.

    Opt-in and additive: values the run config already holds are never touched, and a config without ``preset`` loads
    exactly as before. Returns the keys that came from the preset (dotted) and the preset path.
    """
    ref = data.pop("preset", None)
    if not ref:
        return [], None
    ref = os.path.expandvars(ref)
    p = Path(ref) if Path(ref).is_absolute() else base / ref
    if not p.exists():
        raise ConfigError(f"preset file not found: {p}")
    preset = yaml.safe_load(p.read_text(encoding="utf8")) or {}
    facts = preset.pop("suggested_facts", None) or {}
    bad = [k for k in preset if k not in PRESET_SECTIONS | {"run"}]
    bad += [f"run.{k}" for k in preset.get("run", {}) if k not in PRESET_RUN_KEYS]
    if bad:
        raise ConfigError(f"preset {p.name} may only set {sorted(PRESET_SECTIONS)} and run.{sorted(PRESET_RUN_KEYS)}; not allowed: {bad}")
    applied: list[str] = []
    _fill_nulls(data, preset, "", applied)
    _suggest_facts(data, facts, applied)
    return applied, str(p)


def load_config(path: str | Path) -> Config:
    path = Path(path)
    with open(path, encoding="utf8") as fh:
        data = yaml.safe_load(fh)
    applied, preset_path = apply_preset(data, path.parent.resolve())
    cfg = Config.model_validate(data)
    object.__setattr__(cfg, "_base", str(path.parent.resolve()))
    object.__setattr__(cfg, "_preset", {"path": preset_path, "keys": applied})
    return cfg


def resolve(cfg: Config, p: str) -> Path:
    """Resolve a config path relative to the config file's folder. ``${VAR}`` is expanded first (e.g. ``${REPEAT_KHG}``)."""
    q = Path(os.path.expandvars(p))
    return q if q.is_absolute() else Path(cfg.base_dir) / q


def require_many(items: list[tuple], stage: str) -> None:
    """Like :func:`require` over several sections: ONE message listing every missing key."""
    missing = []
    for section, keys, prefix in items:
        missing += [f"{prefix}.{k}" for k in keys if getattr(section, k) is None]
    if missing:
        raise MissingParameters(
            f"{stage} needs these parameters (TODO(human), see spec section 11): " + ", ".join(missing)
        )


def require(section: BaseModel, keys: list[str], stage: str, prefix: str) -> None:
    """Fail with ONE message listing every null parameter the stage needs."""
    missing = [f"{prefix}.{k}" for k in keys if getattr(section, k) is None]
    if missing:
        raise MissingParameters(
            f"{stage} needs these parameters (TODO(human), see spec section 11): " + ", ".join(missing)
        )
