"""An input file changed in place (same path) makes stage 1 out of date, and a plain run does not reuse the old copy."""
import os

import geopandas as gpd

from repeat_pump.core.config import Config
from repeat_pump.core.pipeline import run_pipeline
from repeat_pump.core.requirements import fingerprint, inputs_digest
from tests.conftest import make_ctx


def _touch_later(path):
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))      # a save one second later, even on coarse file systems


def test_editing_an_input_in_place_changes_the_stage_1_fingerprint(world):
    cfg, tmp = world
    before = fingerprint(Config.model_validate(cfg), 1)
    c = gpd.read_file(tmp / "canals.gpkg")
    c.iloc[:1].to_file(tmp / "canals.gpkg", driver="GPKG")
    _touch_later(tmp / "canals.gpkg")
    after = fingerprint(Config.model_validate(cfg), 1)
    assert before["inputs"] == after["inputs"]                       # same settings and paths
    assert before["inputs_digest"] != after["inputs_digest"]


def test_a_shapefile_sidecar_counts(world):
    cfg, tmp = world
    gpd.read_file(tmp / "canals.gpkg").to_file(tmp / "canals.shp")
    cfg["inputs"]["canals"] = {"path": str(tmp / "canals.shp")}
    before = inputs_digest(Config.model_validate(cfg))
    _touch_later(tmp / "canals.dbf")                                  # attributes edited, geometry file untouched
    assert inputs_digest(Config.model_validate(cfg)) != before


def test_a_plain_run_redoes_stale_stages_and_skips_current_ones(world):
    cfg, tmp = world
    ctx = make_ctx(cfg)
    run_pipeline(ctx.cfg, stop_after=2, accept=[2], ctx=ctx)
    assert len(ctx.read_layer("inputs_clipped_canals")) == 2

    ctx = make_ctx(cfg)
    first = dict(ctx.state["stages"]["1"])
    run_pipeline(ctx.cfg, stop_after=2, accept=[2], ctx=ctx)         # nothing changed: stage 1 is not run again
    assert ctx.state["stages"]["1"] == first

    c = gpd.read_file(tmp / "canals.gpkg")
    c.iloc[:1].to_file(tmp / "canals.gpkg", driver="GPKG")            # the person deletes a canal and saves, same file
    _touch_later(tmp / "canals.gpkg")
    ctx = make_ctx(cfg)
    run_pipeline(ctx.cfg, stop_after=2, accept=[2], ctx=ctx)
    assert len(ctx.read_layer("inputs_clipped_canals")) == 1          # the new data, not the copy from the first run
    assert ctx.state["stages"]["2"]["status"] == "done"
    assert ctx.state["stages"]["2"]["fingerprint"] == fingerprint(ctx.cfg, 2)
