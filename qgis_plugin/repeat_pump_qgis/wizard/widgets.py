"""Small Qt helpers shared by the wizard's modules (labels, buttons, cards, layer filters, file widgets)."""
from __future__ import annotations

from qgis.gui import QgsFileWidget
from qgis.PyQt.QtCore import QByteArray, Qt
from qgis.PyQt.QtGui import QPainter, QPixmap
from qgis.PyQt.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from .i18n import tr


def svg_pixmap(svg: str, color: str, size: int) -> QPixmap:
    """Render an inline SVG (``{c}`` is replaced by ``color``) to a pixmap; an empty pixmap if QtSvg is unavailable."""
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    try:
        from qgis.PyQt.QtSvg import QSvgRenderer
        r = QSvgRenderer(QByteArray(svg.format(c=color).encode("utf8")))
        p = QPainter(pm)
        r.render(p)
        p.end()
    except Exception:
        pass
    pm.setDevicePixelRatio(2.0)
    return pm


def svg_picture(svg: str, width: int, height: int) -> QPixmap:
    """A complete SVG document rendered at 2x for sharp text; an empty pixmap if QtSvg is unavailable."""
    pm = QPixmap(width * 2, height * 2)
    pm.fill(Qt.GlobalColor.transparent)
    try:
        from qgis.PyQt.QtSvg import QSvgRenderer
        r = QSvgRenderer(QByteArray(svg.encode("utf8")))
        p = QPainter(pm)
        r.render(p)
        p.end()
    except Exception:
        pass
    pm.setDevicePixelRatio(2.0)
    return pm


def label(text: str = "", name: str = "", wrap: bool = True) -> QLabel:
    w = QLabel(tr(text))
    w.setProperty("src", text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    w.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return w


def button(text: str, name: str, slot=None, enabled: bool = True) -> QPushButton:
    b = QPushButton(tr(text))
    b.setProperty("src", text)
    b.setObjectName(name)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setEnabled(enabled)
    if slot:
        b.clicked.connect(lambda _=False: slot())
    return b


def prop(w: QWidget, **props) -> QWidget:
    for k, v in props.items():
        w.setProperty(k, v)
    w.style().unpolish(w)
    w.style().polish(w)
    return w


def clear(layout, keep=()) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is None:
            if item.layout() is not None:
                clear(item.layout(), keep)
            continue
        if w in keep:
            w.setParent(None)
        else:
            w.setParent(None)
            w.deleteLater()


def card(name: str = "card") -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName(name)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(10)
    return f, lay


def layer_filter(kind: str):
    """Combo-box layer filter that works on QGIS 3.34 and 4."""
    try:
        from qgis.core import Qgis
        F = Qgis.LayerFilter
        return {"raster": F.RasterLayer, "polygon": F.PolygonLayer, "line": F.LineLayer, "point": F.PointLayer,
                "vector": F.VectorLayer}[kind]
    except Exception:
        from qgis.core import QgsMapLayerProxyModel as M
        return {"raster": M.RasterLayer, "polygon": M.PolygonLayer, "line": M.LineLayer, "point": M.PointLayer, "vector": M.VectorLayer}[kind]


def file_widget(mode: str, flt: str = "") -> QgsFileWidget:
    w = QgsFileWidget()
    sm = getattr(QgsFileWidget, "StorageMode", QgsFileWidget)
    w.setStorageMode(getattr(sm, {"open": "GetFile", "save": "SaveFile"}[mode]))
    if flt:
        w.setFilter(flt)
    return w
