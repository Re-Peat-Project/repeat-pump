"""A2: a setup edited in the wizard but not saved must be noticed before a stage runs (the engine reads only the saved run config)."""
import sys
from pathlib import Path

import yaml

from tests.fixtures.synthetic import build_world, write_cfg

PLUGIN = Path(__file__).resolve().parents[1] / "qgis_plugin"
sys.path.insert(0, str(PLUGIN))
from repeat_pump_qgis import runconfig as rc  # noqa: E402


def _saved_run(tmp):
    """Create run: the wizard builds from the template and writes run_config.yaml next to the output."""
    _, cfg = build_world(tmp)
    tpl = write_cfg(tmp / "template.yaml", cfg)
    run = tmp / "run"
    data = rc.build_run_config(tpl, output_gpkg=str(run / "out.gpkg"), vectors={"canals": (str(tmp / "canals.gpkg"), None)},
                               columns={"canals": {"canal_class": "kelas"}})
    return rc.write_run_config(data, run / "run_config.yaml")


def _form(saved, **kw):
    """What the setup form writes when saved again: the wizard rebuilds on top of the saved run config."""
    args = dict(output_gpkg=str(saved.parent / "out.gpkg"), vectors={"canals": (yaml.safe_load(saved.read_text())["inputs"]["canals"]["path"], None)},
                columns={"canals": {"canal_class": "kelas"}})
    args.update(kw)
    return rc.build_run_config(saved, **args)


def test_an_unchanged_form_has_no_changes(tmp_path):
    saved = _saved_run(tmp_path)
    assert rc.setup_changes(yaml.safe_load(saved.read_text()), _form(saved)) == []


def test_a_changed_column_mapping_is_reported(tmp_path):
    """The team's case: a wrong column name is fixed in Edit setup, then stage 1 is re-run without saving."""
    saved = _saved_run(tmp_path)
    changes = rc.setup_changes(yaml.safe_load(saved.read_text()), _form(saved, columns={"canals": {"canal_class": "canal_clas"}}))
    assert changes == ["inputs.canals.columns.canal_class"]


def test_a_different_layer_is_reported(tmp_path):
    saved = _saved_run(tmp_path)
    changes = rc.setup_changes(yaml.safe_load(saved.read_text()), _form(saved, vectors={"canals": (str(tmp_path / "other.gpkg"), "lines")}))
    assert changes == ["inputs.canals.layer", "inputs.canals.path"]


def test_a_removed_mapping_is_reported(tmp_path):
    saved = _saved_run(tmp_path)
    changes = rc.setup_changes(yaml.safe_load(saved.read_text()), _form(saved, columns={}))
    assert changes == ["inputs.canals.columns.canal_class"]


def test_a_saved_setup_loads_back_with_the_same_layers_and_settings(tmp_path):
    """Save setup as JSON or YAML, load it in a new session: every layer path, column choice and selection comes back."""
    saved = _saved_run(tmp_path)
    data = rc.read_setup(saved)
    for name in ("setup.json", "setup.yaml"):
        rc.write_setup(data, tmp_path / name)
        back = rc.read_setup(tmp_path / name)
        assert back == data
        refs = rc.form_inputs(back)
        assert refs["canals"] == [(str(tmp_path / "canals.gpkg"), None)]
        assert back["inputs"]["canals"]["columns"] == {"canal_class": "kelas"}
        assert Path(back["run"]["output_gpkg"]).is_absolute()


def test_an_unedited_old_preset_copy_is_refreshed_and_an_edited_one_kept(tmp_path):
    bundled = tmp_path / "bundled.yaml"
    bundled.write_text("sekat: {max_spacing_m: 500, target_rise_share: 0.9}\n", encoding="utf8")
    run = tmp_path / "run"
    run.mkdir()
    (run / rc.PRESET_FILE).write_text("sekat: {max_spacing_m: 500}\n", encoding="utf8")          # an older, unedited copy
    rc.attach_preset({}, run, bundled)
    assert "target_rise_share" in (run / rc.PRESET_FILE).read_text(encoding="utf8")
    (run / rc.PRESET_FILE).write_text("sekat: {max_spacing_m: 300}\n", encoding="utf8")           # the team changed a value
    rc.attach_preset({}, run, bundled)
    assert (run / rc.PRESET_FILE).read_text(encoding="utf8") == "sekat: {max_spacing_m: 300}\n"
