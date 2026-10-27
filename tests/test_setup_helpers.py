"""Filling a run from a KHG work folder, canal class guesses and mapping, optional burn and peat layers, and the run plans."""
import sys
from pathlib import Path

import pytest

from repeat_pump.core import hydro, io, prioritise, profiles, segments, topology
from repeat_pump.core.config import ConfigError
from tests.conftest import make_ctx

PLUGIN = Path(__file__).resolve().parents[1] / "qgis_plugin"
sys.path.insert(0, str(PLUGIN))
from repeat_pump_qgis import khgsetup  # noqa: E402
from repeat_pump_qgis.wizard import preflight as pf  # noqa: E402
from repeat_pump_qgis.wizard import viewmodel as vm  # noqa: E402


def _touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")
    return p


def test_a_khg_folder_fills_the_inputs_lidar_first_and_reports_what_is_missing(tmp_path):
    root, data, hub = tmp_path / "_khg", tmp_path / "_data", tmp_path / "re-peat"
    k = root / "16.02.01_sugihan_lumpur"
    for f in ("00_inputs/canals.gpkg", "00_inputs/rivers.gpkg", "00_inputs/blocks.gpkg", "01_dem/inputs/demnas.tif",
              "01_dem/inputs/lidar_oki25.tif", "02_delineation/subkhg_units.gpkg", "04_prioritisation/national_layers/subkhg_priority.csv", "04_prioritisation/national_layers/unit_prioritas.gpkg", "03_neraca/runs/balance/neraca_map.gpkg",
              "cache/16.02.01/annual/ndmi_2019.tif", "cache/16.02.01/annual/ndmi_2023.tif", "cache/16.02.01/annual/ndmi_2024_60m.tif"):
        _touch(k / f)
    _touch(data / khgsetup.BURN_FILE)
    peat = _touch(data / "peat" / "depth.img")
    (hub / "sites" / k.name).mkdir(parents=True)
    (hub / "sites" / k.name / "subkhg.yaml").write_text("rasters: {peat_depth: \"${REPEAT_DATA}/peat/depth.img\"}\nparams: {peat_depth_scale: 0.01}\n")
    (root / "notes").mkdir()
    assert [p.name for p in khgsetup.khg_folders(root)] == [k.name]
    d, missing = khgsetup.setup_from_khg(k, hub=hub, data=data)
    assert missing == []
    assert d["inputs"]["dtm"]["source"] == "lidar" and d["inputs"]["dtm"]["path"].endswith("lidar_oki25.tif")
    assert d["inputs"]["moisture"]["paths"][0].endswith("ndmi_2023.tif")
    assert Path(d["inputs"]["peat_depth"]["path"]) == peat and d["inputs"]["peat_depth"]["units"] == "cm"
    assert d["run"]["output_gpkg"].endswith(str(Path("05_pump") / "sugihan_lumpur.gpkg"))
    (k / "01_dem/inputs/lidar_oki25.tif").unlink()
    (hub / "sites" / k.name / "subkhg.yaml").unlink()
    d, missing = khgsetup.setup_from_khg(k, hub=hub, data=data)
    assert d["inputs"]["dtm"]["source"] == "demnas" and missing == ["peat_depth"]


@pytest.mark.parametrize("value,cls", [("Kanal Primer", "primer"), ("Kanal Sekunder", "sekunder"), ("tertiary canal", "tersier"),
                                       ("1", "primer"), ("2.0", "sekunder"), (3, "tersier"), ("Saluran", "")])
def test_canal_class_values_are_guessed(value, cls):
    assert pf.guess_canal_class(value) == cls


def test_likely_columns_are_guessed_by_name():
    assert pf.guess_column("canals", "canal_class", ["OBJECTID", "KET_KANAL", "KODE_KANAL"]) == "KET_KANAL"
    assert pf.guess_column("sekat_existing", "sekat_id", ["PULAU", "OBJECTID_1"]) == "OBJECTID_1"
    assert pf.guess_column("canals", "canal_class", ["name"]) == ""


def test_a_class_map_turns_codes_into_classes_for_the_filter(world):
    cfg, tmp = world
    import geopandas as gpd
    c = gpd.read_file(cfg["inputs"]["canals"]["path"])
    c["canal_class"] = ["1", "3"]                          # KODE_KANAL style codes
    c.to_file(tmp / "codes.gpkg", driver="GPKG")
    cfg["inputs"]["canals"]["path"] = str(tmp / "codes.gpkg")
    cfg["topology"].update(canal_classes=["primer", "sekunder"], canal_class_map={"1": "primer", "2": "sekunder", "3": "tersier"})
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    topology.run(ctx)
    assert ctx.report["canal_class_filter"]["kept"] == 1 and ctx.report["canal_class_filter"]["dropped"] == {"tersier": 1}


def test_without_burn_and_peat_layers_their_weights_go_to_zero(world):
    cfg, _ = world
    cfg["inputs"].pop("burn_area")
    cfg["inputs"].pop("peat_depth")
    ctx = make_ctx(cfg)
    for f in (io.run_stage1, topology.run, hydro.run, segments.run, profiles.run, prioritise.run):
        f(ctx)
    w = ctx.report["weights"]
    assert w["burn_freq"] == 0 and w["peat_depth"] == 0 and abs(sum(w.values()) - 1) < 1e-9
    assert any("weight set to 0" in m for m in ctx.warnings)


def test_klh_scoring_needs_the_peat_layer(world):
    cfg, _ = world
    cfg["inputs"].pop("peat_depth")
    cfg["prioritise"].update(weights_mode="klh", klh_cpwi_breaks=[0.2, 0.4], klh_flow_breaks=[10, 100], klh_min_score=6)
    ctx = make_ctx(cfg)
    for f in (io.run_stage1, topology.run, hydro.run, segments.run, profiles.run):
        f(ctx)
    with pytest.raises(ConfigError, match="peat depth"):
        prioritise.run(ctx)


def test_run_plans_run_on_to_the_next_review():
    assert vm.WizardModel.plan("run_on", 3) == vm.RunPlan(None, vm.LAST_STAGE)
    assert vm.WizardModel.plan("accept_on", 6) == vm.RunPlan(None, vm.LAST_STAGE, (6,))
    assert vm.WizardModel.plan("run", 3) == vm.RunPlan(None, 3)


def test_interventions_follow_the_flags_in_order():
    from types import SimpleNamespace

    import pandas as pd

    from repeat_pump.core.interventions import CLASSES, classify
    from repeat_pump_qgis.intervention_labels import LABELS
    assert LABELS == CLASSES
    ic = SimpleNamespace(protected_share=0.5, reach_min=0.4, ndmi_dry=0.3, burned_min=0.25, water_max_dist_m=5000, held_target=0.5,
                         deficit_min_mm=50)
    df = pd.DataFrame({
        "i_protected":      [0.8, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1],
        "u_ndmi":           [0.4, 0.2, 0.4, 0.2, 0.4, 0.4, 0.4],
        "burned_ever_frac": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "f_reach":          [0.9, 0.2, 0.9, 0.9, 0.9, 0.2, 0.9],
        "f_water_dist":     [9e3, 9e3, 2e3, 9e3, 9e3, 9e3, 9e3],
        "held_share":       [None, None, 0.1, 0.1, 0.9, None, None],
        "deficit_mm":       [290, 290, 290, 290, 290, 290, 10],
    })
    out = classify(df, ic)
    assert list(out["intervention"]) == ["close_canals", "revegetate_fire", "block_water", "block_wells", "block", "maintain", "block"]
    assert "protected peat" in out["reasons"].iloc[0] and "canals reach little land" in out["reasons"].iloc[1]
    assert out["intervention_otherwise"].iloc[0] == "block" and out["intervention_otherwise"].iloc[1] == ""
