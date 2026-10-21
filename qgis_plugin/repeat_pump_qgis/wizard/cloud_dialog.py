"""Dialogs for "Load moisture from the cloud" and "Load burn scars from the cloud": they ask for what only the user can decide (date or
year windows), run ``repeat-pump fetch-moisture`` / ``fetch-burn`` off the UI thread and hand back the path of the file the engine wrote.
All checking and command building is in ``cloudload`` (pure Python)."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QComboBox, QDialog, QDoubleSpinBox, QHBoxLayout, QLineEdit, QProgressBar, QVBoxLayout

from .. import runner
from . import cloudload, theme
from .controller import FnTask, _Feedback
from .i18n import tr
from .widgets import button, file_widget, label

MIN_WIDTH = 520


class EngineDialog(QDialog):
    """A status line, a progress bar and an engine command run off the UI thread. ``extent`` is the sub-KHG bounding box in ``crs`` (metres)."""
    loaded = pyqtSignal(str)             # path of the file the engine wrote
    _line = pyqtSignal(str)              # worker thread -> UI
    _progress = pyqtSignal(float, str)

    def __init__(self, title: str, extent: Optional[tuple], crs: str, parent=None):
        super().__init__(parent)
        self.extent, self.crs = extent, crs
        self._task: Optional[FnTask] = None
        self._errors: list[str] = []
        self.setWindowTitle(tr(title))
        self.setMinimumWidth(MIN_WIDTH)
        self.lay = QVBoxLayout(self)
        self.lay.setSpacing(8)

    def _footer(self) -> None:
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setVisible(False)
        self.lay.addWidget(self.bar)
        self.status = label("", "hint")
        self.lay.addWidget(self.status)
        row = QHBoxLayout()
        self.run_btn = button("Load", "primary", self._run)
        self.close_btn = button("Close", "ghost", self._close)
        row.addWidget(self.run_btn)
        row.addWidget(self.close_btn)
        row.addStretch(1)
        self.lay.addLayout(row)
        self._line.connect(self._on_line)
        self._progress.connect(self._on_progress)

    def _run(self) -> None:
        raise NotImplementedError

    def _busy(self, on: bool) -> None:
        self.run_btn.setEnabled(not on)
        self.bar.setVisible(on)
        if on:
            self.bar.setValue(0)

    def _say(self, text: str, level: str = "info") -> None:
        color = {"error": theme.RED_TEXT, "warning": theme.AMBER_TEXT}.get(level, theme.MUTED)
        self.status.setText(f"<span style='color:{color}'>{text}</span>")

    def _on_line(self, line: str) -> None:
        if line.startswith("ERROR"):
            self._errors.append(line[len("ERROR:"):].strip())
        self.status.setToolTip(line)

    def _on_progress(self, fraction: float, text: str) -> None:
        self.bar.setValue(int(fraction * 100))
        self._say(text)

    def _start(self, args: list[str], description: str, done) -> None:
        python = runner.get_python()
        if not python:
            self._say(tr("The engine environment is not set up yet."), "error")
            return
        self._errors = []
        self._busy(True)

        def work(task):
            fb = _Feedback(task, self._line.emit, lambda _s, f, t: self._progress.emit(f, t))
            code = runner.run_engine(python, args, tempfile.gettempdir(), fb)
            if code != 0:
                raise RuntimeError("; ".join(self._errors) or tr("The engine stopped with exit code {code}.").format(code=code))
            return code

        def finished(result, error):
            self._task = None
            self._busy(False)
            if error:
                self._say(error, "error")
            else:
                done()

        self._task = FnTask(description, work, finished)
        QgsApplication.taskManager().addTask(self._task)

    def _needs_area(self) -> None:
        if not self.extent or not self.crs:
            raise ValueError(tr("Choose the DTM and the sub-KHG polygons first: they give the area and the coordinate system."))

    def _close(self) -> None:
        if self._task is not None:
            self._task.cancel()
        self.reject()

    def closeEvent(self, e):
        if self._task is not None:
            self._task.cancel()
        super().closeEvent(e)


def _margin_row(lay) -> QDoubleSpinBox:
    row = QHBoxLayout()
    row.addWidget(label("Margin around the sub-KHGs", "paramHelp", wrap=False))
    margin = QDoubleSpinBox()
    margin.setRange(0, 20000)
    margin.setDecimals(0)
    margin.setSuffix(" m")
    margin.setValue(cloudload.DEFAULT_MARGIN_M)
    row.addWidget(margin)
    row.addStretch(1)
    lay.addLayout(row)
    return margin


class CloudLoadDialog(EngineDialog):
    """Moisture raster from Sentinel-2 (open) or Earth Engine (exact CPWI v2); ``out_dir`` is where the raster goes by default."""

    def __init__(self, extent: Optional[tuple], crs: str, out_dir: Optional[str], parent=None):
        super().__init__("Load moisture from the cloud", extent, crs, parent)
        lay = self.lay
        lay.addWidget(label("Builds a moisture raster for your sub-KHGs from satellite images stored online. Nothing is installed in QGIS: the engine does the download.", "paramHelp"))
        lay.addWidget(label("Source", "paramLabel"))
        self.source = QComboBox()
        for code, text in cloudload.SOURCES:
            self.source.addItem(tr(text), code)
        self.source.currentIndexChanged.connect(self._source_changed)
        lay.addWidget(self.source)
        self.source_note = label("", "paramHelp")
        lay.addWidget(self.source_note)

        row = QHBoxLayout()
        self.ee_project = QLineEdit()
        self.ee_project.setPlaceholderText(tr("Earth Engine project id"))
        self.ee_signin = button("Sign in to Earth Engine", "secondary", self._sign_in)
        row.addWidget(self.ee_project, 1)
        row.addWidget(self.ee_signin)
        lay.addLayout(row)

        lay.addWidget(label("Primary window (the dry months you want to represent)", "paramLabel"))
        self.p_start, self.p_end = self._pair(lay, "Start: YYYY-MM-DD", "End: YYYY-MM-DD")
        lay.addWidget(label("Fallback window (wider; fills the gaps clouds leave in the primary one)", "paramLabel"))
        self.f_start, self.f_end = self._pair(lay, "Start: YYYY-MM-DD", "End: YYYY-MM-DD")
        lay.addWidget(label("These dates are your decision: they depend on the site and the year, so there is no default.", "paramHelp"))

        row = QHBoxLayout()
        row.addWidget(label("Skip scenes cloudier than", "paramHelp", wrap=False))
        self.cloud = QDoubleSpinBox()
        self.cloud.setRange(1, 100)
        self.cloud.setDecimals(0)
        self.cloud.setSuffix(" %")
        self.cloud.setValue(cloudload.DEFAULT_MAX_CLOUD)
        row.addWidget(self.cloud)
        row.addStretch(1)
        lay.addLayout(row)
        self.margin = _margin_row(lay)

        lay.addWidget(label("Save the raster as", "paramLabel"))
        self.out = file_widget("save", "GeoTIFF (*.tif)")
        self.out.setFilePath(str(Path(out_dir or tempfile.gettempdir()) / "moisture_cloud.tif"))
        lay.addWidget(self.out)
        self._footer()
        self._source_changed()

    @staticmethod
    def _pair(lay, a_text: str, b_text: str) -> tuple[QLineEdit, QLineEdit]:
        row = QHBoxLayout()
        a, b = QLineEdit(), QLineEdit()
        for w, ph in ((a, a_text), (b, b_text)):
            w.setPlaceholderText(tr(ph))
            row.addWidget(w)
        lay.addLayout(row)
        return a, b

    def _source_changed(self, *_a) -> None:
        ee = self.source.currentData() == "ee"
        self.ee_project.setVisible(ee)
        self.ee_signin.setVisible(ee)
        self.cloud.setEnabled(not ee)
        self.source_note.setText(tr("Needs a free Earth Engine account and the earthengine-api package in the engine environment. Gives exactly the CPWI of the team's Earth Engine script, with radar.") if ee else
                                 tr("Sentinel-2 only: no radar and a different cloud mask than the Earth Engine script, so values differ from CPWI. The result is labelled as an approximation."))

    def _busy(self, on: bool) -> None:
        super()._busy(on)
        self.ee_signin.setEnabled(not on)

    def _sign_in(self) -> None:
        self._say(tr("A browser window opens for the Google sign-in. Come back here when it says it is done."))
        self._start(["fetch-moisture", "--ee-authenticate"], "Earth Engine sign-in", lambda: self._say(tr("Signed in to Earth Engine.")))

    def _run(self) -> None:
        try:
            primary, fallback = cloudload.check_windows(self.p_start.text(), self.p_end.text(), self.f_start.text(), self.f_end.text())
            out = self.out.filePath().strip()
            if not out:
                raise ValueError(tr("Choose where to save the raster."))
            self._needs_area()
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            args = cloudload.fetch_args(self.source.currentData(), cloudload.with_margin(self.extent, self.margin.value()), self.crs, out, primary, fallback,
                                        self.cloud.value(), self.ee_project.text())
        except ValueError as e:
            self._say(str(e), "error")
            return
        self._say(tr("Searching for scenes. This can take several minutes: the images are downloaded window by window."))
        self._start(args, "Load moisture from the cloud", lambda: self._done(out))

    def _done(self, out: str) -> None:
        prov = cloudload.read_provenance(out)
        self._say(cloudload.summary(prov) if prov else tr("Done."))
        self.loaded.emit(out)


class BurnLoadDialog(EngineDialog):
    """Burn frequency polygons from MODIS MCD64A1: a coarse automatic fallback for the burn-scar layer KLH normally provides."""

    def __init__(self, extent: Optional[tuple], crs: str, out_dir: Optional[str], parent=None):
        super().__init__("Load burn scars from the cloud", extent, crs, parent)
        lay = self.lay
        lay.addWidget(label("Counts, for every cell, the years in which the MODIS burned-area product saw a fire. It is coarse (about 460 m) and misses small and smouldering peat fires: use your own burn-scar layer when you have one.", "paramHelp"))
        lay.addWidget(label("Years to count (first and last, both included)", "paramLabel"))
        self.first, self.last = CloudLoadDialog._pair(lay, "First year, for example 2015", "Last year")
        lay.addWidget(label("The period is your decision: it sets what burn frequency means, so there is no default.", "paramHelp"))
        self.margin = _margin_row(lay)
        lay.addWidget(label("Save the burn scars as", "paramLabel"))
        self.out = file_widget("save", "GeoPackage (*.gpkg)")
        self.out.setFilePath(str(Path(out_dir or tempfile.gettempdir()) / "burn_area_modis.gpkg"))
        lay.addWidget(self.out)
        self._footer()

    def _run(self) -> None:
        try:
            years = cloudload.check_years(self.first.text(), self.last.text())
            out = self.out.filePath().strip()
            if not out:
                raise ValueError(tr("Choose where to save the burn scars."))
            self._needs_area()
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            args = cloudload.burn_args(cloudload.with_margin(self.extent, self.margin.value()), self.crs, out, years)
        except ValueError as e:
            self._say(str(e), "error")
            return
        self._say(tr("Searching for burned-area products."))
        self._start(args, "Load burn scars from the cloud", lambda: self._done(out))

    def _done(self, out: str) -> None:
        prov = cloudload.read_provenance(out)
        self._say(cloudload.burn_summary(prov) if prov else tr("Done."))
        self.loaded.emit(out)
