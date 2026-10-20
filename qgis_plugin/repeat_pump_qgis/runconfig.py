"""Build a run YAML from a template config plus values chosen in QGIS. No qgis imports (testable in the engine venv).

Shared by the Processing provider and the wizard so both write the same config.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml

# input key in the config -> (path, optional layer name inside a multi-layer file)
LayerRef = tuple


def _absolute(v: Any, base: Path) -> Any:
    return str(base / v) if isinstance(v, str) and not os.path.isabs(v) else v


def absolutise_inputs(data: dict, base: Path) -> None:
    """Make every input path absolute (relative paths are relative to the config file's folder)."""
    for sec in data.setdefault("inputs", {}).values():
        if isinstance(sec, dict):
            if "path" in sec:
                sec["path"] = _absolute(sec["path"], base)
            if "paths" in sec:
                sec["paths"] = [_absolute(p, base) for p in sec["paths"]]


def set_dotted(data: dict, key: str, value: Any) -> None:
    """``set_dotted(d, 'pumping.manning_n', 0.03)`` sets ``d['pumping']['manning_n']``."""
    node = data
    parts = key.split(".")
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = value


def get_dotted(data: dict, key: str) -> Any:
    node: Any = data
    for p in key.split("."):
        if not isinstance(node, dict) or p not in node:
            return None
        node = node[p]
    return node


def build_run_config(config_file: str | Path, output_gpkg: Optional[str] = None, dtm: Optional[str] = None,
                     moisture: Optional[str] = None, priority: Optional[str] = None,
                     vectors: Optional[dict[str, LayerRef]] = None, params: Optional[dict[str, Any]] = None,
                     drop: Optional[list[str]] = None) -> dict:
    """Template YAML -> run config dict. ``vectors`` maps a config key (``canals``) to ``(path, layer_or_None)``;
    ``params`` maps dotted keys to values (e.g. the human-decided policy parameters). ``drop`` lists optional input keys the
    user left empty: they are removed so a placeholder path from the template cannot reach the engine."""
    config_file = Path(config_file)
    base = config_file.parent
    data = yaml.safe_load(config_file.read_text(encoding="utf8"))
    absolutise_inputs(data, base)
    if data.get("preset"):
        data["preset"] = _absolute(data["preset"], base)      # the run YAML is written to a temp folder
    inp = data["inputs"]
    run = data.setdefault("run", {})
    run["output_gpkg"] = output_gpkg or _absolute(run.get("output_gpkg", "out/run.gpkg"), base)
    if dtm:
        inp.setdefault("dtm", {})["path"] = dtm
    if moisture:
        inp.setdefault("moisture", {})["paths"] = [moisture]
    if priority:
        inp["subkhg_priority"] = {"path": priority}
    for cfgkey, (path, layer) in (vectors or {}).items():
        entry = inp.setdefault(cfgkey, {})
        entry["path"] = path
        if layer:
            entry["layer"] = layer
        else:
            entry.pop("layer", None)
    for key in drop or []:
        inp.pop(key, None)
    for k, v in (params or {}).items():
        set_dotted(data, k, v)
    return data


PRESET_FILE = "proposed_defaults.yaml"


def attach_preset(data: dict, run_dir: str | Path, bundled: str | Path) -> None:
    """Opt the run into the proposed-defaults preset: copy the bundled file next to the run config (an existing copy is kept,
    it may hold the team's edits) and point the config at it by a relative name, so the run folder stays portable."""
    run_dir, bundled = Path(run_dir), Path(bundled)
    if not bundled.is_file():
        raise FileNotFoundError(f"proposed defaults file not found: {bundled}")
    run_dir.mkdir(parents=True, exist_ok=True)
    dest = run_dir / PRESET_FILE
    if not dest.exists():
        dest.write_bytes(bundled.read_bytes())
    data["preset"] = PRESET_FILE


def detach_preset(data: dict) -> None:
    data.pop("preset", None)


def write_run_config(data: dict, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf8")
    return path
