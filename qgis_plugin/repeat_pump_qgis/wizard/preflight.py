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
    river_source: bool = False      # the rivers layer has dry_season_wl_m or perennial, so stage 9 can use it as a water source
    subkhg_id_field: str = ""
    columns_missing: dict[str, list[tuple[str, bool]]] = field(default_factory=dict)   # role -> [(expected column, required)] to map

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]


REQUIRED = {"dtm", "moisture", "subkhg", "canals", "burn_area", "peat_depth"}     # checked for features and coverage when chosen

# Column names a delivery often uses for an expected column. The form preselects the first one present; the person can change it.
# (The engine accepts only the names in COLUMNS on its own, so these become an explicit mapping in the run config.)
GUESSES: dict[str, dict[str, tuple[str, ...]]] = {
    "canals": {"canal_class": ("ket_kanal", "kode_kanal", "kelas", "kelas_kanal", "jenis", "class", "type")},
    "sekat_existing": {"sekat_id": ("objectid_1", "objectid", "id", "kodefikasi", "kode")},
    "subkhg": {"subkhg_id": ("id", "kode", "name")},
    "burn_area": {"burn_freq": ("burnfreq", "frekuensi", "freq")},
    "peat_depth": {"peat_thick": ("ketebalan", "kedalaman", "thickness", "depth")},
}


def guess_column(role: str, canonical: str, fields: list[str]) -> str:
    """A likely field for ``canonical`` among ``fields`` by its name, or ""."""
    by_norm = {norm(f): f for f in fields}
    return next((by_norm[g] for g in GUESSES.get(role, {}).get(canonical, ()) if g in by_norm), "")


def guess_canal_class(value) -> str:
    """primer | sekunder | tersier for a canal class value such as "Kanal Primer", "primary" or the KODE_KANAL codes 1/2/3, else ""."""
    v = str(value).strip().lower()
    words = set(re.split(r"[^a-z0-9]+", v))
    for cls, keys in (("primer", ("primer", "primary", "induk", "utama")), ("sekunder", ("sekunder", "secondary")),
                      ("tersier", ("tersier", "tertiary"))):
        if words & set(keys):
            return cls
    return {"1": "primer", "2": "sekunder", "3": "tersier"}.get(v.removesuffix(".0"), "")

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
    "subkhg_indicators": {"subkhg_id": (True, ("unit_id",))},
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


def _touches(a: tuple, b: tuple) -> bool:
    """Extents meet, edges included: a single straight canal has a flat extent (no area) and still lies inside."""
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


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
    out.river_source = bool(rv is not None and (find_field("rivers", "dry_season_wl_m", rv.fields, columns.get("rivers"))
                                                or find_field("rivers", "perennial", rv.fields, columns.get("rivers"))))
    if rv is not None and rv.fields and not (find_field("rivers", "dry_season_wl_m", rv.fields, columns.get("rivers"))
                                             or find_field("rivers", "perennial", rv.fields, columns.get("rivers"))):
        add("warning", "rivers", tr("{name} has no perennial or dry_season_wl_m column, so no river can be a pump water source. "
                                    "Add one, or plan sekat only (switch off Plan pumps on the stage 8 card).").format(name=rv.name))
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
            if not _touches(sk.extent, info.extent):
                add("error", role, tr("{name} does not overlap the sub-KHGs. Check its coordinate system.").format(name=info.name))
                continue
            if _area(info.extent) <= 0:
                continue                         # flat extent (one straight line): an area share says nothing
            share = _overlap(sk.extent, info.extent) / total
            if share < 0.9 and role in REQUIRED:
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


def value_counts(layer, field_name: str, limit: int = 40) -> list[tuple[str, int]]:
    """The most frequent values of a field and how often each occurs (reads only that attribute)."""
    if layer is None or not field_name or layer.fields().indexOf(field_name) < 0:
        return []
    from qgis.core import QgsFeatureRequest
    req = QgsFeatureRequest().setFlags(QgsFeatureRequest.Flag.NoGeometry).setSubsetOfAttributes([field_name], layer.fields())
    counts: dict[str, int] = {}
    for f in layer.getFeatures(req):
        v = f[field_name]
        if v is not None and str(v).strip() and str(v) != "NULL":
            counts[str(v)] = counts.get(str(v), 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:limit]


def subkhg_ids(layer, field_name: str, selected_only: bool = False) -> list[str]:
    """The sub-KHG ids of a layer (or of the features selected on the map), as the engine sees them: strings."""
    if layer is None or not field_name:
        return []
    feats = layer.selectedFeatures() if selected_only else layer.getFeatures()
    return sorted({str(f[field_name]) for f in feats if f[field_name] is not None})
