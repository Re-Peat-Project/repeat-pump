import copy
import re
from pathlib import Path

import pytest
import rasterio

from repeat_pump.core import io
from repeat_pump.core.config import (Config, CRSMismatchError, InputError, MissingParameters, NeedsHuman, SurfaceTypeError, load_config)
from tests.conftest import make_ctx
from tests.fixtures.synthetic import build_world, write_cfg


def test_crs_mismatch_raises(tmp_path):
    """Test 4: DTM in EPSG:32748 with config EPSG:32749 and auto_reproject false must raise."""
    _, cfg = build_world(tmp_path, dtm_crs="EPSG:32748")
    with pytest.raises(CRSMismatchError):
        io.run_stage1(make_ctx(cfg))


def test_auto_reproject_logs(tmp_path):
    _, cfg = build_world(tmp_path, dtm_crs="EPSG:32748")
    cfg["run"]["auto_reproject"] = True
    ctx = make_ctx(cfg)
    # the fixture raster is mislabelled, so after reprojection it no longer overlaps: a clear InputError, not a silent empty crop
    with pytest.raises(InputError, match="does not overlap"):
        io.run_stage1(ctx)
    assert any("reprojected" in w for w in ctx.warnings)


def test_dsm_refused(world):
    """Test 5: surface_type DSM must raise."""
    cfg, _ = world
    cfg["inputs"]["dtm"]["surface_type"] = "DSM"
    with pytest.raises(SurfaceTypeError):
        io.run_stage1(make_ctx(cfg))


def test_stage1_ok_and_layers(world):
    cfg, _ = world
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    assert ctx.report["validation"]["selected_subkhg"] == ["A"]
    assert len(ctx.read_layer("inputs_clipped_canals")) == 2
    bf = ctx.read_layer("inputs_clipped_burn_area")
    assert bf["burn_freq_n"].iloc[0] == 2
    pe = ctx.read_layer("inputs_clipped_peat_depth")
    assert sorted(pe["depth_min_m"]) == [1.0, 3.0]
    with rasterio.open(ctx.report["inputs"]["dtm"]) as d:
        assert d.crs.to_epsg() == 32749


def test_accuracy_warning(world):
    cfg, _ = world
    cfg["inputs"]["dtm"]["vertical_rmse_m"] = 0.25  # dA 0.4 < 0.5
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    assert any("ACCURACY" in w for w in ctx.warnings)


def test_missing_params_listed_together(world):
    cfg, _ = world
    cfg["run"]["clip_margin_m"] = None
    cfg["inputs"]["dtm"]["vertical_rmse_m"] = None
    with pytest.raises(MissingParameters) as e:
        io.run_stage1(make_ctx(cfg))
    # one stage fails per require() call; the message must name its keys clearly
    assert "run.clip_margin_m" in str(e.value)


def test_river_datum_unknown_stops(world):
    cfg, _ = world
    cfg["inputs"]["rivers"]["vertical_datum"] = None
    with pytest.raises(NeedsHuman):
        io.run_stage1(make_ctx(cfg))


def test_parsers():
    import pandas as pd
    s, bad = io.parse_burn_freq(pd.Series(["2x", "3X", 1, "tidak ada", None]))
    assert list(s.dropna()) == [2, 3, 1] and "tidak ada" in bad
    d, bad = io.parse_peat_class(pd.Series(["3,0 - 4,0 meter", "foo"]))
    assert d.iloc[0].tolist() == [3.0, 4.0] and bad == ["foo"]


def test_core_does_not_import_qgis():
    for p in Path(__file__).parents[1].joinpath("repeat_pump", "core").glob("*.py"):
        assert not re.search(r"^\s*(import|from)\s+qgis", p.read_text(encoding="utf8"), re.M), p


def test_all_missing_stage1_params_in_one_message(world):
    cfg, _ = world
    cfg["run"]["clip_margin_m"] = None
    cfg["inputs"]["dtm"]["vertical_rmse_m"] = None
    with pytest.raises(MissingParameters) as e:
        io.run_stage1(make_ctx(cfg))
    assert "run.clip_margin_m" in str(e.value) and "inputs.dtm.vertical_rmse_m" in str(e.value)


def test_crop_uses_windowed_copy_regardless_of_budget(world):
    cfg, _ = world
    cfg["run"]["memory_budget_gb"] = 1e-9           # a whole-array read would be refused
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    with rasterio.open(ctx.report["inputs"]["dtm"]) as d:
        assert d.width > 0 and d.height > 0


def test_example_config_parses_and_stage1_stops(tmp_path):
    import shutil
    from repeat_pump.cli import main
    src = Path(__file__).parents[1] / "configs" / "example_khg.yaml"
    dst = tmp_path / "example.yaml"
    shutil.copy(src, dst)
    cfg = load_config(dst)
    assert isinstance(cfg, Config)
    with pytest.raises(MissingParameters) as e:
        io.run_stage1(make_ctx(cfg.model_dump()))
    assert "run.clip_margin_m" in str(e.value) and "inputs.dtm.vertical_rmse_m" in str(e.value)
    assert main(["run", "--config", str(dst)]) == 1


def test_cli_review_exit_code(world):
    from repeat_pump.cli import main
    from tests.fixtures.synthetic import write_cfg
    cfg, tmp = world
    assert main(["run", "--config", str(write_cfg(tmp / "c.yaml", cfg))]) == 2   # Stage 2 awaits review
