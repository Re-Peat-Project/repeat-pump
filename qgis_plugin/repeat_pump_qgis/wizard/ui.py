"""The stage-by-stage wizard (Qt widgets). No analysis logic: it shows what ``viewmodel`` derives from the engine's files
and tells ``controller`` what to run.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from qgis.core import QgsProject
from qgis.gui import QgsFileWidget, QgsMapLayerComboBox
from qgis.PyQt.QtCore import QByteArray, QSize, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QPainter, QPixmap
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDockWidget, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                                 QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from ..runconfig import build_run_config
from ..runner import split_source
from . import i18n, styling, theme
from .i18n import tr
from . import viewmodel as vm
from .controller import WizardController

COMPACT_BELOW = 760
RAIL_W, RAIL_COMPACT_W = 296, 76


# ----------------------------------------------------------------------------- small helpers
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


# ----------------------------------------------------------------------------- stage rail row
class StageRow(QPushButton):
    def __init__(self, view: vm.StageView, current: bool, compact: bool):
        super().__init__()
        self.setObjectName("stageRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"Stage {view.id}: {view.title}, {view.sub}")
        self.setToolTip(f"{view.title}: {view.sub}")
        self.setProperty("status", view.status)
        self.setProperty("current", current)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10 if not compact else 18, 6, 10, 6)
        lay.setSpacing(12)
        badge = QLabel()
        badge.setObjectName("badge")
        badge.setProperty("status", view.status)
        badge.setFixedSize(28, 28)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if view.status == "done":
            badge.setPixmap(svg_pixmap(theme.CHECK_SVG, "#FFFFFF", 14))
        elif view.status == "locked":
            badge.setPixmap(svg_pixmap(theme.LOCK_SVG, theme.RAIL_MUTED, 13))
        elif view.status == "failed":
            badge.setText("!")
        else:
            badge.setText(str(view.id))
        lay.addWidget(badge)
        text = QWidget()
        tl = QVBoxLayout(text)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        name, sub = QLabel(view.title), QLabel(view.sub)
        name.setObjectName("stageName")
        sub.setObjectName("stageSub")
        tl.addWidget(name)
        tl.addWidget(sub)
        lay.addWidget(text, 1)
        text.setVisible(not compact)
        for w in (badge, text, name, sub):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        for w in (self, badge, name, sub):
            w.style().unpolish(w)
            w.style().polish(w)


# ----------------------------------------------------------------------------- the wizard
class WizardPanel(QWidget):
    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setObjectName("wizard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(theme.QSS)
        self.setMinimumSize(380, 420)
        self.controller = WizardController(self)
        i18n.set_language(self._initial_language())
        self.learn = False
        self.selected: Optional[int] = None
        self.compact = False
        self._editors: dict[str, QWidget] = {}
        self._last_sig = None
        self._setup_open: Optional[bool] = None

        self._build_skeleton()
        self._make_setup_card()
        self._make_log_view()
        self.controller.changed.connect(self.render)
        self.controller.notice.connect(self._notice)
        self.controller.stage_finished.connect(self._on_stage_finished)
        self.controller.log_line.connect(self._on_log_line)
        self.render()
        self.controller.start()

    # ------------------------------------------------------------------ skeleton
    def _build_skeleton(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.rail = QFrame()
        self.rail.setObjectName("rail")
        self.rail.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.rail_layout = QVBoxLayout(self.rail)
        self.rail_layout.setContentsMargins(14, 22, 14, 14)
        self.rail_layout.setSpacing(14)
        root.addWidget(self.rail)

        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        root.addLayout(main, 1)

        self.header = QFrame()
        self.header.setObjectName("header")
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(28, 12, 28, 12)
        self.crumb = label("", "crumb", wrap=False)
        self.run_chip = label("", "chip", wrap=False)
        self.learn_box = QCheckBox(tr("Learn mode"))
        self.learn_box.setObjectName("learn")
        self.learn_box.setCursor(Qt.CursorShape.PointingHandCursor)
        self.learn_box.toggled.connect(self._toggle_learn)
        hl.addWidget(self.crumb)
        hl.addWidget(self.run_chip)
        hl.addStretch(1)
        self.lang_buttons = {}
        for code, text in (("en", "EN"), ("id", "ID")):
            lb = QPushButton(text)
            lb.setObjectName("lang")
            lb.setCheckable(True)
            lb.setChecked(i18n.language() == code)
            lb.setCursor(Qt.CursorShape.PointingHandCursor)
            lb.setToolTip(i18n.LANGUAGES[code])
            lb.setAccessibleName(i18n.LANGUAGES[code])
            lb.clicked.connect(lambda _=False, c=code: self._set_language(c))
            self.lang_buttons[code] = lb
            hl.addWidget(lb)
        hl.addSpacing(12)
        hl.addWidget(self.learn_box)
        main.addWidget(self.header)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("body")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName("bodyInner")
        inner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(28, 22, 28, 22)
        self.body.setSpacing(16)
        self.scroll.setWidget(inner)
        main.addWidget(self.scroll, 1)

        self.footer = QFrame()
        self.footer.setObjectName("footer")
        self.footer_layout = QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(28, 12, 28, 12)
        self.footer_layout.setSpacing(10)
        main.addWidget(self.footer)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        compact = self.width() < COMPACT_BELOW
        if compact != self.compact:
            self.compact = compact
            self._last_sig = None
            self.render()

    # ------------------------------------------------------------------ persistent widgets
    def _make_log_view(self) -> None:
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(150)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setVisible(False)
        self.log_toggle = button("Show log", "link", self._toggle_log)
        self.log_toggle.setProperty("src", None)

    def _toggle_log(self) -> None:
        show = not self.log_view.isVisible()
        self.log_view.setVisible(show)
        self.log_toggle.setText(tr("Hide log") if show else tr("Show log"))
        if show:
            self.log_view.setPlainText("\n".join(self.controller.log))

    def _on_log_line(self, line: str) -> None:
        if self.log_view.isVisible():
            self.log_view.appendPlainText(line)

    def _make_setup_card(self) -> None:
        self.setup_frame, lay = card()
        top = QHBoxLayout()
        top.addWidget(label("Run setup", "cardTitle"), 1)
        self.setup_toggle = button("Edit setup", "link", self._toggle_setup)
        self.setup_toggle.setProperty("src", None)
        top.addWidget(self.setup_toggle)
        lay.addLayout(top)
        self.setup_summary = label("", "hint")
        lay.addWidget(self.setup_summary)

        self.setup_body = QWidget()
        form = QVBoxLayout(self.setup_body)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        bundled = Path(__file__).parents[1] / "resources" / "example_khg.yaml"
        self.template = file_widget("open", "YAML (*.yaml *.yml)")
        if bundled.exists():
            self.template.setFilePath(str(bundled))
        self.out_file = file_widget("save", "GeoPackage (*.gpkg)")
        self.priority = file_widget("open", "CSV (*.csv)")
        form.addWidget(label("Output GeoPackage (the run folder is its folder)", "paramLabel"))
        form.addWidget(self.out_file)
        form.addWidget(label("Starting config (policy parameters; yours are saved in the run folder)", "paramLabel"))
        form.addWidget(self.template)
        form.addWidget(label("Sub-KHG priority table (CSV)", "paramLabel"))
        form.addWidget(self.priority)
        self.combos: dict[str, tuple[QgsMapLayerComboBox, bool, str]] = {}
        spec = [("dtm", "Bare-earth DTM (metres)", "raster", False), ("moisture", "Moisture index raster", "raster", False),
                ("subkhg", "Sub-KHG polygons", "polygon", False), ("canals", "Canal lines", "line", False),
                ("canal_edits", "Canal edits (optional)", "line", True), ("sekat_existing", "Existing sekat (optional)", "point", True),
                ("rivers", "River polygons or lines, the water sources (optional)", "vector", True),
                ("burn_area", "Burn-scar polygons", "polygon", False), ("peat_depth", "Peat-depth polygons", "polygon", False)]
        for key, text, kind, optional in spec:
            form.addWidget(label(text, "paramLabel"))
            cb = QgsMapLayerComboBox()
            cb.setFilters(layer_filter(kind))
            cb.setAllowEmptyLayer(True)
            cb.setLayer(None)
            self.combos[key] = (cb, optional, text)
            form.addWidget(cb)
        self.setup_msg = label("", "hint")
        form.addWidget(self.setup_msg)
        row = QHBoxLayout()
        row.addWidget(button("Create run", "primary", self._create_run))
        row.addWidget(button("Open an existing run...", "secondary", self._open_run))
        row.addStretch(1)
        form.addLayout(row)
        lay.addWidget(self.setup_body)

    def _toggle_setup(self) -> None:
        self._setup_open = not self.setup_body.isVisible()
        self._apply_setup_visibility()

    def _apply_setup_visibility(self) -> None:
        has_run = self.controller.config_path is not None
        show = self._setup_open if self._setup_open is not None else not has_run
        self.setup_body.setVisible(show)
        self.setup_toggle.setText(tr("Hide setup") if show else tr("Edit setup"))
        self.setup_summary.setVisible(has_run and not show)
        self.setup_summary.setText(tr("Run folder: {path}").format(path=self.controller.config_path.parent) if has_run else "")

    def _create_run(self) -> None:
        try:
            out, tpl = self.out_file.filePath().strip(), self.template.filePath().strip()
            if not out:
                raise ValueError(tr("Choose where the output GeoPackage should go."))
            if not Path(tpl).is_file():
                raise ValueError(tr("Choose a starting config (YAML)."))
            if not self.priority.filePath().strip():
                raise ValueError(tr("Choose the sub-KHG priority table (CSV)."))
            vectors, dtm, moisture, drop = {}, "", "", []
            for key, (cb, optional, text) in self.combos.items():
                layer = cb.currentLayer()
                if layer is None:
                    if optional:
                        drop.append(key)             # left empty on purpose: do not keep the template's placeholder path
                        continue
                    raise ValueError(tr("Choose a layer for: {text}.").format(text=tr(text)))
                path, name = split_source(layer.source())
                if not os.path.exists(path):
                    raise ValueError(tr("{text}: the layer must be saved to a file (temporary layers cannot be passed to the engine).").format(text=tr(text)))
                if key == "dtm":
                    dtm = path
                elif key == "moisture":
                    moisture = path
                else:
                    vectors[key] = (path, name)
            cfg_path = Path(out).parent / "run_config.yaml"
            base = cfg_path if cfg_path.exists() else Path(tpl)
            data = build_run_config(base, output_gpkg=str(Path(out)), dtm=dtm, moisture=moisture,
                                    priority=self.priority.filePath().strip(), vectors=vectors, drop=drop)
        except Exception as e:
            self.setup_msg.setText(f"<span style='color:{theme.RED_TEXT}'>{e}</span>")
            return
        self.setup_msg.setText("")
        self._setup_open = False
        self.selected = 1
        self.controller.write_config(data, cfg_path)

    def _open_run(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Open a run config"), "", "YAML (*.yaml *.yml)")
        if path:
            self._setup_open = False
            self.selected = None
            self.controller.open_run(path)

    # ------------------------------------------------------------------ language
    @staticmethod
    def _initial_language() -> str:
        try:
            from qgis.core import QgsSettings
            saved = QgsSettings().value("repeat_pump/language", "") or ""
            if saved in i18n.LANGUAGES:
                return saved
            from qgis.PyQt.QtCore import QLocale
            return i18n.default_language(str(QgsSettings().value("locale/userLocale", "") or QLocale().name()))
        except Exception:
            return "en"

    def _set_language(self, code: str) -> None:
        i18n.set_language(code)
        try:
            from qgis.core import QgsSettings
            QgsSettings().setValue("repeat_pump/language", code)
        except Exception:
            pass
        for c, b in self.lang_buttons.items():
            b.setChecked(c == code)
        self.learn_box.setText(tr("Learn mode"))
        for w in self.setup_frame.findChildren(QLabel) + self.setup_frame.findChildren(QPushButton):
            src = w.property("src")
            if src:
                w.setText(tr(src))
        self.log_toggle.setText(tr("Hide log") if self.log_view.isVisible() else tr("Show log"))
        self.controller.reload_state()          # rebuilds the model (its texts are translated) and re-renders
        self._last_sig = None
        self.render()

    # ------------------------------------------------------------------ events
    def _toggle_learn(self, on: bool) -> None:
        self.learn = on
        self._last_sig = None
        self.render()

    def _notice(self, level: str, text: str) -> None:
        if self.iface is None:
            return
        try:
            from qgis.core import Qgis
            lv = getattr(Qgis, "MessageLevel", Qgis)
            L = {"info": "Info", "success": "Success", "warning": "Warning", "error": "Critical"}[level]
            self.iface.messageBar().pushMessage("RE-PEAT", text, getattr(lv, L), 8)
        except Exception:
            pass

    def _on_stage_finished(self, stage: int, code: int) -> None:
        model = self.controller.model
        if model is None:
            return
        view = model.stage(stage)
        if code in (0, 2) and view.layers and self.controller.output_gpkg:
            names = styling.load_layers(self.controller.output_gpkg, view.layers, model.check["run_name"])
            if names and stage == 2 and self.iface is not None:
                try:
                    lyr = QgsProject.instance().mapLayersByName(names[0])[0]
                    self.iface.mapCanvas().setExtent(lyr.extent())
                    self.iface.mapCanvas().refresh()
                except Exception:
                    pass
        self.selected = model.current
        self._last_sig = None
        self.render()

    def _select(self, sid: int) -> None:
        self.selected = sid
        self._last_sig = None
        self.render()

    def _act(self, action: str, sid: int) -> None:
        model = self.controller.model
        if action == "rerun" and model is not None:
            later = [v for v in model.stages if v.id > sid and v.status in ("done", "needs_review", "stale")]
            if later:
                ok = QMessageBox.question(self, tr("Re-run stage"), tr("Re-running stage {sid} clears the results of stages {first} to {last}, "
                                          "because they depend on it. Continue?").format(sid=sid, first=later[0].id, last=later[-1].id))
                if ok != QMessageBox.StandardButton.Yes:
                    return
        self.controller.run(action, sid)

    # ------------------------------------------------------------------ rendering
    def render(self) -> None:
        c = self.controller
        model = c.model or vm.WizardModel(vm.placeholder_check(), {"stages": {}, "warnings": [], "report": {}}, None, bool(c.engine_ready))
        has_run = c.config_path is not None and c.model is not None
        if self.selected is None or self.selected not in {v.id for v in model.stages}:
            self.selected = model.current
        view = model.stage(self.selected)

        self._render_rail(model, has_run)
        run_name = model.check.get("run_name") or ""
        self.crumb.setText(tr("Stage {n} of {total}").format(n=view.id, total=len(model.stages)))
        self.run_chip.setText(run_name or tr("No run yet"))
        self.run_chip.setVisible(not self.compact)
        self._apply_setup_visibility()

        sig = (view.id, view.status, tuple(p.key for p in view.params), len(view.tiles), view.error, self.learn, c.engine_ready,
               bool(c.busy), c.running is not None, has_run, self.compact, tuple(view.warnings), view.sub)
        if sig != self._last_sig:
            self._last_sig = sig
            bar = self.scroll.verticalScrollBar()
            keep_pos = bar.value() if self._same_stage(view.id) else 0
            self._render_body(model, view, has_run)
            self.scroll.widget().adjustSize()
            bar.setValue(keep_pos)
            self._body_stage = view.id
        else:
            self._refresh_editors(view)
        self._render_footer(model, view, has_run)

    def _same_stage(self, sid: int) -> bool:
        return getattr(self, "_body_stage", None) == sid

    # ---- rail
    def _render_rail(self, model: vm.WizardModel, has_run: bool) -> None:
        c = self.controller
        clear(self.rail_layout)
        self.rail.setFixedWidth(RAIL_COMPACT_W if self.compact else RAIL_W)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setFixedSize(38, 38)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(f"background:{theme.TEAL}; border-radius:11px;")
        logo.setPixmap(svg_pixmap(theme.DROP_SVG, "#E8FBF7", 22))
        brand.addWidget(logo)
        if not self.compact:
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(label("RE-PEAT", "brandTitle", wrap=False))
            col.addWidget(label("Rewetting with pompanisasi", "brandSub"))
            brand.addLayout(col, 1)
        else:
            brand.addStretch(1)
        self.rail_layout.addLayout(brand)
        if not self.compact:
            chip = QFrame()
            chip.setObjectName("runChip")
            cl = QVBoxLayout(chip)
            cl.setContentsMargins(12, 8, 12, 8)
            cl.setSpacing(0)
            cl.addWidget(label(model.check.get("run_name") or "No run yet", "runChipTitle", wrap=False))
            done = sum(1 for v in model.stages if v.status == "done")
            cl.addWidget(label(tr("{done} of {total} stages done").format(done=done, total=len(model.stages)) if has_run else "Start with the setup on stage 1", "runChipSub"))
            self.rail_layout.addWidget(chip)
        for v in model.stages:
            row = StageRow(v, v.id == self.selected, self.compact)
            row.clicked.connect(lambda _=False, sid=v.id: self._select(sid))
            self.rail_layout.addWidget(row)
        self.rail_layout.addStretch(1)
        if c.busy:
            if not self.compact:
                self.rail_layout.addWidget(label(c.busy, "railNote"))
        elif c.engine_ready is False:
            self.rail_layout.addWidget(button("Set up" if self.compact else "Set up engine", "railBtn", c.setup_engine))
        elif not self.compact:
            self.rail_layout.addWidget(label("Engine ready" if c.engine_ready else "", "railNote"))

    # ---- body
    def _render_body(self, model: vm.WizardModel, view: vm.StageView, has_run: bool) -> None:
        clear(self.body, keep=(self.setup_frame, self.log_view, self.log_toggle))
        self._editors = {}
        c = self.controller
        b = self.body
        b.addWidget(self._heading(view))
        if c.engine_ready is False:
            b.addWidget(self._callout("error", "The engine is not set up", c.engine_message + "\n" +
                                      tr("Use the Set up engine button on the left. It needs internet once and Python 3.11 or newer.")))
        if view.status == "failed" and view.error:
            b.addWidget(self._callout("error", "This stage stopped", view.error))
        if view.status == "stale":
            b.addWidget(self._callout("warn", "These results are out of date", view.stale_reason))
        if self.learn:
            b.addWidget(self._learn(view))
        if view.id == 1:
            b.addWidget(self.setup_frame)
        if view.tiles:
            b.addWidget(self._tiles(view))
        if view.review_hint:
            b.addWidget(self._callout("warn", "Your review is needed", view.review_hint))
        if view.warnings:
            shown = view.warnings[:4]
            more = len(view.warnings) - len(shown)
            b.addWidget(self._callout("warn", "Worth a look", "\n".join(shown) + ("\n" + tr("...and {n} more in the run report.").format(n=more) if more > 0 else "")))
        if view.params:
            b.addWidget(self._params_card(view))
        if view.id == 11 and view.status == "done" and self.controller.output_gpkg:
            rp = self.controller.output_gpkg.parent / "run_report.md"
            b.addWidget(button("Open run report", "secondary", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(rp)))))
        if has_run or c.log:
            b.addWidget(self.log_toggle)
            b.addWidget(self.log_view)
        b.addStretch(1)

    def _heading(self, view: vm.StageView) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        tone = "review" if (view.review and view.status in ("needs_review", "locked", "ready")) or view.status == "stale" \
            else ("failed" if view.status == "failed" else "")
        suffix = {"needs_review": " · REVIEW NEEDED", "failed": " · FAILED", "running": " · RUNNING", "done": " · DONE",
                  "stale": " · OUT OF DATE"}.get(view.status, "")
        if view.review and view.status in ("ready", "locked"):
            suffix = " · REVIEW STAGE"
        eyebrow = label(tr("STAGE {n}").format(n=view.id) + (tr(suffix) if suffix else ""), "eyebrow", wrap=False)
        prop(eyebrow, tone=tone)
        lay.addWidget(eyebrow)
        lay.addWidget(label(view.title, "title"))
        lay.addWidget(label(view.purpose, "purpose"))
        return w

    def _learn(self, view: vm.StageView) -> QWidget:
        w = QWidget()
        lay = QGridLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        for i, (title, text, ref) in enumerate([("What this does", view.what, ""), ("Why it matters", view.why, view.reference)]):
            f = QFrame()
            f.setObjectName("learnCard")
            fl = QVBoxLayout(f)
            fl.setContentsMargins(16, 14, 16, 14)
            fl.setSpacing(4)
            fl.addWidget(label(title, "cardTitle"))
            fl.addWidget(label(text))
            if ref:
                fl.addWidget(label(tr("Reference:") + " " + ref, "learnRef"))
            lay.addWidget(f, 0 if not self.compact else i, i if not self.compact else 0)
        return w

    def _callout(self, tone: str, title: str, text: str) -> QWidget:
        f = QFrame()
        f.setObjectName("callout")
        prop(f, tone=tone)
        lay = QHBoxLayout(f)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(svg_pixmap(theme.WARN_SVG, theme.RED_TEXT if tone == "error" else theme.AMBER_TEXT, 20))
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        lay.addWidget(icon)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = label(title)
        t.setStyleSheet("font-weight:700;")
        col.addWidget(t)
        col.addWidget(label(text))
        lay.addLayout(col, 1)
        return f

    def _tiles(self, view: vm.StageView) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(12)
        cols = 2 if self.compact else 4
        for i, t in enumerate(view.tiles):
            f = QFrame()
            f.setObjectName("tile")
            prop(f, warn=t.warn)
            fl = QVBoxLayout(f)
            fl.setContentsMargins(16, 12, 16, 12)
            fl.setSpacing(0)
            fl.addWidget(label(t.label, "tileLabel"))
            fl.addWidget(label(t.value, "tileValue", wrap=False))
            if t.note:
                fl.addWidget(label(t.note, "tileNote"))
            g.addWidget(f, i // cols, i % cols)
        for k in range(cols):
            g.setColumnStretch(k, 1)
        return w

    def _params_card(self, view: vm.StageView) -> QWidget:
        f, lay = card()
        n_missing = sum(1 for p in view.params if p.missing and not p.recommended)
        head = "Decisions for this stage" if n_missing == 0 else tr("Decisions needed ({n})").format(n=n_missing)
        lay.addWidget(label(head, "cardTitle"))
        lay.addWidget(label("These values are policy choices for your team. The wizard never fills them in for you. They are saved in the run config.", "hint"))
        for p in view.params:
            fld = vm.field_for(p.key)
            lay.addWidget(label(fld.label + ("  " + tr("(needed if river water levels are used)") if p.recommended else ""), "paramLabel"))
            if fld.help:
                lay.addWidget(label(fld.help, "paramHelp"))
            row = QHBoxLayout()
            ed = self._editor(p, fld)
            self._editors[p.key] = ed
            row.addWidget(ed, 1)
            if fld.unit and fld.kind in ("float", "int"):
                row.addWidget(label(fld.unit, "paramUnit", wrap=False))
            lay.addLayout(row)
        return f

    def _editor(self, p: vm.Param, fld: vm.Field_) -> QWidget:
        if fld.kind == "matrix":
            return label("Edit this in the run YAML file (a matrix cannot be typed here).", "paramHelp")
        if fld.kind in ("bool", "enum"):
            cb = QComboBox()
            items = [tr("Not decided")] + ([tr("Yes"), tr("No")] if fld.kind == "bool" else list(fld.options))
            cb.addItems(items)
            cur = p.value
            idx = 0 if cur is None else ((1 if cur else 2) if fld.kind == "bool" else (items.index(cur) if cur in items else 0))
            cb.setCurrentIndex(idx)
            prop(cb, missing=p.missing, paramKey=p.key)
            cb.currentIndexChanged.connect(lambda i, k=p.key, kind=fld.kind, o=fld.options: self._commit(
                k, None if i == 0 else ((i == 1) if kind == "bool" else o[i - 1])))
            return cb
        le = QLineEdit("" if p.value is None else str(p.value))
        le.setPlaceholderText(tr("Not decided yet"))
        le.setProperty("saved", "" if p.value is None else str(p.value))
        prop(le, missing=p.missing, invalid=False, paramKey=p.key)
        le.editingFinished.connect(lambda k=p.key, kind=fld.kind, w=le: self._commit_text(k, kind, w))
        return le

    def _commit_text(self, key: str, kind: str, w: QLineEdit) -> None:
        text = w.text().strip()
        if text == w.property("saved"):
            return
        try:
            value = None if not text else (float(text.replace(",", ".")) if kind == "float" else int(text) if kind == "int" else text)
        except ValueError:
            prop(w, invalid=True)
            return
        prop(w, invalid=False)
        w.setProperty("saved", text)
        self._commit(key, value)

    def _commit(self, key: str, value) -> None:
        self.controller.set_param(key, value)

    def _refresh_editors(self, view: vm.StageView) -> None:
        """Update highlighting of existing editors without rebuilding them (keeps keyboard focus while typing)."""
        for p in view.params:
            w = self._editors.get(p.key)
            if w is not None and w.property("missing") != p.missing:
                prop(w, missing=p.missing)

    # ---- footer
    def _render_footer(self, model: vm.WizardModel, view: vm.StageView, has_run: bool) -> None:
        c = self.controller
        clear(self.footer_layout)
        note = label("", "footerNote")
        self.footer_layout.addWidget(note, 1)
        if view.id > 1:
            self.footer_layout.addWidget(button("Back", "ghost", lambda: self._select(view.id - 1), enabled=c.running is None))

        def add(text, name, slot, enabled=True):
            self.footer_layout.addWidget(button(text, name, slot, enabled))

        if c.running is not None:
            note.setText(tr("Stage {n} is running. QGIS stays usable meanwhile.").format(n=c.running))
            add("Cancel run", "ghost", c.cancel)
        elif c.busy:
            note.setText(c.busy)
        elif not has_run:
            note.setText(tr("Set up your run on stage 1 first."))
            add("Run stage", "primary", None, False)
        elif view.status == "locked":
            note.setText(tr("Finish stage {n} first. You can already prepare its decisions.").format(n=view.id - 1))
            add("Run stage", "primary", None, False)
        elif view.status == "ready":
            note.setText(view.blocking)
            add(tr("Run stage {n}").format(n=view.id), "primary", lambda: self._act("run", view.id), view.can_run)
        elif view.status == "needs_review":
            nxt = model.stage(view.id + 1).title if view.id < len(model.stages) else ""
            add("Re-run this stage", "secondary", lambda: self._act("rerun", view.id), view.can_rerun)
            add(tr("Accept and continue: {title}").format(title=nxt) if nxt else tr("Accept and continue"), "primary", lambda: self._act("accept", view.id), view.can_accept)
            note.setText(view.blocking)
        elif view.status == "done":
            add("Re-run this stage", "secondary", lambda: self._act("rerun", view.id), view.can_rerun)
            if view.id < len(model.stages):
                add(tr("Next: {title}").format(title=model.stage(view.id + 1).title), "primary", lambda: self._select(view.id + 1))
            note.setText(view.blocking)
        elif view.status == "stale":
            note.setText(view.blocking)
            add("Re-run to apply your change", "primary", lambda: self._act("rerun", view.id), view.can_rerun)
        else:  # failed
            note.setText(view.blocking)
            add("Run again", "primary", lambda: self._act("rerun", view.id), view.can_rerun)


class WizardDock(QDockWidget):
    """Dock that can float: the wizard collapses its stage rail to icons when narrow."""

    def __init__(self, iface=None, parent=None):
        super().__init__("RE-PEAT Pompanisasi", parent)
        self.setObjectName("RepeatPumpWizardDock")
        self.panel = WizardPanel(iface, self)
        self.setWidget(self.panel)
