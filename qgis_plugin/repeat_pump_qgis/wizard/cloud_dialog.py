"""Dialog for "Load moisture from the cloud": asks for the date windows and the source, runs ``repeat-pump fetch-moisture`` off the
UI thread and hands back the path of the raster it wrote. All checking and command building is in ``cloudload`` (pure Python)."""
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


class CloudLoadDialog(QDialog):
    """``extent`` is the sub-KHG bounding box in ``crs`` (metres); ``out_dir`` is where the raster goes by default."""
    loaded = pyqtSignal(str)             # path of the written GeoTIFF
    _line = pyqtSignal(str)              # worker thread -> UI
    _progress = pyqtSignal(float, str)

    def __init__(self, extent: tuple, crs: str, out_dir: Optional[str], parent=None):
        super().__init__(parent)
        self.extent, self.crs = extent, crs
        self._task: Optional[FnTask] = None
        self._errors: list[str] = []
        self.setWindowTitle(tr("Load moisture from the cloud"))
        self.setMinimumWidth(MIN_WIDTH)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.addWidget(label("Builds a moisture raster for your sub-KHGs from satellite images stored online. Nothing is installed in QGIS: the engine does the download.", "paramHelp"))

        lay.addWidget(label("Source", "paramLabel"))
        self.source = QComboBox()
        for code, text in cloudload.SOURCES:
            self.source.addItem(tr(text), code)
        self.source.currentIndexChanged.connect(self._source_changed)
        lay.addWidget(self.source)
        self.source_note = label("", "paramHelp")
        lay.addWidget(self.source_note)

        self.ee_row = QHBoxLayout()
        self.ee_project = QLineEdit()
        self.ee_project.setPlaceholderText(tr("Earth Engine project id"))
        self.ee_signin = button("Sign in to Earth Engine", "secondary", self._sign_in)
        self.ee_row.addWidget(self.ee_project, 1)
        self.ee_row.addWidget(self.ee_signin)
        lay.addLayout(self.ee_row)

        lay.addWidget(label("Primary window (the dry months you want to represent)", "paramLabel"))
        self.p_start, self.p_end = self._date_pair(lay)
        lay.addWidget(label("Fallback window (wider; fills the gaps clouds leave in the primary one)", "paramLabel"))
        self.f_start, self.f_end = self._date_pair(lay)
        lay.addWidget(label("These dates are your decision: they depend on the site and the year, so there is no default.", "paramHelp"))

        row = QHBoxLayout()
        row.addWidget(label("Skip scenes cloudier than", "paramHelp", wrap=False))
        self.cloud = QDoubleSpinBox()
        self.cloud.setRange(1, 100)
        self.cloud.setDecimals(0)
        self.cloud.setSuffix(" %")
        self.cloud.setValue(cloudload.DEFAULT_MAX_CLOUD)
        row.addWidget(self.cloud)
        row.addWidget(label("Margin around the sub-KHGs", "paramHelp", wrap=False))
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0, 20000)
        self.margin.setDecimals(0)
        self.margin.setSuffix(" m")
        self.margin.setValue(cloudload.DEFAULT_MARGIN_M)
        row.addWidget(self.margin)
        row.addStretch(1)
        lay.addLayout(row)

        lay.addWidget(label("Save the raster as", "paramLabel"))
        self.out = file_widget("save", "GeoTIFF (*.tif)")
        self.out.setFilePath(str(Path(out_dir or tempfile.gettempdir()) / "moisture_cloud.tif"))
        lay.addWidget(self.out)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.status = label("", "hint")
        lay.addWidget(self.status)
        row = QHBoxLayout()
        self.run_btn = button("Load", "primary", self._run)
        self.close_btn = button("Close", "ghost", self._close)
        row.addWidget(self.run_btn)
        row.addWidget(self.close_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self._line.connect(self._on_line)
        self._progress.connect(self._on_progress)
        self._source_changed()

    def _date_pair(self, lay) -> tuple[QLineEdit, QLineEdit]:
        row = QHBoxLayout()
        a, b = QLineEdit(), QLineEdit()
        for w, ph in ((a, "Start: YYYY-MM-DD"), (b, "End: YYYY-MM-DD")):
            w.setPlaceholderText(tr(ph))
            row.addWidget(w)
        lay.addLayout(row)
        return a, b

    # ------------------------------------------------------------------ state
    def _source_changed(self, *_a) -> None:
        ee = self.source.currentData() == "ee"
        self.ee_project.setVisible(ee)
        self.ee_signin.setVisible(ee)
        self.cloud.setEnabled(not ee)
        self.source_note.setText(tr("Needs a free Earth Engine account and the earthengine-api package in the engine environment. Gives exactly the CPWI of the team's Earth Engine script, with radar.") if ee else
                                 tr("Sentinel-2 only: no radar and a different cloud mask than the Earth Engine script, so values differ from CPWI. The result is labelled as an approximation."))

    def _busy(self, on: bool) -> None:
        self.run_btn.setEnabled(not on)
        self.ee_signin.setEnabled(not on)
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

    # ------------------------------------------------------------------ running
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

    def _sign_in(self) -> None:
        self._say(tr("A browser window opens for the Google sign-in. Come back here when it says it is done."))
        self._start(["fetch-moisture", "--ee-authenticate"], "Earth Engine sign-in", lambda: self._say(tr("Signed in to Earth Engine.")))

    def _run(self) -> None:
        try:
            primary, fallback = cloudload.check_windows(self.p_start.text(), self.p_end.text(), self.f_start.text(), self.f_end.text())
            out = self.out.filePath().strip()
            if not out:
                raise ValueError(tr("Choose where to save the raster."))
            if not self.extent or not self.crs:
                raise ValueError(tr("Choose the DTM and the sub-KHG polygons first: they give the area and the coordinate system."))
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

    def _close(self) -> None:
        if self._task is not None:
            self._task.cancel()
        self.reject()

    def closeEvent(self, e):
        if self._task is not None:
            self._task.cancel()
        super().closeEvent(e)
