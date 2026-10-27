"""The parts of the run setup that need to know about the chosen layers: more moisture tiles, which sub-KHGs to analyse, the
coordinate system and vertical datum read from the DTM, and the early checks of ``preflight``."""
from __future__ import annotations

import csv
from typing import Callable, Optional

from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QSpinBox, QVBoxLayout, QWidget

from . import cloudload, preflight, theme
from .i18n import tr
from .widgets import button, clear, label, layer_filter

ROLE_NAMES = {"subkhg": "Sub-KHG polygons", "subkhg_priority": "Sub-KHG priority table (CSV, optional)", "canals": "Canal lines",
              "sekat_existing": "Existing sekat (optional)", "rivers": "Rivers", "burn_area": "Burn-scar polygons", "peat_depth": "Peat depth (class polygons or a depth raster)"}


def csv_header(path: str) -> list[str]:
    """Column names of a CSV file (empty when it cannot be read)."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            return next(csv.reader(fh), [])
    except (OSError, UnicodeDecodeError, csv.Error):
        return []


SELECTION_MODES = [("top_n", "Highest-priority sub-KHGs"), ("ids", "Chosen sub-KHGs"), ("all", "All sub-KHGs")]


def dtm_source_guess(path: str) -> str:
    """What a DTM file probably is, from its name: lidar | deltadtm | demnas, or '' when the name does not say."""
    n = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for key, words in (("deltadtm", ("deltadtm",)), ("demnas", ("demnas",)), ("lidar", ("lidar",))):
        if any(w in n for w in words):
            return key
    return ""


class SetupExtras(QWidget):
    """``get_layers`` returns ``{config key: QgsMapLayer or None}`` for the layers chosen in the main form."""
    changed = pyqtSignal()

    def __init__(self, get_layers: Callable[[], dict], on_cloud_raster: Optional[Callable[[str], None]] = None,
                 on_cloud_burn: Optional[Callable[[str], None]] = None, get_out_dir: Optional[Callable[[], Optional[str]]] = None,
                 get_priority: Optional[Callable[[], str]] = None, parent=None):
        super().__init__(parent)
        self._get_priority = get_priority or (lambda: "")
        self._col_choice: dict[tuple[str, str], str] = {}      # (input, expected column) -> the user's column
        self._col_signature: tuple = ()
        self._get_layers = get_layers
        self._on_cloud_raster = on_cloud_raster
        self._on_cloud_burn = on_cloud_burn
        self._get_out_dir = get_out_dir or (lambda: None)
        self._datum_edited = False
        self._ids_for: tuple = ()
        self.assessment = preflight.Assessment()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # more moisture tiles (the engine mosaics them)
        self.extra_moisture: list[QgsMapLayerComboBox] = []
        self.moisture_box = QVBoxLayout()
        self.moisture_box.setSpacing(6)
        lay.addLayout(self.moisture_box)
        self.cloud_btn = button("Load moisture from the cloud...", "secondary", self._open_cloud)
        lay.addWidget(self.cloud_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.burn_btn = button("Load burn scars from the cloud...", "secondary", self._open_burn)
        lay.addWidget(self.burn_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.add_moisture = button("Add another moisture raster (a neighbouring tile)", "link", self._add_moisture)
        lay.addWidget(self.add_moisture, 0, Qt.AlignmentFlag.AlignLeft)

        # which sub-KHGs
        lay.addWidget(label("Sub-KHGs to analyse", "paramLabel"))
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_touched = False
        self.mode.activated.connect(lambda _i: setattr(self, "_mode_touched", True))
        self.n = QSpinBox()
        self.n.setRange(1, 999)
        self.n.setValue(3)
        self.n_label = label("how many", "paramHelp", wrap=False)
        row.addWidget(self.mode, 1)
        row.addWidget(self.n_label)
        row.addWidget(self.n)
        lay.addLayout(row)
        self.ids = QListWidget()
        self.ids.setMaximumHeight(110)
        self.ids.itemChanged.connect(lambda _i: self.changed.emit())
        self.use_selected = button("Use the features selected on the map", "link", self._use_map_selection)
        lay.addWidget(self.ids)
        lay.addWidget(self.use_selected, 0, Qt.AlignmentFlag.AlignLeft)

        # column names that differ from what the engine expects
        self.columns_title = label("Column names", "paramLabel")
        self.columns_note = label("Your data names some columns differently from what the engine expects. Say which of your columns is which.", "paramHelp")
        self.columns_box = QVBoxLayout()
        self.columns_box.setSpacing(4)
        lay.addWidget(self.columns_title)
        lay.addWidget(self.columns_note)
        lay.addLayout(self.columns_box)
        self.columns_title.setVisible(False)
        self.columns_note.setVisible(False)

        # canal classes: what each value of the class column means
        self.classes_title = label("Canal classes", "paramLabel")
        self.classes_note = label("What each value of the canal class column means. The guess is filled in; change it if it is wrong.", "paramHelp")
        self.classes_box = QVBoxLayout()
        self.classes_box.setSpacing(4)
        lay.addWidget(self.classes_title)
        lay.addWidget(self.classes_note)
        lay.addLayout(self.classes_box)
        self._class_choice: dict[str, str] = {}
        self.tertiary = QCheckBox()
        self.tertiary.setChecked(False)
        lay.addWidget(self.tertiary)
        self._classes_for: tuple = ()

        # water source for pumps
        self.pumps = QCheckBox()
        self.pumps.setChecked(True)
        self._pumps_touched = False
        self.pumps.toggled.connect(lambda _b: setattr(self, "_pumps_touched", True))
        lay.addWidget(self.pumps)
        self.pumps_note = label("", "paramHelp")
        lay.addWidget(self.pumps_note)
        self._loaded: dict = {}          # settings from a loaded setup that the form has no widget for (peat units, DTM type, ...)

        # coordinate system and datum
        lay.addWidget(label("Coordinate system and vertical datum", "paramLabel"))
        self.crs_note = label("", "paramHelp")
        lay.addWidget(self.crs_note)
        self.reproject = QCheckBox()
        self._reproject_touched = False
        self.reproject.toggled.connect(lambda _b: self.refresh())
        self.reproject.clicked.connect(lambda _b: setattr(self, "_reproject_touched", True))
        lay.addWidget(self.reproject)
        self.datum = QLineEdit()
        self.datum.textEdited.connect(self._datum_typed)
        lay.addWidget(self.datum)
        self.datum_note = label("", "paramHelp")
        lay.addWidget(self.datum_note)

        self.findings = label("", "paramHelp")
        lay.addWidget(self.findings)
        self.retranslate()

    # ------------------------------------------------------------------ language
    def retranslate(self) -> None:
        cur = self.mode.currentData() if self.mode.count() else "top_n"
        self.mode.blockSignals(True)
        self.mode.clear()
        for code, text in SELECTION_MODES:
            self.mode.addItem(tr(text), code)
        self.mode.setCurrentIndex(max(0, [c for c, _ in SELECTION_MODES].index(cur)))
        self.mode.blockSignals(False)
        self.reproject.setText(tr("Reproject layers that use another coordinate system"))
        self.pumps.setText(tr("Plan pumps (needs a river that can supply water)"))
        self.tertiary.setText(tr("Include tertiary canals (small; off in the KLH guide)"))
        self.datum.setPlaceholderText(tr("Vertical datum, for example EGM2008"))
        self.use_selected.setText(tr("Use the features selected on the map"))
        self.add_moisture.setText(tr("Add another moisture raster (a neighbouring tile)"))
        self.cloud_btn.setText(tr("Load moisture from the cloud..."))
        self._col_signature = ()                    # rebuild the column rows in the new language
        self.burn_btn.setText(tr("Load burn scars from the cloud..."))
        self._mode_changed()
        self.refresh()

    # ------------------------------------------------------------------ moisture tiles
    def _add_moisture(self) -> None:
        cb = QgsMapLayerComboBox()
        cb.setFilters(layer_filter("raster"))
        cb.setAllowEmptyLayer(True)
        cb.setLayer(None)
        cb.layerChanged.connect(lambda _l: self.refresh())
        self.extra_moisture.append(cb)
        self.moisture_box.addWidget(cb)

    def set_extra_moisture(self, layers: list) -> None:
        """Show these layers as the extra moisture tiles (a loaded setup)."""
        clear(self.moisture_box)
        self.extra_moisture = []
        for lyr in layers:
            self._add_moisture()
            self.extra_moisture[-1].setLayer(lyr)

    def moisture_layers(self) -> list:
        return [cb.currentLayer() for cb in self.extra_moisture if cb.currentLayer() is not None]

    # ------------------------------------------------------------------ moisture from the cloud
    def _cloud_extent(self) -> Optional[tuple]:
        """Bounding box (x0, y0, x1, y1) of the sub-KHGs that will be analysed, in the run's coordinate system."""
        from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsRectangle
        layer, crs = self._get_layers().get("subkhg"), self.assessment.crs
        if layer is None or not crs:
            return None
        box = None
        if self.mode.currentData() == "ids" and self.checked_ids():
            want, field = set(self.checked_ids()), self.assessment.subkhg_id_field
            for f in layer.getFeatures():
                if str(f[field]) in want and f.hasGeometry():
                    r = f.geometry().boundingBox()
                    box = QgsRectangle(r) if box is None else (box.combineExtentWith(r) or box)
        if box is None:
            box = layer.extent()
        if layer.crs().authid() != crs:
            box = QgsCoordinateTransform(layer.crs(), QgsCoordinateReferenceSystem(crs), QgsProject.instance()).transformBoundingBox(box)
        return (box.xMinimum(), box.yMinimum(), box.xMaximum(), box.yMaximum())

    def _open_cloud(self) -> None:
        from .cloud_dialog import CloudLoadDialog
        self.refresh()
        dlg = CloudLoadDialog(self._cloud_extent(), self.assessment.crs, self._get_out_dir(), self)
        dlg.loaded.connect(lambda path: self._on_cloud_raster(path) if self._on_cloud_raster else None)
        dlg.exec()

    def _open_burn(self) -> None:
        from .cloud_dialog import BurnLoadDialog
        self.refresh()
        dlg = BurnLoadDialog(self._cloud_extent(), self.assessment.crs, self._get_out_dir(), self)
        dlg.loaded.connect(lambda path: self._on_cloud_burn(path) if self._on_cloud_burn else None)
        dlg.exec()

    def cloud_provenance(self) -> Optional[dict]:
        """Provenance of the chosen moisture layer when it came from the cloud button, else ``None``."""
        layer = self._get_layers().get("moisture")
        return cloudload.read_provenance(layer.source().split("|")[0]) if layer is not None else None

    # ------------------------------------------------------------------ selection
    def _mode_changed(self, *_a) -> None:
        mode = self.mode.currentData()
        self.n.setVisible(mode == "top_n")
        self.n_label.setVisible(mode == "top_n")
        self.ids.setVisible(mode == "ids")
        self.use_selected.setVisible(mode == "ids")
        self.changed.emit()

    def _fill_ids(self, layer, field: str) -> None:
        key = (layer.id() if layer is not None else "", field)
        if key == self._ids_for:
            return
        self._ids_for = key
        keep = {self.ids.item(i).text() for i in range(self.ids.count()) if self.ids.item(i).checkState() == Qt.CheckState.Checked}
        self.ids.blockSignals(True)
        self.ids.clear()
        for v in preflight.subkhg_ids(layer, field):
            it = QListWidgetItem(v)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if v in keep else Qt.CheckState.Unchecked)
            self.ids.addItem(it)
        self.ids.blockSignals(False)

    def _use_map_selection(self) -> None:
        layer = self._get_layers().get("subkhg")
        chosen = set(preflight.subkhg_ids(layer, self.assessment.subkhg_id_field, selected_only=True))
        self.ids.blockSignals(True)
        for i in range(self.ids.count()):
            it = self.ids.item(i)
            it.setCheckState(Qt.CheckState.Checked if it.text() in chosen else Qt.CheckState.Unchecked)
        self.ids.blockSignals(False)
        self.changed.emit()

    def checked_ids(self) -> list[str]:
        return [self.ids.item(i).text() for i in range(self.ids.count()) if self.ids.item(i).checkState() == Qt.CheckState.Checked]

    # ------------------------------------------------------------------ datum
    def _datum_typed(self, _text: str) -> None:
        self._datum_edited = True

    # ------------------------------------------------------------------ column names
    def _rebuild_columns(self) -> None:
        """One row per expected column that the chosen layer does not carry under a name the engine recognises."""
        rows = []
        for role in preflight.COLUMNS:
            info = self._infos.get(role)
            if info is not None and info.fields:
                rows += [(role, col, req, tuple(info.fields)) for col, req in preflight.missing_columns(role, info.fields)]
        signature = tuple(rows)
        if signature == self._col_signature:
            return
        self._col_signature = signature
        clear(self.columns_box)
        for role, col, required, fields in rows:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(label(f"{tr(ROLE_NAMES.get(role, role))}: {col}" + (" *" if required else ""), "paramHelp", wrap=False), 1)
            cb = QComboBox()
            cb.addItem(tr("Choose a column...") if required else tr("Not available"), "")
            choices = [f for f in fields if f.lower() != "fid"]          # GeoPackage's own row id is never the answer
            for f in choices:
                cb.addItem(f, f)
            keep = self._col_choice.get((role, col), "")
            if keep in choices:
                cb.setCurrentIndex(choices.index(keep) + 1)
            cb.currentIndexChanged.connect(lambda _i, r=role, c=col, w=cb: self._column_chosen(r, c, w.currentData()))
            h.addWidget(cb, 2)
            self.columns_box.addWidget(row)
        self.columns_title.setVisible(bool(rows))
        self.columns_note.setVisible(bool(rows))

    def _rebuild_classes(self, layer) -> None:
        """One row per value of the canal class column, with the class it is taken as (guessed, changeable)."""
        info = self._infos.get("canals")
        field = preflight.find_field("canals", "canal_class", info.fields, self.columns().get("canals")) if info is not None else ""
        key = (layer.id() if layer is not None else "", field)
        if key == self._classes_for:
            return
        self._classes_for = key
        clear(self.classes_box)
        values = preflight.value_counts(layer, field) if layer is not None and field else []
        for v, n in values:
            if v not in self._class_choice:
                self._class_choice[v] = preflight.guess_canal_class(v) or "other"
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(label(f"{v}  ({n})", "paramHelp", wrap=False), 1)
            cb = QComboBox()
            for code, text in (("primer", "Primary"), ("sekunder", "Secondary"), ("tersier", "Tertiary"), ("other", "Other, not a canal class")):
                cb.addItem(tr(text), code)
            cb.setCurrentIndex(max(0, cb.findData(self._class_choice[v])))
            cb.currentIndexChanged.connect(lambda _i, val=v, w=cb: self._class_choice.__setitem__(val, w.currentData()))
            h.addWidget(cb, 1)
            self.classes_box.addWidget(row)
        self.classes_title.setVisible(bool(values))
        self.classes_note.setVisible(bool(values))
        self._class_values = [v for v, _n in values]

    def class_map(self) -> dict:
        """``{value: class}`` for the values of the canal class column that are not already the class name itself."""
        return {v: c for v, c in self._class_choice.items() if v in getattr(self, "_class_values", []) and v.strip().lower() != c}

    def _column_chosen(self, role: str, col: str, field: Optional[str]) -> None:
        self._col_choice[(role, col)] = field or ""
        self.refresh()

    def columns(self) -> dict[str, dict[str, str]]:
        """``{input: {expected column: your column}}`` for the choices made, only for inputs that are still chosen."""
        out: dict[str, dict[str, str]] = {}
        for (role, col), field in self._col_choice.items():
            info = getattr(self, "_infos", {}).get(role)
            if field and info is not None and field in info.fields:
                out.setdefault(role, {})[col] = field
        return out

    # ------------------------------------------------------------------ checks
    def refresh(self) -> None:
        layers = self._get_layers()
        infos = {role: preflight.info_from_layer(role, lyr) for role, lyr in layers.items()}
        for k, cb in enumerate(self.extra_moisture):
            infos[f"moisture_{k + 2}"] = preflight.info_from_layer("moisture", cb.currentLayer())
        prio = self._get_priority()
        if prio:
            infos["subkhg_priority"] = preflight.LayerInfo("subkhg_priority", prio.replace("\\", "/").rsplit("/", 1)[-1], fields=csv_header(prio))
        self._infos = {r: i for r, i in infos.items() if i is not None}
        for role, info in self._infos.items():                 # preselect a likely column for each missing required one
            for col, req in preflight.missing_columns(role, info.fields, self.columns().get(role)):
                g = preflight.guess_column(role, col, info.fields) if req else ""
                if g and not self._col_choice.get((role, col)):
                    self._col_choice[(role, col)] = g
        self._rebuild_columns()
        a = preflight.assess(self._infos, reproject=self.reproject.isChecked(), columns=self.columns())
        if a.needs_reproject and not self.reproject.isChecked() and not self._reproject_touched:
            self.reproject.blockSignals(True)               # layers in another system: reproject them, unless the person said no
            self.reproject.setChecked(True)
            self.reproject.blockSignals(False)
            a = preflight.assess(self._infos, reproject=True, columns=self.columns())
        self.assessment = a
        self._fill_ids(layers.get("subkhg"), a.subkhg_id_field)
        self._rebuild_classes(layers.get("canals"))
        if not prio and self.mode.currentData() == "top_n" and not self._mode_touched:
            self.mode.setCurrentIndex(self.mode.findData("all"))   # no priority table: there is no "highest priority"
        if not self._pumps_touched:
            self.pumps.blockSignals(True)
            self.pumps.setChecked(a.river_source)
            self.pumps.blockSignals(False)
        self.pumps_note.setText(tr("Rivers with a dry-season level or a perennial flag can supply pumps.") if a.river_source else
                                tr("No river layer with a dry-season level or a perennial flag: the plan covers sekat only (stages 8 to 10 are skipped)."))
        self.crs_note.setText(tr("Coordinate system for the run: {crs} (taken from the DTM).").format(crs=a.crs) if a.crs else
                              tr("The run's coordinate system is taken from the DTM once you choose it."))
        self.reproject.setVisible(a.needs_reproject or self.reproject.isChecked())
        if not self._datum_edited:
            self.datum.setText(a.vertical_datum)
        if a.vertical_datum and not self._datum_edited:
            self.datum_note.setText(tr("Read from the DTM's metadata. Check that it is right."))
        elif a.river_levels:
            self.datum_note.setText(tr("The rivers have water levels, so this is needed. The DTM does not name its datum: ask the data provider."))
        else:
            self.datum_note.setText(tr("Optional here. It is needed in stage 1 if river water levels are used."))
        color = {"error": theme.RED_TEXT, "warning": theme.AMBER_TEXT, "info": theme.MUTED}
        self.findings.setText("<br>".join(f"<span style='color:{color[f.level]}'>{'•'} {f.text}</span>" for f in a.findings))
        self.changed.emit()

    def load_from(self, data: dict) -> None:
        """Fill column choices, sub-KHG selection, reprojection and datum from a saved setup or run config."""
        inp = data.get("inputs") or {}
        self._loaded = {}
        for key, val in (("inputs.peat_depth.units", (inp.get("peat_depth") or {}).get("units")), ("inputs.dtm.source", (inp.get("dtm") or {}).get("source")),
                         ("inputs.dtm.vertical_rmse_m", (inp.get("dtm") or {}).get("vertical_rmse_m")),
                         ("inputs.moisture.higher_is_wetter", (inp.get("moisture") or {}).get("higher_is_wetter"))):
            if val is not None:
                self._loaded[key] = val
        et = (data.get("optimise") or {}).get("et_mm_day")
        if et is not None:
            self._loaded["optimise.et_mm_day"] = et
        for v, c in ((data.get("topology") or {}).get("canal_class_map") or {}).items():
            self._class_choice[str(v)] = c
        self._classes_for = ()
        classes = (data.get("topology") or {}).get("canal_classes")
        if classes:
            self.tertiary.setChecked("tersier" in [str(c).lower() for c in classes])
        if (data.get("pumping") or {}).get("enabled") is not None:
            self.pumps.setChecked(bool(data["pumping"]["enabled"]))
            self._pumps_touched = True
        for role, sec in (data.get("inputs") or {}).items():
            if isinstance(sec, dict):
                for col, field in (sec.get("columns") or {}).items():
                    self._col_choice[(role, col)] = field
        self._col_signature = ()
        run = data.get("run") or {}
        sel = run.get("subkhg_selection") or {}
        i = self.mode.findData(sel.get("mode", "top_n"))
        if i >= 0:
            self.mode.setCurrentIndex(i)
        if sel.get("n"):
            self.n.setValue(int(sel["n"]))
        self.reproject.setChecked(bool(run.get("auto_reproject")))
        if run.get("vertical_datum"):
            self.datum.setText(str(run["vertical_datum"]))
            self._datum_edited = True
        self._ids_for = ()
        self.refresh()
        want = {str(v) for v in sel.get("ids") or []}
        if want:
            self.ids.blockSignals(True)
            for k in range(self.ids.count()):
                it = self.ids.item(k)
                it.setCheckState(Qt.CheckState.Checked if it.text() in want else Qt.CheckState.Unchecked)
            self.ids.blockSignals(False)
        self.changed.emit()

    def errors(self) -> list[str]:
        out = [f.text for f in self.assessment.errors]
        if self.mode.currentData() == "ids" and not self.checked_ids():
            out.append(tr("Tick at least one sub-KHG, or choose another way to select them."))
        return out

    # ------------------------------------------------------------------ result
    def params(self) -> dict:
        """Dotted config keys for the run YAML."""
        a = self.assessment
        p: dict = dict(self._loaded)
        p["pumping.enabled"] = bool(self.pumps.isChecked())
        p["topology.canal_classes"] = ["primer", "sekunder", "tersier"] if self.tertiary.isChecked() else ["primer", "sekunder"]
        cmap = self.class_map()
        if cmap:
            p["topology.canal_class_map"] = cmap
        if a.crs:
            p["run.crs"] = a.crs
        p["run.auto_reproject"] = bool(self.reproject.isChecked())
        mode = self.mode.currentData()
        p["run.subkhg_selection.mode"] = mode
        if mode == "top_n":
            p["run.subkhg_selection.n"] = int(self.n.value())
        elif mode == "ids":
            p["run.subkhg_selection.ids"] = self.checked_ids()
        dtm = self._get_layers().get("dtm")
        guess = dtm_source_guess(dtm.source() if dtm is not None else "")
        if guess:
            p["inputs.dtm.source"] = guess                     # from the file name; the stage 1 card shows it and can change it
        prov = self.cloud_provenance()
        if prov and "higher_is_wetter" in prov:
            p["inputs.moisture.higher_is_wetter"] = bool(prov["higher_is_wetter"])        # a fact about the index the engine just built
        datum = self.datum.text().strip()
        if datum:
            p["run.vertical_datum"] = datum
            p["inputs.rivers.vertical_datum"] = datum
        return p

    def moisture_paths(self, first: Optional[str]) -> list[str]:
        paths = [first] if first else []
        paths += [l.source() for l in self.moisture_layers()]
        return paths
