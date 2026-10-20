"""Map handling for the wizard: which layers belong on screen for a stage, zooming to them, and exporting a finished map.

``visibility_plan`` is pure (tested in the engine venv). The functions after it touch the QGIS project and do nothing when no
``iface`` is given, so the offscreen smoke tests run without a main window.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from .i18n import tr

# layers worth looking at for each stage: the stage's own result plus the quiet context it is judged against.
# Stages not listed show everything.
STAGE_VISIBLE: dict[int, list[str]] = {
    2: ["canals_clean", "qa_topology_dangles", "qa_topology_gaps"],
    3: ["flow_acc", "canals_clean"],
    4: ["canal_segments"],
    5: ["canal_profiles", "canal_segments"],
    6: ["canal_segments"],
    7: ["canals_clean", "sekat_existing_assessed", "sekat_proposed"],
    8: ["network_edges", "network_nodes"],
    9: ["canal_segments", "pump_sources", "pump_targets", "pump_routes", "qa_unreachable_targets"],
    10: ["canal_segments", "pump_routes", "pump_stations", "gates_required"],
    11: ["canal_segments", "sekat_proposed", "pump_routes", "pump_stations", "gates_required", "pump_sources", "pump_targets"],
    12: ["canal_segments", "sekat_existing_assessed", "sekat_optimised"],
}

# names shown in a map legend (English here, translated when used)
LEGEND_NAMES = {
    "canals_clean": "Canals", "canal_segments": "Canal segments, by need score", "canal_profiles": "Land profile stations",
    "qa_topology_dangles": "Loose canal ends", "qa_topology_gaps": "Gaps snapped", "sekat_existing_assessed": "Existing sekat",
    "sekat_proposed": "Proposed sekat", "sekat_optimised": "Sekat layout from the optimisation", "network_edges": "Canal network",
    "network_nodes": "Network nodes", "pump_sources": "Water sources", "pump_targets": "Targets", "pump_routes": "Pump routes",
    "pump_stations": "Pump stations (size follows power)", "gates_required": "Gates needed", "qa_unreachable_targets": "Unreachable targets",
    "flow_acc": "Flow accumulation", "dtm_conditioned": "Conditioned DTM",
}

# what a stage's map answers, used as the title of an exported map
STAGE_QUESTION = {
    2: "Which canal ends are loose?", 6: "Which canal segments need rewetting most?", 7: "Where should new sekat go?",
    9: "How does pumped water reach the targets?", 10: "Where do the pump stations go?", 11: "The rewetting plan",
}


def visibility_plan(stage: int, present: list[str]) -> dict[str, bool]:
    """``{layer name: visible}`` for the layers of a run that are on the map. Stages without an entry show everything."""
    wanted = STAGE_VISIBLE.get(stage)
    return {n: (wanted is None or n in wanted) for n in present}


def legend_name(layer_name: str) -> str:
    return tr(LEGEND_NAMES.get(layer_name, layer_name))


# ----------------------------------------------------------------------------- project actions
def _group(run_name: str):
    from qgis.core import QgsProject
    return QgsProject.instance().layerTreeRoot().findGroup(f"RE-PEAT {run_name}")


def show_stage(run_name: str, stage: int) -> list[str]:
    """Tick the layers that belong to ``stage`` and untick the rest of the run's layers. Returns the names now visible."""
    group = _group(run_name)
    if group is None:
        return []
    nodes = [n for n in group.findLayers() if n.layer() is not None]
    plan = visibility_plan(stage, [n.layer().name() for n in nodes])
    for n in nodes:
        n.setItemVisibilityChecked(plan[n.layer().name()])
    return [name for name, on in plan.items() if on]


def show_all(run_name: str) -> None:
    group = _group(run_name)
    if group is not None:
        for n in group.findLayers():
            n.setItemVisibilityChecked(True)


def visible_layers(run_name: str) -> list:
    """The run's layers that are ticked on, top of the drawing order first."""
    group = _group(run_name)
    return [n.layer() for n in group.findLayers() if n.layer() is not None and n.isVisible()] if group is not None else []


def results_extent(layers: list, dest_crs):
    """Union of the layers' extents in ``dest_crs`` (layers without features are skipped), or None."""
    from qgis.core import QgsCoordinateTransform, QgsProject, QgsRectangle, QgsVectorLayer
    box: Optional[QgsRectangle] = None
    for lyr in layers:
        if isinstance(lyr, QgsVectorLayer) and lyr.featureCount() == 0:
            continue
        ext = lyr.extent()
        if ext.isEmpty() and ext.width() == 0 and ext.height() == 0 and ext.isNull():
            continue
        if lyr.crs() != dest_crs:
            ext = QgsCoordinateTransform(lyr.crs(), dest_crs, QgsProject.instance()).transformBoundingBox(ext)
        if box is None:
            box = QgsRectangle(ext)
        else:
            box.combineExtentWith(ext)
    if box is not None:
        box.scale(1.1)         # a little context around the results
    return box


def zoom_to_stage(iface, run_name: str, only_names: Optional[list[str]] = None) -> bool:
    """Zoom the canvas to the visible layers of the run (or just ``only_names``). False when there is nothing to zoom to."""
    if iface is None:
        return False
    layers = [l for l in visible_layers(run_name) if only_names is None or l.name() in only_names]
    canvas = iface.mapCanvas()
    box = results_extent(layers, canvas.mapSettings().destinationCrs())
    if box is None or box.isEmpty():
        return False
    canvas.setExtent(box)
    canvas.refresh()
    return True


# ----------------------------------------------------------------------------- export a map
def _mm():
    """Millimetre layout unit on QGIS 3 and 4."""
    try:
        from qgis.core import Qgis
        return Qgis.LayoutUnit.Millimeters
    except AttributeError:
        from qgis.core import QgsUnitTypes
        return QgsUnitTypes.LayoutMillimeters


def _metres():
    try:
        from qgis.core import Qgis
        return Qgis.DistanceUnit.Meters
    except AttributeError:
        from qgis.core import QgsUnitTypes
        return QgsUnitTypes.DistanceMeters


def _legend_fonts(legend) -> None:
    """Use the same typeface as the rest of the map for every legend text (the QGIS default can differ per machine)."""
    from qgis.core import QgsLegendStyle
    from qgis.PyQt.QtGui import QFont
    styles = getattr(QgsLegendStyle, "Style", QgsLegendStyle)
    for name, size, weight in (("Title", 13, QFont.Weight.DemiBold), ("Group", 10, QFont.Weight.DemiBold), ("Subgroup", 9, QFont.Weight.DemiBold),
                               ("SymbolLabel", 9, QFont.Weight.Normal)):
        try:
            legend.rstyle(getattr(styles, name)).setFont(QFont("Segoe UI", size, weight))
        except Exception:                                           # a style or setter missing in this QGIS build: keep the default
            pass


def export_map(run_name: str, stage: int, path: str | Path, crs, notes: str = "") -> Path:
    """Export the run's visible layers as an A4 landscape map (PDF or PNG by file extension): title, map, legend, scale bar, notes.

    The extent is fixed from the results, not taken from the canvas. A north arrow is left out on purpose: the map is north-up in a
    projected CRS, and the CRS is stated in the notes.
    """
    from qgis.core import (QgsLayoutExporter, QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLayoutItemMap, QgsLayoutItemScaleBar,
                           QgsLayoutPoint, QgsLayoutSize, QgsPrintLayout, QgsProject)
    from qgis.PyQt.QtGui import QFont
    layers = visible_layers(run_name)
    if not layers:
        raise ValueError(tr("There is nothing on the map to export for this run."))
    box = results_extent(layers, crs)
    if box is None or box.isEmpty():
        raise ValueError(tr("The visible layers have no features to map."))
    project, mm = QgsProject.instance(), _mm()
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(f"RE-PEAT {run_name} stage {stage}")
    page_w, page_h, margin = 297.0, 210.0, 10.0

    title = QgsLayoutItemLabel(layout)
    title.setText(tr(STAGE_QUESTION.get(stage, "RE-PEAT pompanisasi")))
    title.setFont(QFont("Segoe UI", 18, QFont.Weight.DemiBold))
    layout.addLayoutItem(title)
    title.attemptMove(QgsLayoutPoint(margin, margin, mm))
    title.attemptResize(QgsLayoutSize(page_w - 2 * margin, 11, mm))

    map_item = QgsLayoutItemMap(layout)
    layout.addLayoutItem(map_item)
    map_w = page_w - 2 * margin - 62
    map_item.attemptMove(QgsLayoutPoint(margin, margin + 14, mm))
    map_item.attemptResize(QgsLayoutSize(map_w, page_h - 2 * margin - 14 - 18, mm))
    map_item.setCrs(crs)
    map_item.setLayers(layers)
    map_item.setKeepLayerSet(True)
    map_item.zoomToExtent(box)
    map_item.setFrameEnabled(True)

    legend = QgsLayoutItemLegend(layout)
    legend.setTitle(tr("Legend"))
    legend.setLinkedMap(map_item)
    legend.setAutoUpdateModel(False)
    root = legend.model().rootGroup()
    root.clear()
    from qgis.core import QgsMapLayerLegendUtils
    for lyr in layers:
        node = root.addLayer(lyr)
        name = legend_name(lyr.name())
        node.setCustomProperty("legend/title-label", name)          # layers with several classes show this as their heading
        try:
            single = len(lyr.renderer().legendSymbolItems()) == 1
        except Exception:                                           # rasters
            single = False
        if single:                                                  # one symbol: its label is the layer's name, so rename that
            QgsMapLayerLegendUtils.setLegendNodeUserLabel(node, 0, name)
            legend.model().refreshLayerLegend(node)
    _legend_fonts(legend)
    legend.updateLegend()
    layout.addLayoutItem(legend)
    legend.attemptMove(QgsLayoutPoint(margin + map_w + 4, margin + 14, mm))

    bar = QgsLayoutItemScaleBar(layout)
    bar.setLinkedMap(map_item)
    bar.setUnits(_metres())
    bar.setNumberOfSegments(2)
    bar.setNumberOfSegmentsLeft(0)
    bar.setStyle("Single Box")
    bar.setFont(QFont("Segoe UI", 8))
    bar.applyDefaultSize(_metres())
    layout.addLayoutItem(bar)
    bar.attemptMove(QgsLayoutPoint(margin + 3, page_h - margin - 28, mm))

    note = QgsLayoutItemLabel(layout)
    how = tr("Thicker segments are the selected targets.") if any(
        l.name() == "canal_segments" and l.fields().indexOf("need_score") >= 0 for l in layers) else ""
    note.setText("\n".join(filter(None, [f"{tr('Run')}: {run_name}  |  {tr('Stage')} {stage}  |  {date.today().isoformat()}",
                                          f"{tr('Projection')}: {crs.authid()} ({crs.description()})", how, notes])))
    note.setFont(QFont("Segoe UI", 8))
    layout.addLayoutItem(note)
    note.attemptMove(QgsLayoutPoint(margin, page_h - margin - 14, mm))
    note.attemptResize(QgsLayoutSize(page_w - 2 * margin, 14, mm))

    path = Path(path)
    exporter = QgsLayoutExporter(layout)
    if path.suffix.lower() == ".pdf":
        result = exporter.exportToPdf(str(path), QgsLayoutExporter.PdfExportSettings())
    else:
        settings = QgsLayoutExporter.ImageExportSettings()
        settings.dpi = 150
        result = exporter.exportToImage(str(path), settings)
    if int(getattr(result, "value", result)) != 0:           # QgsLayoutExporter.Success
        raise RuntimeError(tr("The map could not be exported ({code}).").format(code=int(getattr(result, "value", result))))
    return path
