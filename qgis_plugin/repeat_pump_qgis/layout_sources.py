"""The "Sumber Data" lines of a map layout, from the run's inputs and the RE-PEAT data catalogue. No qgis imports (testable).

A file under ``_data`` is described by its row in ``re-peat/sites/data_catalog.csv`` (description, source, year). A file in a KHG work
folder is traced to what it was made from: the ``00_inputs`` clips to the national layers ``subkhg.prepare_inputs`` clips (the
command is in each site's README), the ``01_dem/inputs`` clips through their ``manifest.csv``, and the module outputs to the module
that wrote them. Anything else is listed by file name.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Optional

# the national layers subkhg.prepare_inputs clips into 00_inputs (re-peat/sites/<khg>/README.md, "Prepare the inputs")
CLIPPED_FROM = {"canals.gpkg": "kanal_osgm_khg_existing_Indonesia.gpkg", "rivers.gpkg": "RBI_sungai.gpkg", "lakes.gpkg": "RBI_wadukdanau.gpkg",
                "blocks.gpkg": "infrastruktur_hidrologis_existing_BRGM_Indonesia.gpkg", "khg.gpkg": "batas_khg_indonesia.gpkg"}
MODULE_OUTPUTS = {"subkhg_units.gpkg": "Batas sub-KHG: delineasi RE-PEAT (repeat-delineation)",
                  "unit_prioritas.gpkg": "Indikator dan prioritas sub-KHG: RE-PEAT (repeat-prioritisation)",
                  "subkhg_priority.csv": "Prioritas sub-KHG dan defisit neraca air: RE-PEAT (repeat-prioritisation, repeat-neraca)",
                  "neraca_map.gpkg": "Neraca air per sub-KHG (CHIRPS, MODIS MOD16) dan stasiun SiTMAT: RE-PEAT (repeat-neraca)"}


def _catalog(path: Path) -> dict:
    if not path.is_file():
        return {}
    with open(path, encoding="utf8", newline="") as fh:
        out: dict = {}
        for r in csv.DictReader(fh):
            out.setdefault(r["path"].replace("\\", "/"), []).append(r)
        return out


def _describe(row: dict) -> str:
    desc = row.get("description", "").strip().split(". ")[0].rstrip(".")      # the first sentence: the catalogue notes are for analysts
    bits = [desc]
    src, year = row.get("source", "").strip(), row.get("year", "").strip()
    if src:
        bits.append(src)
    if year:
        bits.append(year)
    return ", ".join(b for b in bits if b)


def source_lines(inputs: dict, data_dir: str | Path, catalog_csv: str | Path, khg_root: Optional[str | Path] = None) -> list[str]:
    """One line per distinct source of the run's inputs (``inputs`` as in a run config, absolute paths)."""
    data_dir = Path(data_dir).resolve()
    cat = _catalog(Path(catalog_csv))
    out: list[str] = []

    def add(line: str) -> None:
        if line and line not in out:
            out.append(line)

    def from_data(p: Path) -> None:
        try:
            rel = p.resolve().relative_to(data_dir).as_posix()
        except ValueError:
            add(p.name)
            return
        rows = cat.get(rel) or cat.get(rel.rsplit("/", 1)[0] + "/*") or []   # collapsed folders are catalogued once (catalog_collapse.csv)
        raster = p.suffix.lower() in (".tif", ".tiff", ".img", ".vrt", ".asc")
        row = next((r for r in rows if r.get("layer", "").startswith("[raster") == raster), rows[0] if rows else None)
        add(_describe(row) if row else rel)

    for sec in inputs.values():
        if not isinstance(sec, dict):
            continue
        for raw in ([sec["path"]] if sec.get("path") else []) + list(sec.get("paths") or []):
            p = Path(os.path.expandvars(str(raw)))
            if p.name in MODULE_OUTPUTS:
                add(MODULE_OUTPUTS[p.name])
            elif p.parent.name == "00_inputs" and p.name in CLIPPED_FROM:
                from_data(data_dir / CLIPPED_FROM[p.name])
            elif p.parent.name == "inputs" and p.parent.parent.name == "01_dem" and (p.parent / "manifest.csv").is_file():
                with open(p.parent / "manifest.csv", encoding="utf8", newline="") as fh:
                    rows = [r for r in csv.DictReader(fh) if r.get("file") == p.name]
                for r in rows:
                    for s in (r.get("sources") or "").split(";"):
                        if s.strip():
                            from_data(data_dir / s.strip())
                            break
            elif p.name.startswith("ndmi_"):
                add("Sentinel-2 L2A NDMI musim kemarau, Microsoft Planetary Computer")
            else:
                from_data(p)
    return out
