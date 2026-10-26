"""Load stage outputs from the run GeoPackage (and the two rasters) into the project with a consistent look.

Design rules (qgis-cartography): one question per stage, the thematic layer on top and the reference layers quiet, sequential
colour for ordered magnitudes, a neutral grey for "not scored" instead of the lowest class, rasters under vectors.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from qgis.core import (QgsFillSymbol, QgsLineSymbol, QgsMarkerSymbol, QgsPalLayerSettings, QgsProject, QgsProperty, QgsRasterLayer,
                       QgsRuleBasedRenderer, QgsSingleSymbolRenderer, QgsTextBufferSettings, QgsTextFormat, QgsVectorLayer,
                       QgsVectorLayerSimpleLabeling)
from qgis.PyQt.QtGui import QColor, QFont

TEAL, AMBER, AMBER_DARK, INK, WATER = "#2B6B6B", "#E0922F", "#7A4300", "#17261F", "#3F9DAA"

# need score 0..1 in five equal steps (the score is already on a 0..1 scale), light to dark orange-red (ColorBrewer OrRd)
NEED_CLASSES = [(0.0, 0.2, "#fdd49e", "0.0 to 0.2 (lowest need)"), (0.2, 0.4, "#fdbb84", "0.2 to 0.4"), (0.4, 0.6, "#fc8d59", "0.4 to 0.6"),
                (0.6, 0.8, "#e34a33", "0.6 to 0.8"), (0.8, 1.0001, "#b30000", "0.8 to 1.0 (highest need)")]
NOT_SCORED = "#B8BEBB"

# layer -> ("line"|"point", symbol properties); names are the engine's output contract
LOOK: dict[str, tuple[str, dict]] = {
    "canals_clean": ("line", {"color": TEAL, "width": "0.5"}),
    "canal_profiles": ("point", {"name": "circle", "color": "#8D7B5E", "outline_style": "no", "size": "1.2"}),
    "network_edges": ("line", {"color": "#8A948F", "width": "0.3"}),
    "network_nodes": ("point", {"name": "circle", "color": "#8A948F", "outline_style": "no", "size": "1.6"}),
    "qa_topology_dangles": ("point", {"name": "circle", "color": "#F2A93B", "outline_color": AMBER_DARK, "outline_width": "0.4", "size": "3.2"}),
    "qa_topology_gaps": ("point", {"name": "diamond", "color": "#D8574A", "outline_color": "#6B1F18", "outline_width": "0.3", "size": "3"}),
    "sekat_existing_assessed": ("point", {"name": "square", "color": INK, "outline_color": "#FFFFFF", "outline_width": "0.3", "size": "3.2"}),
    "pump_routes": ("line", {"color": "#1F6FB5", "width": "0.9"}),
    "pump_sources": ("point", {"name": "circle", "color": WATER, "outline_color": "#0F2B26", "outline_width": "0.4", "size": "3.6"}),
    "pump_targets": ("point", {"name": "star", "color": "#2E9E7B", "outline_color": "#0F2B26", "outline_width": "0.3", "size": "4"}),
    "gates_required": ("point", {"name": "diamond", "color": "#7D4FB5", "outline_color": "#FFFFFF", "outline_width": "0.3", "size": "3.4"}),
    "qa_unreachable_targets": ("point", {"name": "cross2", "color": "#C0392B", "outline_color": "#C0392B", "outline_width": "0.8", "size": "4"}),
}


def _symbol(kind: str, props: dict):
    return (QgsLineSymbol if kind == "line" else QgsMarkerSymbol).createSimple(props)


def _rules(layer: QgsVectorLayer, rules: list[tuple]) -> None:
    """Rule-based renderer from ``(symbol, filter expression, label)``; the last rule may use ``"ELSE"``."""
    root = QgsRuleBasedRenderer.Rule(None)
    for symbol, expr, label in rules:
        root.appendChild(QgsRuleBasedRenderer.Rule(symbol, 0, 0, expr, label))
    layer.setRenderer(QgsRuleBasedRenderer(root))


def _has(layer: QgsVectorLayer, field: str) -> bool:
    return layer.fields().indexOf(field) >= 0


def _label(layer: QgsVectorLayer, expression: str, size: float = 8.0, color: str = INK) -> None:
    fmt = QgsTextFormat()
    fmt.setFont(QFont("Segoe UI"))
    fmt.setSize(size)
    fmt.setColor(QColor(color))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(1.0)
    buf.setColor(QColor("#FFFFFF"))
    fmt.setBuffer(buf)
    pal = QgsPalLayerSettings()
    pal.setFormat(fmt)
    pal.fieldName = expression
    pal.isExpression = True
    layer.setLabeling(QgsVectorLayerSimpleLabeling(pal))
    layer.setLabelsEnabled(True)


def _style_need_score(layer: QgsVectorLayer) -> None:
    """Colour by need score, grey for segments that were not scored; selected targets are drawn thicker."""
    width = QgsProperty.fromExpression('CASE WHEN "selected" IS TRUE THEN 1.8 ELSE 0.7 END')
    rules = []
    for lo, hi, colour, text in NEED_CLASSES:
        sym = _symbol("line", {"color": colour, "width": "0.7", "capstyle": "round"})
        sym.setDataDefinedWidth(width)
        rules.append((sym, f'"need_score" >= {lo} AND "need_score" < {hi}', text))
    grey = _symbol("line", {"color": NOT_SCORED, "width": "0.4"})
    rules.append((grey, "ELSE", "Not scored"))
    _rules(layer, rules)


def style_layer(layer: QgsVectorLayer) -> None:
    name = layer.name()
    if name == "sekat_optimised":                     # the chosen layout stands out, the other candidates are quiet
        _rules(layer, [(_symbol("point", {"name": "square", "color": "#2E9E7B", "outline_color": "#0F2B26", "outline_width": "0.4", "size": "4.2"}),
                        '"selected_best" IS TRUE', "Chosen layout"),
                       (_symbol("point", {"name": "square", "color": "#C9C3B3", "outline_color": "#8A948F", "outline_width": "0.3", "size": "2.6"}),
                        "ELSE", "Other candidates")])
    elif name == "sekat_proposed":                    # reinforced blocks differ from standard ones
        std = {"name": "square", "color": AMBER, "outline_color": AMBER_DARK, "outline_width": "0.4", "size": "3.2"}
        if _has(layer, "sekat_type"):
            _rules(layer, [(_symbol("point", std), '"sekat_type" = \'standard\'', "Proposed sekat, standard"),
                           (_symbol("point", {**std, "name": "diamond", "color": "#C0661A", "size": "3.8"}), "ELSE", "Proposed sekat, leaky or reinforced")])
        else:
            layer.setRenderer(QgsSingleSymbolRenderer(_symbol("point", std)))
    elif name == "sekat_scope":                       # in the plan by where it sits; the rest is greyed out (rules must not overlap: each match is drawn)
        base = {"name": "square", "outline_color": "#FFFFFF", "outline_width": "0.3", "size": "3.2"}
        _rules(layer, [(_symbol("point", {**base, "color": "#2E9E7B"}), '"planned" AND "scope" = \'target\'', "Sekat on selected canals"),
                       (_symbol("point", {**base, "color": "#7D4FB5"}), '"planned" AND "scope" = \'route\'', "Sekat on pump routes (gates)"),
                       (_symbol("point", {**base, "color": AMBER}), '"planned" AND "scope" = \'other\'', "Other sekat in the plan"),
                       (_symbol("point", {**base, "color": "#C9C3B3", "size": "2.4"}), "ELSE", "Not in the plan")])
    elif name == "pump_stations":                     # symbol area follows the power
        sym = _symbol("point", {"name": "triangle", "color": "#C0392B", "outline_color": "#FFFFFF", "outline_width": "0.3", "size": "4.4"})
        if _has(layer, "p_kw") and layer.featureCount():
            top = max((f["p_kw"] or 0) for f in layer.getFeatures()) or 1.0
            sym.setDataDefinedSize(QgsProperty.fromExpression(f'3.5 + 4.5 * sqrt(coalesce("p_kw", 0) / {top})'))
        layer.setRenderer(QgsSingleSymbolRenderer(sym))
        if _has(layer, "station_id"):
            _label(layer, '"station_id"', 8.5, "#7A1D14")
    elif name == "canal_segments":
        if _has(layer, "need_score"):
            _style_need_score(layer)
        else:
            layer.setRenderer(QgsSingleSymbolRenderer(_symbol("line", {"color": TEAL, "width": "0.6"})))
    elif name == "canals_clean":
        layer.setRenderer(QgsSingleSymbolRenderer(_symbol("line", {"color": TEAL, "width": "0.5"})))
        if _has(layer, "ipg"):                        # the gap-analysis result, readable on the map (IPG above 1 means enough sekat)
            _label(layer, 'CASE WHEN "ipg" IS NULL THEN \'\' ELSE \'IPG \' || format_number("ipg", 1) END', 8.0, TEAL)
    elif name in LOOK:
        kind, props = LOOK[name]
        layer.setRenderer(QgsSingleSymbolRenderer(_symbol(kind, props)))
    else:
        return
    layer.triggerRepaint()


# ----------------------------------------------------------------------------- rasters
RASTER_NAMES = {"dtm_conditioned": "dtm_conditioned", "flow_acc": "flow_acc"}


def style_raster(layer: QgsRasterLayer) -> None:
    """Quiet, translucent surfaces under the vectors: heights in greys, flow accumulation in blues clipped at the 98th percentile."""
    from qgis.core import QgsColorRampShader, QgsRasterShader, QgsSingleBandPseudoColorRenderer
    prov = layer.dataProvider()
    lo, hi = prov.cumulativeCut(1, 0.02, 0.98, layer.extent(), 250000)
    if not hi > lo:
        return
    stops = ["#F4F1EA", "#CFCABC", "#9A9684", "#5E5C50"] if layer.name() == "dtm_conditioned" else ["#EAF3F5", "#B9D9E0", "#6BB0C0", "#2B6B8F"]
    shader = QgsColorRampShader(lo, hi)
    shader.setColorRampItemList([QgsColorRampShader.ColorRampItem(lo + (hi - lo) * i / (len(stops) - 1), QColor(c)) for i, c in enumerate(stops)])
    ramp = QgsRasterShader()
    ramp.setRasterShaderFunction(shader)
    layer.setRenderer(QgsSingleBandPseudoColorRenderer(prov, 1, ramp))
    layer.renderer().setOpacity(0.75)
    layer.triggerRepaint()


# ----------------------------------------------------------------------------- layer tree
def _group(run_name: str, create: bool = True):
    root = QgsProject.instance().layerTreeRoot()
    name = f"RE-PEAT {run_name}"
    return root.findGroup(name) or (root.addGroup(name) if create else None)


# Draw order, bottom to top. Later stages add their layers last, so loading order alone would bury a route under the canals.
DRAW_ORDER = ["dtm_conditioned", "flow_acc", "canals_clean", "network_edges", "canal_segments", "pump_routes", "canal_profiles", "network_nodes",
              "qa_topology_gaps", "sekat_existing_assessed", "sekat_proposed", "sekat_scope", "sekat_optimised", "pump_sources", "pump_targets", "gates_required",
              "pump_stations", "qa_topology_dangles", "qa_unreachable_targets"]


def _rank(layer) -> int:
    """Draw rank, higher is drawn higher up: the fixed order above, else rasters, polygons, lines, points."""
    if layer.name() in DRAW_ORDER:
        return DRAW_ORDER.index(layer.name())
    if isinstance(layer, QgsRasterLayer):
        return -3
    try:
        from qgis.core import Qgis
        g = layer.geometryType()
        g = getattr(g, "value", g)
        return 100 + {2: 1, 1: 2, 0: 3}.get(int(g), 2)         # layers not in the fixed order sit above it
    except Exception:
        return 102


def reorder_group(group) -> None:
    """Rasters at the bottom, then polygons, lines and points, so points are never hidden under lines or surfaces."""
    nodes = [n for n in group.findLayers() if n.layer() is not None]
    order = sorted(nodes, key=lambda n: -_rank(n.layer()))              # top of the group first
    for position, node in enumerate(order):
        if group.children().index(node) != position:
            group.insertChildNode(position, node.clone())
            group.removeChildNode(node)


def remove_layers(run_name: str, names: list[str]) -> None:
    """Take outputs of stages that are about to be invalidated off the map (so stale results are not mistaken for current ones)."""
    project = QgsProject.instance()
    group = _group(run_name, create=False)
    if group is None:
        return
    for node in list(group.findLayers()):
        if node.layer() is not None and node.layer().name() in names:
            project.removeMapLayer(node.layer().id())


def remove_run_group(run_name: str) -> None:
    """Remove the run's whole group and layers (before its files are deleted: Windows will not delete an open GeoPackage)."""
    project = QgsProject.instance()
    group = _group(run_name, create=False)
    if group is None:
        return
    for node in list(group.findLayers()):
        if node.layer() is not None:
            project.removeMapLayer(node.layer().id())
    group.parent().removeChildNode(group)


def load_layers(gpkg: Path, names: list[str], run_name: str) -> list[str]:
    """Add ``names`` from the GeoPackage into a group for this run, replacing earlier copies. Returns the names loaded."""
    if not Path(gpkg).exists():
        return []
    project = QgsProject.instance()
    group = _group(run_name)
    loaded = []
    for name in names:
        for node in group.findLayers():
            if node.layer() is not None and node.layer().name() == name:
                project.removeMapLayer(node.layer().id())
        layer = QgsVectorLayer(f"{gpkg}|layername={name}", name, "ogr")
        if not layer.isValid():
            continue
        project.addMapLayer(layer, False)
        group.addLayer(layer)
        style_layer(layer)
        loaded.append(name)
    reorder_group(group)
    return loaded


def load_rasters(files: dict, run_name: str, names: Optional[list[str]] = None) -> list[str]:
    """Add the conditioned DTM and the flow accumulation (GeoTIFFs outside the GeoPackage) under the run's vector layers."""
    project = QgsProject.instance()
    group = _group(run_name)
    loaded = []
    for name in names or list(RASTER_NAMES):
        path = files.get(name)
        if not path or not Path(path).exists():
            continue
        for node in group.findLayers():
            if node.layer() is not None and node.layer().name() == name:
                project.removeMapLayer(node.layer().id())
        layer = QgsRasterLayer(str(path), name)
        if not layer.isValid():
            continue
        project.addMapLayer(layer, False)
        group.addLayer(layer)
        style_raster(layer)
        loaded.append(name)
    reorder_group(group)
    return loaded
