"""Pydantic models for the YAML run config (spec section 4) and error types.

Null-valued policy parameters (``# TODO(human)`` in the spec) are accepted at load
time. Each stage calls :func:`require` for the keys it needs and fails with one
message listing every missing key, so ``--stop-after`` works before all of
section 11 is answered.
"""
from __future__ import annotations

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


class MoistureCfg(_M):
    paths: list[str]
    higher_is_wetter: Optional[bool] = None


class RiversCfg(_M):
    path: str
    layer: Optional[str] = None
    vertical_datum: Optional[str] = None  # TODO(human): datum of dry_season_wl_m


class PathCfg(_M):
    path: str
    layer: Optional[str] = None   # layer name inside a multi-layer file (e.g. GeoPackage)


class InputsCfg(_M):
    dtm: DtmCfg
    subkhg: PathCfg
    subkhg_priority: Optional[PathCfg] = None   # optional: without it all selected sub-KHGs get equal priority and demand comes from specific yield
    canals: PathCfg
    canal_edits: Optional[PathCfg] = None   # lines with an "action" column: add | delete (reproducible manual fixes)
    sekat_existing: Optional[PathCfg] = None
    rivers: Optional[RiversCfg] = None
    burn_area: PathCfg
    peat_depth: PathCfg
    moisture: MoistureCfg
    concession: Optional[PathCfg] = None
    tma_obs: Optional[PathCfg] = None


class TopologyCfg(_M):
    snap_tolerance_m: Optional[float] = None  # TODO(human)
    overshoot_max_m: Optional[float] = None   # TODO(human): null = overshoot trimming off
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


class SekatCfg(_M):
    dA_m: float = 0.40
    max_spacing_m: Optional[float] = None  # TODO(human)
    slope_reinforced_pct: float = 5.0
    snap_tolerance_m: Optional[float] = None  # TODO(human)
    min_spacing_m: Optional[float] = None  # TODO(human)
    min_new_spacing_m: Optional[float] = None  # no two NEW sekat closer than this along a canal (legacy JARAK_MIN, 500 m); null = off. Overrides the head rule on steep land
    dedup_tol_m: Optional[float] = None    # a proposed sekat within this distance of an existing one, or of one proposed on another canal, is dropped (legacy DEDUP_TOL, 50 m); null = off


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
    routing: Literal["steiner", "per_target"] = "steiner"
    allow_gate_addition: bool = False


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
    review: ReviewCfg = Field(default_factory=ReviewCfg)

    @property
    def base_dir(self) -> Path:
        return Path(getattr(self, "_base", "."))

    @property
    def preset(self) -> dict:
        """``{"path": ..., "keys": [...]}``: the proposed-defaults preset the run opted into and the keys it filled."""
        return getattr(self, "_preset", {"path": None, "keys": []})


# What a proposed-defaults preset may fill: policy and engineering values only. Facts about the data (datums, RMSE, which
# way the moisture index runs) and every input path stay with the user, so a preset can never describe the wrong dataset.
PRESET_SECTIONS = {"topology", "hydro", "sekat", "prioritise", "pumping", "optimise"}
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


def apply_preset(data: dict, base: Path) -> tuple[list[str], Optional[str]]:
    """Fill the null policy/engineering parameters of a run config from the preset file named by its top-level ``preset`` key.

    Opt-in and additive: values the run config already holds are never touched, and a config without ``preset`` loads
    exactly as before. Returns the keys that came from the preset (dotted) and the preset path.
    """
    ref = data.pop("preset", None)
    if not ref:
        return [], None
    p = Path(ref) if Path(ref).is_absolute() else base / ref
    if not p.exists():
        raise ConfigError(f"preset file not found: {p}")
    preset = yaml.safe_load(p.read_text(encoding="utf8")) or {}
    bad = [k for k in preset if k not in PRESET_SECTIONS | {"run"}]
    bad += [f"run.{k}" for k in preset.get("run", {}) if k not in PRESET_RUN_KEYS]
    if bad:
        raise ConfigError(f"preset {p.name} may only set {sorted(PRESET_SECTIONS)} and run.{sorted(PRESET_RUN_KEYS)}; not allowed: {bad}")
    applied: list[str] = []
    _fill_nulls(data, preset, "", applied)
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
    """Resolve a config path relative to the config file's folder."""
    q = Path(p)
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
