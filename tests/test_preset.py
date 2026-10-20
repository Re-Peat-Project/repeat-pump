"""Proposed-defaults preset: opt-in, fills only nulls, never touches data facts, and stays visible."""
import shutil
from pathlib import Path

import pytest
import yaml

from repeat_pump.core.config import ConfigError, load_config
from repeat_pump.core.requirements import check, required_by_stage

CONFIGS = Path(__file__).parents[1] / "configs"


def _copy(tmp_path, preset=True):
    shutil.copy(CONFIGS / "example_khg.yaml", tmp_path / "run.yaml")
    shutil.copy(CONFIGS / "proposed_defaults.yaml", tmp_path / "proposed_defaults.yaml")
    if preset:
        p = tmp_path / "run.yaml"
        p.write_text("preset: proposed_defaults.yaml\n" + p.read_text(encoding="utf8"), encoding="utf8")
    return tmp_path / "run.yaml"


def test_no_preset_key_changes_nothing(tmp_path):
    cfg = load_config(_copy(tmp_path, preset=False))
    assert cfg.preset == {"path": None, "keys": []}
    assert cfg.pumping.manning_n is None and cfg.sekat.max_spacing_m is None


def test_preset_fills_nulls_and_lists_keys(tmp_path):
    cfg = load_config(_copy(tmp_path))
    assert cfg.sekat.max_spacing_m == 500 and cfg.pumping.manning_n == 0.035
    assert cfg.prioritise.criteria["burn_freq"].weight == 0.25
    assert "pumping.manning_n" in cfg.preset["keys"] and "prioritise.criteria.dryness.weight" in cfg.preset["keys"]


def test_run_config_value_wins(tmp_path):
    f = _copy(tmp_path)
    d = yaml.safe_load(f.read_text(encoding="utf8"))
    d["pumping"]["manning_n"] = 0.05
    f.write_text(yaml.safe_dump(d), encoding="utf8")
    cfg = load_config(f)
    assert cfg.pumping.manning_n == 0.05 and "pumping.manning_n" not in cfg.preset["keys"]


def test_data_facts_stay_with_the_user(tmp_path):
    """Datum, RMSE and moisture direction describe the dataset, so the preset must not supply them."""
    cfg = load_config(_copy(tmp_path))
    missing = {k for ks in required_by_stage(cfg).values() for k in ks}
    assert {"inputs.dtm.vertical_rmse_m", "inputs.moisture.higher_is_wetter"} <= missing
    assert "pumping.manning_n" not in missing and "optimise.enabled" not in missing


def test_preset_cannot_set_inputs_or_datum(tmp_path):
    f = _copy(tmp_path)
    (tmp_path / "proposed_defaults.yaml").write_text("inputs: {dtm: {vertical_rmse_m: 0.1}}\nrun: {vertical_datum: EGM2008}\n", encoding="utf8")
    with pytest.raises(ConfigError, match="not allowed"):
        load_config(f)


def test_missing_preset_file_fails_clearly(tmp_path):
    f = _copy(tmp_path)
    (tmp_path / "proposed_defaults.yaml").unlink()
    with pytest.raises(ConfigError, match="preset file not found"):
        load_config(f)


def test_check_reports_preset_and_fingerprint_follows_values(tmp_path):
    f = _copy(tmp_path)
    out = check(load_config(f))
    assert "pumping.manning_n" in out["preset"]["keys"]
    before = {s["id"]: s["fingerprint"] for s in out["stages"]}
    p = tmp_path / "proposed_defaults.yaml"
    p.write_text(p.read_text(encoding="utf8").replace("sekat:\n  max_spacing_m: 500", "sekat:\n  max_spacing_m: 400"), encoding="utf8")
    after = {s["id"]: s["fingerprint"] for s in check(load_config(f))["stages"]}
    assert before[7] != after[7] and before[2] == after[2]       # editing the preset makes stage 7 stale, not stage 2


def test_plugin_runconfig_makes_preset_path_absolute(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("runconfig", Path(__file__).parents[1] / "qgis_plugin" / "repeat_pump_qgis" / "runconfig.py")
    rc = importlib.util.module_from_spec(spec); spec.loader.exec_module(rc)
    data = rc.build_run_config(_copy(tmp_path))
    assert Path(data["preset"]).is_absolute() and Path(data["preset"]).exists()
