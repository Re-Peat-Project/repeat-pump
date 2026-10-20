"""Run context: output GeoPackage access, logging, warnings, resumable state."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio

from .config import Config, resolve

_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class RunContext:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.gpkg = resolve(cfg, cfg.run.output_gpkg)
        self.out_dir = self.gpkg.parent
        self.work = self.out_dir / (self.gpkg.stem + "_work")
        self.work.mkdir(parents=True, exist_ok=True)
        self.crs = cfg.run.crs
        self.warnings: list[str] = []
        self.report: dict[str, Any] = {}
        self.log = logging.getLogger("repeat_pump")
        self.state_path = self.out_dir / "run_state.json"
        self.state: dict[str, Any] = (
            json.loads(self.state_path.read_text()) if self.state_path.exists() else {"stages": {}, "warnings": [], "report": {}}
        )
        self.warnings = list(self.state.get("warnings", []))
        self.report = dict(self.state.get("report", {}))

    # ---- state
    def save_state(self) -> None:
        self.state["warnings"] = self.warnings
        self.state["report"] = self.report
        self.state_path.write_text(json.dumps(self.state, indent=2, default=str))

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)
        self.log.warning(msg)

    # ---- layers
    def write_layer(self, name: str, df: pd.DataFrame, stage: str) -> None:
        if not _NAME.match(name):
            raise ValueError(f"layer name {name!r} must be lower_snake_case")
        df = df.copy()
        df["run_name"] = self.cfg.run.name
        df["stage"] = stage
        for c in df.columns:
            if c != "geometry" and (not _NAME.match(c) or len(c) > 30):
                raise ValueError(f"field {c!r} in layer {name!r} must be lower_snake_case and <= 30 chars")
        if isinstance(df, gpd.GeoDataFrame) and df.geometry.name in df and df.geometry.notna().any():
            if df.crs is None:
                df = df.set_crs(self.crs)
            pyogrio.write_dataframe(df, self.gpkg, layer=name, driver="GPKG")
        else:
            pyogrio.write_dataframe(pd.DataFrame(df.drop(columns="geometry", errors="ignore")), self.gpkg, layer=name, driver="GPKG")

    def read_layer(self, name: str) -> gpd.GeoDataFrame:
        return pyogrio.read_dataframe(self.gpkg, layer=name)

    def has_layer(self, name: str) -> bool:
        return self.gpkg.exists() and name in [l[0] for l in pyogrio.list_layers(self.gpkg)]

    def set_counts(self, stage: str, **counts: Any) -> None:
        self.report.setdefault("counts", {})[stage] = counts
