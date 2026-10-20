"""Wizard pieces that need no Qt: early layer checks, map visibility, advanced settings, list parsing, one datum field."""
import sys
from pathlib import Path

import pytest
import yaml

from repeat_pump.core.config import load_config
from repeat_pump.core.requirements import OPTIONS_BY_STAGE, check
from tests.fixtures.synthetic import write_cfg

PLUGIN = Path(__file__).parents[1] / "qgis_plugin" / "repeat_pump_qgis"
sys.path.insert(0, str(PLUGIN.parent))
from repeat_pump_qgis import runconfig as rc  # noqa: E402
from repeat_pump_qgis.wizard import i18n, maptools, preflight as pf, viewmodel as vm  # noqa: E402

EXAMPLE = Path(__file__).parents[1] / "configs" / "example_khg.yaml"
BOX = (0.0, 0.0, 1000.0, 1000.0)


@pytest.fixture(autouse=True)
def english_after():
    yield
    i18n.set_language("en")


def L(role, **kw):
    kw.setdefault("crs", "EPSG:32749")
    kw.setdefault("extent", BOX)
    return pf.LayerInfo(role, role, **kw)


def good():
    return {"dtm": L("dtm"), "moisture": L("moisture"), "subkhg": L("subkhg", fields=["unit_id"], features=2),
            "canals": L("canals", fields=["canal_class"], features=5), "burn_area": L("burn_area", features=3), "peat_depth": L("peat_depth", features=3)}


# ---------------------------------------------------------------- early layer checks
def test_clean_setup_has_no_findings_and_takes_crs_from_the_dtm():
    a = pf.assess(good())
    assert not a.findings and a.crs == "EPSG:32749" and a.subkhg_id_field == "unit_id" and not a.needs_reproject


def test_dtm_in_degrees_is_an_error():
    d = good(); d["dtm"] = L("dtm", crs="EPSG:4326", geographic=True)
    assert any("projected" in f.text for f in pf.assess(d).errors)


def test_another_crs_blocks_unless_reprojection_is_ticked():
    d = good(); d["canals"] = L("canals", crs="EPSG:32748", fields=["canal_class"], features=5)
    a = pf.assess(d)
    assert a.needs_reproject and any("32748" in f.text and "reproject" in f.text for f in a.errors)
    b = pf.assess(d, reproject=True)
    assert b.needs_reproject and not b.errors and any(f.level == "info" and "will be reprojected" in f.text for f in b.findings)


def test_missing_columns_and_empty_or_temporary_layers_are_errors():
    d = good()
    d["subkhg"] = L("subkhg", fields=["name"], features=2)
    d["canals"] = L("canals", fields=["depth_m"], features=5)
    d["burn_area"] = L("burn_area", features=0)
    d["peat_depth"] = L("peat_depth", features=3, is_file=False)
    text = " | ".join(f.text for f in pf.assess(d).errors)
    assert "subkhg_id" in text and "canal_class" in text and "no features" in text and "saved to a file" in text


def test_coverage_and_overlap_use_the_subkhg_extent():
    d = good(); d["peat_depth"] = L("peat_depth", features=3, extent=(0, 0, 500, 1000))
    assert any("50 %" in f.text for f in pf.assess(d).findings)
    d["peat_depth"] = L("peat_depth", features=3, extent=(5000, 5000, 6000, 6000))
    assert any("does not overlap" in f.text for f in pf.assess(d).errors)


def test_river_levels_and_the_dtm_datum_are_picked_up():
    d = good(); d["rivers"] = L("rivers", fields=["dry_season_wl_m"]); d["dtm"] = L("dtm", vertical_crs="EPSG:5773")
    a = pf.assess(d)
    assert a.river_levels and a.vertical_datum == "EPSG:5773"


def test_findings_are_translated():
    i18n.set_language("id")
    d = good(); d["dtm"] = L("dtm", crs="EPSG:4326", geographic=True)
    assert "terproyeksi" in pf.assess(d).errors[0].text


# ---------------------------------------------------------------- map handling
def test_a_stage_shows_its_own_layers_and_hides_the_rest():
    present = ["canals_clean", "canal_segments", "sekat_proposed", "pump_routes", "flow_acc"]
    assert maptools.visibility_plan(6, present) == {"canals_clean": False, "canal_segments": True, "sekat_proposed": False, "pump_routes": False, "flow_acc": False}
    plan = maptools.visibility_plan(7, present)
    assert plan["sekat_proposed"] and plan["canals_clean"] and not plan["pump_routes"]
    assert maptools.visibility_plan(3, present)["flow_acc"]


def test_stages_without_an_entry_show_everything():
    assert all(maptools.visibility_plan(1, ["a", "b"]).values())


def test_every_layer_in_the_plans_has_a_legend_name():
    names = {n for ns in maptools.STAGE_VISIBLE.values() for n in ns}
    assert names <= set(maptools.LEGEND_NAMES), names - set(maptools.LEGEND_NAMES)


# ---------------------------------------------------------------- advanced settings
def test_every_option_has_a_field_with_a_readable_name_and_an_indonesian_text():
    for keys in OPTIONS_BY_STAGE.values():
        for k in keys:
            f = vm.FIELDS[k]
            assert f.label in i18n.ID and (not f.help or f.help in i18n.ID), k
            if f.kind in ("enum", "multi"):
                assert len(f.labels) == len(f.options) and all(x in i18n.ID for x in f.labels), k


def test_options_are_listed_per_stage_and_never_block_a_run():
    m = vm.WizardModel(check(load_config(EXAMPLE)), {"stages": {}, "warnings": [], "report": {}}, None)
    assert "sekat.dA_m" in {p.key for p in m.stage(7).options} and m.stage(8).options == []
    assert all(p.option and not p.recommended for v in m.stages for p in v.options)
    assert "pumping.routing" in {p.key for p in m.stage(9).options}


def test_a_check_without_options_still_works():
    c = check(load_config(EXAMPLE))
    for s in c["stages"]:
        s.pop("options")
    assert vm.WizardModel(c, {"stages": {}, "warnings": [], "report": {}}, None).stage(7).options == []


def test_list_and_id_parsing():
    assert vm.parse_floatlist("6; 10") == [6.0, 10.0] and vm.parse_floatlist("15,100", 2) == [15.0, 100.0]
    assert vm.parse_floatlist("15", 2) is None and vm.parse_floatlist("a;b") is None and vm.parse_floatlist("") is None
    assert vm.format_list([6.0, 10.0]) == "6, 10" and vm.parse_idlist("1, 4; KHG-7") == [1, 4, "KHG-7"]
    assert vm.option_labels(vm.FIELDS["hydro.flow_algorithm"])[0].startswith("D-infinity")


def test_emptying_an_option_removes_the_key_so_the_default_applies():
    d = {"sekat": {"dA_m": 0.5, "max_spacing_m": 400}}
    rc.unset_dotted(d, "sekat.dA_m")
    rc.unset_dotted(d, "sekat.not_there")
    rc.unset_dotted(d, "nothing.at.all")
    assert d == {"sekat": {"max_spacing_m": 400}}


def test_moisture_tiles_are_written_as_a_list(tmp_path):
    f = tmp_path / "t.yaml"
    f.write_text(EXAMPLE.read_text(encoding="utf8"), encoding="utf8")
    assert rc.build_run_config(f, moisture=["a.tif", "b.tif"])["inputs"]["moisture"]["paths"] == ["a.tif", "b.tif"]
    assert rc.build_run_config(f, moisture="a.tif")["inputs"]["moisture"]["paths"] == ["a.tif"]


# ---------------------------------------------------------------- one datum field
def test_the_two_datums_are_one_field_in_the_wizard(world):
    cfg, tmp = world
    cfg["run"]["vertical_datum"] = None
    cfg["inputs"]["rivers"]["vertical_datum"] = None
    m = vm.WizardModel(check(load_config(write_cfg(tmp / "c.yaml", cfg))), {"stages": {}, "warnings": [], "report": {}}, None)
    v = m.stage(1)
    keys = [p.key for p in v.params]
    assert "run.vertical_datum" in keys and "inputs.rivers.vertical_datum" not in keys
    assert v.missing.count("run.vertical_datum") == 1 and "inputs.rivers.vertical_datum" not in v.missing


# ---------------------------------------------------------------- final screen and diagrams
REPORT = {"counts": {"4": {"short_flagged": 1}, "6": {"scored": 5, "selected": 1}, "7": {"existing": 2, "proposed": 2}, "10": {"gates_required": 3}},
          "ipg": [{"ipg": 0.33}, {"ipg": 1.5}, {"ipg": None}],
          "routing": {"n_targets": 1, "n_unreachable": 1, "total_length_m": 1780.0, "total_lift_m": 1.78},
          "pumps": [{"station_id": "PS001", "q_m3s": 0.0288, "h_m": 1.4, "p_kw": 0.61, "units_needed": 1, "shortfall_m3s": 0.01}],
          "files": {"flow_acc": "x/flow_acc.tif"}, "warnings": ["a", "b"], "preset": {"keys": ["pumping.manning_n"]}}


def test_summary_restates_the_report_and_flags_what_needs_attention():
    from repeat_pump_qgis.wizard import summary
    s = summary.summarise(REPORT)
    rows = {name: dict(sec.rows) for name, sec in ((x.title, x) for x in s.sections)}
    assert rows["Canal segments"]["Selected as targets"] == "1" and rows["Sekat"]["Canals with too few sekat (IPG below 1)"] == "1 / 2"
    assert rows["Routes"]["Total lift"] == "1.78 m" and rows["Pumps"]["Total flow"] == "28.8 L/s"
    assert s.pump_table[0][0] == "Station" and s.pump_table[1] == ["PS001", "28.8", "1.40", "0.61", "1"]
    text = " ".join(s.notes)
    assert "cannot deliver" in text and "cannot be reached" in text and "1 values came from the proposed defaults" in text and "2 warnings" in text
    assert s.files == [("Flow accumulation", "x/flow_acc.tif")]


def test_summary_of_an_empty_report_does_not_fail(tmp_path):
    from repeat_pump_qgis.wizard import summary
    assert summary.summarise({}).sections == [] and summary.load_report(tmp_path / "none.gpkg") is None
    (tmp_path / "run_report.json").write_text("not json", encoding="utf8")
    assert summary.load_report(tmp_path / "x.gpkg") is None


def test_diagrams_are_well_formed_in_both_languages_and_follow_the_language():
    import xml.etree.ElementTree as ET
    from repeat_pump_qgis.wizard import diagrams
    assert set(diagrams.DIAGRAMS) == {6, 7, 9} and diagrams.svg_for(3) is None
    for stage in diagrams.DIAGRAMS:
        en = diagrams.svg_for(stage)
        ET.fromstring(en)
        i18n.set_language("id")
        id_ = diagrams.svg_for(stage)
        ET.fromstring(id_)
        i18n.set_language("en")
        assert en != id_, stage
    assert "jarak = dA / kemiringan" not in diagrams.svg_for(7)
