"""Edit the run's network on the map: canals (stage 2) and proposed sekat (stage 7), saved as files the engine reads.

``EditsEditor`` holds what both share: an edits GeoPackage in the run folder (not in the output GeoPackage, so *Start over* never
destroys hand edits), its layer on the map in a group of its own (a stage re-run never removes it), the map tool lifecycle (the
previous tool and the project's snapping come back on stop) and saving (commit, then point the run's config at the file).
The wizard changes nothing itself: the engine reads the file and reports what it applied.

* canals: ``canal_edits.gpkg``, lines with an ``action`` of add or delete (``inputs.canal_edits``, read by stages 1 and 2). A deleted
  canal is the whole line of the user's canal layer that was clicked.
* sekat: ``sekat_edits.gpkg``, points with an ``action`` of add or delete (``sekat.edits``, read by stage 7). Removing a proposal writes a
  delete at its place; removing a sekat that an earlier edit added removes that add instead.

Map tools look their layers up by name on every click (a re-run replaces the run's layers) and are kept alive by a Python reference.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from qgis.core import (QgsCategorizedSymbolRenderer, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsDefaultValue, QgsFeature,
                       QgsFeatureRequest, QgsGeometry, QgsLineSymbol, QgsMarkerSymbol, QgsProject, QgsRendererCategory, QgsVectorLayer)
from qgis.PyQt.QtCore import QObject, pyqtSignal

from .i18n import tr
from .pointtool import PointTool

EDITS_FILE = "canal_edits.gpkg"
EDITS_LAYER = "canal_edits"
EDITS_TITLE = "Canal edits (yours)"
SEKAT_FILE = "sekat_edits.gpkg"
SEKAT_LAYER = "sekat_edits"
SEKAT_TITLE = "Sekat edits (yours)"
PIXEL_TOLERANCE = 8                 # a click this close (screen pixels) to a feature picks it


def edits_path(run_dir: str | Path, file: str = EDITS_FILE) -> Path:
    return Path(run_dir) / file


def create_edits_file(path: Path, crs_authid: str, layer: str = EDITS_LAYER, geometry: str = "LineString",
                      fields: tuple = (("action", "String"), ("canal_class", "String"), ("depth_m", "Real"), ("width_m", "Real"))) -> None:
    """An empty edits GeoPackage in the run CRS with the columns the engine reads. An existing file is left alone."""
    if path.exists():
        return
    from osgeo import ogr, osr
    srs = osr.SpatialReference()
    srs.SetFromUserInput(crs_authid)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    lyr = ds.CreateLayer(layer, srs, getattr(ogr, "wkb" + geometry))
    for name, kind in fields:
        lyr.CreateField(ogr.FieldDefn(name, getattr(ogr, "OFT" + kind)))
    ds = None


def _snap_flag(name: str):
    from qgis import core
    scoped = getattr(getattr(core, "Qgis", None), "SnappingType", None)
    return getattr(scoped, name) if scoped is not None and hasattr(scoped, name) else getattr(core.QgsSnappingConfig, name)


class EditsEditor(QObject):
    FILE, LAYER, TITLE, GEOMETRY = EDITS_FILE, EDITS_LAYER, EDITS_TITLE, "LineString"
    FIELDS: tuple = (("action", "String"), ("canal_class", "String"), ("depth_m", "Real"), ("width_m", "Real"))
    CONFIG_ROOT = "inputs.canal_edits"          # holds .path and .layer
    SAVED = "Canal edits saved. Run stage 1 and then stage 2 again to apply them."
    ADD_COLOR, DELETE_COLOR = "#1F8A4C", "#C0392B"
    ADD_LABEL, DELETE_LABEL = "Canal to add", "Canal to delete"

    notice = pyqtSignal(str, str)          # level (info|success|warning|error), text
    state_changed = pyqtSignal()

    def __init__(self, iface, controller, parent=None):
        super().__init__(parent)
        self.iface, self.controller = iface, controller
        self._tool: Optional[PointTool] = None
        self._prev_tool = None
        self._prev_snapping = None

    # ------------------------------------------------------------------ what the run says
    def _cfg(self) -> dict:
        path = self.controller.config_path
        return yaml.safe_load(Path(path).read_text(encoding="utf8")) if path else {}

    def run_crs(self) -> str:
        return (self._cfg().get("run") or {}).get("crs", "")

    def run_name(self) -> str:
        return (self._cfg().get("run") or {}).get("name", "run")

    @property
    def available(self) -> bool:
        return self.iface is not None and self.controller.config_path is not None and bool(self.run_crs())

    def run_layer(self, name: str, needs_field: str = ""):
        """A layer of the run's own group on the map, looked up now (a re-run replaces it), or None."""
        group = QgsProject.instance().layerTreeRoot().findGroup(f"RE-PEAT {self.run_name()}")
        for node in (group.findLayers() if group is not None else []):
            lyr = node.layer()
            if lyr is not None and lyr.name() == name and (not needs_field or lyr.fields().indexOf(needs_field) >= 0):
                return lyr
        return None

    # ------------------------------------------------------------------ the edits layer
    def edits_layer(self, create: bool = True):
        """The edits layer on the map (added to its own group the first time), or None."""
        path = edits_path(Path(self.controller.config_path).parent, self.FILE)
        for lyr in QgsProject.instance().mapLayersByName(self.TITLE):
            if isinstance(lyr, QgsVectorLayer) and Path(lyr.source().split("|")[0]) == path:
                return lyr
        if not create and not path.exists():
            return None
        create_edits_file(path, self.run_crs(), self.LAYER, self.GEOMETRY, self.FIELDS)
        lyr = QgsVectorLayer(f"{path}|layername={self.LAYER}", self.TITLE, "ogr")
        if not lyr.isValid():
            return None
        project = QgsProject.instance()
        project.addMapLayer(lyr, False)
        root = project.layerTreeRoot()
        name = f"RE-PEAT {self.run_name()} edits"            # not the run's own group, so a re-run or Start over never removes it
        group = root.findGroup(name) or root.insertGroup(0, name)
        group.addLayer(lyr)
        self._style(lyr)
        return lyr

    def _style(self, layer) -> None:
        if self.GEOMETRY == "Point":
            add = QgsMarkerSymbol.createSimple({"name": "circle", "color": self.ADD_COLOR, "outline_color": "#FFFFFF", "size": "3.6"})
            delete = QgsMarkerSymbol.createSimple({"name": "cross2", "color": self.DELETE_COLOR, "outline_color": self.DELETE_COLOR, "outline_width": "0.8", "size": "4"})
        else:
            add = QgsLineSymbol.createSimple({"color": self.ADD_COLOR, "width": "0.9"})
            delete = QgsLineSymbol.createSimple({"color": self.DELETE_COLOR, "width": "0.9", "line_style": "dash"})
        layer.setRenderer(QgsCategorizedSymbolRenderer("action", [QgsRendererCategory("add", add, tr(self.ADD_LABEL)),
                                                                  QgsRendererCategory("delete", delete, tr(self.DELETE_LABEL))]))
        idx = layer.fields().indexOf("action")
        if idx >= 0:
            layer.setDefaultValueDefinition(idx, QgsDefaultValue("'add'"))
        layer.triggerRepaint()

    # ------------------------------------------------------------------ tools
    def _remember_tool(self) -> None:
        if self._prev_tool is None:
            self._prev_tool = self.iface.mapCanvas().mapTool()

    def _set_tool(self, callback) -> None:
        self._tool = PointTool(self.iface.mapCanvas(), callback)       # keep a Python reference: QGIS does not own it
        self.iface.mapCanvas().setMapTool(self._tool)

    def _snapping_on(self, layers: list) -> bool:
        """Snap new vertices to ``layers`` while drawing, so an added canal joins the network instead of leaving a new loose end."""
        try:
            from qgis.core import QgsSnappingConfig, QgsTolerance
            project = QgsProject.instance()
            if self._prev_snapping is None:
                self._prev_snapping = QgsSnappingConfig(project.snappingConfig())
            cfg = QgsSnappingConfig(project.snappingConfig())
            cfg.setEnabled(True)
            cfg.setMode(getattr(getattr(QgsSnappingConfig, "SnappingMode", QgsSnappingConfig), "AdvancedConfiguration"))
            kinds = _snap_flag("Vertex") | _snap_flag("Segment")
            px = getattr(QgsTolerance, "UnitType", QgsTolerance).Pixels
            for lyr in layers:
                if lyr is not None:
                    cfg.setIndividualLayerSettings(lyr, QgsSnappingConfig.IndividualLayerSettings(True, kinds, 12, px))
            project.setSnappingConfig(cfg)
            return True
        except Exception:
            return False

    def _to_run_crs(self, point):
        """A point of the map canvas as a geometry in the run's CRS."""
        tr_ = QgsCoordinateTransform(self.iface.mapCanvas().mapSettings().destinationCrs(), QgsCoordinateReferenceSystem(self.run_crs()), QgsProject.instance())
        return QgsGeometry.fromPointXY(tr_.transform(point))

    def _pick_nearest(self, layer, point, request_filter=None):
        """The feature of ``layer`` nearest to ``point`` (canvas CRS) within the click tolerance, or None."""
        canvas = self.iface.mapCanvas()
        to_layer = QgsCoordinateTransform(canvas.mapSettings().destinationCrs(), layer.crs(), QgsProject.instance())
        tol = canvas.mapUnitsPerPixel() * PIXEL_TOLERANCE
        box = to_layer.transformBoundingBox(QgsGeometry.fromPointXY(point).buffer(tol, 4).boundingBox())
        target = QgsGeometry.fromPointXY(to_layer.transform(point))
        best, best_d = None, None
        for f in layer.getFeatures(QgsFeatureRequest().setFilterRect(box)):
            if f.hasGeometry() and (request_filter is None or request_filter(f)):
                d = f.geometry().distance(target)
                if best_d is None or d < best_d:
                    best, best_d = f, d
        return best

    def _add_edit(self, geometry, action: str) -> None:
        lyr = self.edits_layer()
        if not lyr.isEditable():
            lyr.startEditing()
        feat = QgsFeature(lyr.fields())
        feat.setGeometry(geometry)
        feat["action"] = action
        lyr.addFeature(feat)
        lyr.triggerRepaint()
        self.state_changed.emit()

    def stop(self) -> None:
        """Leave the edit tools: previous map tool and snapping come back. Edits not yet saved stay in the layer's edit session."""
        if self.iface is None:
            return
        canvas = self.iface.mapCanvas()
        if self._tool is not None and canvas.mapTool() is self._tool:
            canvas.setMapTool(self._prev_tool) if self._prev_tool is not None else canvas.unsetMapTool(self._tool)
        self._tool, self._prev_tool = None, None
        if self._prev_snapping is not None:
            try:
                QgsProject.instance().setSnappingConfig(self._prev_snapping)
            except Exception:
                pass
            self._prev_snapping = None
        self.state_changed.emit()

    # ------------------------------------------------------------------ save
    def pending(self) -> int:
        lyr = self.edits_layer(create=False)
        return int(lyr.featureCount()) if lyr is not None else 0

    def apply(self) -> bool:
        """Save the edits and point the run at them. The file's content is in a stage fingerprint, so that stage shows as out of date."""
        lyr = self.edits_layer(create=False)
        if lyr is None:
            self.notice.emit("warning", tr("There are no edits to save."))
            return False
        if lyr.isEditable() and not lyr.commitChanges():
            self.notice.emit("error", tr("The edits could not be saved: {err}").format(err="; ".join(lyr.commitErrors())))
            return False
        self.stop()
        path = str(edits_path(Path(self.controller.config_path).parent, self.FILE))
        if lyr.featureCount() == 0:
            self.controller.unset_params([self.CONFIG_ROOT])
            self.notice.emit("info", tr("The edits layer is empty, so the run no longer uses these edits."))
        else:
            self.controller.set_params({f"{self.CONFIG_ROOT}.path": path, f"{self.CONFIG_ROOT}.layer": self.LAYER})
            self.notice.emit("success", tr(self.SAVED))
        return True


class CanalEditor(EditsEditor):
    """Stage 2: add canals the data misses, delete canals that should not be there."""

    def input_canals_layer(self):
        """The project layer that is the run's canal input (matched by file and layer name), or None."""
        sec = (self._cfg().get("inputs") or {}).get("canals") or {}
        want = Path(str(sec.get("path", ""))).resolve() if sec.get("path") else None
        for lyr in QgsProject.instance().mapLayers().values():
            if not isinstance(lyr, QgsVectorLayer) or want is None:
                continue
            src = lyr.source().split("|")[0]
            try:
                same_file = Path(src).resolve() == want
            except OSError:
                same_file = False
            if same_file and (not sec.get("layer") or f"layername={sec['layer']}" in lyr.source() or "layername=" not in lyr.source()):
                return lyr
        return None

    def start_add(self) -> None:
        if not self.available:
            return
        lyr = self.edits_layer()
        if lyr is None:
            self.notice.emit("error", tr("The edits layer could not be created in the run folder."))
            return
        self._remember_tool()
        if not lyr.isEditable():
            lyr.startEditing()
        self.iface.setActiveLayer(lyr)
        if not self._snapping_on([self.input_canals_layer(), self.run_layer("canals_clean")]):
            self.notice.emit("warning", tr("Turn on snapping yourself (Project > Snapping Options) so a new canal joins the existing ones."))
        self.iface.actionAddFeature().trigger()
        self.notice.emit("info", tr("Click along the canal to add, double-click or right-click to finish it."))
        self.state_changed.emit()

    def start_delete(self) -> None:
        if not self.available:
            return
        if self.input_canals_layer() is None:
            self.notice.emit("warning", tr("Add the canal layer you chose for this run to the QGIS project first: the canal to delete is picked from it."))
            return
        if self.edits_layer() is None:
            return
        self._remember_tool()
        self._set_tool(self.handle_delete_point)
        self.notice.emit("info", tr("Click the canal to delete."))
        self.state_changed.emit()

    def handle_delete_point(self, point) -> str:
        """Add a delete edit for the input canal nearest to ``point`` (canvas CRS). Returns what happened."""
        canals, lyr = self.input_canals_layer(), self.edits_layer()
        if canals is None or lyr is None:
            return ""
        best = self._pick_nearest(canals, point)
        if best is None:
            self.notice.emit("warning", tr("No canal of your canal layer near that click."))
            return ""
        geom = QgsGeometry(best.geometry())
        geom.transform(QgsCoordinateTransform(canals.crs(), QgsCoordinateReferenceSystem(self.run_crs()), QgsProject.instance()))
        for f in lyr.getFeatures():                                       # clicking the same canal twice adds nothing
            if f["action"] == "delete" and f.geometry().equals(geom):
                self.notice.emit("info", tr("That canal is already marked for deletion."))
                return "duplicate"
        self._add_edit(geom, "delete")
        self.notice.emit("success", tr("Canal marked for deletion. Click another, or save your edits."))
        return "deleted"


class SekatEditor(EditsEditor):
    """Stage 7: add a sekat the head rule did not place, remove a proposed one."""
    FILE, LAYER, TITLE, GEOMETRY = SEKAT_FILE, SEKAT_LAYER, SEKAT_TITLE, "Point"
    FIELDS = (("action", "String"),)
    CONFIG_ROOT = "sekat.edits"
    SAVED = "Sekat edits saved. Run stage 7 again to apply them."
    ADD_LABEL, DELETE_LABEL = "Sekat to add", "Proposed sekat to remove"

    def start_add(self) -> None:
        if not self.available:
            return
        if self.edits_layer() is None:
            self.notice.emit("error", tr("The edits layer could not be created in the run folder."))
            return
        self._remember_tool()
        self._set_tool(self.handle_add_point)
        self.notice.emit("info", tr("Click the canal where the sekat should go. The engine places it on the nearest canal."))
        self.state_changed.emit()

    def start_remove(self) -> None:
        if not self.available:
            return
        if self.run_layer("sekat_proposed") is None:
            self.notice.emit("warning", tr("Run stage 7 first: the proposed sekat are not on the map yet."))
            return
        if self.edits_layer() is None:
            return
        self._remember_tool()
        self._set_tool(self.handle_remove_point)
        self.notice.emit("info", tr("Click the proposed sekat to remove."))
        self.state_changed.emit()

    def handle_add_point(self, point) -> str:
        if self.edits_layer() is None:
            return ""
        self._add_edit(self._to_run_crs(point), "add")
        self.notice.emit("success", tr("Sekat added. Click another, or save your edits."))
        return "added"

    def handle_remove_point(self, point) -> str:
        """Remove the proposed sekat nearest to ``point`` (canvas CRS). A sekat that an earlier edit added is removed by dropping that edit."""
        proposed, lyr = self.run_layer("sekat_proposed"), self.edits_layer()
        if proposed is None or lyr is None:
            self.notice.emit("warning", tr("The proposed sekat are no longer on the map. Run stage 7 again."))
            return ""
        best = self._pick_nearest(proposed, point)
        if best is None:
            self.notice.emit("warning", tr("No proposed sekat near that click."))
            return ""
        geom = QgsGeometry(best.geometry())
        geom.transform(QgsCoordinateTransform(proposed.crs(), QgsCoordinateReferenceSystem(self.run_crs()), QgsProject.instance()))
        names = [f.name() for f in proposed.fields()]
        manual = "manual" in names and best["manual"] not in (None, False, 0) and str(best["manual"]) != "NULL"
        if manual:                                                         # the proposal came from an add edit: drop that edit instead
            adds = [f for f in lyr.getFeatures() if f["action"] == "add"]
            if adds:
                nearest = min(adds, key=lambda f: f.geometry().distance(geom))
                if not lyr.isEditable():
                    lyr.startEditing()
                lyr.deleteFeature(nearest.id())
                lyr.triggerRepaint()
                self.state_changed.emit()
                self.notice.emit("success", tr("The sekat you added is removed. Save your edits to apply it."))
                return "removed_add"
        for f in lyr.getFeatures():
            if f["action"] == "delete" and f.geometry().distance(geom) < 0.5:
                self.notice.emit("info", tr("That sekat is already marked for removal."))
                return "duplicate"
        self._add_edit(geom, "delete")
        self.notice.emit("success", tr("Sekat marked for removal. Click another, or save your edits."))
        return "deleted"
