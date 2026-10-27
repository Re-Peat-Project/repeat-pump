"""Fill a run setup from a RE-PEAT per-KHG work folder (``_khg/<code>_<name>/``). No qgis imports (testable in the engine venv).

The folder layout is the workspace's (AGENTS.md, "Per-KHG work folders"): 00_inputs (canals, rivers, blocks), 01_dem/inputs (DTM
clips), 02_delineation (sub-KHG units), 04_prioritisation (the ranking), cache (NDMI), 05_pump (this module's output). The peat depth
raster is the one the KHG's sub-KHG ranking config names (``re-peat/sites/<folder>/subkhg.yaml``). Whatever is not found stays empty,
so the form shows what still has to be chosen.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import yaml

DTM_ORDER = (("lidar", "lidar*.tif"), ("deltadtm", "deltadtm*.tif"), ("demnas", "demnas*.tif"))
BURN_FILE = "burnt_area_2015_2026_Indonesia.gpkg"


def khg_folders(root: str | Path) -> list[Path]:
    """The KHG work folders under ``root``: sub-folders whose name starts with a KHG code (digits and dots)."""
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and re.match(r"^\d[\d.\-]*_", p.name))


def _first(*paths: Path) -> Optional[Path]:
    return next((p for p in paths if p.is_file()), None)


def _latest(paths: list[Path]) -> Optional[Path]:
    """The file with the highest year in its name (ndmi_2023.tif beats ndmi_2019.tif); coarse copies (*_60m) are skipped."""
    paths = [p for p in paths if not p.stem.endswith("_60m")]
    return max(paths, key=lambda p: [int(x) for x in re.findall(r"\d{4}", p.stem)] or [0], default=None)


DEM_SURFACES = {"deltadtm": "deltadtm", "demnas": "demnas"}


def setup_from_khg(khg_dir: str | Path, hub: Optional[str | Path] = None, data: Optional[str | Path] = None, dem: Optional[str] = None,
                   dtm: Optional[str | Path] = None) -> tuple[dict, list[str]]:
    """A setup dict (the shape ``runconfig.read_setup`` returns, absolute paths) for one KHG folder, and the inputs it could not find.
    ``hub`` is the re-peat folder and ``data`` the shared _data folder; both default to the workspace next to the _khg root.
    ``dem`` (lidar, deltadtm, demnas): one variant of the full chain (re-peat/docs/18-full-run-plan.md); its units, prioritisation and
    neraca map come from ``<step>/<dem>/``, the run goes to ``05_pump/<dem>/``, and the DTM is ``dtm`` (else the LiDAR clip with the
    largest cover, or the corrected DeltaDTM / DEMNAS of 01_dem/processed/<dem>/ or of the benchmark). Without ``dem``: the older
    single layout (LiDAR first)."""
    k = Path(khg_dir).resolve()
    ws = k.parent.parent
    hub = Path(hub or os.environ.get("REPEAT_HUB") or ws / "re-peat")
    data = Path(data or os.environ.get("REPEAT_DATA") or ws / "_data")
    inputs: dict = {}
    missing: list[str] = []

    def put(key: str, path: Optional[Path], **extra) -> None:
        if path is None:
            missing.append(key)
        else:
            inputs[key] = {"path": str(path), **extra}

    sd = lambda step: k / step / dem if dem else k / step     # noqa: E731
    if dem:
        if dtm is None and dem == "lidar":
            dtm = _first(*sorted((k / "01_dem" / "inputs").glob("lidar_*.tif")))
        elif dtm is None:
            dtm = _first(k / "01_dem" / "processed" / dem / "dtm_smooth.tif", k / "01_dem" / "benchmark" / "04_processed" / dem / "dtm_smooth.tif")
        if dtm is None:
            missing.append("dtm")
        else:
            inputs["dtm"] = {"path": str(dtm), "surface_type": "DTM", "source": dem}
    else:
        for key, source in DTM_ORDER:                   # LiDAR first: it is the reference the other DTMs were benchmarked against
            hit = sorted((k / "01_dem" / "inputs").glob(source))
            if hit:
                inputs["dtm"] = {"path": str(hit[0]), "surface_type": "DTM", "source": key}
                break
        else:
            missing.append("dtm")
    put("subkhg", _first(sd("02_delineation") / "subkhg_units.gpkg"))
    put("subkhg_priority", _first(sd("04_prioritisation") / "national_layers" / "subkhg_priority.csv", sd("04_prioritisation") / "subkhg_priority.csv"))
    put("canals", _first(k / "00_inputs" / "canals.gpkg"))
    put("rivers", _first(k / "00_inputs" / "rivers.gpkg"))
    put("sekat_existing", _first(k / "00_inputs" / "blocks.gpkg"))
    put("burn_area", _first(k / "00_inputs" / "national" / BURN_FILE, data / BURN_FILE))   # the KHG's clipped copy first
    put("neraca_map", _first(sd("03_neraca") / "runs" / "balance" / "neraca_map.gpkg"))
    put("subkhg_indicators", _first(sd("04_prioritisation") / "national_layers" / "unit_prioritas.gpkg", sd("04_prioritisation") / "unit_prioritas.gpkg"))
    ndmi = _latest(list(k.glob("cache/*/annual/ndmi_*.tif")))
    if ndmi is None:
        missing.append("moisture")
    else:
        inputs["moisture"] = {"paths": [str(ndmi)], "higher_is_wetter": True}
    peat = None
    if (k / "00_inputs" / "peat_depth.tif").is_file():          # the KHG's own copy (re-peat local_inputs step), in cm like the source
        peat = {"path": str(k / "00_inputs" / "peat_depth.tif"), "units": "cm"}
    khg_yaml = hub / "sites" / k.name / "khg.yaml"            # the full-chain settings of this KHG (re-peat tools/khg_pipeline.py init)
    if peat is None and khg_yaml.is_file():
        pd_ = (yaml.safe_load(khg_yaml.read_text(encoding="utf8")) or {}).get("peat_depth") or {}
        raw = str(pd_.get("path") or "").replace("${REPEAT_DATA}", str(data)).replace("${REPEAT_KHG}", str(k.parent))
        if raw and Path(raw).is_file():
            peat = {"path": raw, "units": "cm" if pd_.get("scale") == 0.01 else "m"}
    site = hub / "sites" / k.name / (f"{dem}/" if dem else "") / "subkhg.yaml"
    if peat is None and site.is_file():
        cfg = yaml.safe_load(site.read_text(encoding="utf8")) or {}
        raw = ((cfg.get("rasters") or {}).get("peat_depth") or "")
        raw = raw.replace("${REPEAT_DATA}", str(data)).replace("${REPEAT_KHG}", str(k.parent))
        scale = (cfg.get("params") or {}).get("peat_depth_scale")
        if raw and Path(raw).is_file():
            peat = {"path": raw, "units": "cm" if scale == 0.01 else ("m" if scale in (None, 1, 1.0) else None)}
    if peat is None:
        missing.append("peat_depth")
    else:
        inputs["peat_depth"] = peat
    run = {"name": k.name, "output_gpkg": str(sd("05_pump") / f"{k.name.split('_', 1)[-1]}.gpkg")}
    out = {"run": run, "inputs": inputs}
    et = dry_season_et(k)
    if et is not None:                              # the dry-spell loss of the optional stage 11, from this KHG's own data
        out["optimise"] = {"et_mm_day": et}
    return out, missing


DRY_MONTHS = (6, 7, 8, 9)


def dry_season_et(khg_dir: str | Path) -> Optional[float]:
    """Mean evapotranspiration of June to September (mm/day) from the neraca air inputs: MOD16 dekads of the sub-KHG units
    (``03_neraca/inputs/balance_mod16_dekad.csv``, repeat_common.fetch_gee_balance), every year with data. None without the file."""
    import csv
    f = Path(khg_dir) / "03_neraca" / "inputs" / "balance_mod16_dekad.csv"
    if not f.is_file():
        return None
    rates = []
    with f.open(encoding="utf8") as fh:
        for r in csv.DictReader(fh):
            try:
                if int(r["start"][5:7]) in DRY_MONTHS and r["mm"] not in ("", "nan") and float(r["days"]) > 0:
                    rates.append(float(r["mm"]) / float(r["days"]))
            except (KeyError, ValueError):
                continue
    return round(sum(rates) / len(rates), 2) if rates else None
