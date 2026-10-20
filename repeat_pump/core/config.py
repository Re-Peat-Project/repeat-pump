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
    mode: Literal["top_n", "ids"] = "top_n"
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
    subkhg_priority: PathCfg
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
    weights_mode: Literal["direct", "ahp"] = "direct"
    ahp_matrix: Optional[list[list[float]]] = None
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
    influence_distance_m: Optional[float] = None
    routing: Literal["steiner", "per_target"] = "steiner"
    allow_gate_addition: bool = False


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
    review: ReviewCfg = Field(default_factory=ReviewCfg)

    @property
    def base_dir(self) -> Path:
        return Path(getattr(self, "_base", "."))


def load_config(path: str | Path) -> Config:
    path = Path(path)
    with open(path, encoding="utf8") as fh:
        data = yaml.safe_load(fh)
    cfg = Config.model_validate(data)
    object.__setattr__(cfg, "_base", str(path.parent.resolve()))
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
