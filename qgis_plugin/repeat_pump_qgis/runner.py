"""Run the repeat-pump CLI in an external Python environment (option B).

No ``repeat_pump`` import happens inside QGIS, so the engine's dependencies
(rasterio, geopandas, ...) never clash with QGIS's own Python packages.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

KEY = "repeat_pump/python"
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def split_source(source: str):
    """File path and layer name from a QGIS layer source such as ``/x/a.gpkg|layername=canals``."""
    path = source.split("|")[0]
    m = re.search(r"layername=([^|]+)", source)
    return path, (m.group(1) if m else None)


_DROP = ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUSERBASE", "VIRTUAL_ENV", "GDAL_DATA", "GDAL_DRIVER_PATH",
         "GDAL_PLUGINS", "PROJ_LIB", "PROJ_DATA", "GEOTIFF_CSV", "QGIS_PREFIX_PATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "O4W_QT_PREFIX")


def clean_env() -> dict:
    """Environment for the engine process: QGIS's Python/GDAL/PROJ settings must not leak into the venv."""
    env = {k: v for k, v in os.environ.items() if k.upper() not in _DROP and not k.upper().startswith("PYTHON")}
    parts = [p for p in env.get("PATH", "").split(os.pathsep) if p and not re.search(r"osgeo4w|qgis", p, re.I)]
    root = os.environ.get("SystemRoot")
    if root:
        for extra in (root, os.path.join(root, "System32")):
            if extra not in parts:
                parts.append(extra)
    env["PATH"] = os.pathsep.join(parts)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["REPEAT_PUMP_PROGRESS"] = "1"       # the engine then prints "@@progress|stage|fraction|text" lines (see stream_process)
    return env


def get_python() -> str:
    """Engine interpreter: REPEAT_PUMP_PYTHON, then a user-chosen one, then the auto-managed environment."""
    env = os.environ.get("REPEAT_PUMP_PYTHON")
    if env:
        return env
    try:
        from qgis.core import QgsSettings
        chosen = QgsSettings().value(KEY, "") or ""
    except Exception:
        chosen = ""
    if chosen:
        return chosen
    auto = venv_python(env_dir())
    return str(auto) if auto.exists() else ""


def set_python(path: str) -> None:
    from qgis.core import QgsSettings
    QgsSettings().setValue(KEY, path)


def check_environment(python: str) -> tuple[bool, str]:
    """True if ``python -m repeat_pump.cli --version`` works there."""
    if not python or not os.path.exists(python):
        return False, "No engine environment yet. Run RE-PEAT Pompanisasi > Set up engine environment (or choose a Python with Plugins > RE-PEAT Pompanisasi > Set Python environment)."
    try:
        r = subprocess.run([python, "-m", "repeat_pump.cli", "--version"], capture_output=True, text=True, timeout=60,
                           creationflags=CREATE_NO_WINDOW, env=clean_env(), cwd=tempfile.gettempdir())
    except Exception as e:
        return False, f"Could not start {python}: {e}"
    if r.returncode != 0:
        return False, f"repeat-pump is not installed in {python}:\n{(r.stderr or r.stdout).strip()[-400:]}"
    return True, f"OK: {r.stdout.strip()} ({python})"


def run_check(python: str, config: str) -> dict:
    """``repeat-pump check``: stages, review flags and the null parameters each stage still needs."""
    r = subprocess.run([python, "-m", "repeat_pump.cli", "check", "--config", config], capture_output=True, text=True, timeout=180,
                       creationflags=CREATE_NO_WINDOW, env=clean_env(), cwd=tempfile.gettempdir())
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[-600:] or f"check exited with {r.returncode}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def run_reset(python: str, config: str) -> list[str]:
    """``repeat-pump reset``: delete the run's GeoPackage, work folder, state and report (never the config or the inputs).
    Returns the paths removed. Close the run's layers in QGIS first: Windows will not delete a file that is open."""
    r = subprocess.run([python, "-m", "repeat_pump.cli", "reset", "--config", config], capture_output=True, text=True, timeout=180,
                       creationflags=CREATE_NO_WINDOW, env=clean_env(), cwd=tempfile.gettempdir())
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[-600:] or f"reset exited with {r.returncode}")
    return [l[len("removed "):] for l in r.stdout.splitlines() if l.startswith("removed ")]


def run_cli(python: str, config: str, cwd: str, first, last, accept, feedback, rerun: bool = False) -> int:
    """Stream the CLI output into the Processing feedback; return the exit code (0 ok, 1 error, 2 review stop).

    ``rerun=True`` forces stage ``first`` (and everything after it up to ``last``) to run again, even stage 1.
    """
    cmd = [python, "-u", "-m", "repeat_pump.cli", "run", "--config", config]
    if last:
        cmd += ["--stop-after", str(last)]
    if first and (first > 1 or rerun):
        cmd += ["--resume-from", str(first)]
    for a in accept:
        cmd += ["--accept", str(a)]
    feedback.pushInfo("Running: " + " ".join(cmd))
    return stream_process(cmd, cwd, clean_env(), feedback)


CANCELLED = 130


def run_engine(python: str, args: list[str], cwd: str, feedback) -> int:
    """Run any engine command (``repeat-pump <args>``), streaming its output like ``run_cli``; returns the exit code."""
    cmd = [python, "-u", "-m", "repeat_pump.cli", *args]
    feedback.pushInfo("Running: " + " ".join(cmd))
    return stream_process(cmd, cwd, clean_env(), feedback)


def kill_tree(p: subprocess.Popen) -> None:
    """Stop the process and everything it started (WhiteboxTools runs as a child and would otherwise keep files locked)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, creationflags=CREATE_NO_WINDOW)
    else:
        p.kill()


def parse_progress(line: str):
    """``@@progress|3|0.25|removing depressions`` -> (3, 0.25, "removing depressions"); None if malformed."""
    try:
        _, stage, frac, text = (line.split("|", 3) + [""])[:4]
        return int(stage), min(max(float(frac), 0.0), 1.0), text
    except ValueError:
        return None


def report_progress(feedback, line: str) -> None:
    """Pass a progress line on to whatever the feedback object offers: the wizard's ``progress(stage, fraction, text)`` or the
    Processing feedback's ``setProgress(percent)``. Feedback objects with neither (tests) simply ignore it."""
    p = parse_progress(line)
    if p is None:
        return
    if hasattr(feedback, "progress"):
        feedback.progress(*p)
    elif hasattr(feedback, "setProgress"):
        feedback.setProgress(p[1] * 100)


def stream_process(cmd, cwd, env, feedback) -> int:
    """Run ``cmd``, stream its output lines to ``feedback`` and return its exit code, or ``CANCELLED`` if the user cancelled.

    Output is read on its own thread so cancelling works even when the process is silent (a long download, a hung tool).
    """
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                         creationflags=CREATE_NO_WINDOW, env=env)
    lines: queue.Queue = queue.Queue()

    def pump():
        try:
            for line in p.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    cancelled = False
    while True:
        try:
            line = lines.get(timeout=0.2)
        except queue.Empty:
            line = ""
        else:
            if line is None:
                break
            line = line.rstrip()
            if line.startswith("@@progress|"):
                report_progress(feedback, line)
            elif line:
                (feedback.pushWarning if line.startswith(("WARNING", "ERROR")) else feedback.pushInfo)(line)
        if feedback.isCanceled():
            cancelled = True
            kill_tree(p)
            break
    code = p.wait()
    reader.join(timeout=3)                 # the reader ends at EOF once the process (and its children) are gone
    return CANCELLED if cancelled else code


# ---------------------------------------------------------------------------- auto-managed environment
MIN_PY = (3, 11)


def engine_dir() -> Path:
    """Engine source bundled inside the plugin by scripts/install_plugin.py."""
    return Path(__file__).parent / "engine"


def bundled_version() -> str:
    """Engine version plus the source hash written by scripts/install_plugin.py, so a changed engine is reinstalled even when
    the version was not bumped. The hash is fixed at build time because pip writes build files into the engine folder."""
    f = engine_dir() / "repeat_pump" / "__init__.py"
    m = re.search(r'__version__\s*=\s*"([^"]+)"', f.read_text(encoding="utf8")) if f.exists() else None
    if not m:
        return ""
    h = engine_dir() / "ENGINE_HASH"
    return f"{m.group(1)}+{h.read_text().strip()}" if h.exists() else m.group(1)


def env_dir() -> Path:
    d = os.environ.get("REPEAT_PUMP_ENV_DIR")
    if d:
        return Path(d)
    try:
        from qgis.core import QgsApplication
        return Path(QgsApplication.qgisSettingsDirPath()) / "repeat_pump_env"
    except Exception:
        return Path.home() / ".repeat_pump" / "env"


def environment_outdated(python: str) -> bool:
    """True if ``python`` is the plugin's own environment and the engine bundled in the plugin is newer than the installed one."""
    ver = bundled_version()
    d = env_dir()
    if not ver or str(venv_python(d)) != str(python):
        return False
    stamp = d / "engine_version.txt"
    return not (stamp.exists() and stamp.read_text().strip() == ver)


def venv_python(d: Path) -> Path:
    return d / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _probe(exe: str, extra_env: dict | None = None) -> bool:
    """True if ``exe`` is Python >= 3.11 with venv, ensurepip and ssl (pip needs it)."""
    env = clean_env()
    env.update(extra_env or {})
    try:
        r = subprocess.run([exe, "-c", "import sys,venv,ensurepip,ssl;print(sys.version_info[0],sys.version_info[1])"], capture_output=True,
                           text=True, timeout=60, creationflags=CREATE_NO_WINDOW, env=env, cwd=tempfile.gettempdir())
        if r.returncode != 0:
            return False
        major, minor = map(int, r.stdout.split()[:2])
        return (major, minor) >= MIN_PY
    except Exception:
        return False


def _windows_pythons() -> list:
    """Installed CPython executables from the registry (PEP 514) and the usual install folders."""
    found = []
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                core = winreg.OpenKey(hive, r"SOFTWARE\Python\PythonCore")
            except OSError:
                continue
            for k in range(winreg.QueryInfoKey(core)[0]):
                ver = winreg.EnumKey(core, k)
                try:
                    ip = winreg.OpenKey(core, ver + r"\InstallPath")
                    try:
                        exe = winreg.QueryValueEx(ip, "ExecutablePath")[0]
                    except OSError:
                        exe = os.path.join(winreg.QueryValueEx(ip, "")[0], "python.exe")
                    found.append((ver, exe))
                except OSError:
                    pass
    except ImportError:
        pass
    import glob
    for pat in (os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python3*\python.exe"), r"C:\Program Files\Python3*\python.exe", r"C:\Python3*\python.exe"):
        for exe in glob.glob(pat):
            found.append((os.path.basename(os.path.dirname(exe)), exe))
    found.sort(key=lambda t: t[0], reverse=True)      # newest first (string order is fine for 3.11..3.99)
    return [exe for _, exe in found if os.path.exists(exe)]


def find_base_python():
    """A system Python >= 3.11 (with venv, pip and ssl) to build the venv from, as (exe, extra_env)."""
    cands = []
    if sys.platform == "win32":
        cands += [(exe, {}) for exe in _windows_pythons()]
    for name in ("python3", "python"):
        w = shutil.which(name, path=clean_env().get("PATH"))
        if w and "WindowsApps" not in w:        # skip the Microsoft Store stubs
            cands.append((w, {}))
    home = os.environ.get("PYTHONHOME")          # set by QGIS itself: its bundled Python (often lacks ssl)
    if home:
        for exe in ("python.exe", "bin/python3"):
            if (Path(home) / exe).exists():
                cands.append((str(Path(home) / exe), {"PYTHONHOME": home}))
    seen = set()
    for exe, extra in cands:
        if exe.lower() in seen:
            continue
        seen.add(exe.lower())
        if _probe(exe, extra):
            return exe, extra
    return None


def _run_stream(cmd, log, extra_env=None) -> None:
    env = clean_env()
    env.update(extra_env or {})
    log("$ " + " ".join(str(c) for c in cmd))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env,
                         creationflags=CREATE_NO_WINDOW, cwd=tempfile.gettempdir())
    for line in p.stdout:
        if line.strip():
            log(line.rstrip())
    p.stdout.close()
    if p.wait() != 0:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(str(c) for c in cmd)}")


def ensure_environment(log=print, force: bool = False) -> str:
    """Create or update the plugin's own venv with the bundled engine; return its python. Needs internet for pip."""
    d = env_dir()
    py = venv_python(d)
    stamp = d / "engine_version.txt"
    ver = bundled_version()
    if not force and py.exists() and stamp.exists() and stamp.read_text().strip() == ver and check_environment(str(py))[0]:
        return str(py)
    if not force and py.exists() and check_environment(str(py))[0] and (engine_dir() / "pyproject.toml").exists():
        log("Updating the engine in the existing environment")          # quick path: keep the venv, replace the engine
        try:
            _run_stream([str(py), "-m", "pip", "install", "--force-reinstall", "--no-deps", str(engine_dir())], log)
            _run_stream([str(py), "-m", "pip", "install", str(engine_dir())], log)     # picks up any new dependency
            ok, msg = check_environment(str(py))
            if ok:
                stamp.write_text(ver)
                log(msg)
                return str(py)
        except RuntimeError as e:
            log(f"Update failed ({e}); rebuilding the environment")
    if not (engine_dir() / "pyproject.toml").exists():
        raise RuntimeError("This plugin copy has no bundled engine. Install it with scripts/install_plugin.py or the zip, "
                           "or set a Python environment manually.")
    base = find_base_python()
    if base is None:
        raise RuntimeError("No Python 3.11+ with venv/pip found. Install Python from python.org, then run the setup again, "
                           "or set a Python environment manually.")
    log(f"Setting up the engine environment in {d} (first time only; needs internet, may take several minutes)")
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.parent.mkdir(parents=True, exist_ok=True)
    _run_stream([base[0], "-m", "venv", str(d)], log, base[1])
    _run_stream([str(py), "-m", "pip", "install", "--upgrade", "pip"], log)
    _run_stream([str(py), "-m", "pip", "install", str(engine_dir())], log)
    ok, msg = check_environment(str(py))
    if not ok:
        raise RuntimeError(msg)
    stamp.write_text(ver)
    log(msg)
    return str(py)
