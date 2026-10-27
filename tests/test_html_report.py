"""The HTML report: assets ship with the package, and the page states the run's own numbers (no recomputation)."""
import json
import re
from importlib import resources

import pytest

from repeat_pump.core import html_report
from repeat_pump.core.config import load_config
from repeat_pump.core.pipeline import ReviewRequired, run_pipeline
from tests.fixtures.synthetic import build_world, write_cfg


def test_assets_load_through_package_resources():
    for name in ("report.html", "report.css", "report.js", "d3.v7.9.0.min.js", "maplibre-gl.v5.24.0.js", "maplibre-gl.v5.24.0.css",
                 "basemap-positron.json"):
        assert resources.files("repeat_pump.data").joinpath("report_assets", name).is_file(), name
    assert "BSD" in html_report._asset("maplibre-gl.v5.24.0.js")[:300] and "d3js.org" in html_report._asset("d3.v7.9.0.min.js")[:200]


@pytest.mark.parametrize("depth,cls", [(-5, "flooded"), (0, "normal"), (40, "normal"), (41, "at_risk"), (80, "at_risk"), (81, "high_risk")])
def test_klh_water_table_classes(depth, cls):
    assert html_report.tmat_class(depth) == cls


def test_the_page_carries_the_run_numbers(tmp_path):
    _, cfg = build_world(tmp_path)
    cfg["sekat"].update(target_rise_share=0.9, balance_drawdown_m=1.0)
    c = load_config(write_cfg(tmp_path / "c.yaml", cfg))
    for acc in ([], [2], [2, 6]):
        with pytest.raises(ReviewRequired):
            run_pipeline(c, accept=acc)
    run_pipeline(c, accept=[2, 6, 9], stop_after=11)
    out = html_report.build(tmp_path / "c.yaml", tmp_path / "r.html")
    html = out.read_text(encoding="utf8")
    data = json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1))
    rep = json.loads((tmp_path / "c.yaml").parent.joinpath(load_config(tmp_path / "c.yaml").run.output_gpkg).parent.joinpath("run_report.json").read_text())
    assert data["tiles"]["kept"] == rep["counts"]["7"]["proposed"] == len(data["geo"]["kept"]["features"])
    assert data["tiles"]["head_rule"] == rep["counts"]["7"]["head_rule"] == len(data["curve"])
    assert abs(data["curve"][-1]["cum"] - 1.0) < 1e-6
    assert "/*DATA*/" not in html and "/*JS*/" not in html and "generated, do not edit" in html
    # the rewetting paths: every kept block has its reach, ranks are numbers, and each pump route starts at an intake
    reach = data["geo"]["reach"]["features"]
    kept_ids = {f["properties"]["sekat_pro_id"] for f in data["geo"]["kept"]["features"]}
    assert reach and {f["properties"]["sekat_pro_id"] for f in reach} <= kept_ids
    assert all(isinstance(f["properties"]["benefit_rank"], int) for f in reach)
    routes, srcs = data["geo"]["routes"]["features"], data["geo"]["sources"]["features"]
    assert len(routes) == rep["counts"]["9"]["routes"]       # this world has no reachable target; direction is tested in test_m6_routing
    for f in routes:
        start = f["geometry"]["coordinates"][0]
        assert min(abs(start[0] - s["geometry"]["coordinates"][0]) + abs(start[1] - s["geometry"]["coordinates"][1]) for s in srcs) < 1e-4
    # the price register travels with the page; prices the run took from the preset are marked as described by it
    keys = {r["key"] for r in data["budget_sources"]}
    assert {"sekat_standard_idr", "revegetation_idr_per_ha", "well_idr", "fuel_idr_per_l", "standard"} <= keys
    assert all(r["url"] and r["accessed"] and r["status"] for r in data["budget_sources"] if r["key"] != "fuel_l_per_kwh")
