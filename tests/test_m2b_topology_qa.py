import geopandas as gpd
from shapely.geometry import LineString

from repeat_pump.core import io, topology
from tests.conftest import make_ctx
from tests.fixtures.synthetic import CRS, X0, Y0


def _canals(ctx, geoms):
    ctx.write_layer("inputs_clipped_canals", gpd.GeoDataFrame({"canal_class": ["primer"] * len(geoms), "depth_m": 2.0, "width_m": 4.0},
                                                              geometry=geoms, crs=CRS), "1")


def test_overshoot_trimmed_only_when_configured(world):
    cfg, _ = world
    main = LineString([(X0, Y0 + 500), (X0 + 1000, Y0 + 500)])
    cross = LineString([(X0 + 500, Y0 + 500), (X0 + 500, Y0 + 900)])
    stub = LineString([(X0 + 500, Y0 + 500), (X0 + 500, Y0 + 497)])      # 3 m overshoot below the junction
    ctx = make_ctx(cfg); _canals(ctx, [main, cross, stub]); topology.run(ctx)
    assert len(ctx.read_layer("qa_topology_trimmed")) == 0                # off while overshoot_max_m is null
    cfg["topology"]["overshoot_max_m"] = 5.0
    ctx2 = make_ctx(cfg); _canals(ctx2, [main, cross, stub]); topology.run(ctx2)
    t = ctx2.read_layer("qa_topology_trimmed")
    assert len(t) == 1 and abs(t.length_m.iloc[0] - 3.0) < 1e-6
    assert len(ctx2.read_layer("canals_clean")) == 3                       # main split in two, cross; stub gone


def test_disconnected_component_and_issues_flagged(world):
    cfg, _ = world
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    connected = LineString([(X0, Y0 + 500), (X0 + 800, Y0 + 500)])            # reaches the river
    island = LineString([(X0 + 1200, Y0 + 200), (X0 + 1500, Y0 + 200)])       # no river connection
    bow = LineString([(X0 + 1200, Y0 + 800), (X0 + 1300, Y0 + 900), (X0 + 1300, Y0 + 800), (X0 + 1200, Y0 + 900)])  # self-intersecting
    _canals(ctx, [connected, island, bow])
    topology.run(ctx)
    c = ctx.read_layer("canals_clean")
    assert set(c[c.reaches_river].length_m.round()) == {800.0}
    disc = ctx.read_layer("qa_topology_disconnected")
    assert len(disc) == 4 and disc.component_id.nunique() == 2 and any("no connection to a river" in w for w in ctx.warnings)
    assert "self_intersection" in set(ctx.read_layer("qa_topology_issues").issue)


def test_unreachable_target_links_to_topology(world):
    """A target on a canal island is reported as disconnected_from_river, not as a routing failure."""
    from repeat_pump.core import hydro, network, prioritise, profiles, routing, segments, sekat
    cfg, _ = world
    cfg["pumping"]["allow_gate_addition"] = True
    cfg["prioritise"]["top_fraction"] = 1.0
    ctx = make_ctx(cfg)
    io.run_stage1(ctx)
    _canals(ctx, [LineString([(X0, Y0 + 500), (X0 + 800, Y0 + 500)]), LineString([(X0 + 1200, Y0 + 200), (X0 + 1700, Y0 + 200)])])
    for f in (topology.run, hydro.run, segments.run, profiles.run, prioritise.run, sekat.run, network.run, routing.run):
        f(ctx)
    un = ctx.read_layer("qa_unreachable_targets")
    assert "disconnected_from_river" in set(un.reason)
