"""A run created in the wizard is named after its folder (or what was typed), not after the template it starts from."""
import sys
from pathlib import Path

import yaml

from tests.fixtures.synthetic import build_world, write_cfg

PLUGIN = Path(__file__).resolve().parents[1] / "qgis_plugin"
sys.path.insert(0, str(PLUGIN))
from repeat_pump_qgis import runconfig as rc  # noqa: E402


def _template(tmp):
    _, cfg = build_world(tmp)
    cfg["run"]["name"] = "khg_kahayan_sebangau_pilot"
    return write_cfg(tmp / "template.yaml", cfg)


def _create(tpl, out, typed=""):
    """What Create run / Save setup writes: built on the run's own config when it exists, else on the template."""
    cfg_path = Path(out).parent / "run_config.yaml"
    base = cfg_path if cfg_path.exists() else tpl
    data = rc.build_run_config(base, output_gpkg=str(out), run_name=rc.new_run_name(typed, out, cfg_path.exists()))
    return yaml.safe_load(rc.write_run_config(data, cfg_path).read_text())["run"]["name"]


def test_a_new_run_is_named_after_its_folder(tmp_path):
    """The team's case: a Mendahara run created from the bundled example showed the example's Kahayan-Sebangau name."""
    assert _create(_template(tmp_path), tmp_path / "New_run2" / "pump_run.gpkg") == "New_run2"


def test_a_typed_name_wins(tmp_path):
    assert _create(_template(tmp_path), tmp_path / "New_run2" / "pump_run.gpkg", typed=" mendahara ") == "mendahara"


def test_saving_an_open_run_keeps_its_name(tmp_path):
    """Save setup with the name field left empty must not rename a run (for example one renamed in its YAML)."""
    tpl, out = _template(tmp_path), tmp_path / "New_run2" / "pump_run.gpkg"
    _create(tpl, out, typed="mendahara")
    assert _create(tpl, out) == "mendahara"
    assert _create(tpl, out, typed="mendahara_v2") == "mendahara_v2"


def test_without_a_name_the_config_keeps_its_own():
    assert rc.new_run_name("", "x/run/out.gpkg", run_exists=True) is None
    assert rc.default_run_name("out.gpkg") == "out"


def test_the_field_is_filled_from_the_folder(tmp_path):
    """The Run name field shows the folder's name for a new folder, and the run's own name for a folder that holds a run, so
    Save setup on it (for example after a restart) does not rename the run."""
    tpl, out = _template(tmp_path), tmp_path / "New_run2" / "pump_run.gpkg"
    assert rc.folder_run_name(out) == "New_run2"
    _create(tpl, out, typed="nguji2")
    assert rc.folder_run_name(out) == "nguji2"
    assert rc.folder_run_name(tmp_path / "New_run4" / "pump_run.gpkg") == "New_run4"


def test_the_name_follows_the_folder_until_one_is_typed():
    assert rc.name_follows_folder("", None)
    assert rc.name_follows_folder("New_run2", "New_run2")        # still what the wizard filled in
    assert not rc.name_follows_folder("mendahara", "New_run2")   # typed over it
    assert not rc.name_follows_folder("mendahara", None)
