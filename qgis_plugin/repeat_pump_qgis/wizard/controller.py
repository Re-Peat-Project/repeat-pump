"""Wizard controller: owns the run, talks to the engine as an external process, never imports ``repeat_pump``.

Long operations (engine check, stage runs, environment setup) run in ``QgsTask``s so QGIS stays responsive.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

import yaml
from qgis.core import QgsApplication, QgsTask
from qgis.PyQt.QtCore import QObject, pyqtSignal

from .. import runner
from ..runconfig import set_dotted, write_run_config
from . import viewmodel as vm


def _flag(name: str):
    flag = getattr(QgsTask, "Flag", None)
    return getattr(flag, name) if flag is not None and hasattr(flag, name) else getattr(QgsTask, name)


class FnTask(QgsTask):
    """Run ``fn(task)`` off the UI thread; ``on_done(result, error)`` is called on the UI thread."""

    def __init__(self, description: str, fn: Callable, on_done: Callable):
        super().__init__(description, _flag("CanCancel"))
        self._fn, self._on_done = fn, on_done
        self.result: Any = None
        self.error = ""

    def run(self) -> bool:
        try:
            self.result = self._fn(self)
            return True
        except Exception as e:  # reported to the UI, never raised in the worker
            self.error = str(e) or e.__class__.__name__
            return False

    def finished(self, ok: bool) -> None:
        self._on_done(self.result if ok else None, "" if ok else (self.error or "Cancelled"))


class _Feedback:
    """The slice of QgsProcessingFeedback that ``runner.run_cli`` uses."""

    def __init__(self, task: QgsTask, emit: Callable[[str], None]):
        self._task, self._emit = task, emit

    def pushInfo(self, line: str) -> None:
        self._emit(line)

    def pushWarning(self, line: str) -> None:
        self._emit(line)

    def isCanceled(self) -> bool:
        return self._task.isCanceled()


class WizardController(QObject):
    changed = pyqtSignal()           # model or busy state changed: re-render
    log_line = pyqtSignal(str)       # thread-safe: may be emitted from a worker
    notice = pyqtSignal(str, str)    # level (info|success|warning|error), text
    stage_finished = pyqtSignal(int, int)   # stage id, exit code

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config_path: Optional[Path] = None
        self.check_json: Optional[dict] = None
        self.model: Optional[vm.WizardModel] = None
        self.engine_ready: Optional[bool] = None     # None = still checking
        self.engine_message = "Checking the engine..."
        self.running: Optional[int] = None
        self.busy = ""                               # description of a non-stage task ("Checking...", "Setting up...")
        self.log: list[str] = []
        self._tasks: list[QgsTask] = []
        self.log_line.connect(self._append_log)

    # ------------------------------------------------------------------ helpers
    def _submit(self, description: str, fn: Callable, on_done: Callable) -> None:
        def done(result, error):
            self._tasks[:] = [t for t in self._tasks if t is not task]
            on_done(result, error)
        task = FnTask(description, fn, done)
        self._tasks.append(task)          # keep a Python reference alive while QGIS runs it
        QgsApplication.taskManager().addTask(task)

    def _append_log(self, line: str) -> None:
        self.log.append(line)
        del self.log[:-2000]

    @property
    def output_gpkg(self) -> Optional[Path]:
        if not self.check_json or not self.config_path:
            return None
        p = Path(self.check_json["output_gpkg"])
        return p if p.is_absolute() else self.config_path.parent / p

    def _rebuild(self) -> None:
        if self.check_json is None:
            self.model = None
        else:
            self.model = vm.WizardModel(self.check_json, vm.load_state(self.output_gpkg), self.running, bool(self.engine_ready))
        self.changed.emit()

    # ------------------------------------------------------------------ engine environment
    def start(self) -> None:
        """Check whether the engine environment works (async), then the open run if there is one."""
        self.busy = "Checking the engine..."
        self.changed.emit()

        def work(task):
            py = runner.get_python()
            return py, runner.check_environment(py)

        def done(res, err):
            self.busy = ""
            if err or res is None:
                self.engine_ready, self.engine_message = False, err or "Could not check the engine."
            else:
                self.engine_ready, self.engine_message = bool(res[1][0]), res[1][1]
            if self.engine_ready and self.config_path:
                self.refresh_check()
            else:
                self._rebuild()
        self._submit("RE-PEAT: check engine", work, done)

    def setup_engine(self) -> None:
        """Create or repair the private engine environment (needs internet once)."""
        if self.busy or self.running is not None:
            return
        self.busy = "Setting up the engine environment (a few minutes, needs internet)..."
        self.log.clear()
        self.changed.emit()
        self._submit("RE-PEAT: set up engine", lambda task: runner.ensure_environment(self.log_line.emit), self._after_setup)

    def _after_setup(self, res, err) -> None:
        self.busy = ""
        if err:
            self.engine_ready, self.engine_message = False, err
            self.notice.emit("error", f"Engine setup failed: {err}")
        else:
            self.engine_ready, self.engine_message = True, "Engine ready"
            self.notice.emit("success", "Engine environment is ready.")
            if self.config_path:
                self.refresh_check()
                return
        self._rebuild()

    # ------------------------------------------------------------------ the run
    def open_run(self, config: str | Path) -> None:
        self.config_path = Path(config)
        self.log.clear()
        self.refresh_check()

    def refresh_check(self) -> None:
        """Ask the engine which parameters each stage still needs (async), then rebuild the model."""
        if not self.config_path or not self.engine_ready:
            self._rebuild()
            return
        cfg, py = str(self.config_path), runner.get_python()

        def done(res, err):
            if err:
                self.notice.emit("error", f"The run config is not valid: {err}")
            else:
                self.check_json = res
            self._rebuild()
        self._submit("RE-PEAT: check config", lambda task: runner.run_check(py, cfg), done)

    def reload_state(self) -> None:
        self._rebuild()

    def set_param(self, key: str, value: Any) -> None:
        """Write one decision into the run YAML, then re-check (the stages' needs can depend on it)."""
        if not self.config_path:
            return
        data = yaml.safe_load(self.config_path.read_text(encoding="utf8"))
        set_dotted(data, key, value)
        write_run_config(data, self.config_path)
        self.refresh_check()

    def write_config(self, data: dict, path: Path) -> None:
        write_run_config(data, path)
        self.open_run(path)

    # ------------------------------------------------------------------ running stages
    def run(self, action: str, stage: int) -> None:
        if self.running is not None or not self.config_path or not self.engine_ready:
            return
        plan = vm.WizardModel.plan(action, stage)
        py, cfg = runner.get_python(), str(self.config_path)
        if action == "rerun" and self.model is not None:
            # results of later stages are about to be discarded: take them off the map too
            from . import styling
            styling.remove_layers(self.check_json.get("run_name", ""), vm.layers_after(stage))
        self.running = stage
        self.log.clear()
        self.log_line.emit(f"--- {action} stage {stage} ---")
        self._rebuild()

        def work(task):
            return runner.run_cli(py, cfg, str(self.config_path.parent), plan.first, plan.last, list(plan.accept),
                                  _Feedback(task, self.log_line.emit), rerun=plan.rerun)

        def done(code, err):
            self.running = None
            if err:
                self.notice.emit("error", f"Stage {stage} could not run: {err}")
                code = 1
            elif code == runner.CANCELLED:
                self.notice.emit("warning", f"Stage {stage} was cancelled. Run it again when you are ready.")
            elif code == 1:
                self.notice.emit("error", f"Stage {stage} failed. See the message on the card.")
            elif code == 2:
                self.notice.emit("warning", f"Stage {stage} is ready for your review.")
            elif code == 0:
                self.notice.emit("success", f"Stage {stage} finished.")
            self._rebuild()
            self.stage_finished.emit(stage, int(code if code is not None else 1))
        self._submit(f"RE-PEAT: stage {stage}", work, done)

    def cancel(self) -> None:
        for t in self._tasks:
            if t.description().startswith("RE-PEAT: stage"):
                t.cancel()
