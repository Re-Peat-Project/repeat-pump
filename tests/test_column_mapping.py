"""Inputs whose columns are named differently: ``inputs.<role>.columns`` maps the expected name to the user's."""
import geopandas as gpd
import pandas as pd
import pytest

from repeat_pump.core import io
from repeat_pump.core.config import CANONICAL_COLUMNS, Config, InputError, InputsCfg, snake_name
from repeat_pump.core.requirements import _priority_columns, rivers_have_levels
from tests.conftest import make_ctx


def rewrite(path, rename):
    g = gpd.read_file(path)
    g.rename(columns=rename).to_file(path, driver="GPKG")


def test_canals_columns_are_mapped_with_the_engines_name_normalising(world):
    cfg, tmp = world
    rewrite(tmp / "canals.gpkg", {"canal_class": "Kelas Kanal", "depth_m": "Dalam (m)"})
    cfg["inputs"]["canals"]["columns"] = {"canal_class": "Kelas Kanal", "depth_m": "dalam (M)"}       # case and punctuation do not matter
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    c = ctx.read_layer("inputs_clipped_canals")
    assert sorted(c["canal_class"]) == ["primer", "sekunder"] and (c["depth_m"] == 2.0).all()


def test_a_mapped_column_that_is_not_in_the_data_is_a_clear_error(world):
    cfg, _ = world
    cfg["inputs"]["canals"]["columns"] = {"canal_class": "no_such_column"}
    with pytest.raises(InputError, match="no_such_column.*canal_class|canal_class.*no_such_column"):
        io.run_stage1(make_ctx(cfg))


def test_mapping_wins_over_an_existing_column_of_the_expected_name_and_warns(world):
    cfg, tmp = world
    g = gpd.read_file(tmp / "canals.gpkg")
    g["jenis"] = g["canal_class"]
    g["canal_class"] = "tersier"                         # the data's own column is wrong for the engine
    g.to_file(tmp / "canals.gpkg", driver="GPKG")
    cfg["inputs"]["canals"]["columns"] = {"canal_class": "jenis"}
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    assert sorted(ctx.read_layer("inputs_clipped_canals")["canal_class"]) == ["primer", "sekunder"]
    assert any("ignored" in w for w in ctx.warnings)


def test_burn_and_peat_and_sekat_and_subkhg_mapping(world):
    cfg, tmp = world
    rewrite(tmp / "burn.gpkg", {"BURN_FREQ": "Frekuensi Bakar"})
    rewrite(tmp / "peat.gpkg", {"PEAT_THICK": "Tebal Gambut"})
    rewrite(tmp / "sekat.gpkg", {"sekat_id": "Kode"})
    rewrite(tmp / "subkhg.gpkg", {"subkhg_id": "Kode KHG"})
    cfg["inputs"]["burn_area"]["columns"] = {"burn_freq": "Frekuensi Bakar"}
    cfg["inputs"]["peat_depth"]["columns"] = {"peat_thick": "Tebal Gambut"}
    cfg["inputs"]["sekat_existing"]["columns"] = {"sekat_id": "Kode"}
    cfg["inputs"]["subkhg"]["columns"] = {"subkhg_id": "Kode KHG"}
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    assert ctx.report["validation"]["selected_subkhg"] == ["A"]
    assert ctx.read_layer("inputs_clipped_burn_area")["burn_freq_n"].iloc[0] == 2
    assert sorted(ctx.read_layer("inputs_clipped_peat_depth")["depth_min_m"]) == [1.0, 3.0]
    assert sorted(ctx.read_layer("inputs_clipped_sekat_existing")["sekat_id"]) == ["E1", "E2"]


def test_priority_csv_mapping_stage1_and_requirements_agree(world):
    cfg, tmp = world
    pd.DataFrame({"Kode KHG": ["A", "B"], "Peringkat": [1, 2], "Defisit mm": [200.0, 100.0], "Hari": [90, 90]}).to_csv(tmp / "prio.csv", index=False)
    cfg["inputs"]["subkhg_priority"]["columns"] = {"subkhg_id": "Kode KHG", "priority_rank": "peringkat", "deficit_mm": "defisit_mm", "design_period_days": "hari"}
    c = Config.model_validate(cfg)
    assert {"subkhg_id", "priority_rank", "deficit_mm", "design_period_days"} <= _priority_columns(c)      # stage 10's needs see the mapped names
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    sel = ctx.read_layer("subkhg_selected")
    assert list(sel["subkhg_id"]) == ["A"] and sel["deficit_mm"].iloc[0] == 200.0 and ctx.report["validation"]["demand_source"] == "deficit_table"


def test_rivers_levels_are_seen_by_requirements_under_any_spelling_and_mapping(world):
    cfg, tmp = world
    assert rivers_have_levels(Config.model_validate(cfg))
    rewrite(tmp / "rivers.gpkg", {"dry_season_wl_m": "DRY_SEASON_WL_M"})                # upper case: stage 1 accepts it, so must the check
    assert rivers_have_levels(Config.model_validate(cfg))
    rewrite(tmp / "rivers.gpkg", {"DRY_SEASON_WL_M": "Muka Air Kemarau"})
    assert not rivers_have_levels(Config.model_validate(cfg))
    cfg["inputs"]["rivers"]["columns"] = {"dry_season_wl_m": "Muka Air Kemarau"}
    assert rivers_have_levels(Config.model_validate(cfg))
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    assert ctx.read_layer("inputs_clipped_rivers")["dry_season_wl_m"].iloc[0] == 2.0


def test_canonical_columns_name_real_inputs_and_snake_name_is_the_engines_rule():
    assert set(CANONICAL_COLUMNS) <= set(InputsCfg.model_fields)
    assert all(snake_name(c) == c for cols in CANONICAL_COLUMNS.values() for c in cols)
    assert snake_name("Kelas Kanal") == "kelas_kanal" and snake_name("  BURN_FREQ ") == "burn_freq" and snake_name("1x") == "f_1x"
