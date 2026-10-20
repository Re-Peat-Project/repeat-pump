"""The plugin's runner has no qgis dependency at import time, so it can be tested here."""
import importlib.util
import sys
from pathlib import Path

from tests.fixtures.synthetic import write_cfg

spec = importlib.util.spec_from_file_location("runner", Path(__file__).parents[1] / "qgis_plugin" / "repeat_pump_qgis" / "runner.py")
runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)


class Fb:
    def __init__(self): self.lines = []
    def pushInfo(self, m): self.lines.append(m)
    def pushWarning(self, m): self.lines.append("W:" + m)
    def isCanceled(self): return False


def test_check_environment():
    ok, msg = runner.check_environment(sys.executable)
    assert ok and "repeat-pump" in msg
    ok, msg = runner.check_environment("")
    assert not ok and "No engine environment yet" in msg


def test_split_source():
    assert runner.split_source("/x/a.gpkg|layername=canals|subset=1") == ("/x/a.gpkg", "canals")
    assert runner.split_source("/x/a.shp") == ("/x/a.shp", None)


def test_run_cli_streams_and_returns_review_code(world):
    cfg, tmp = world
    fb = Fb()
    code = runner.run_cli(sys.executable, str(write_cfg(tmp / "c.yaml", cfg)), str(tmp), 1, 11, [], fb)
    assert code == 2 and any("--accept 2" in l or "Stage 2" in l for l in fb.lines)


def test_layer_name_in_config_is_honoured(world):
    """A multi-layer GeoPackage input is read through ``inputs.<x>.layer`` (what the plugin passes)."""
    import geopandas as gpd
    from repeat_pump.core import io
    from tests.conftest import make_ctx
    cfg, tmp = world
    canals = gpd.read_file(tmp / "canals.gpkg")
    canals.to_file(tmp / "multi.gpkg", layer="other", driver="GPKG")
    canals.to_file(tmp / "multi.gpkg", layer="canals_here", driver="GPKG")
    cfg["inputs"]["canals"] = {"path": str(tmp / "multi.gpkg"), "layer": "canals_here"}
    ctx = make_ctx(cfg); io.run_stage1(ctx)
    assert len(ctx.read_layer("inputs_clipped_canals")) == 2


def test_child_env_is_isolated_from_qgis(monkeypatch):
    """QGIS exports PYTHONHOME/PATH of its own Python; the engine venv must not inherit them."""
    monkeypatch.setenv("PYTHONHOME", r"C:\does\not\exist")
    monkeypatch.setenv("PATH", r"C:\Users\x\AppData\Local\Programs\OSGeo4W\bin" + __import__("os").pathsep + __import__("os").environ["PATH"])
    env = runner.clean_env()
    assert "PYTHONHOME" not in env and "PYTHONEXECUTABLE" not in env and "osgeo4w" not in env["PATH"].lower()
    ok, msg = runner.check_environment(sys.executable)
    assert ok, msg


def test_find_base_python_skips_pythons_without_ssl_and_finds_a_usable_one():
    found = runner.find_base_python()
    assert found is not None
    exe, extra = found
    assert runner._probe(exe, extra)            # >= 3.11 with venv, ensurepip and ssl


def test_ensure_environment_explains_missing_bundled_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("REPEAT_PUMP_ENV_DIR", str(tmp_path / "env"))
    import pytest
    with pytest.raises(RuntimeError, match="no bundled engine"):
        runner.ensure_environment(lambda m: None)    # the source tree has no engine/ folder; only the installed copy does


def test_environment_outdated_only_for_the_plugins_own_env(tmp_path, monkeypatch):
    monkeypatch.setenv("REPEAT_PUMP_ENV_DIR", str(tmp_path / "env"))
    py = runner.venv_python(tmp_path / "env")
    monkeypatch.setattr(runner, "bundled_version", lambda: "")
    assert not runner.environment_outdated(str(py))                        # source checkout: nothing bundled to compare with
    monkeypatch.setattr(runner, "bundled_version", lambda: "0.2.0")
    assert runner.environment_outdated(str(py))                            # no version stamp yet
    py.parent.mkdir(parents=True)
    (tmp_path / "env" / "engine_version.txt").write_text("0.1.0")
    assert runner.environment_outdated(str(py))                            # an older engine is installed
    (tmp_path / "env" / "engine_version.txt").write_text("0.2.0")
    assert not runner.environment_outdated(str(py))
    assert not runner.environment_outdated(sys.executable)                 # a user-chosen interpreter is never "outdated"


def test_get_python_prefers_explicit_then_auto_env(tmp_path, monkeypatch):
    monkeypatch.delenv("REPEAT_PUMP_PYTHON", raising=False)
    monkeypatch.setenv("REPEAT_PUMP_ENV_DIR", str(tmp_path / "env"))
    assert runner.get_python() == ""
    py = runner.venv_python(tmp_path / "env"); py.parent.mkdir(parents=True); py.write_text("")
    assert runner.get_python() == str(py)
    monkeypatch.setenv("REPEAT_PUMP_PYTHON", "X")
    assert runner.get_python() == "X"
