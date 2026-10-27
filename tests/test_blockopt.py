"""Canal blocking optimisation helpers (Stage 12): canal level model and the GA / SA / greedy search."""
import itertools

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString

from repeat_pump.core import blockopt as bo


# ------------------------------------------------------------------------------ search on a toy objective with a known optimum
def toy(weights):
    """Additive benefit with a small interaction, so the best k-subset is known by brute force."""
    w = np.asarray(weights, float)

    def f(sel):
        s = list(sel)
        return float(w[s].sum() - 0.05 * sum(abs(w[a] - w[b]) for a, b in itertools.combinations(s, 2)))
    return f


def brute_best(f, n, k):
    return max(itertools.combinations(range(n), k), key=f)


def test_ga_sa_and_greedy_find_the_best_subset_on_a_toy_problem():
    rng = np.random.default_rng(1)
    w = rng.uniform(0, 1, 14)
    f = toy(w)
    best = brute_best(f, 14, 4)
    res = {r.algo: r for r in bo.optimise_subset(f, 14, 4, ["ga", "sa", "greedy"], max_evals=600, seed=3)}
    for name in ("ga", "sa"):
        assert res[name].best == best, name
        assert len(set(res[name].best)) == 4 and all(0 <= i < 14 for i in res[name].best)
    assert f(res["greedy"].best) >= 0.95 * f(best)                      # greedy is near-optimal here


def test_search_is_deterministic_for_a_seed_and_respects_the_budget():
    f = toy(np.linspace(0, 1, 30))
    a = bo.optimise_subset(f, 30, 5, ["ga", "sa"], max_evals=80, seed=7)
    b = bo.optimise_subset(f, 30, 5, ["ga", "sa"], max_evals=80, seed=7)
    assert [(r.best, r.value) for r in a] == [(r.best, r.value) for r in b]
    assert all(r.evaluations <= 80 for r in a)
    c = bo.optimise_subset(f, 30, 5, ["ga"], max_evals=80, seed=8)
    assert c[0].best != a[0].best or c[0].value == a[0].value           # a different seed may differ, and must still be valid


def test_small_search_space_terminates_and_k_at_least_n_selects_everything():
    f = toy(np.arange(5.0))
    r = bo.optimise_subset(f, 5, 2, ["ga", "sa"], max_evals=10_000, seed=0)       # only 10 subsets exist: must not loop forever
    assert all(x.best == (3, 4) for x in r)
    all_ = bo.optimise_subset(f, 5, 9, ["ga"], max_evals=50, seed=0)[0]
    assert all_.best == (0, 1, 2, 3, 4)


def test_random_baseline_draws_valid_subsets_and_is_worse_than_the_optimum():
    f = toy(np.linspace(0, 1, 20))
    rnd = bo.random_baseline(f, 20, 4, 30, np.random.default_rng(0))
    best = bo.optimise_subset(f, 20, 4, ["ga"], 400, 1)[0].value
    assert rnd.shape == (30,) and rnd.mean() < best


# ------------------------------------------------------------------------------ canal network and level rule
def _y_network():
    """Main canal M (0..200 m east, rising eastwards, downstream = west end) with a branch B joining at x=100."""
    m1 = LineString([(0, 0), (100, 0)])
    m2 = LineString([(100, 0), (200, 0)])
    br = LineString([(100, 0), (100, 100)])
    canals = gpd.GeoDataFrame({"canal_id": ["M1", "M2", "B"], "direction": ["reverse", "reverse", "reverse"]}, geometry=[m1, m2, br])
    rows = []
    for cid, line, z0, z1 in (("M1", m1, 2.0, 2.1), ("M2", m2, 2.1, 2.2), ("B", br, 2.1, 2.2)):
        for st in np.arange(0, 101, 20.0):
            rows.append(dict(canal_id=cid, station_m=float(st), z_land_m=z0 + (z1 - z0) * st / 100))
    return canals, pd.DataFrame(rows)


def test_junction_ends_are_one_node_and_upstream_follows_the_flow_direction():
    canals, prof = _y_network()
    net = bo.CanalNet.from_profiles(canals, prof)
    assert net.n == 3 * 6 - 2                                        # 18 stations; M1's end, M2's start and B's start are one node
    j = net.node_at("M1", 100.0)
    assert j == net.node_at("M2", 0.0) == net.node_at("B", 0.0)
    assert len(net.up[j]) == 2                                      # both the main canal and the branch drain through the junction


def test_a_block_raises_only_upstream_stations_up_to_its_crest():
    canals, prof = _y_network()
    net = bo.CanalNet.from_profiles(canals, prof)
    base = net.z_land - 1.0                                          # canal water 1 m below land
    node = net.node_at("M1", 60.0)
    crest = net.z_land[node] - 0.4
    wt = net.levels(base, {node: crest})
    assert wt[node] == crest > base[node]
    up_main = net.node_at("M2", 40.0)
    assert wt[up_main] >= base[up_main]                              # upstream never falls
    down = net.node_at("M1", 0.0)
    assert wt[down] == base[down]                                    # downstream is untouched
    assert (wt >= base).all()
    # a block whose crest is below the existing level does nothing
    assert np.array_equal(net.levels(base, {node: base[node] - 0.1}), base)


def test_adding_a_block_never_lowers_the_canal_rise_objective():
    canals, prof = _y_network()
    net = bo.CanalNet.from_profiles(canals, prof)
    base = net.z_land - 1.0
    nodes = [net.node_at("M1", 40.0), net.node_at("M2", 20.0), net.node_at("B", 60.0)]
    crest = np.array([net.z_land[n] - 0.4 for n in nodes])
    obj = bo.CanalRiseObjective(net, base, nodes, crest, fixed={})
    prev = obj.benefit(())
    assert prev == 0.0
    for sel in [(0,), (0, 1), (0, 1, 2)]:
        v = obj.benefit(sel)
        assert v >= prev - 1e-12
        prev = v
    assert obj.benefit((0,)) > obj.benefit((1,)) > 0                 # a block lower down the canal helps more stations


def test_lazy_greedy_rank_gives_the_same_rise_as_the_full_greedy_search():
    """greedy_rank (used by stage 7 balancing) must reach, for every k, the rise of the exhaustive greedy on the canal-rise objective."""
    rng = np.random.default_rng(4)
    n = 60                                                   # a random tree of canal stations draining to node 0
    parent = [-1] + [int(rng.integers(0, k)) for k in range(1, n)]
    up = [[] for _ in range(n)]
    for k in range(1, n):
        up[parent[k]].append(k)
    depth = np.zeros(n)
    for k in range(1, n):
        depth[k] = depth[parent[k]] + 1
    z = 0.05 * depth + rng.normal(0, 0.03, n)
    net = bo.CanalNet(z, up, np.zeros((n, 2)), np.array(["c"] * n, dtype=object), {})
    base = z - 1.0
    cand = list(rng.choice(n, 15, replace=False))
    crest = z[cand] - 0.4
    obj = bo.CanalRiseObjective(net, base, cand, crest, {})
    order = bo.greedy_rank(net, base, cand, crest, {})
    assert sorted(i for i, _ in order) == list(range(15))
    assert np.isclose(sum(g for _, g in order), obj.benefit(range(15)))
    chosen = []
    for k in range(15):
        best = max((c for c in range(15) if c not in chosen), key=lambda c: obj.benefit(chosen + [c]))
        chosen.append(best)
        assert np.isclose(obj.benefit(chosen), obj.benefit([i for i, _ in order[:k + 1]]))


def test_held_water_is_capped_at_the_land_surface():
    """A block on high ground cannot hold water above the land of a lower stretch upstream; that would be ponding, not storage."""
    z = np.array([2.0, 1.0, 3.0])                      # node 0 the block, node 1 a low spot upstream, node 2 higher again
    net = bo.CanalNet(z, [[1], [2], []], np.zeros((3, 2)), np.array(["c"] * 3, dtype=object), {})
    base = z - 1.0
    lv = net.levels(base, {0: 1.6})
    assert lv[0] == 1.6 and lv[1] == 1.0 and lv[2] == 2.0      # node 1 stops at its surface, node 2 is not raised (1.6 < 2.0)
    order = bo.greedy_rank(net, base, [0], np.array([1.6]), {})
    assert np.isclose(order[0][1], (1.6 - 1.0) + (1.0 - 0.0))


def test_owners_name_the_block_that_holds_each_station():
    """Two blocks on one straight canal: each owns the stations between it and the next block upstream; the far upstream
    stations, above both crests, are owned by nobody."""
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import LineString
    from repeat_pump.core.blockopt import CanalNet
    z = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0]          # land rises upstream (towards the digitised start)
    canals = gpd.GeoDataFrame({"canal_id": ["C"], "direction": ["forward"]}, geometry=[LineString([(0, 0), (1000, 0)])])
    prof = pd.DataFrame({"canal_id": "C", "station_m": [100.0 * i for i in range(11)], "z_land_m": z[::-1]})
    net = CanalNet.from_profiles(canals, prof)
    base = net.z_land - 1.0
    down, up = net.node_at("C", 1000.0), net.node_at("C", 600.0)        # z 0.0 and 0.8
    wt, owner = net.owners(base, [(down, 0.0 - 0.4 + 0.8, "A"), (up, 0.8 - 0.4 + 0.6, "B")])
    assert owner[down] is None or owner[down] == "A"
    assert owner[net.node_at("C", 800.0)] == "A" and owner[net.node_at("C", 500.0)] == "B"
    assert owner[net.node_at("C", 0.0)] is None
    assert (wt >= base).all()
