"""The parts of the run setup that need to know about the chosen layers: more moisture tiles, which sub-KHGs to analyse, the
coordinate system and vertical datum read from the DTM, and the early checks of ``preflight``."""
from __future__ import annotations

from typing import Callable, Optional

from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QSpinBox, QVBoxLayout, QWidget

from . import preflight, theme
from .i18n import tr
from .widgets import button, label, layer_filter

SELECTION_MODES = [("top_n", "Highest-priority sub-KHGs"), ("ids", "Chosen sub-KHGs"), ("all", "All sub-KHGs")]


class SetupExtras(QWidget):
    """``get_layers`` returns ``{config key: QgsMapLayer or None}`` for the layers chosen in the main form."""
    changed = pyqtSignal()

    def __init__(self, get_layers: Callable[[], dict], parent=None):
        super().__init__(parent)
        self._get_layers = get_layers
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
        self.add_moisture = button("Add another moisture raster (a neighbouring tile)", "link", self._add_moisture)
        lay.addWidget(self.add_moisture, 0, Qt.AlignmentFlag.AlignLeft)

        # which sub-KHGs
        lay.addWidget(label("Sub-KHGs to analyse", "paramLabel"))
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.currentIndexChanged.connect(self._mode_changed)
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

        # coordinate system and datum
        lay.addWidget(label("Coordinate system and vertical datum", "paramLabel"))
        self.crs_note = label("", "paramHelp")
        lay.addWidget(self.crs_note)
        self.reproject = QCheckBox()
        self.reproject.toggled.connect(lambda _b: self.refresh())
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
        self.datum.setPlaceholderText(tr("Vertical datum, for example EGM2008"))
        self.use_selected.setText(tr("Use the features selected on the map"))
        self.add_moisture.setText(tr("Add another moisture raster (a neighbouring tile)"))
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

    def moisture_layers(self) -> list:
        return [cb.currentLayer() for cb in self.extra_moisture if cb.currentLayer() is not None]

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

    # ------------------------------------------------------------------ checks
    def refresh(self) -> None:
        layers = self._get_layers()
        infos = {role: preflight.info_from_layer(role, lyr) for role, lyr in layers.items()}
        for k, cb in enumerate(self.extra_moisture):
            infos[f"moisture_{k + 2}"] = preflight.info_from_layer("moisture", cb.currentLayer())
        a = self.assessment = preflight.assess({r: i for r, i in infos.items() if i is not None}, reproject=self.reproject.isChecked())
        self._fill_ids(layers.get("subkhg"), a.subkhg_id_field)
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

    def errors(self) -> list[str]:
        out = [f.text for f in self.assessment.errors]
        if self.mode.currentData() == "ids" and not self.checked_ids():
            out.append(tr("Tick at least one sub-KHG, or choose another way to select them."))
        return out

    # ------------------------------------------------------------------ result
    def params(self) -> dict:
        """Dotted config keys for the run YAML."""
        a = self.assessment
        p: dict = {}
        if a.crs:
            p["run.crs"] = a.crs
        p["run.auto_reproject"] = bool(self.reproject.isChecked())
        mode = self.mode.currentData()
        p["run.subkhg_selection.mode"] = mode
        if mode == "top_n":
            p["run.subkhg_selection.n"] = int(self.n.value())
        elif mode == "ids":
            p["run.subkhg_selection.ids"] = self.checked_ids()
        datum = self.datum.text().strip()
        if datum:
            p["run.vertical_datum"] = datum
            p["inputs.rivers.vertical_datum"] = datum
        return p

    def moisture_paths(self, first: Optional[str]) -> list[str]:
        paths = [first] if first else []
        paths += [l.source() for l in self.moisture_layers()]
        return paths
