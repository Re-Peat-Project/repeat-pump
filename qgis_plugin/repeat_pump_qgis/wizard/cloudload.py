"""Pure-Python side of "Load moisture from the cloud": check the dialog's values, build the ``repeat-pump fetch-moisture``
command line, read the provenance file the engine writes next to the raster. No Qt and no ``repeat_pump`` import."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Optional

from .i18n import tr

SOURCES = [("stac", "Open Sentinel-2 (no login)"), ("ee", "Google Earth Engine (exact CPWI v2)")]
DEFAULT_MAX_CLOUD = 80          # the legacy script's pre-filter, shown in the form and editable
DEFAULT_MARGIN_M = 1000         # download buffer around the chosen sub-KHGs, larger than the usual stage 1 clip margin
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(text: str, what: str) -> date:
    text = text.strip()
    if not _DATE.match(text):
        raise ValueError(tr("{what}: write the date as YYYY-MM-DD.").format(what=what))
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(tr("{what}: {text} is not a real date.").format(what=what, text=text))


def check_windows(p_start: str, p_end: str, f_start: str, f_end: str) -> tuple[tuple[str, str], tuple[str, str]]:
    """Both windows as ISO strings. The fallback window must contain the primary one."""
    ps, pe = parse_date(p_start, tr("Primary window start")), parse_date(p_end, tr("Primary window end"))
    fs, fe = parse_date(f_start, tr("Fallback window start")), parse_date(f_end, tr("Fallback window end"))
    if pe < ps or fe < fs:
        raise ValueError(tr("A window ends before it starts."))
    if fs > ps or fe < pe:
        raise ValueError(tr("The fallback window must contain the primary window."))
    return (ps.isoformat(), pe.isoformat()), (fs.isoformat(), fe.isoformat())


def with_margin(bounds: tuple[float, float, float, float], margin_m: float) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bounds
    return (x0 - margin_m, y0 - margin_m, x1 + margin_m, y1 + margin_m)


def fetch_args(source: str, bounds, crs: str, out: str, primary, fallback, max_cloud: Optional[float] = None,
               ee_project: str = "", memory_gb: Optional[float] = None) -> list[str]:
    """Arguments after ``-m repeat_pump.cli`` for the engine command."""
    if source not in dict(SOURCES):
        raise ValueError(f"unknown source {source!r}")
    if source == "ee" and not ee_project.strip():
        raise ValueError(tr("Enter your Earth Engine project id."))
    args = ["fetch-moisture", "--source", source, "--bounds", *[f"{v:.3f}" for v in bounds], "--crs", crs, "--out", out,
            "--primary", *primary, "--fallback", *fallback]
    if max_cloud is not None and source == "stac":
        args += ["--max-cloud", f"{max_cloud:g}"]
    if source == "ee":
        args += ["--ee-project", ee_project.strip()]
    if memory_gb:
        args += ["--memory-gb", f"{memory_gb:g}"]
    return args


def sidecar_path(raster_path: str) -> Path:
    return Path(str(raster_path) + ".provenance.json")


def read_provenance(raster_path: str) -> Optional[dict]:
    """The provenance the engine wrote next to a downloaded raster, or ``None`` for any other raster."""
    try:
        return json.loads(sidecar_path(raster_path).read_text(encoding="utf8"))
    except (OSError, ValueError):
        return None


def summary(prov: dict) -> str:
    """One short paragraph for the dialog and the layer's tooltip."""
    s = tr("{product}. Scenes: {n}. Valid pixels: {pct}.").format(product=prov.get("product", ""), n=prov.get("scenes_total", "n/a"),
                                                                 pct=f"{float(prov.get('valid_fraction', 0)):.0%}")
    return s
