"""Early checks on the layers chosen in the run setup, done with what QGIS already knows about them.

The engine stays the authority: it validates everything again in stage 1. These checks only warn before *Create run*, so a
trainee sees "this layer uses another coordinate system" at once instead of after a failed stage.

``assess`` is pure (``LayerInfo`` in, findings out) and is tested without QGIS; ``collect`` reads the QGIS layers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .i18n import tr

LEVELS = ("error", "warning", "info")


@dataclass
class LayerInfo:
    role: str                       # config key: dtm, subkhg, canals, ...
    name: str                       # what the person sees in the layer list
    crs: str = ""                   # authid, e.g. EPSG:32749
    geographic: bool = False        # degrees instead of metres
    fields: list[str] = field(default_factory=list)
    extent: Optional[tuple] = None  # xmin, ymin, xmax, ymax in the layer's own CRS
    features: Optional[int] = None  # None for rasters
    is_file: bool = True            # False for temporary (memory) layers
    vertical_crs: str = ""          # DTM only: vertical datum named by the layer, if it has one


@dataclass
class Finding:
    level: str
    role: str
    text: str


@dataclass
class Assessment:
    findings: list[Finding] = field(default_factory=list)
    crs: str = ""                   # run CRS taken from the DTM
    needs_reproject: bool = False   # some layer is in another CRS
    vertical_datum: str = ""        # from the DTM's metadata, empty when it has none
    river_levels: bool = False      # the rivers layer has a dry_season_wl_m field
    subkhg_id_field: str = ""
    columns_missing: dict[str, list[tuple[str, bool]]] = field(default_factory=dict)   # role -> [(expected column, required)] to map

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]


REQUIRED = {"dtm", "moisture", "subkhg", "canals", "burn_area", "peat_depth"}

# Columns the engine looks for, per input: expected name -> (required, other names it accepts by itself). The engine ignores case,
# spaces and punctuation in names (BURN_FREQ is burn_freq). tests/test_wizard_setup.py keeps this equal to the engine's CANONICAL_COLUMNS.
COLUMNS: dict[str, dict[str, tuple[bool, tuple[str, ...]]]] = {
    "subkhg": {"subkhg_id": (True, ("unit_id",))},
    "subkhg_priority": {"subkhg_id": (True, ("unit_id",)), "priority_rank": (False, ()), "deficit_mm": (False, ()), "design_period_days": (False, ())},
    "canals": {"canal_class": (True, ()), "depth_m": (False, ()), "width_m": (False, ())},
    "sekat_existing": {"sekat_id": (True, ()), "has_gate": (False, ()), "crest_elev_m": (False, ())},
    "rivers": {"dry_season_wl_m": (False, ()), "perennial": (False, ())},
    "burn_area": {"burn_freq": (True, ("burn_frequency",))},
    "peat_depth": {"peat_thick": (True, ("peat_depth", "peat_class"))},
}
STRICT_ROLES = {"subkhg", "canals"}      # reported even when QGIS lists no fields at all; the others are only checked when fields are known


def norm(name: str) -> str:
    """The engine's rule for column names (config.snake_name): lower case, letters and digits only."""
    n = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")[:30] or "col"
    return "f_" + n if not n[0].isalpha() else n


def find_field(role: str, canonical: str, fields: list[str], mapping: Optional[dict[str, str]] = None) -> str:
    """The actual field of ``fields`` that serves as ``canonical`` for ``role`` ("" when none): the user's mapping first, then the
    expected name or one of the names the engine accepts on its own."""
    by_norm = {norm(f): f for f in fields}
    if mapping and mapping.get(canonical):
        return by_norm.get(norm(mapping[canonical]), "")
    for cand in (canonical, *COLUMNS.get(role, {}).get(canonical, (False, ()))[1]):
        if norm(cand) in by_norm:
            return by_norm[norm(cand)]
    return ""


def missing_columns(role: str, fields: list[str], mapping: Optional[dict[str, str]] = None) -> list[tuple[str, bool]]:
    """``[(expected column, required)]`` that cannot be found among ``fields`` even with ``mapping``."""
    return [(c, req) for c, (req, _a) in COLUMNS.get(role, {}).items() if not find_field(role, c, fields, mapping)]


def _area(e: tuple) -> float:
    return max(e[2] - e[0], 0.0) * max(e[3] - e[1], 0.0)


def _overlap(a: tuple, b: tuple) -> float:
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def assess(layers: dict[str, Optional[LayerInfo]], reproject: bool = False, columns: Optional[dict[str, dict[str, str]]] = None) -> Assessment:
    """Findings for the chosen layers (``None`` = nothing chosen for that role). A layer in another CRS is an error unless
    ``reproject`` (the engine's auto_reproject) is on, in which case it is only noted. ``columns`` is the user's column mapping,
    ``{role: {expected column: field}}``."""
    columns = columns or {}
    out = Assessment()
    add = lambda level, role, text: out.findings.append(Finding(level, role, text))
    dtm = layers.get("dtm")
    if dtm is not None:
        out.crs = dtm.crs
        out.vertical_datum = dtm.vertical_crs
        if dtm.geographic or not dtm.crs:
            add("error", "dtm", tr("The DTM must be in a projected coordinate system (metres), not degrees. Reproject it in QGIS first."))
    for role, info in layers.items():
        if info is None:
            continue
        if not info.is_file:
            add("error", role, tr("{name}: the layer must be saved to a file (temporary layers cannot be passed to the engine).").format(name=info.name))
        if info.features == 0 and role in REQUIRED:
            add("error", role, tr("{name} has no features.").format(name=info.name))
        if role != "dtm" and out.crs and info.crs and info.crs != out.crs:
            out.needs_reproject = True
            if reproject:
                add("info", role, tr("{name} uses {crs} and will be reprojected to {dtm}.").format(name=info.name, crs=info.crs, dtm=out.crs))
            else:
                add("error", role, tr("{name} uses {crs}, the DTM uses {dtm}. Tick the reproject option below, or reproject it in QGIS.").format(
                    name=info.name, crs=info.crs, dtm=out.crs))
    sk = layers.get("subkhg")
    if sk is not None:
        out.subkhg_id_field = find_field("subkhg", "subkhg_id", sk.fields, columns.get("subkhg"))
    for role, info in layers.items():
        if info is None or role not in COLUMNS or (not info.fields and role not in STRICT_ROLES):
            continue
        miss = missing_columns(role, info.fields, columns.get(role))
        if miss:
            out.columns_missing[role] = miss
        for col, required in miss:
            if not required:
                continue
            if role == "subkhg":
                add("error", role, tr("{name} needs a unique id column named subkhg_id (or unit_id). Choose which column holds it under Column names below.").format(name=info.name))
            elif role == "canals":
                add("error", role, tr("{name} needs a canal_class column (primer, sekunder or tersier). Choose which column holds it under Column names below.").format(name=info.name))
            else:
                add("error", role, tr("{name} needs a column for {col}. Choose which column holds it under Column names below.").format(name=info.name, col=col))
    rv = layers.get("rivers")
    if rv is not None and find_field("rivers", "dry_season_wl_m", rv.fields, columns.get("rivers")):
        out.river_levels = True
        add("info", "rivers", tr("The rivers have dry-season water levels, so a vertical datum is needed (set it in stage 1)."))
    # coverage: compare extents in the same CRS only (a different CRS is already flagged; the engine checks exact geometry)
    if sk is not None and sk.extent is not None:
        for role, info in layers.items():
            if role == "subkhg" or info is None or info.extent is None or info.crs != sk.crs or role in ("sekat_existing", "tma_obs", "canal_edits"):
                continue
            total = _area(sk.extent)
            if total <= 0:
                continue
            share = _overlap(sk.extent, info.extent) / total
            if share == 0:
                add("error", role, tr("{name} does not overlap the sub-KHGs. Check its coordinate system.").format(name=info.name))
            elif share < 0.9 and role in REQUIRED:
                add("warning", role, tr("{name} covers only about {pct} % of the sub-KHG area.").format(name=info.name, pct=int(share * 100)))
    return out


# ----------------------------------------------------------------------------- QGIS side
def info_from_layer(role: str, layer) -> Optional[LayerInfo]:
    """Read what the preflight needs from a QGIS layer (vector or raster); None when no layer is chosen."""
    if layer is None:
        return None
    crs = layer.crs()
    ext = layer.extent()
    is_vector = hasattr(layer, "fields")
    vertical = ""
    if role == "dtm":
        try:
            vc = crs.verticalCrs() if hasattr(crs, "verticalCrs") else None       # not in every QGIS 3 build; many GeoTIFFs have none
            if vc is not None and vc.isValid():
                vertical = vc.authid() or vc.description()
        except Exception:
            vertical = ""
    return LayerInfo(role=role, name=layer.name(), crs=crs.authid() if crs.isValid() else "", geographic=bool(crs.isValid() and crs.isGeographic()),
                     fields=[f.name() for f in layer.fields()] if is_vector else [],
                     extent=None if ext.isNull() else (ext.xMinimum(), ext.yMinimum(), ext.xMaximum(), ext.yMaximum()),
                     features=int(layer.featureCount()) if is_vector else None,
                     is_file=bool(layer.source()) and layer.providerType() not in ("memory", "virtual"),
                     vertical_crs=vertical)


def subkhg_ids(layer, field_name: str, selected_only: bool = False) -> list[str]:
    """The sub-KHG ids of a layer (or of the features selected on the map), as the engine sees them: strings."""
    if layer is None or not field_name:
        return []
    feats = layer.selectedFeatures() if selected_only else layer.getFeatures()
    return sorted({str(f[field_name]) for f in feats if f[field_name] is not None})
