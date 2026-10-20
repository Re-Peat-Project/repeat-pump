"""Load stage outputs from the run GeoPackage into the project with a consistent look."""
from __future__ import annotations

from pathlib import Path

from qgis.core import (QgsLineSymbol, QgsMarkerSymbol, QgsProject, QgsRuleBasedRenderer, QgsSingleSymbolRenderer, QgsVectorLayer)

TEAL, AMBER, AMBER_DARK, INK, WATER = "#2B6B6B", "#E0922F", "#7A4300", "#17261F", "#3F9DAA"

# layer -> ("line"|"point", symbol properties); order matters little, names are the engine's output contract
LOOK: dict[str, tuple[str, dict]] = {
    "canals_clean": ("line", {"color": TEAL, "width": "0.5"}),
    "canal_profiles": ("point", {"name": "circle", "color": "#8D7B5E", "outline_style": "no", "size": "1.2"}),
    "network_edges": ("line", {"color": "#8A948F", "width": "0.3"}),
    "network_nodes": ("point", {"name": "circle", "color": "#8A948F", "outline_style": "no", "size": "1.6"}),
    "qa_topology_dangles": ("point", {"name": "circle", "color": "#F2A93B", "outline_color": AMBER_DARK, "outline_width": "0.4", "size": "3.2"}),
    "qa_topology_gaps": ("point", {"name": "diamond", "color": "#D8574A", "outline_color": "#6B1F18", "outline_width": "0.3", "size": "3"}),
    "sekat_existing_assessed": ("point", {"name": "square", "color": INK, "outline_color": "#FFFFFF", "outline_width": "0.3", "size": "3.2"}),
    "sekat_proposed": ("point", {"name": "square", "color": AMBER, "outline_color": AMBER_DARK, "outline_width": "0.4", "size": "3.2"}),
    "pump_routes": ("line", {"color": "#1F6FB5", "width": "0.9"}),
    "pump_sources": ("point", {"name": "circle", "color": WATER, "outline_color": "#0F2B26", "outline_width": "0.4", "size": "3.6"}),
    "pump_targets": ("point", {"name": "star", "color": "#2E9E7B", "outline_color": "#0F2B26", "outline_width": "0.3", "size": "4"}),
    "pump_stations": ("point", {"name": "triangle", "color": "#C0392B", "outline_color": "#FFFFFF", "outline_width": "0.3", "size": "4.4"}),
    "gates_required": ("point", {"name": "diamond", "color": "#7D4FB5", "outline_color": "#FFFFFF", "outline_width": "0.3", "size": "3.4"}),
    "qa_unreachable_targets": ("point", {"name": "cross2", "color": "#C0392B", "outline_color": "#C0392B", "outline_width": "0.8", "size": "4"}),
}


def _symbol(kind: str, props: dict):
    return (QgsLineSymbol if kind == "line" else QgsMarkerSymbol).createSimple(props)


def style_layer(layer: QgsVectorLayer) -> None:
    name = layer.name()
    if name == "canal_segments":                      # selected targets stand out, the rest is quiet
        root = QgsRuleBasedRenderer.Rule(None)
        root.appendChild(QgsRuleBasedRenderer.Rule(_symbol("line", {"color": "#D8574A", "width": "1.2"}), 0, 0, '"selected" IS TRUE', "Selected target"))
        root.appendChild(QgsRuleBasedRenderer.Rule(_symbol("line", {"color": TEAL, "width": "0.5"}), 0, 0, "ELSE", "Other segments"))
        layer.setRenderer(QgsRuleBasedRenderer(root))
    elif name in LOOK:
        kind, props = LOOK[name]
        layer.setRenderer(QgsSingleSymbolRenderer(_symbol(kind, props)))
    else:
        return
    layer.triggerRepaint()


def load_layers(gpkg: Path, names: list[str], run_name: str) -> list[str]:
    """Add ``names`` from the GeoPackage into a group for this run, replacing earlier copies. Returns the names loaded."""
    if not Path(gpkg).exists():
        return []
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.findGroup(f"RE-PEAT {run_name}") or root.addGroup(f"RE-PEAT {run_name}")
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
    return loaded
