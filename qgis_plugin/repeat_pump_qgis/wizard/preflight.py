"""Early checks on the layers chosen in the run setup, done with what QGIS already knows about them.

The engine stays the authority: it validates everything again in stage 1. These checks only warn before *Create run*, so a
trainee sees "this layer uses another coordinate system" at once instead of after a failed stage.

``assess`` is pure (``LayerInfo`` in, findings out) and is tested without QGIS; ``collect`` reads the QGIS layers.
"""
from __future__ import annotations

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

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]


REQUIRED = {"dtm", "moisture", "subkhg", "canals", "burn_area", "peat_depth"}


def _area(e: tuple) -> float:
    return max(e[2] - e[0], 0.0) * max(e[3] - e[1], 0.0)


def _overlap(a: tuple, b: tuple) -> float:
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def assess(layers: dict[str, Optional[LayerInfo]], reproject: bool = False) -> Assessment:
    """Findings for the chosen layers (``None`` = nothing chosen for that role). A layer in another CRS is an error unless
    ``reproject`` (the engine's auto_reproject) is on, in which case it is only noted."""
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
        out.subkhg_id_field = next((f for f in ("subkhg_id", "unit_id") if f in sk.fields), "")
        if not out.subkhg_id_field:
            add("error", "subkhg", tr("{name} needs a unique id column named subkhg_id (or unit_id).").format(name=sk.name))
    cn = layers.get("canals")
    if cn is not None and "canal_class" not in cn.fields:
        add("error", "canals", tr("{name} needs a canal_class column (primer, sekunder or tersier).").format(name=cn.name))
    rv = layers.get("rivers")
    if rv is not None and "dry_season_wl_m" in rv.fields:
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
