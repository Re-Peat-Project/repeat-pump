"""The stage-by-stage wizard (Qt widgets). No analysis logic: it shows what ``viewmodel`` derives from the engine's files
and tells ``controller`` what to run.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from qgis.core import QgsProject
from qgis.gui import QgsFileWidget, QgsMapLayerComboBox
from qgis.PyQt.QtCore import QByteArray, QSize, QStandardPaths, Qt, QTimer, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QPainter, QPixmap
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDockWidget, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                                 QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

import yaml

from ..runconfig import attach_preset, build_run_config, form_inputs, read_setup, setup_changes, write_setup
from ..runner import split_source
from . import i18n, styling, theme
from .i18n import tr
from . import diagrams, maptools, summary, viewmodel as vm
from .canal_edit import CanalEditor, RouteEditor, SekatEditor
from .controller import PRESET_RESOURCE, WizardController
from .explain_tool import SegmentExplainer
from .setup_form import SetupExtras

COMPACT_BELOW = 760
RAIL_W, RAIL_COMPACT_W = 296, 76


from .widgets import button, card, clear, file_widget, label, layer_filter, prop, svg_picture, svg_pixmap  # noqa: F401  (re-exported for the other modules)


# ----------------------------------------------------------------------------- AHP pairwise matrix editor

SETUP_FILTER = "JSON (*.json);;YAML (*.yaml *.yml)"


def default_output() -> str:
    """A new run's output: Documents/RE-PEAT/pump_<date>/pump_run.gpkg (the folder is created when the run is)."""
    import datetime
    docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) or str(Path.home())
    return str(Path(docs) / "RE-PEAT" / f"pump_{datetime.date.today():%Y%m%d}" / "pump_run.gpkg")


def find_or_add_layer(path: str, name: Optional[str] = None):
    """The map layer that reads ``path`` (and ``name`` inside a GeoPackage), added to the map when it is not there yet."""
    from qgis.core import QgsRasterLayer, QgsVectorLayer
    want = os.path.normcase(os.path.abspath(path))
    for lyr in QgsProject.instance().mapLayers().values():
        p, n = split_source(lyr.source())
        if p and os.path.normcase(os.path.abspath(p)) == want and (not name or not n or n == name):
            return lyr
    if not os.path.exists(path):
        return None
    stem = Path(path).stem
    if Path(path).suffix.lower() in (".tif", ".tiff", ".img", ".vrt", ".asc"):
        lyr = QgsRasterLayer(path, stem)
    else:
        lyr = QgsVectorLayer(f"{path}|layername={name}" if name else path, name or stem, "ogr")
    if not lyr.isValid():
        return None
    QgsProject.instance().addMapLayer(lyr)
    return lyr

class AhpEditor(QWidget):
    """Grid for the pairwise comparisons: type the cells above the diagonal, the mirrored cells follow as reciprocals.
    The weights and the consistency ratio update while typing; a complete matrix is saved through ``on_commit``."""

    def __init__(self, matrix, on_commit):
        super().__init__()
        ok = isinstance(matrix, list) and matrix and all(isinstance(r, list) and len(r) == len(matrix) for r in matrix)
        self.n = len(matrix) if ok else len(vm.CRITERIA)
        self._on_commit = on_commit
        self._last = [[float(x) for x in r] for r in matrix] if ok else None
        names = [tr(t) for t in vm.CRITERIA.values()]
        names += [tr("criterion {n}").format(n=k + 1) for k in range(len(names), self.n)]
        self.names = names[:self.n]
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        for k, name in enumerate(self.names):
            grid.addWidget(label(name, "paramHelp", wrap=False), 0, k + 1)
            grid.addWidget(label(name, "paramHelp", wrap=False), k + 1, 0)
        self.cells: dict[tuple[int, int], QLineEdit] = {}
        self.mirror: dict[tuple[int, int], QLabel] = {}
        for i in range(self.n):
            for j in range(self.n):
                if i == j:
                    grid.addWidget(label("1", "paramHelp", wrap=False), i + 1, j + 1)
                elif i < j:
                    le = QLineEdit("" if not ok else vm.format_ratio(float(matrix[i][j])))
                    le.setPlaceholderText("1-9")
                    le.setMaximumWidth(64)
                    le.textChanged.connect(self._changed)
                    le.editingFinished.connect(self._commit)
                    self.cells[(i, j)] = le
                    grid.addWidget(le, i + 1, j + 1)
                else:
                    lb = label("", "paramHelp", wrap=False)
                    self.mirror[(i, j)] = lb
                    grid.addWidget(lb, i + 1, j + 1)
        self.summary = label("", "paramHelp")
        grid.addWidget(self.summary, self.n + 1, 0, 1, self.n + 1)
        self._changed()

    def _read(self) -> tuple[dict, bool]:
        upper, bad = {}, False
        for (i, j), le in self.cells.items():
            x = vm.parse_ratio(le.text())
            prop(le, invalid=bool(le.text().strip()) and x is None)
            bad = bad or (bool(le.text().strip()) and x is None)
            if x is not None:
                upper[(i, j)] = x
        return upper, bad

    def _changed(self) -> None:
        upper, bad = self._read()
        for (i, j), lb in self.mirror.items():
            x = upper.get((j, i))
            lb.setText("" if x is None else vm.format_ratio(1 / x))
        m = vm.ahp_matrix(self.n, upper)
        if bad:
            self.summary.setText(f"<span style='color:{theme.RED_TEXT}'>{tr('Use a number from 1 to 9, or a fraction such as 1/3.')}</span>")
        elif m is None:
            self.summary.setText(tr("Fill every cell above the diagonal to see the weights."))
        else:
            w, cr = vm.ahp_weights_cr(m)
            parts = ", ".join(f"{n} {x * 100:.0f} %" for n, x in zip(self.names, w))
            verdict = tr("Consistency ratio {cr} (must be 0.10 or less).").format(cr=f"{cr:.2f}")
            if cr > vm.AHP_MAX_CR:
                verdict = f"<span style='color:{theme.RED_TEXT}'>{verdict} {tr('Revise the comparisons.')}</span>"
            self.summary.setText(f"{tr('Weights')}: {parts}. {verdict}")

    def _commit(self) -> None:
        upper, bad = self._read()
        m = None if bad else vm.ahp_matrix(self.n, upper)
        if m is not None and m != self._last:
            self._last = m
            self._on_commit(m)


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
        elif view.status == "skipped":
            badge.setText("-")
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
        self.preview = False               # demo view: every stage's cards and tools are shown, whatever has been run
        self._tools_live = True
        self.selected: Optional[int] = None
        self.compact = False
        self._editors: dict[str, QWidget] = {}
        self._last_sig = None
        self._setup_open: Optional[bool] = None
        self._setup_touched = False          # the setup form was opened after the run was created or opened
        self._options_open: set[int] = set()
        self._run_started: Optional[float] = None
        self._progress: tuple = (0, 0.0, "")

        self._build_skeleton()
        self._make_setup_card()
        self._make_log_view()
        self.canal_editor = CanalEditor(iface, self.controller, self)
        self.canal_editor.notice.connect(self._notice)
        self.sekat_editor = SekatEditor(iface, self.controller, self)
        self.sekat_editor.notice.connect(self._notice)
        self.route_editor = RouteEditor(iface, self.controller, self)
        self.route_editor.notice.connect(self._notice)
        self.segment_explainer = SegmentExplainer(iface, self.controller, self)
        self.segment_explainer.notice.connect(self._notice)
        self.controller.changed.connect(self.render)
        self.controller.notice.connect(self._notice)
        self.controller.stage_finished.connect(self._on_stage_finished)
        self.controller.log_line.connect(self._on_log_line)
        self.controller.progress_changed.connect(self._on_progress)
        self._ticker = QTimer(self)
        self._ticker.setInterval(1000)
        self._ticker.timeout.connect(self._update_progress)
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
        self.preview_box = QCheckBox(tr("Demo view"))
        self.preview_box.setObjectName("learn")
        self.preview_box.setToolTip(tr("Show every stage's decisions and map tools at once, even before they can run. Nothing is run or changed."))
        self.preview_box.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview_box.toggled.connect(self._toggle_preview)
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
        hl.addWidget(self.preview_box)
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

        self.progress_frame = QFrame()
        self.progress_frame.setObjectName("progressFrame")
        pl = QVBoxLayout(self.progress_frame)
        pl.setContentsMargins(28, 8, 28, 8)
        pl.setSpacing(4)
        self.progress_text = label("", "paramHelp")
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        self.progress_overall = label("", "paramHelp")
        for w in (self.progress_text, self.progress_bar, self.progress_overall):
            pl.addWidget(w)
        self.progress_frame.setVisible(False)
        main.addWidget(self.progress_frame)

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
        # a RE-PEAT KHG work folder fills everything below in one step
        khg_row = QHBoxLayout()
        self.khg_combo = QComboBox()
        self.khg_combo.activated.connect(lambda _i: self._fill_from_khg(self.khg_combo.currentData()))
        khg_row.addWidget(self.khg_combo, 1)
        khg_row.addWidget(button("KHG folders...", "link", self._choose_khg_root))
        form.addWidget(label("KHG (fills every input from its work folder)", "paramLabel"))
        form.addLayout(khg_row)
        self._refresh_khg_list()
        bundled = Path(__file__).parents[1] / "resources" / "example_khg.yaml"
        self.template = file_widget("open", "YAML (*.yaml *.yml)")
        if bundled.exists():
            self.template.setFilePath(str(bundled))
        self.out_file = file_widget("save", "GeoPackage (*.gpkg)")
        self.out_file.setFilePath(default_output())
        self.priority = file_widget("open", "CSV (*.csv)")
        form.addWidget(label("Output GeoPackage (the run folder is its folder)", "paramLabel"))
        form.addWidget(self.out_file)
        self.advanced_btn = button("Advanced: starting config", "link", lambda: self.advanced_box.setVisible(not self.advanced_box.isVisible()))
        self.advanced_box = QWidget()
        adv = QVBoxLayout(self.advanced_box)
        adv.setContentsMargins(0, 0, 0, 0)
        adv.addWidget(label("Starting config (policy parameters; yours are saved in the run folder)", "paramLabel"))
        adv.addWidget(self.template)
        self.advanced_box.setVisible(False)
        self.use_preset = QCheckBox(tr("Use the proposed defaults (for trial runs, not team decisions)"))
        self.use_preset.setProperty("src", "Use the proposed defaults (for trial runs, not team decisions)")
        self.use_preset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.use_preset.setChecked(True)                     # suggested values on by default; each stays marked as proposed
        self.use_preset.toggled.connect(self._toggle_preset)
        form.addWidget(self.use_preset)
        form.addWidget(label("Fills the empty decision fields with researched starting values. Each one stays marked as proposed until you enter a value. Values you type always win.", "paramHelp"))
        form.addWidget(label("Sub-KHG priority table (CSV, optional)", "paramLabel"))
        form.addWidget(self.priority)
        self.combos: dict[str, tuple[QgsMapLayerComboBox, bool, str]] = {}
        spec = [("dtm", "Bare-earth DTM (metres)", "raster", False), ("moisture", "Moisture index raster", "raster", False),
                ("subkhg", "Sub-KHG polygons", "polygon", False), ("canals", "Canal lines", "line", False),
                ("canal_edits", "Canal edits (optional)", "line", True), ("sekat_existing", "Existing sekat (optional)", "point", True),
                ("rivers", "River polygons or lines, the water sources (optional)", "vector", True),
                ("burn_area", "Burn-scar polygons (optional)", "polygon", True), ("peat_depth", "Peat depth, class polygons or a depth raster (optional)", "polygon_raster", True),
                ("concession", "Concession polygons (optional, a feasibility filter)", "polygon", True),
                ("tma_obs", "Water-level observations (optional, for validation)", "point", True),
                ("subkhg_indicators", "Sub-KHG indicators from the prioritisation (optional, for the interventions)", "polygon", True)]
        for key, text, kind, optional in spec:
            form.addWidget(label(text, "paramLabel"))
            cb = QgsMapLayerComboBox()
            cb.setFilters(layer_filter(kind))
            cb.setAllowEmptyLayer(True)
            cb.setLayer(None)
            self.combos[key] = (cb, optional, text)
            form.addWidget(cb)
        self.extras = SetupExtras(lambda: {k: c.currentLayer() for k, (c, _o, _t) in self.combos.items()}, self._add_cloud_raster, self._add_cloud_burn,
                                  lambda: str(Path(self.out_file.filePath()).parent) if self.out_file.filePath().strip() else None,
                                  lambda: self.priority.filePath().strip())
        self.priority.fileChanged.connect(lambda _p: self.extras.refresh())
        for cb, _o, _t in self.combos.values():
            cb.layerChanged.connect(lambda _l: self.extras.refresh())
        form.addWidget(self.extras)
        self.setup_msg = label("", "hint")
        form.addWidget(self.advanced_btn, 0, Qt.AlignmentFlag.AlignLeft)
        form.addWidget(self.advanced_box)
        form.addWidget(self.setup_msg)
        row = QHBoxLayout()
        self.create_btn = button("Create run", "primary", self._create_run)
        row.addWidget(self.create_btn)
        row.addWidget(button("Open an existing run...", "secondary", self._open_run))
        row.addWidget(button("Load setup...", "ghost", self._load_setup_file))
        row.addWidget(button("Save setup as...", "ghost", self._save_setup_file))
        self.start_over = button("Start over...", "ghost", self._start_over)
        row.addWidget(self.start_over)
        row.addStretch(1)
        form.addLayout(row)
        lay.addWidget(self.setup_body)

    def _add_cloud_raster(self, path: str) -> None:
        """The moisture raster the cloud dialog wrote: put it on the map and choose it as the moisture layer."""
        from qgis.core import QgsProject, QgsRasterLayer
        layer = QgsRasterLayer(path, Path(path).stem)
        if not layer.isValid():
            self.setup_msg.setText(f"<span style='color:{theme.RED_TEXT}'>{tr('QGIS could not open the downloaded raster: {path}').format(path=path)}</span>")
            return
        QgsProject.instance().addMapLayer(layer)
        self.combos["moisture"][0].setLayer(layer)
        self.extras.refresh()

    def _add_cloud_burn(self, path: str) -> None:
        """The burn_area layer the cloud dialog wrote: put it on the map and choose it as the burn-scar layer."""
        from qgis.core import QgsVectorLayer
        layer = QgsVectorLayer(f"{path}|layername=burn_area", Path(path).stem, "ogr")
        if not layer.isValid():
            self.setup_msg.setText(f"<span style='color:{theme.RED_TEXT}'>{tr('QGIS could not open the downloaded layer: {path}').format(path=path)}</span>")
            return
        QgsProject.instance().addMapLayer(layer)
        self.combos["burn_area"][0].setLayer(layer)
        self.extras.refresh()

    def _toggle_setup(self) -> None:
        self._setup_open = not self.setup_body.isVisible()
        if self._setup_open and self.controller.config_path is not None:
            self._setup_touched = True
        self._apply_setup_visibility()

    def _apply_setup_visibility(self) -> None:
        has_run = self.controller.config_path is not None
        show = self._setup_open if self._setup_open is not None else not has_run
        self.setup_body.setVisible(show)
        self.setup_toggle.setText(tr("Hide setup") if show else tr("Edit setup"))
        src = "Save setup" if has_run else "Create run"          # with a run open the button saves the edited setup into it
        self.create_btn.setProperty("src", src)
        self.create_btn.setText(tr(src))
        self.setup_summary.setVisible(has_run and not show)
        self.start_over.setVisible(has_run)
        self.setup_summary.setText(tr("Run folder: {path}").format(path=self.controller.config_path.parent) if has_run else "")

    def _create_run(self) -> None:
        try:
            data, cfg_path = self._build_setup()
        except Exception as e:
            self.setup_msg.setText(f"<span style='color:{theme.RED_TEXT}'>{e}</span>".replace("\n", "<br>"))
            return
        self._save_setup(data, cfg_path)

    def _build_setup(self) -> tuple[dict, Path]:
        """The run config the setup form describes, and where it is written. Raises ValueError with a message for the person."""
        out, tpl = self.out_file.filePath().strip(), self.template.filePath().strip()
        if not out:
            raise ValueError(tr("Choose where the output GeoPackage should go."))
        if not Path(tpl).is_file():
            raise ValueError(tr("Choose a starting config (YAML)."))
        vectors, dtm, moisture, drop = {}, "", "", []
        priority = self.priority.filePath().strip()
        if not priority:
            drop.append("subkhg_priority")       # optional: equal priority and specific-yield demand apply instead
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
        self.extras.refresh()
        problems = self.extras.errors()
        if problems:
            raise ValueError("\n".join(problems))
        extra_moisture = [split_source(l.source())[0] for l in self.extras.moisture_layers()]
        params = self.extras.params()
        if "rivers" not in vectors:
            params.pop("inputs.rivers.vertical_datum", None)      # no rivers layer: there is nothing to put a datum on
        cfg_path = Path(out).parent / "run_config.yaml"
        base = cfg_path if cfg_path.exists() else Path(tpl)
        data = build_run_config(base, output_gpkg=str(Path(out)), dtm=dtm, moisture=[moisture] + extra_moisture,
                                priority=priority or None, vectors=vectors, drop=drop, params=params, columns=self.extras.columns())
        if self.use_preset.isChecked():
            try:
                attach_preset(data, cfg_path.parent, PRESET_RESOURCE)
            except OSError as e:
                raise ValueError(tr("Could not turn on the proposed defaults: {err}").format(err=e))
        return data, cfg_path

    def _save_setup(self, data: dict, cfg_path: Path) -> None:
        self.setup_msg.setText("")
        self._setup_open = False
        self._setup_touched = False
        self.selected = 1
        self.controller.write_config(data, cfg_path)

    def _setup_saved_or_skipped(self) -> bool:
        """Before a stage runs: if the setup form was edited but not saved, say what changed and let the person save it first.

        The engine reads only the saved run config, so without this an edited column or layer silently never reaches it.
        True = go on with the run."""
        if self.controller.config_path is None or not self._setup_touched:
            return True
        try:
            data, cfg_path = self._build_setup()
            saved = yaml.safe_load(self.controller.config_path.read_text(encoding="utf8"))
        except Exception as e:
            # the form cannot be turned into a config (incomplete, e.g. a run opened in a new session): say so instead of guessing
            ok = QMessageBox.question(self, tr("Unsaved setup"), tr("The setup form was opened but cannot be checked, so any change in it "
                                      "would not be used:") + f"\n\n{e}\n\n" + tr("Run with the saved setup?"))
            return ok == QMessageBox.StandardButton.Yes
        changes = setup_changes(saved, data)
        if cfg_path != self.controller.config_path:
            changes = ["run.output_gpkg"] + [c for c in changes if c != "run.output_gpkg"]
        if not changes:
            self._setup_touched = False
            return True
        box = QMessageBox(self)
        box.setWindowTitle(tr("Unsaved setup"))
        box.setText(tr("The setup has changes that are not saved, so the engine would not use them:") + "\n\n" +
                    "\n".join(f"- {c}" for c in changes[:12]) + (f"\n- ... (+{len(changes) - 12})" if len(changes) > 12 else ""))
        save = box.addButton(tr("Save setup"), QMessageBox.ButtonRole.AcceptRole)
        run = box.addButton(tr("Run without saving"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(tr("Cancel"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is save:
            self._save_setup(data, cfg_path)     # the changed inputs make the stages out of date; the person re-runs them knowingly
            return False
        return box.clickedButton() is run

    def _start_over(self) -> None:
        if self.controller.config_path is None or self.controller.running is not None:
            return
        ok = QMessageBox.question(self, tr("Start over"), tr("This deletes the results of this run (the GeoPackage, the work folder and the report) "
                                                              "and takes its layers off the map. Your settings and your data are kept. Continue?"))
        if ok == QMessageBox.StandardButton.Yes:
            self.selected = 1
            self.controller.reset_run()

    def _toggle_preset(self, on: bool) -> None:
        if self.controller.config_path is not None:          # a run is open: apply at once (a new run reads it on Create)
            self.controller.set_preset(on)

    def _sync_preset_box(self, model) -> None:
        """Show what the open run actually uses, without re-triggering the toggle."""
        if model is None or self.controller.config_path is None:
            return
        want = bool(model.preset_path)
        if self.use_preset.isChecked() != want:
            self.use_preset.blockSignals(True)
            self.use_preset.setChecked(want)
            self.use_preset.blockSignals(False)

    def _open_run(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Open a run config"), "", "YAML (*.yaml *.yml)")
        if path:
            self._fill_setup(path)
            self._setup_open = False
            self._setup_touched = False
            self.selected = None
            self.controller.open_run(path)

    def _load_setup_file(self) -> None:
        """Fill the form from a saved setup or another run's config, to repeat a run without picking every layer again.
        Nothing runs: change what differs (usually the output GeoPackage), then Create run."""
        path, _ = QFileDialog.getOpenFileName(self, tr("Load a saved setup"), "", tr("Setup files") + " (*.json *.yaml *.yml)")
        if path:
            self._fill_setup(path)

    def _save_setup_file(self) -> None:
        try:
            data, _cfg = self._build_setup()
        except Exception as e:
            self.setup_msg.setText(f"<span style='color:{theme.RED_TEXT}'>{e}</span>".replace("\n", "<br>"))
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("Save the setup"), "repeat_pump_setup.json", SETUP_FILTER)
        if path:
            write_setup(data, path)
            self.setup_msg.setText(tr("Setup saved: {path}").format(path=path))

    def _fill_setup(self, path: str) -> None:
        """Choose in the form every layer, file and setting a saved setup names; layers not yet on the map are added."""
        try:
            data = read_setup(path)
        except Exception as e:
            self.setup_msg.setText(f"<span style='color:{theme.RED_TEXT}'>" + tr("Could not read the setup: {err}").format(err=e) + "</span>")
            return
        self._fill_setup_data(data, tr("Setup loaded from {path}.").format(path=path), preset=bool(data.get("preset")))

    # ------------------------------------------------------------------ KHG work folders
    def _khg_root(self) -> str:
        from qgis.core import QgsSettings
        return str(QgsSettings().value("repeat_pump/khg_root", "") or os.environ.get("REPEAT_KHG", ""))

    def _choose_khg_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("Folder that holds the KHG work folders (_khg)"), self._khg_root())
        if path:
            from qgis.core import QgsSettings
            QgsSettings().setValue("repeat_pump/khg_root", path)
            self._refresh_khg_list()

    def _refresh_khg_list(self) -> None:
        from ..khgsetup import khg_folders
        self.khg_combo.clear()
        folders = khg_folders(self._khg_root()) if self._khg_root() else []
        self.khg_combo.addItem(tr("Choose a KHG...") if folders else tr("No KHG folders yet: choose the _khg folder"), None)
        for p in folders:
            self.khg_combo.addItem(p.name, str(p))

    def _fill_from_khg(self, folder: Optional[str]) -> None:
        if not folder:
            return
        from ..khgsetup import setup_from_khg
        data, missing = setup_from_khg(folder)
        msg = tr("Filled from the KHG folder {name}.").format(name=Path(folder).name)
        if missing:
            msg += " " + tr("Not found there, choose them yourself: {items}").format(items=", ".join(missing))
        self._fill_setup_data(data, msg, preset=True)

    def _fill_setup_data(self, data: dict, message: str, preset: bool) -> None:
        missing = []
        for key, refs in form_inputs(data).items():
            layers = [find_or_add_layer(p, name) for p, name in refs]
            missing += [p for (p, _n), lyr in zip(refs, layers) if lyr is None]
            if key in self.combos and layers and layers[0] is not None:
                self.combos[key][0].setLayer(layers[0])
            if key == "moisture":
                self.extras.set_extra_moisture([lyr for lyr in layers[1:] if lyr is not None])
        run = data.get("run") or {}
        if run.get("output_gpkg"):
            self.out_file.setFilePath(run["output_gpkg"])
        prio = (data.get("inputs") or {}).get("subkhg_priority") or {}
        self.priority.setFilePath(prio.get("path", ""))
        self.use_preset.blockSignals(True)
        self.use_preset.setChecked(preset)
        self.use_preset.blockSignals(False)
        self.extras.load_from(data)
        msg = message
        if missing:
            msg += f"<br><span style='color:{theme.AMBER_TEXT}'>" + tr("Not found, choose again: {files}").format(files=", ".join(missing)) + "</span>"
        self.setup_msg.setText(msg)

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
        self.preview_box.setText(tr("Demo view"))
        self.preview_box.setToolTip(tr("Show every stage's decisions and map tools at once, even before they can run. Nothing is run or changed."))
        self.use_preset.setText(tr(self.use_preset.property("src")))
        self.extras.retranslate()
        for w in self.setup_frame.findChildren(QLabel) + self.setup_frame.findChildren(QPushButton):
            src = w.property("src")
            if src:
                w.setText(tr(src))
        self.log_toggle.setText(tr("Hide log") if self.log_view.isVisible() else tr("Show log"))
        self.controller.reload_state()          # rebuilds the model (its texts are translated) and re-renders
        self._last_sig = None
        self.render()

    # ------------------------------------------------------------------ events
    def _toggle_preview(self, on: bool) -> None:
        self.preview = on
        if on:
            self.controller.load_preview()
        self._last_sig = None
        self.render()

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
        run = model.check["run_name"]
        if code in (0, 2) and self.controller.output_gpkg:
            ran = [v for v in model.stages if v.id >= stage and v.status in ("done", "needs_review")] or [view]
            ran = [v for v in ran if v.id <= max(stage, model.current)]
            shown = None
            for v in ran:                                   # a run to the next review covers several stages
                names = styling.load_layers(self.controller.output_gpkg, v.layers, run) if v.layers else []
                rasters = styling.load_rasters(model.state.get("report", {}).get("inputs", {}), run, vm.STAGE_RASTERS.get(v.id)) \
                    if v.id in vm.STAGE_RASTERS else []
                if names or rasters:
                    shown = v.id
            if shown is not None:
                maptools.show_stage(run, shown)
                maptools.zoom_to_stage(self.iface, run)
        self.selected = model.current
        self._last_sig = None
        self.render()

    def hideEvent(self, event) -> None:
        self.canal_editor.stop()                      # the map tools must not outlive the panel
        self.sekat_editor.stop()
        self.route_editor.stop()
        self.segment_explainer.stop()
        super().hideEvent(event)

    def _select(self, sid: int) -> None:
        if sid != 2:
            self.canal_editor.stop()
        if sid != 7:
            self.sekat_editor.stop()
        if sid != 9:
            self.route_editor.stop()
        if sid < 6:
            self.segment_explainer.stop()
        self.selected = sid
        self._last_sig = None
        self.render()

    def _act(self, action: str, sid: int) -> None:
        if not self._setup_saved_or_skipped():
            return
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
        model = c.model or vm.WizardModel(c.preview_json if (self.preview and c.preview_json) else vm.placeholder_check(),
                                          {"stages": {}, "warnings": [], "report": {}}, None, bool(c.engine_ready))
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
        self._sync_preset_box(model)

        sig = (view.id, view.status, tuple((p.key, p.from_preset) for p in view.params), tuple(p.key for p in view.options),
               view.id in self._options_open, len(view.tiles), view.error, self.learn, self.preview, c.preview_json is not None, c.engine_ready,
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
        self._sync_progress(model)

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
        self._tools_live = view.status in ("done", "needs_review", "stale") and self.controller.output_gpkg is not None
        if self.preview and not self._tools_live:
            b.addWidget(self._callout("info", "Demo view", "This is what the stage offers. Nothing here runs yet: the decisions and the map tools switch on "
                                      "once the stage before it has run and this stage has results."))
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
            card_ = self._params_card(view)
            card_.setEnabled(has_run)                 # without a run there is no config to write into: show it, do not let it be edited
            b.addWidget(card_)
        if view.options:
            card_ = self._options_card(view)
            card_.setEnabled(has_run)
            b.addWidget(card_)
        if (self._tools_live and (view.layers or view.id in maptools.STAGE_VISIBLE)) or (self.preview and view.id in maptools.STAGE_VISIBLE):
            b.addWidget(self._map_bar(view, model))
            if view.id == 2:
                b.addWidget(self._edit_bar())
            if view.id == 7:
                b.addWidget(self._sekat_edit_bar())
            if view.id == 9:
                b.addWidget(self._route_edit_bar())
        if view.id == 11 and view.status == "done" and self.controller.output_gpkg:
            b.addWidget(self._results_card())
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
        if view.optional and view.status in ("ready", "locked", "skipped"):
            suffix = " · OPTIONAL"
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
        svg = diagrams.svg_for(view.id)
        if svg:                                           # the key idea of the stage as one small picture
            pic = QLabel()
            pic.setPixmap(svg_picture(svg, diagrams.W, diagrams.H))
            pic.setAccessibleName(tr("Diagram of the key idea of this stage"))
            lay.addWidget(pic, 1, 0, 1, 2 if not self.compact else 1)
        return w

    def _results_card(self) -> QWidget:
        """The final screen: the run's key results in one place, and where the outputs are."""
        gpkg = self.controller.output_gpkg
        rep = summary.load_report(gpkg)
        f, lay = card()
        lay.addWidget(label("Results at a glance", "cardTitle"))
        if rep is None:
            lay.addWidget(label("The run report could not be read.", "hint"))
        else:
            s = summary.summarise(rep)
            cols = 2 if self.compact else 4
            for sec in s.sections:                          # each section a row of tiles: the number first, the label under it
                lay.addWidget(label(sec.title, "paramLabel"))
                g = QGridLayout()
                g.setSpacing(12)
                for i, (name, value) in enumerate(sec.rows):
                    t = QFrame()
                    t.setObjectName("tile")
                    tl = QVBoxLayout(t)
                    tl.setContentsMargins(16, 12, 16, 12)
                    tl.setSpacing(0)
                    tl.addWidget(label(name, "tileLabel"))
                    tl.addWidget(label(value, "tileValue", wrap=False))
                    g.addWidget(t, i // cols, i % cols)
                for k in range(cols):
                    g.setColumnStretch(k, 1)
                lay.addLayout(g)
            if s.pump_table:
                lay.addWidget(label("Pump stations", "paramLabel"))
                table = QGridLayout()
                table.setHorizontalSpacing(18)
                for r, row in enumerate(s.pump_table):
                    for c, cell in enumerate(row):
                        table.addWidget(label(cell, "paramLabel" if r == 0 else "paramHelp", wrap=False) if r == 0 else
                                        QLabel(cell), r, c)
                lay.addLayout(table)
            for note in s.notes:
                lay.addWidget(label(note, "hint"))
        row = QHBoxLayout()
        folder = gpkg.parent
        row.addWidget(button("Open the run folder", "secondary", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))))
        row.addWidget(button("Open run report", "secondary", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder / "run_report.md")))))
        row.addStretch(1)
        lay.addLayout(row)
        return f

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

    def _param_rows(self, lay: QVBoxLayout, params: list) -> None:
        for p in params:
            fld = vm.field_for(p.key)
            lay.addWidget(label(fld.label + ("  " + tr("(needed if river water levels are used)") if p.recommended else ""), "paramLabel"))
            if fld.help:
                lay.addWidget(label(fld.help, "paramHelp"))
            if p.from_preset:
                lay.addWidget(label("Proposed default, not a team decision. Enter a value to make it yours; the run report lists it until then.", "paramProposed"))
            row = QHBoxLayout()
            ed = self._editor(p, fld)
            self._editors[p.key] = ed
            row.addWidget(ed, 1)
            if fld.unit and fld.kind in ("float", "int", "floatlist"):
                row.addWidget(label(fld.unit, "paramUnit", wrap=False))
            lay.addLayout(row)

    def _params_card(self, view: vm.StageView) -> QWidget:
        f, lay = card()
        n_missing = sum(1 for p in view.params if p.missing and not p.recommended)
        head = "Decisions for this stage" if n_missing == 0 else tr("Decisions needed ({n})").format(n=n_missing)
        lay.addWidget(label(head, "cardTitle"))
        lay.addWidget(label("These values are choices for your team. Values marked proposed come from the proposed defaults; replace them with your own. They are saved in the run config.", "hint"))
        self._param_rows(lay, view.params)
        return f

    def _options_card(self, view: vm.StageView) -> QWidget:
        """Settings that already have a default. Folded away so a first-time trainee is not asked about them."""
        f, lay = card()
        is_open = view.id in self._options_open
        head = QHBoxLayout()
        head.addWidget(label(tr("Advanced settings ({n})").format(n=len(view.options)), "cardTitle"), 1)
        head.addWidget(button("Hide" if is_open else "Show", "link", lambda sid=view.id: self._toggle_options(sid)))
        lay.addLayout(head)
        if is_open:
            lay.addWidget(label("These have sensible defaults. Change one only when you know why. Leave a field empty to go back to the default.", "hint"))
            self._param_rows(lay, view.options)
        return f

    def _toggle_options(self, sid: int) -> None:
        self._options_open.symmetric_difference_update({sid})
        self._last_sig = None
        self.render()

    def _editor(self, p: vm.Param, fld: vm.Field_) -> QWidget:
        if fld.kind == "matrix":
            ed = AhpEditor(p.value, lambda m, k=p.key: self._commit(k, m))
            prop(ed, missing=p.missing, paramKey=p.key)
            return ed
        if fld.kind == "multi":
            return self._multi_editor(p, fld)
        if fld.kind in ("bool", "enum"):
            cb = QComboBox()
            names = vm.option_labels(fld) if fld.kind == "enum" else [tr("Yes"), tr("No")]
            codes = list(fld.options) if fld.kind == "enum" else [True, False]
            undecided = not p.option                      # a setting with a default always has a value; a decision may still be open
            items = ([tr("Not decided")] if undecided else []) + names
            cb.addItems(items)
            if p.value in codes:
                cb.setCurrentIndex(codes.index(p.value) + (1 if undecided else 0))
            else:
                cb.setCurrentIndex(0)
            prop(cb, missing=p.missing, paramKey=p.key)
            cb.currentIndexChanged.connect(lambda i, k=p.key, cs=codes, u=undecided, o=p.option: self._commit(
                k, None if (u and i == 0) else cs[i - (1 if u else 0)], o))
            return cb
        text = "" if p.value is None else (vm.format_list(p.value) if fld.kind == "floatlist" else
                                            ", ".join(str(x) for x in p.value) if fld.kind == "idlist" and p.value else str(p.value))
        le = QLineEdit(text)
        le.setPlaceholderText(tr("Engine default") if p.option else tr("Not decided yet"))
        le.setProperty("saved", "" if p.value is None or p.from_preset else text)   # typing a proposed value again pins it
        prop(le, missing=p.missing, invalid=False, paramKey=p.key)
        le.editingFinished.connect(lambda k=p.key, kind=fld.kind, w=le, o=p.option: self._commit_text(k, kind, w, o))
        return le

    def _multi_editor(self, p: vm.Param, fld: vm.Field_) -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        boxes = []
        chosen = list(p.value or [])

        def changed(_state, boxes=boxes, key=p.key, codes=list(fld.options), option=p.option):
            picked = [c for c, b in zip(codes, boxes) if b.isChecked()]
            if not picked and key in vm.EMPTY_OK:          # nothing ticked means "no filter": the engine default applies again
                self._commit(key, None, option)
                return
            if not picked:                                 # at least one method must stay on
                boxes[0].blockSignals(True)
                boxes[0].setChecked(True)
                boxes[0].blockSignals(False)
                picked = [codes[0]]
            self._commit(key, picked, option)
        for code, name in zip(fld.options, vm.option_labels(fld)):
            cb = QCheckBox(name)
            cb.setChecked(code in chosen)
            cb.stateChanged.connect(changed)
            boxes.append(cb)
            col.addWidget(cb)
        prop(box, missing=p.missing, paramKey=p.key)
        return box

    def _commit_text(self, key: str, kind: str, w: QLineEdit, option: bool = False) -> None:
        text = w.text().strip()
        if text == w.property("saved"):
            return
        try:
            if not text:
                value = None
            elif kind == "float":
                value = float(text.replace(",", "."))
            elif kind == "int":
                value = int(text)
            elif kind == "floatlist":
                value = vm.parse_floatlist(text, 2 if key == "prioritise.ring_buffer_m" else None)
                if value is None:
                    raise ValueError(text)
            elif kind == "idlist":
                value = vm.parse_idlist(text) or None
            else:
                value = text
        except ValueError:
            prop(w, invalid=True)
            return
        prop(w, invalid=False)
        w.setProperty("saved", text)
        self._commit(key, value, option)

    def _commit(self, key: str, value, option: bool = False) -> None:
        (self.controller.set_option if option else self.controller.set_param)(key, value)

    # ---- map toolbar
    def _map_bar(self, view: vm.StageView, model: vm.WizardModel) -> QWidget:
        f, lay = card()
        lay.addWidget(label("Map", "cardTitle"))
        row = QHBoxLayout()
        live = self._tools_live
        row.addWidget(button("Show this stage on the map", "secondary", lambda sid=view.id: self._show_on_map(sid), live))
        row.addWidget(button("Show every layer", "ghost", lambda: self._show_all(), live))
        if view.id >= 6:
            row.addWidget(button("Explain a segment", "secondary", self.segment_explainer.start, live and self.segment_explainer.available))
        if view.id == 11:
            row.addWidget(button("Export the map...", "secondary", self._export_map, live))
        row.addStretch(1)
        lay.addLayout(row)
        return f

    def _edit_bar(self) -> QWidget:
        """Stage 2: fix the canal network on the map (see canal_edit.py)."""
        f, lay = card()
        lay.addWidget(label("Fix the canals on the map", "cardTitle"))
        lay.addWidget(label("Add a canal the data misses, or delete one that should not be there. Your edits are kept in canal_edits.gpkg in the run folder "
                            "and applied the next time stages 1 and 2 run.", "paramHelp"))
        ed = self.canal_editor
        row = QHBoxLayout()
        row.addWidget(button("Draw a canal to add", "secondary", ed.start_add, ed.available and self._tools_live))
        row.addWidget(button("Click a canal to delete", "secondary", ed.start_delete, ed.available and self._tools_live))
        row.addStretch(1)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(button("Save my edits", "primary", self._save_canal_edits, ed.available and self._tools_live))
        row.addWidget(button("Stop editing", "ghost", ed.stop, ed.available))
        row.addStretch(1)
        lay.addLayout(row)
        if not ed.available:
            lay.addWidget(label("These tools need the QGIS map and an open run.", "paramHelp"))
        return f

    def _sekat_edit_bar(self) -> QWidget:
        """Stage 7: change the proposed sekat on the map (see canal_edit.py)."""
        f, lay = card()
        lay.addWidget(label("Change the proposed sekat on the map", "cardTitle"))
        lay.addWidget(label("Add a sekat the head rule did not place, or remove a proposed one. Your edits are kept in sekat_edits.gpkg in the run folder "
                            "and applied the next time stage 7 runs. Added sekat are marked as manual.", "paramHelp"))
        ed = self.sekat_editor
        row = QHBoxLayout()
        row.addWidget(button("Add a sekat", "secondary", ed.start_add, ed.available and self._tools_live))
        row.addWidget(button("Remove a proposed sekat", "secondary", ed.start_remove, ed.available and self._tools_live))
        row.addStretch(1)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(button("Save my edits", "primary", self._save_sekat_edits, ed.available and self._tools_live))
        row.addWidget(button("Stop editing", "ghost", ed.stop, ed.available))
        row.addStretch(1)
        lay.addLayout(row)
        if not ed.available:
            lay.addWidget(label("These tools need the QGIS map and an open run.", "paramHelp"))
        return f

    def _route_edit_bar(self) -> QWidget:
        """Stage 9: change the water sources and targets on the map (see canal_edit.py)."""
        f, lay = card()
        lay.addWidget(label("Change the water sources and targets on the map", "cardTitle"))
        lay.addWidget(label("Add a water source the river layer misses, exclude one you cannot use (for example salty or tidal), add a target where water must arrive, "
                            "or remove a computed one. Your edits are kept in route_edits.gpkg in the run folder and applied the next time stages 8 and 9 run.", "paramHelp"))
        ed = self.route_editor
        for pair in ((("Add a water source", ed.start_add_source), ("Exclude a water source", ed.start_exclude_source)),
                     (("Add a target", ed.start_add_target), ("Remove a target", ed.start_remove_target))):
            row = QHBoxLayout()
            for text, slot in pair:
                row.addWidget(button(text, "secondary", slot, ed.available and self._tools_live))
            row.addStretch(1)
            lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(button("Save my edits", "primary", self._save_route_edits, ed.available and self._tools_live))
        row.addWidget(button("Stop editing", "ghost", ed.stop, ed.available))
        row.addStretch(1)
        lay.addLayout(row)
        if not ed.available:
            lay.addWidget(label("These tools need the QGIS map and an open run.", "paramHelp"))
        return f

    def _save_route_edits(self) -> None:
        if self.route_editor.apply():
            self._select(8)

    def _save_sekat_edits(self) -> None:
        if self.sekat_editor.apply():
            self._select(7)

    def _save_canal_edits(self) -> None:
        if self.canal_editor.apply():
            self._select(1)

    def _run_name(self) -> str:
        m = self.controller.model
        return (m.check.get("run_name") if m else "") or ""

    def _show_on_map(self, sid: int) -> None:
        maptools.show_stage(self._run_name(), sid)
        maptools.zoom_to_stage(self.iface, self._run_name())

    def _show_all(self) -> None:
        maptools.show_all(self._run_name())
        maptools.zoom_to_stage(self.iface, self._run_name())

    def _export_map(self) -> None:
        run = self._run_name()
        layers = maptools.visible_layers(run)
        if not layers:
            self._notice("warning", tr("There is nothing on the map to export. Use Show this stage on the map first."))
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("Export the map"), f"{run}_map.pdf", "PDF (*.pdf);;PNG (*.png)")
        if not path:
            return
        note = tr("Includes values from the proposed defaults (not team decisions).") if self.controller.model and self.controller.model.preset_path else ""
        try:
            maptools.export_map(run, self.selected or 11, path, layers[0].crs(), note)
            self._notice("success", tr("Map saved to {path}.").format(path=path))
        except Exception as e:
            self._notice("error", tr("The map could not be exported: {err}").format(err=e))

    # ---- progress
    def _on_progress(self, stage: int, fraction: float, text: str) -> None:
        self._progress = (stage, fraction, text)
        self._update_progress()

    def _sync_progress(self, model: vm.WizardModel) -> None:
        running = self.controller.running
        if running is not None and self._run_started is None:
            import time
            self._run_started = time.monotonic()
            self._progress = (running, 0.0, "")
            self._ticker.start()
        elif running is None and self._run_started is not None:
            self._run_started = None
            self._ticker.stop()
        self.progress_frame.setVisible(running is not None)
        self._update_progress()

    def _update_progress(self) -> None:
        c = self.controller
        if c.running is None or self._run_started is None or c.model is None:
            return
        import time
        stage, frac, text = self._progress
        elapsed = int(time.monotonic() - self._run_started)
        view = c.model.stage(c.running)
        self.progress_text.setText(f"{tr('Stage {n}').format(n=c.running)}: {tr(view.title)}"
                                   + (f" · {text}" if text else "") + f" · {elapsed // 60}:{elapsed % 60:02d}")
        if frac > 0:
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(int(frac * 1000))
        else:
            self.progress_bar.setRange(0, 0)               # busy, no figure yet
        done = sum(1 for v in c.model.stages if v.status in ("done", "skipped"))
        self.progress_overall.setText(tr("{done} of {total} stages done").format(done=done, total=len(c.model.stages)))

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
            add(tr("Run stage {n} only").format(n=view.id), "secondary", lambda: self._act("run", view.id), view.can_run)
            add("Run to the next review", "primary", lambda: self._act("run_on", view.id), view.can_run)
        elif view.status == "needs_review":
            nxt = model.stage(view.id + 1).title if view.id < len(model.stages) else ""
            add("Re-run this stage", "secondary", lambda: self._act("rerun", view.id), view.can_rerun)
            add(tr("Accept and continue: {title}").format(title=nxt) if nxt else tr("Accept and continue"), "primary", lambda: self._act("accept_on", view.id), view.can_accept)
            note.setText(view.blocking)
        elif view.status == "done":
            add("Re-run this stage", "secondary", lambda: self._act("rerun", view.id), view.can_rerun)
            if view.id < len(model.stages):
                add(tr("Next: {title}").format(title=model.stage(view.id + 1).title), "primary", lambda: self._select(view.id + 1))
            note.setText(view.blocking)
        elif view.status == "skipped":
            note.setText(tr("This optional stage is switched off. Choose Yes under Decisions to use it."))
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
