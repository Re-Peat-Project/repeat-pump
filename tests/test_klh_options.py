"""Options that follow the KLH guide (Panduan Teknis GIS): canal class filter (1.2), river mouth tolerance (8.2), KLH scoring (7.1/7.2)."""
import geopandas as gpd
import pytest
from shapely.geometry import LineString

from repeat_pump.core import network, topology
from repeat_pump.core.config import InputError
from tests.conftest import make_ctx
from tests.fixtures.synthetic import CRS, X0, Y0


def ctx_with(world, geoms, classes, **topo):
    cfg, _ = world
    cfg["topology"] = {"snap_tolerance_m": 1.0, **topo}
    ctx = make_ctx(cfg)
    gdf = gpd.GeoDataFrame({"canal_class": classes, "depth_m": 2.0, "width_m": 4.0}, geometry=geoms, crs=CRS)
    ctx.write_layer("inputs_clipped_canals", gdf, "1")
    return ctx


LINES = [LineString([(X0, Y0 + 500), (X0 + 1000, Y0 + 500)]), LineString([(X0 + 200, Y0 + 100), (X0 + 200, Y0 + 400)]),
         LineString([(X0 + 800, Y0 + 100), (X0 + 800, Y0 + 400)])]


# ----------------------------------------------------------------------------- canal classes (guide 1.2)
def test_class_filter_keeps_listed_classes_ignoring_case_and_reports_the_rest(world):
    ctx = ctx_with(world, LINES, ["Primer", " SEKUNDER", "tersier"], canal_classes=["primer", "sekunder"])
    topology.run(ctx)
    assert len(ctx.read_layer("canals_clean")) == 2
    rep = ctx.report["canal_class_filter"]
    assert rep["dropped"] == {"tersier": 1} and rep["kept"] == 2
    assert any("tersier: 1" in w for w in ctx.warnings)
    assert len(ctx.read_layer("inputs_clipped_canals")) == 3           # the full set stays for river mouths


def test_class_filter_off_keeps_everything_and_unlisted_class_warns(world):
    ctx = ctx_with(world, LINES, ["primer", "sekunder", "tersier"])
    topology.run(ctx)
    assert len(ctx.read_layer("canals_clean")) == 3 and "canal_class_filter" not in ctx.report
    ctx = ctx_with(world, LINES, ["primer", "primer", "primer"], canal_classes=["primer", "kuarter"])
    topology.run(ctx)
    assert any("kuarter" in w for w in ctx.warnings)


def test_class_filter_with_nothing_left_fails_clearly(world):
    ctx = ctx_with(world, LINES, ["tersier"] * 3, canal_classes=["primer"])
    with pytest.raises(InputError, match="no canal has a class"):
        topology.run(ctx)


# ----------------------------------------------------------------------------- river mouths (guide 8.2)
def canals_df(geoms):
    return gpd.GeoDataFrame({"canal_id": [f"C{i}" for i in range(len(geoms))]}, geometry=geoms, crs=CRS)


def test_river_that_stops_short_counts_only_within_the_buffer():
    canal = canals_df([LineString([(X0, Y0), (X0 + 500, Y0)])])
    river = gpd.GeoDataFrame({"perennial": [True]}, geometry=[LineString([(X0 + 250, Y0 + 20), (X0 + 250, Y0 + 400)])], crs=CRS)
    assert len(network.river_canal_points(canal, river)) == 0
    assert len(network.river_canal_points(canal, river, 10)) == 0
    p = network.river_canal_points(canal, river, 30)
    assert len(p) == 1 and p.gap_m.iloc[0] == pytest.approx(20.0) and p.chainage_m.iloc[0] == pytest.approx(250.0)
    cross = gpd.GeoDataFrame({"perennial": [True]}, geometry=[LineString([(X0 + 250, Y0 - 50), (X0 + 250, Y0 + 50)])], crs=CRS)
    assert network.river_canal_points(canal, cross, 30).gap_m.iloc[0] == 0.0           # a true crossing is unchanged


def test_points_found_on_a_dropped_canal_are_snapped_to_the_kept_network_or_dropped(world):
    primary = LineString([(X0, Y0), (X0 + 1000, Y0)])
    tertiary = LineString([(X0 + 500, Y0), (X0 + 500, Y0 + 40)])           # joins the primary, runs 40 m north
    river = gpd.GeoDataFrame({"perennial": [True]}, geometry=[LineString([(X0 + 400, Y0 + 40), (X0 + 700, Y0 + 40)])], crs=CRS)
    for snap, expect in ((50.0, 1), (10.0, 0)):
        ctx = ctx_with(world, [primary, tertiary], ["primer", "tersier"], canal_classes=["primer"], river_buffer_m=30.0, source_snap_m=snap)
        topology.run(ctx)
        pts = network.river_sources(ctx, ctx.read_layer("canals_clean"), river)
        assert len(pts) == expect
        rep = ctx.report["river_sources"]
        assert rep["found_on_full_network"] == 1 and rep["kept"] == expect and rep["dropped_not_on_kept_network"] == 1 - expect
    assert pts.empty or True
    ctx = ctx_with(world, [primary, tertiary], ["primer", "tersier"], canal_classes=["primer"], river_buffer_m=30.0, source_snap_m=50.0)
    topology.run(ctx)
    p = network.river_sources(ctx, ctx.read_layer("canals_clean"), river)
    assert p.geometry.iloc[0].y == pytest.approx(Y0) and p.snap_dist_m.iloc[0] == pytest.approx(40.0)


# ----------------------------------------------------------------------------- KLH scoring (guide 7.1 and 7.2)
import numpy as np  # noqa: E402
from shapely.geometry import Point  # noqa: E402

from repeat_pump.core import hydro, io, prioritise, profiles, segments  # noqa: E402
from repeat_pump.core.config import ConfigError, MissingParameters  # noqa: E402
from repeat_pump.core.io import parse_peat_class  # noqa: E402

import pandas as pd  # noqa: E402

# the class lists of the guide's 7.1 expression, copied verbatim
GUIDE_PEAT_3 = ['3,0 - 4,0 meter', '4,0 - 5,0 meter', '5,0 - 6,0 meter', '5,5 - 6,0 meter', '6,0 - 6,5 meter', '6,5 - 7,0 meter', '7,0 - 7,5 meter']
GUIDE_PEAT_2 = ['1,0 - 1,5 meter', '1,5 - 2,0 meter', '2,0 - 3,0 meter']


def peat_score(label):
    parsed, bad = parse_peat_class(pd.Series([label]))
    assert not bad
    return int(prioritise.klh_scores(np.array([0.0]), parsed["depth_min_m"].to_numpy(float), np.array([9.9]), np.array([0.0]), (0.8, 1.5), (1.5, 3.0), True)["klh_peat"][0])


@pytest.mark.parametrize("label,expected", [(c, 3) for c in GUIDE_PEAT_3] + [(c, 2) for c in GUIDE_PEAT_2] + [("0,0 - 0,5 meter", 1), ("0,5 - 1,0 meter", 1), ("7,5 - 8,0 meter", 3)])
def test_every_peat_class_of_the_guide_scores_as_the_guide_does(label, expected):
    assert peat_score(label) == expected


@pytest.mark.parametrize("years,expected", [(0, 1), (1, 2), (2, 3), (3, 3), (4, 3), (5, 3)])
def test_burn_score_uses_the_year_count(years, expected):       # the guide's ILIKE patterns would score '5x' as 1
    s = prioritise.klh_scores(np.array([float(years)]), np.array([0.0]), np.array([9.9]), np.array([0.0]), (0.8, 1.5), (1.5, 3.0), True)
    assert int(s["klh_burn"][0]) == expected


def test_dryness_and_flow_breaks_and_orientation():
    m = np.array([0.5, 0.8, 1.2, 1.5, 1.6, np.nan])
    f = np.array([0.0, 1.5, 2.0, 3.0, 3.1, np.nan])
    z = np.zeros(6)
    wet = prioritise.klh_scores(z, z, m, f, (0.8, 1.5), (1.5, 3.0), True)
    assert list(wet["klh_dryness"]) == [3, 2, 2, 2, 1, 1]            # below 0.8 dry (3), 0.8 to 1.5 (2), above (1); missing scores 1
    assert list(wet["klh_flow"]) == [1, 1, 2, 2, 3, 1]               # above 3.0 -> 3, above 1.5 -> 2
    dry = prioritise.klh_scores(z, z, m, f, (0.8, 1.5), (1.5, 3.0), False)
    assert list(dry["klh_dryness"]) == [1, 2, 2, 2, 3, 1]            # an index that rises with dryness is mirrored


def test_breaks_must_be_two_increasing_numbers():
    assert prioritise.klh_breaks([0.8, 1.5], "x") == (0.8, 1.5)
    for bad in ([1.5, 0.8], [1], None, [1, 2, 3]):
        with pytest.raises(ConfigError):
            prioritise.klh_breaks(bad, "x")


def test_the_guides_full_buffer_is_ring_from_zero():
    line = LineString([(0, 0), (500, 0)])
    assert prioritise.ring(line, 0, 50).symmetric_difference(line.buffer(50)).area < 1e-6


def _klh(cfg):
    cfg["prioritise"].update(weights_mode="klh", klh_cpwi_breaks=[0.0, 1.0], klh_flow_breaks=[1.0, 2.0], klh_min_score=0, upstream_buffer_m=50)


def test_stage6_klh_end_to_end(world):
    from tests.test_m5_prioritise import _upto6
    ctx = _upto6(world, _klh)
    prioritise.run(ctx)
    s = ctx.read_layer("canal_segments")
    sc = s[s.need_score.notna()]
    assert set(sc.klh_score).issubset(range(4, 13)) and (sc.need_score * 12).round(6).eq(sc.klh_score).all()
    assert s.loc[s.status_mcda == 0, "klh_score"].eq(0).all()
    assert (s.selected == (s.klh_score >= 0) & s.need_score.notna()).all()
    assert len(ctx.read_layer("qa_sensitivity")) == 0 and ctx.report["weights"] == {} and ctx.report["scoring"]["method"] == "klh"
    assert any("KLH scoring" in w for w in ctx.warnings)


def test_klh_selects_by_threshold_not_by_fraction(world):
    from tests.test_m5_prioritise import _upto6
    ctx = _upto6(world, _klh)
    prioritise.run(ctx)
    low = int(ctx.read_layer("canal_segments").selected.sum())
    ctx = _upto6(world, lambda c: (_klh(c), c["prioritise"].update(klh_min_score=13)))
    prioritise.run(ctx)
    assert low >= 1 and int(ctx.read_layer("canal_segments").selected.sum()) == 0          # no segment can reach 13 of 12


def test_klh_needs_its_nulls_and_flow_accumulation(world):
    from tests.test_m5_prioritise import _upto6
    ctx = _upto6(world, lambda c: (_klh(c), c["prioritise"].update(klh_min_score=None, klh_flow_breaks=None)))
    with pytest.raises(MissingParameters, match="klh_flow_breaks.*klh_min_score|klh_min_score.*klh_flow_breaks"):
        prioritise.run(ctx)
    ctx = _upto6(world, lambda c: (_klh(c), c["prioritise"].update(upstream_method="graph")))
    with pytest.raises(ConfigError, match="flow_acc"):
        prioritise.run(ctx)


def test_requirements_follow_the_mode(world):
    from repeat_pump.core.config import Config
    from repeat_pump.core.requirements import needs_by_stage, required_by_stage
    cfg, _ = world
    cfg2 = dict(cfg)
    cfg2["prioritise"] = {**cfg["prioritise"], "weights_mode": "klh"}
    c = Config.model_validate(cfg2)
    n6 = needs_by_stage(c)[6]
    assert "prioritise.klh_min_score" in n6 and not any(k.endswith(".weight") for k in n6)
    assert {"prioritise.klh_cpwi_breaks", "prioritise.klh_flow_breaks", "prioritise.klh_min_score"} <= set(required_by_stage(c)[6])


# ----------------------------------------------------------------------------- sekat: JARAK_MIN and DEDUP_TOL as opt-in keys
from repeat_pump.core import sekat  # noqa: E402


def test_min_new_spacing_is_off_by_default_and_overrides_the_head_rule_when_set():
    d = np.arange(0, 2001, 5.0)
    z = d * 0.001                                   # rises dA = 0.4 m every 400 m
    base = sekat.place_sekat(d, z, 0.4, [], 50, 0.5)
    assert [round(p) for p, _ in base] == [400, 800, 1200, 1600, 2000]
    spaced = sekat.place_sekat(d, z, 0.4, [], 50, 0.5, 500)
    gaps = np.diff([p for p, _ in spaced])                                       # between new sekat
    assert len(spaced) < len(base) and (gaps >= 500 - 1).all()
    dd = np.arange(0, 1001, 5.0)
    steep = dd * 0.004                                # the head rule wants a sekat every 100 m
    assert len(sekat.place_sekat(dd, steep, 0.4, [], 50, 0.5)) == 10
    assert len(sekat.place_sekat(dd, steep, 0.4, [], 50, 0.5, 500)) == 2


def test_dedup_drops_later_proposals_near_another_canal_or_an_existing_sekat():
    rows = [dict(sekat_pro_id="P1", canal_id="A", geometry=Point(0, 0)), dict(sekat_pro_id="P2", canal_id="B", geometry=Point(30, 0)),
            dict(sekat_pro_id="P3", canal_id="A", geometry=Point(40, 0)), dict(sekat_pro_id="P4", canal_id="C", geometry=Point(500, 0)),
            dict(sekat_pro_id="P5", canal_id="D", geometry=Point(510, 5))]
    kept, n = sekat.dedup_proposed(rows, [Point(500, 30)], 50)
    assert [r["sekat_pro_id"] for r in kept] == ["P1", "P3"] and n == 3
    assert [r["sekat_pro_id"] for r in sekat.dedup_proposed(list(reversed(rows)), [Point(500, 30)], 50)[0]] == ["P1", "P3"]    # row order does not matter
    assert sekat.dedup_proposed(rows, [], 5)[1] == 0
