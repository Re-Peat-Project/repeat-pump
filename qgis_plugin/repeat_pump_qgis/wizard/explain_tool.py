"""Click a canal segment on the map and see why it scored as it did (the breakdown comes from ``explain``)."""
from __future__ import annotations

from typing import Optional

from qgis.core import NULL, QgsCoordinateTransform, QgsFeatureRequest, QgsGeometry, QgsProject
from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QDialog, QLabel, QScrollArea, QVBoxLayout

from . import explain as ex
from . import viewmodel as vm
from .i18n import tr
from .pointtool import PointTool

PIXEL_TOLERANCE = 8
LAYER = "canal_segments"


def _py(v):
    """A QGIS attribute as plain Python (NULL becomes None)."""
    return None if v == NULL else v


class SegmentExplainer(QObject):
    notice = pyqtSignal(str, str)

    def __init__(self, iface, controller, parent=None):
        super().__init__(parent)
        self.iface, self.controller = iface, controller
        self._tool: Optional[PointTool] = None
        self._prev_tool = None
        self.dialog: Optional[QDialog] = None
        self.label: Optional[QLabel] = None

    @property
    def available(self) -> bool:
        return self.iface is not None and self.controller.config_path is not None and self.controller.output_gpkg is not None

    def _run_name(self) -> str:
        return (self.controller.check_json or {}).get("run_name", "")

    def segments_layer(self):
        """The run's ``canal_segments`` layer, looked up now (a re-run replaces it), or None."""
        group = QgsProject.instance().layerTreeRoot().findGroup(f"RE-PEAT {self._run_name()}")
        for node in (group.findLayers() if group is not None else []):
            if node.layer() is not None and node.layer().name() == LAYER and node.layer().fields().indexOf("need_score") >= 0:
                return node.layer()
        return None

    def start(self) -> None:
        if not self.available:
            return
        if self.segments_layer() is None:
            self.notice.emit("warning", tr("Run stage 6 first: the canal segments with their scores are not on the map yet."))
            return
        canvas = self.iface.mapCanvas()
        if self._prev_tool is None:
            self._prev_tool = canvas.mapTool()
        self._tool = PointTool(canvas, self.handle_point)
        canvas.setMapTool(self._tool)
        self.notice.emit("info", tr("Click a canal segment to see why it scored as it did."))

    def stop(self) -> None:
        if self.iface is None or self._tool is None:
            return
        canvas = self.iface.mapCanvas()
        if canvas.mapTool() is self._tool:
            canvas.setMapTool(self._prev_tool) if self._prev_tool is not None else canvas.unsetMapTool(self._tool)
        self._tool, self._prev_tool = None, None

    def handle_point(self, point) -> Optional[ex.Explanation]:
        """Explain the segment nearest to ``point`` (map canvas CRS), or say there is none. Returns the explanation."""
        layer = self.segments_layer()
        if layer is None:
            self.notice.emit("warning", tr("The canal segments are no longer on the map. Run stage 6 again."))
            return None
        canvas = self.iface.mapCanvas()
        to_layer = QgsCoordinateTransform(canvas.mapSettings().destinationCrs(), layer.crs(), QgsProject.instance())
        tol = canvas.mapUnitsPerPixel() * PIXEL_TOLERANCE
        box = to_layer.transformBoundingBox(QgsGeometry.fromPointXY(point).buffer(tol, 4).boundingBox())
        target = QgsGeometry.fromPointXY(to_layer.transform(point))
        names = [f.name() for f in layer.fields()]
        best, best_d, rows = None, None, []
        for f in layer.getFeatures():
            rows.append({n: _py(f[n]) for n in names})
        for f in layer.getFeatures(QgsFeatureRequest().setFilterRect(box)):
            if f.hasGeometry() and (best_d is None or f.geometry().distance(target) < best_d):
                best, best_d = f, f.geometry().distance(target)
        if best is None:
            self.notice.emit("info", tr("No canal segment near that click."))
            return None
        attrs = {n: _py(best[n]) for n in names}
        model = self.controller.model
        stale = bool(model is not None and model.stage(6).status == "stale")
        report = (vm.load_state(self.controller.output_gpkg) or {}).get("report", {})
        e = ex.explain(attrs, report, ex.stats_from_rows(rows), stale)
        self._show(e)
        try:
            canvas.flashFeatureIds(layer, [best.id()])
        except Exception:
            pass
        return e

    def _show(self, e: ex.Explanation) -> None:
        if self.dialog is None:
            self.dialog = QDialog(self.iface.mainWindow() if hasattr(self.iface, "mainWindow") else None)
            self.dialog.setWindowTitle(tr("Why this score?"))
            self.dialog.setMinimumWidth(520)
            self.dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            lay = QVBoxLayout(self.dialog)
            self.label = QLabel()
            self.label.setWordWrap(True)
            self.label.setTextFormat(Qt.TextFormat.RichText)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(self.label)
            lay.addWidget(scroll)
        self.label.setText(ex.to_html(e))
        self.dialog.show()
        self.dialog.raise_()
