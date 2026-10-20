import itertools

import networkx as nx
import pytest

from repeat_pump.core import hydro, io, network, prioritise, profiles, routing, segments, sekat, topology
from tests.conftest import make_ctx


def _graph(edges, nodes_extra=None):
    """edges: (u, v, length, dz). Both directions are added with dz negated."""
    G = nx.DiGraph()
    for u, v, L, dz in edges:
        for a, b, d in ((u, v, dz), (v, u, -dz)):
            G.add_edge(a, b, length_m=L, dz_m=d, geom=None, seg_id=f"{u}{v}", selected=False)
    for n in G.nodes:
        G.nodes[n].update(kinds=[], z_land_m=0.0)
    for n, kw in (nodes_extra or {}).items():
        G.nodes[n].update(kw)
    return G


def _brute_force_opt(R, sources, targets):
    """Minimum-cost edge subset in which every target is reachable from a source (directed Steiner optimum)."""
    edges = [(u, v, d["cost"]) for u, v, d in R.edges(data=True)]
    best = float("inf")
    for k in range(len(edges) + 1):
        for sub in itertools.combinations(edges, k):
            c = sum(e[2] for e in sub)
            if c >= best:
                continue
            H = nx.DiGraph([(u, v) for u, v, _ in sub]); H.add_nodes_from(R.nodes)
            if all(any(nx.has_path(H, s, t) for s in sources) for t in targets):
                best = c
    return best


def test_steiner_heuristic_vs_bruteforce():
    """Test 6: heuristic cost <= 2x optimal and equal on trivial cases."""
    G = _graph([("S", "a", 10, 0), ("a", "b", 10, 0), ("a", "c", 10, 0), ("S", "b", 25, 0), ("c", "d", 5, 0), ("b", "d", 20, 0)])
    R = routing.routing_graph(G, 0.0, True)
    routes, bad, tree = routing.route_steiner(R, ["S"], ["b", "c", "d"])
    cost = sum(R[u][v]["cost"] for u, v in tree if u != routing.SUPER)
    opt = _brute_force_opt(R, ["S"], ["b", "c", "d"])
    assert not bad and cost <= 2 * opt + 1e-9
    assert cost == opt                                    # tree is optimal here: shared prefix S-a reused
    # trivial case: single target equals the shortest path
    r, b, t = routing.route_steiner(R, ["S"], ["d"])
    assert sum(R[u][v]["cost"] for u, v in t if u != routing.SUPER) == nx.shortest_path_length(R, "S", "d", weight="cost")


def test_ungated_sekat_blocks_target():
    G = _graph([("S", "a", 10, 0), ("a", "T", 10, 0)], {"a": dict(kinds=["sekat_existing"], has_gate=False)})
    R = routing.routing_graph(G, 0.0, allow_gate_addition=False)
    routes, bad = routing.route_per_target(R, ["S"], ["T", "a"])
    assert bad == ["T"] and "a" in routes                      # sekat node itself reachable, target behind it is not
    R2 = routing.routing_graph(G, 0.0, allow_gate_addition=True)
    assert routing.route_per_target(R2, ["S"], ["T"])[1] == []
    G.nodes["a"]["has_gate"] = True
    assert routing.route_per_target(routing.routing_graph(G, 0.0, False), ["S"], ["T"])[1] == []


def test_head_aware_cost_prefers_flat_path():
    """Test 7: short uphill path vs longer flat path; large lambda picks the flat one."""
    G = _graph([("S", "u", 50, 5), ("u", "T", 50, 5), ("S", "f", 80, 0), ("f", "T", 80, 0)])
    near = routing.route_per_target(routing.routing_graph(G, 0.0, True), ["S"], ["T"])[0]["T"]
    far = routing.route_per_target(routing.routing_graph(G, 100.0, True), ["S"], ["T"])[0]["T"]
    assert "u" in near and "f" in far


@pytest.mark.skip(reason="Test 10 (pilot regression vs legacy routes) needs a pilot sub-KHG fixture that does not exist yet")
def test_pilot_regression_per_target_matches_legacy():
    ...


def test_network_and_routing_end_to_end(world):
    cfg, _ = world
    ctx = make_ctx(cfg)
    for f in (io.run_stage1, topology.run, hydro.run, segments.run, profiles.run, prioritise.run, sekat.run, network.run, routing.run):
        f(ctx)
    nodes = ctx.read_layer("network_nodes")
    assert {"river", "sekat_existing", "sekat_proposed"} <= set(",".join(nodes.kinds).split(","))
    tg = ctx.read_layer("pump_targets"); assert len(tg) >= 1
    # target = highest node of the selected cluster (not a centroid)
    sel_nodes = nodes.set_index("node_id")
    for _, t in tg.iterrows():
        assert t.z_land_m >= sel_nodes.z_land_m.min()
    unreach = ctx.read_layer("qa_unreachable_targets")
    routes = ctx.read_layer("pump_routes")
    assert len(routes) + len(unreach) == len(tg)
    assert ctx.report["routing"]["mode"] == "steiner"


def test_proposed_sekat_do_not_block_and_need_gates(world):
    """Default allow_gate_addition=false: only existing ungated sekat block; proposed sekat are listed in gates_required."""
    from repeat_pump.core import pumps
    import geopandas as gpd
    from tests.fixtures.synthetic import X0, Y0, CRS
    cfg, tmp = world
    gpd.GeoDataFrame({"sekat_id": ["E1", "E2"], "has_gate": [True, True]}, geometry=gpd.points_from_xy([X0 + 300, X0 + 1000], [Y0 + 503, Y0 + 497]),
                     crs=CRS).to_file(tmp / "sekat.gpkg", driver="GPKG")
    assert cfg["pumping"].get("allow_gate_addition", False) is False
    ctx = make_ctx(cfg)
    for f in (io.run_stage1, topology.run, hydro.run, segments.run, profiles.run, prioritise.run, sekat.run, network.run, routing.run, pumps.run):
        f(ctx)
    routes = ctx.read_layer("pump_routes")
    assert len(routes) >= 1
    gates = ctx.read_layer("gates_required")
    assert len(gates) >= 1 and gates.kind.str.contains("sekat_proposed").any()
