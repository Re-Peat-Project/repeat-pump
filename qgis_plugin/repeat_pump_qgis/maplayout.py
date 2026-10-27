"""Print layouts in the style of the KLH peat maps (A0 to A4, landscape or portrait), filled from a run.

Landscape follows the KLH sheets (Peta Intervensi Pembasahan, Peta Pengendalian Karhutla): the map fills the frame with a
lat/long border (degree-minute-second ticks, no grid lines) and a strip along the bottom holds, from left to right, the title with
north arrow, scale and scale bar, the legend in columns, the data sources with the institution, and a locator inset. Portrait
stacks the same items under the map.

Every item has a fixed id (``ITEM_IDS``), so a layout saved as a template (.qpt) can be edited by hand in the layout designer and
filled again by ``fill_layout``: an id the user deleted is skipped, everything else keeps the user's position and style.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Optional

from qgis.core import (Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFillSymbol, QgsLayerTree, QgsLayerTreeLayer,
                       QgsLayout, QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLayoutItemMap, QgsLayoutItemMapGrid, QgsLayoutItemMapOverview,
                       QgsLayoutItemPage, QgsLayoutItemPicture, QgsLayoutItemScaleBar, QgsLayoutItemShape, QgsLayoutMeasurement, QgsLayoutPoint,
                       QgsLayoutSize, QgsLegendStyle, QgsPrintLayout, QgsProject, QgsReadWriteContext, QgsRectangle, QgsTextFormat)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtXml import QDomDocument

MM = Qgis.LayoutUnit.Millimeters
PAPERS = {"A0": (1189, 841), "A1": (841, 594), "A2": (594, 420), "A3": (420, 297), "A4": (297, 210)}   # landscape width x height, mm
ITEM_IDS = ["map_main", "map_inset", "title", "north", "scale_text", "scalebar", "legend", "sources", "institution", "logo", "note", "frame_strip",
            "budget_table"]
FONT = "Arial"
INK = QColor("#1a1a1a")


@dataclass
class LayoutSpec:
    """What a layout shows. ``layers`` are drawn in list order, the first on top; ``legend_layers`` default to the same."""
    title: str
    subtitle: str = ""
    layers: list = field(default_factory=list)
    legend_layers: Optional[list] = None
    extent: Optional[QgsRectangle] = None          # in ``crs``; default: the layers' combined extent
    crs: Optional[QgsCoordinateReferenceSystem] = None
    paper: str = "A3"
    orientation: str = "landscape"                 # landscape | portrait
    sources: list = field(default_factory=list)
    institution: str = ""
    note: str = "Catatan: Peta ini bukan referensi resmi mengenai garis-garis batas administrasi nasional"
    inset_layers: list = field(default_factory=list)   # e.g. the national KHG boundaries; the inset is hidden without them
    inset_highlight: Optional[object] = None           # a layer drawn on top in the inset (the KHG)
    legend_title: str = "Legenda:"
    legend_names: dict = field(default_factory=dict)  # layer id -> legend heading (the layer keeps its own name)
    name: str = ""
    placeholder: bool = False                      # a template: every item, including an empty inset map, and no layers
    budget_rows: list = field(default_factory=list)   # rows of text, the first the header; a box in the map's top-right corner when given


def symbol_scale(paper: str) -> float:
    """How much larger point and line symbols are drawn on this paper than on A3 (never smaller): a sheet that is read from further
    away needs larger marks. A2 1.3, A1 1.6, A0 2.1."""
    return max(1.0, _f(paper) / _f("A3"))


# ----------------------------------------------------------------------------- numbers
def nice_scale(s: float) -> int:
    """Round a scale denominator up to two significant digits (1:76.543 -> 1:77.000, as on the KLH sheets)."""
    if s <= 0:
        return 1
    step = 10 ** max(0, int(math.floor(math.log10(s))) - 1)
    return int(math.ceil(s / step) * step)


def scale_text(s: int) -> str:
    return "Skala 1:" + f"{s:,}".replace(",", ".")


def grid_interval(span_deg: float, target: int = 5) -> float:
    """A round lat/long tick interval (minutes or degrees) giving about ``target`` ticks over ``span_deg``."""
    for v in [m / 60 for m in (1, 2, 5, 10, 15, 20, 30)] + [1, 2, 5, 10]:
        if span_deg / v <= target:
            return v
    return 10.0


def _f(paper: str) -> float:
    w, h = PAPERS[paper]
    return (w * h / (1189 * 841)) ** 0.35         # text size factor against A0


PT_MM = 0.3528


def fit_size(text: str, w_mm: float, h_mm: float, max_pt: float, bold: bool = False) -> float:
    """The largest font size (pt, at most ``max_pt``) at which ``text`` fits a box: lines by height, the longest line by width."""
    lines = text.split("\n") or [""]
    by_h = h_mm / (len(lines) * 1.22 * PT_MM)
    upper = sum(c.isupper() for c in text) > 0.6 * sum(c.isalpha() for c in text)
    per_char = (0.72 if upper else 0.62) if bold else (0.66 if upper else 0.55)     # em widths of Arial, capitals are wider
    by_w = w_mm / (max(len(l) for l in lines) * per_char * PT_MM) if any(lines) else max_pt
    return max(3.0, min(max_pt, by_h, by_w))


def _fmt(size_pt: float, bold: bool = False, color: QColor = INK) -> QgsTextFormat:
    tf = QgsTextFormat()
    font = QFont(FONT)
    font.setBold(bold)
    tf.setFont(font)
    tf.setSize(size_pt)
    tf.setSizeUnit(Qgis.RenderUnit.Points)
    tf.setColor(color)
    return tf


# ----------------------------------------------------------------------------- items
def _place(item, x, y, w, h):
    item.attemptMove(QgsLayoutPoint(x, y, MM))
    item.attemptResize(QgsLayoutSize(w, h, MM))


def _label(layout, iid, text, size, x, y, w, h, bold=False, halign=Qt.AlignmentFlag.AlignLeft, valign=Qt.AlignmentFlag.AlignTop):
    lab = QgsLayoutItemLabel(layout)        # ``size`` is the largest size; it shrinks until the text fits its box
    lab.setId(iid)
    lab.setText(text)
    lab.setTextFormat(_fmt(fit_size(text, w, h, size, bold), bold))
    lab.setCustomProperty("repeat_max_pt", size)           # fill_layout re-fits new text up to this size
    lab.setHAlign(halign)
    lab.setVAlign(valign)
    layout.addLayoutItem(lab)
    _place(lab, x, y, w, h)
    return lab


def _rect(layout, iid, x, y, w, h, width_mm=0.5):
    sh = QgsLayoutItemShape(layout)
    sh.setShapeType(QgsLayoutItemShape.Shape.Rectangle)
    sh.setId(iid)
    sh.setSymbol(QgsFillSymbol.createSimple({"color": "0,0,0,0", "outline_color": "26,26,26", "outline_width": str(width_mm), "outline_width_unit": "MM"}))
    layout.addLayoutItem(sh)
    _place(sh, x, y, w, h)
    return sh


def _north_svg() -> str:
    return os.path.join(QgsApplication.pkgDataPath(), "svg", "arrows", "NorthArrow_11.svg")


def build_layout(project: QgsProject, spec: LayoutSpec) -> QgsPrintLayout:
    """A new print layout for ``spec`` (not yet added to the project's layout manager)."""
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(spec.name or spec.title.replace("\n", " ")[:80])
    pw, ph = PAPERS[spec.paper]
    if spec.orientation == "portrait":
        pw, ph = ph, pw
    page = layout.pageCollection().page(0)
    page.setPageSize(QgsLayoutSize(pw, ph, MM))
    f = _f(spec.paper)
    m = max(5.0, 0.012 * max(pw, ph))                       # outer margin
    gap = 0.4 * m                                            # room for the lat/long ticks and labels inside the outer frame
    tick = 1.4 * m
    x0, y0, W, H = m, m, pw - 2 * m, ph - 2 * m
    _rect(layout, "frame_outer", x0 - 1.0, y0 - 1.0, W + 2.0, H + 2.0, 0.25)
    _rect(layout, "frame_inner", x0, y0, W, H, 0.6)
    if spec.orientation == "landscape":
        strip = {"A0": 0.13, "A1": 0.13, "A2": 0.17, "A3": 0.17}.get(spec.paper, 0.22) * H     # symbols keep their size: small paper needs room
        map_box = (x0 + tick, y0 + tick, W - 2 * tick, H - strip - 2 * tick)
        sy = y0 + H - strip
        cols = [0.20, 0.45, 0.22, 0.13]
        xs = [x0]
        for c in cols[:-1]:
            xs.append(xs[-1] + c * W)
        boxes = {"title": (xs[0], sy, cols[0] * W, strip), "legend": (xs[1], sy, cols[1] * W, strip),
                 "sources": (xs[2], sy, cols[2] * W, strip), "inset": (xs[3], sy, cols[3] * W, strip)}
        legend_cols = 4
    else:
        strip = {"A0": 0.27, "A1": 0.27, "A2": 0.30, "A3": 0.30}.get(spec.paper, 0.34) * H
        map_box = (x0 + tick, y0 + tick, W - 2 * tick, H - strip - 2 * tick)
        sy = y0 + H - strip
        left, right = 0.62 * W, 0.38 * W
        boxes = {"title": (x0, sy, left, 0.36 * strip), "legend": (x0, sy + 0.36 * strip, left, 0.64 * strip),
                 "inset": (x0 + left, sy, right, 0.5 * strip), "sources": (x0 + left, sy + 0.5 * strip, right, 0.5 * strip)}
        legend_cols = 2
    _rect(layout, "frame_strip", x0, sy, W, H - (sy - y0), 0.6)
    for k in ("legend", "sources", "inset"):
        bx = boxes[k]
        _rect(layout, f"frame_{k}", bx[0], bx[1], bx[2], bx[3], 0.3)

    # ---- main map
    crs = spec.crs or (spec.layers[0].crs() if spec.layers else project.crs())
    mp = QgsLayoutItemMap(layout)
    mp.setId("map_main")
    layout.addLayoutItem(mp)
    _place(mp, *map_box)
    mp.setCrs(crs)
    mp.setLayers(list(spec.layers))
    mp.setKeepLayerSet(True)
    mp.setFrameEnabled(True)
    mp.setFrameStrokeWidth(QgsLayoutMeasurement(0.4, MM))
    ext = spec.extent or _combined_extent(spec.layers, crs, project)
    if ext is not None:
        mp.zoomToExtent(ext.buffered(0.03 * max(ext.width(), ext.height())))
        mp.setScale(nice_scale(mp.scale()))
    _latlong_grid(mp, crs, project, f)

    # ---- title block: title, north arrow, scale, scale bar
    tx, ty, tw, th = boxes["title"]
    pad = 0.06 * min(tw, th)
    _label(layout, "title", spec.title.upper() + (("\n" + spec.subtitle.upper()) if spec.subtitle else ""), 32 * f,
           tx + pad, ty + pad, tw - 2 * pad, 0.50 * th - pad, bold=True, halign=Qt.AlignmentFlag.AlignHCenter)
    na = QgsLayoutItemPicture(layout)
    na.setId("north")
    na.setPicturePath(_north_svg())
    na.setLinkedMap(mp)
    layout.addLayoutItem(na)
    nsz = 0.22 * th
    _place(na, tx + pad, ty + 0.53 * th, nsz, nsz)
    _label(layout, "scale_text", scale_text(int(round(mp.scale()))), 22 * f, tx + 2 * pad + nsz, ty + 0.53 * th, tw - 3 * pad - nsz, nsz,
           bold=True, valign=Qt.AlignmentFlag.AlignVCenter)
    sb = QgsLayoutItemScaleBar(layout)
    sb.setId("scalebar")
    sb.setStyle("Double Box")
    sb.setLinkedMap(mp)
    sb.setUnits(Qgis.DistanceUnit.Kilometers)
    sb.setUnitLabel("Kilometer")
    sb.setNumberOfSegmentsLeft(1)
    sb.setNumberOfSegments(3)
    km_per_mm = mp.scale() / 1e6                            # ground km per mm of paper
    seg = _nice_segment(0.80 * (tw - 2 * pad) * km_per_mm / 4)      # 1 segment left of zero, 3 right: four in all
    sb.setUnitsPerSegment(seg)
    sb.setSegmentSizeMode(Qgis.ScaleBarSegmentSizeMode.Fixed)
    sb.setHeight(max(1.0, 0.05 * th))
    sb.setTextFormat(_fmt(fit_size("0000", 0.12 * tw, 0.06 * th, 12 * f)))
    sb.setLabelBarSpace(0.6)
    sb.setBoxContentSpace(0.4)
    layout.addLayoutItem(sb)
    sb.attemptMove(QgsLayoutPoint(tx + pad, ty + 0.79 * th, MM))

    # ---- legend
    lx, ly, lw, lh = boxes["legend"]
    lg = QgsLayoutItemLegend(layout)
    lg.setId("legend")
    lg.setTitle(spec.legend_title)
    lg.setLinkedMap(mp)
    lg.setAutoUpdateModel(False)
    root = lg.model().rootGroup()
    root.removeAllChildren()
    for lyr in (spec.legend_layers if spec.legend_layers is not None else spec.layers):
        root.addChildNode(_legend_node(lyr, spec))
    lg.setLegendFilterByMapEnabled(True)
    lg.setColumnCount(legend_cols)
    lg.setSplitLayer(True)
    lg.setEqualColumnWidth(True)
    lg.setFrameEnabled(False)
    layout.addLayoutItem(lg)
    lg.attemptMove(QgsLayoutPoint(lx + pad, ly + pad, MM))
    fit_legend(lg, lw - 2 * pad, lh - 2 * pad, f)

    # ---- sources, institution, logo placeholder, note
    sx, syy, sw, shh = boxes["sources"]
    src = "Sumber Data:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(spec.sources, 1)) if spec.sources else "Sumber Data:"
    _label(layout, "sources", src, 12 * f, sx + pad, syy + pad, sw - 2 * pad, 0.64 * shh - pad)
    _label(layout, "note", spec.note, 10 * f, sx + pad, syy + 0.65 * shh, sw - 2 * pad, 0.08 * shh)
    logo = QgsLayoutItemPicture(layout)
    logo.setId("logo")
    logo.setFrameEnabled(False)                              # a placeholder: choose the institution's logo in the layout designer
    layout.addLayoutItem(logo)
    lsz = 0.22 * shh
    _place(logo, sx + pad, syy + shh - lsz - pad, lsz, lsz)
    _label(layout, "institution", spec.institution, 12 * f, sx + 2 * pad + lsz, syy + shh - lsz - pad, sw - 3 * pad - lsz, lsz, bold=True,
           valign=Qt.AlignmentFlag.AlignVCenter)

    # ---- budget table, in the map's top-right corner (move it in the layout designer if it covers the area)
    if spec.budget_rows or spec.placeholder:
        rows = spec.budget_rows or [["Item", "Jumlah", "Biaya (miliar Rp)"]]
        _budget_table(layout, rows, map_box, f)

    # ---- inset
    ix, iy, iw, ih = boxes["inset"]
    if spec.inset_layers or spec.placeholder:
        ins = QgsLayoutItemMap(layout)
        ins.setId("map_inset")
        layout.addLayoutItem(ins)
        _place(ins, ix + pad, iy + pad, iw - 2 * pad, ih - 2 * pad)
        wgs = QgsCoordinateReferenceSystem("EPSG:4326")
        ins.setCrs(wgs)
        lyrs = ([spec.inset_highlight] if spec.inset_highlight is not None else []) + list(spec.inset_layers)
        ins.setLayers(lyrs)
        ins.setKeepLayerSet(True)
        ins.setFrameEnabled(True)
        c = QgsCoordinateTransform(crs, wgs, project).transformBoundingBox(mp.extent()).center()
        aspect = (iw - 2 * pad) / max(1e-6, ih - 2 * pad)
        half_h = 5.0
        ins.zoomToExtent(QgsRectangle(c.x() - half_h * aspect, c.y() - half_h, c.x() + half_h * aspect, c.y() + half_h))
        ov = QgsLayoutItemMapOverview("frame", ins)
        ov.setLinkedMap(mp)
        ov.setFrameSymbol(QgsFillSymbol.createSimple({"color": "208,59,59,60", "outline_color": "208,59,59", "outline_width": "0.4"}))
        ins.overviews().addOverview(ov)
    return layout


def _set_budget_rows(table, rows: list, f: float) -> None:
    from qgis.core import QgsTableCell
    head, body = _fmt(11 * f, True), _fmt(10 * f)
    cells, width = [], max(len(r) for r in rows)
    for i, r in enumerate(rows):
        if len(r) == 1:                                    # a note under the table, across every column
            c = QgsTableCell(r[0])
            c.setTextFormat(_fmt(8.5 * f))
            c.setSpan(1, width)
            cells.append([c] + [QgsTableCell("") for _ in range(width - 1)])
            continue
        line = []
        for j, v in enumerate(r):
            c = QgsTableCell(v)
            c.setTextFormat(head if i == 0 or str(r[0]).lower() == "total" else body)
            c.setHorizontalAlignment(Qt.AlignmentFlag.AlignLeft if j == 0 else Qt.AlignmentFlag.AlignRight)
            line.append(c)
        cells.append(line)
    table.setTableContents(cells)


def _budget_table(layout, rows: list, map_box: tuple, f: float):
    """A manual table (rows of text) in a frame with the id ``budget_table`` at the top-right corner of the main map."""
    from qgis.core import QgsLayoutFrame, QgsLayoutItemManualTable
    table = QgsLayoutItemManualTable.create(layout)
    layout.addMultiFrame(table)
    table.setIncludeTableHeader(False)
    table.setCellMargin(0.8 * f + 0.4)
    table.setGridStrokeWidth(0.15)
    table.setGridColor(QColor("#c3c2b7"))
    table.setVerticalGrid(False)
    table.setBackgroundColor(QColor(255, 255, 255, 235))
    table.setContentTextFormat(_fmt(10 * f))
    _set_budget_rows(table, rows, f)
    frame = QgsLayoutFrame(layout, table)
    frame.setId("budget_table")
    frame.setFrameEnabled(True)
    frame.setFrameStrokeWidth(QgsLayoutMeasurement(0.3, MM))
    table.addFrame(frame)
    mx, my, mw, mh = map_box
    w = min(0.42 * mw, table.totalWidth() + 1.0)
    h = len(rows) * (10 * f * PT_MM * 1.2 + 2 * table.cellMargin()) + 0.5
    pad = 0.015 * mw
    _place(frame, mx + mw - w - pad, my + pad, w, h)
    return frame


def _legend_sizes(lg: QgsLayoutItemLegend, k: float) -> None:
    lg.rstyle(QgsLegendStyle.Style.Title).setTextFormat(_fmt(20 * k, True))
    lg.rstyle(QgsLegendStyle.Style.Group).setTextFormat(_fmt(15 * k, True))
    lg.rstyle(QgsLegendStyle.Style.Subgroup).setTextFormat(_fmt(15 * k, True))
    lg.rstyle(QgsLegendStyle.Style.SymbolLabel).setTextFormat(_fmt(13 * k))
    lg.setSymbolWidth(11 * k)
    lg.setSymbolHeight(6.5 * k)
    for st in (QgsLegendStyle.Style.Group, QgsLegendStyle.Style.Subgroup, QgsLegendStyle.Style.Symbol, QgsLegendStyle.Style.SymbolLabel):
        lg.rstyle(st).setMargin(QgsLegendStyle.Side.Top, 1.2 * k)


def _legend_content_size(lg: QgsLayoutItemLegend) -> tuple[float, float]:
    """Width and height (mm) the legend content needs, measured by the legend renderer (the item only knows it once drawn)."""
    from qgis.core import QgsLayoutUtils, QgsLegendRenderer
    ctx = QgsLayoutUtils.createRenderContextForLayout(lg.layout(), None)
    size = QgsLegendRenderer(lg.model(), lg.legendSettings()).minimumSize(ctx)
    return size.width(), size.height()


def fit_legend(lg: QgsLayoutItemLegend, w_mm: float, h_mm: float, f: float) -> float:
    """The largest text that lets the legend content fit ``w_mm`` x ``h_mm``, trying every column count up to the one set (fewer
    columns are taller and narrower). The legend cannot do this itself. Returns the size factor; the best column count is kept."""
    max_cols = lg.columnCount()
    best = (0.0, max_cols)
    for cols in range(max_cols, 0, -1):
        lg.setColumnCount(cols)
        k = f
        for _ in range(16):
            _legend_sizes(lg, k)
            if hasattr(lg, "invalidateCache"):
                lg.invalidateCache()
            sw, sh = _legend_content_size(lg)
            if os.environ.get("REPEAT_LAYOUT_DEBUG"):
                print(f"legend cols={cols} k={k:.3f} size {sw:.1f} x {sh:.1f} mm, box {w_mm:.1f} x {h_mm:.1f}")
            if sw <= w_mm and sh <= h_mm:
                break
            k *= 0.92
        else:
            continue
        if k > best[0]:
            best = (k, cols)
    k, cols = best if best[0] > 0 else (0.25 * f, max_cols)
    lg.setColumnCount(cols)
    _legend_sizes(lg, k)
    lg.setResizeToContents(False)
    lg.attemptResize(QgsLayoutSize(w_mm, h_mm, MM))
    return k


def _legend_node(lyr, spec: LayoutSpec) -> QgsLayerTreeLayer:
    node = QgsLayerTreeLayer(lyr)
    if lyr.id() in spec.legend_names:
        node.setUseLayerName(False)
        node.setName(spec.legend_names[lyr.id()])
    return node


def _nice_segment(km: float) -> float:
    """The largest round segment length (km) not longer than ``km``, so the bar fits its box."""
    best = 0.05
    for v in (0.05, 0.1, 0.2, 0.25, 0.5, 1, 1.5, 2, 2.5, 3, 5, 10, 15, 20, 25, 50, 100):
        if v <= km:
            best = v
    return best


def _combined_extent(layers, crs, project) -> Optional[QgsRectangle]:
    ext = None
    for lyr in layers:
        e = QgsCoordinateTransform(lyr.crs(), crs, project).transformBoundingBox(lyr.extent())
        if e.isNull() or e.isEmpty():
            continue
        ext = QgsRectangle(e) if ext is None else (ext.combineExtentWith(e) or ext)
    return ext


def _latlong_grid(mp: QgsLayoutItemMap, crs, project, f: float) -> None:
    """Degree-minute-second ticks and labels on the map border, no grid lines (as on the KLH sheets)."""
    wgs = QgsCoordinateReferenceSystem("EPSG:4326")
    e = QgsCoordinateTransform(crs, wgs, project).transformBoundingBox(mp.extent())
    g = QgsLayoutItemMapGrid("latlong", mp)
    g.setCrs(wgs)
    g.setStyle(QgsLayoutItemMapGrid.GridStyle.FrameAnnotationsOnly)
    g.setIntervalX(grid_interval(e.width()))
    g.setIntervalY(grid_interval(e.height()))
    g.setFrameStyle(QgsLayoutItemMapGrid.FrameStyle.InteriorExteriorTicks)
    g.setFrameWidth(2.0 * f * 2)
    g.setFramePenSize(0.3)
    g.setAnnotationEnabled(True)
    g.setAnnotationFormat(QgsLayoutItemMapGrid.AnnotationFormat.DegreeMinuteSecond)
    g.setAnnotationPrecision(0)
    g.setAnnotationTextFormat(_fmt(11 * f))
    for side in (QgsLayoutItemMapGrid.BorderSide.Left, QgsLayoutItemMapGrid.BorderSide.Right):
        g.setAnnotationDirection(QgsLayoutItemMapGrid.AnnotationDirection.Vertical, side)
    mp.grids().addGrid(g)


# ----------------------------------------------------------------------------- templates
def save_template(layout: QgsLayout, path: str) -> None:
    layout.saveAsTemplate(path, QgsReadWriteContext())


def load_template(project: QgsProject, path: str) -> QgsPrintLayout:
    layout = QgsPrintLayout(project)
    doc = QDomDocument()
    with open(path, encoding="utf8") as fh:
        doc.setContent(fh.read())
    layout.loadFromTemplate(doc, QgsReadWriteContext())
    return layout


def fill_layout(layout: QgsLayout, spec: LayoutSpec, project: QgsProject) -> list[str]:
    """Put ``spec`` into a layout made from a template: layers, extent, scale, title, sources, legend, inset. Items found by id;
    ids that are missing (deleted by the user) are skipped and returned."""
    missing = []
    item = lambda iid: layout.itemById(iid)  # noqa: E731
    mp = item("map_main")
    if mp is None:
        return ["map_main"]
    crs = spec.crs or (spec.layers[0].crs() if spec.layers else project.crs())
    mp.setCrs(crs)
    mp.setLayers(list(spec.layers))
    mp.setKeepLayerSet(True)
    ext = spec.extent or _combined_extent(spec.layers, crs, project)
    if ext is not None:
        mp.zoomToExtent(ext.buffered(0.03 * max(ext.width(), ext.height())))
        mp.setScale(nice_scale(mp.scale()))
    for iid, text in (("title", spec.title.upper() + (("\n" + spec.subtitle.upper()) if spec.subtitle else "")), ("scale_text", scale_text(int(round(mp.scale())))),
                      ("sources", "Sumber Data:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(spec.sources, 1))), ("institution", spec.institution), ("note", spec.note)):
        it = item(iid)
        if it is None:
            missing.append(iid)
        else:
            it.setText(text)
            tf = it.textFormat()
            box = it.sizeWithUnits()
            max_pt = float(it.customProperty("repeat_max_pt", tf.size()))
            tf.setSize(fit_size(text, box.width(), box.height(), max_pt, tf.font().bold()))
            it.setTextFormat(tf)
    lg = item("legend")
    if lg is None:
        missing.append("legend")
    else:
        lg.setAutoUpdateModel(False)
        root = lg.model().rootGroup()
        root.removeAllChildren()
        for lyr in (spec.legend_layers if spec.legend_layers is not None else spec.layers):
            root.addChildNode(_legend_node(lyr, spec))
        lg.setLinkedMap(mp)
        lg.setLegendFilterByMapEnabled(True)
        page = layout.pageCollection().page(0).pageSize()
        f = (page.width() * page.height() / (1189 * 841)) ** 0.35
        box = lg.sizeWithUnits()
        fit_legend(lg, box.width(), box.height(), f)              # the legend keeps the box the template gives it
    bt = item("budget_table")
    if bt is not None and spec.budget_rows:
        page = layout.pageCollection().page(0).pageSize()
        _set_budget_rows(bt.multiFrame(), spec.budget_rows, (page.width() * page.height() / (1189 * 841)) ** 0.35)
    elif bt is None and spec.budget_rows:
        missing.append("budget_table")
    ins = item("map_inset")
    if ins is not None and spec.inset_layers:
        ins.setLayers(([spec.inset_highlight] if spec.inset_highlight is not None else []) + list(spec.inset_layers))
        ins.setKeepLayerSet(True)
        wgs = QgsCoordinateReferenceSystem("EPSG:4326")
        c = QgsCoordinateTransform(crs, wgs, project).transformBoundingBox(mp.extent()).center()
        r = ins.extent()
        ins.zoomToExtent(QgsRectangle(c.x() - r.width() / 2, c.y() - r.height() / 2, c.x() + r.width() / 2, c.y() + r.height() / 2))
    layout.refresh()
    return missing


def export_png(layout: QgsLayout, path: str, dpi: int = 96) -> int:
    from qgis.core import QgsLayoutExporter
    s = QgsLayoutExporter.ImageExportSettings()
    s.dpi = dpi
    return int(QgsLayoutExporter(layout).exportToImage(path, s))


def export_pdf(layout: QgsLayout, path: str) -> int:
    from qgis.core import QgsLayoutExporter
    return int(QgsLayoutExporter(layout).exportToPdf(path, QgsLayoutExporter.PdfExportSettings()))
