"""Canal blocking optimisation (helpers of the optional Stage 12).

Choose which K of the candidate sekat sites to build so that a groundwater objective improves most, as in
Urzainki et al. (2020) [Urzainki2020]: a Boussinesq groundwater model scores each block layout and a heuristic
search (genetic algorithm, simulated annealing) looks for the best layout. This module keeps the same logic and
changes two things on purpose:

* The canal water level rule does not compare neighbouring DEM cells (the step the authors themselves flag as
  non-monotonic and resolution-bound). It uses the directed canal network of Stages 5 and 8: a block holds water at its
  own land level minus ``sekat.dA_m`` and raises every station upstream of it, along the flow direction, up to that level.
* Candidates are the Stage 7 proposed sekat, so the search chooses which of the head-rule sites to build under a budget.

Search methods: genetic algorithm [Holland1975], simulated annealing [Kirkpatrick1983], plus a greedy and a random
comparator (the original paper compared against random and rule-based siting, not greedy). Everything is
deterministic for a given seed.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np


# ----------------------------------------------------------------------------- canal network on the Stage 5 stations
@dataclass
class CanalNet:
    """Canal stations as nodes. ``up[k]`` lists the nodes directly upstream of node ``k``."""
    z_land: np.ndarray                  # land elevation per node (m)
    up: list                            # upstream neighbours per node
    xy: np.ndarray                      # (N, 2) coordinates
    canal: np.ndarray                   # canal id of each node (first canal that created it)
    lookup: dict                        # canal_id -> (station_m array, node index array)

    @property
    def n(self) -> int:
        return len(self.z_land)

    @classmethod
    def from_profiles(cls, canals, prof) -> "CanalNet":
        """``canals``: GeoDataFrame with canal_id, direction (forward = downstream at the digitised end) and line geometry.
        ``prof``: canal_profiles points (canal_id, station_m, z_land_m). End stations that meet at the same coordinate are one node."""
        key_to_node: dict = {}
        z_sum: list = []
        z_cnt: list = []
        xy: list = []
        canal_of: list = []
        up: list = []
        lookup: dict = {}

        def node_for(key, x, y, z, cid):
            k = key_to_node.get(key)
            if k is None:
                k = len(z_sum)
                key_to_node[key] = k
                z_sum.append(0.0); z_cnt.append(0); xy.append((x, y)); canal_of.append(cid); up.append([])
            if np.isfinite(z):
                z_sum[k] += z; z_cnt[k] += 1
            return k

        by = {c: g.sort_values("station_m") for c, g in prof.groupby("canal_id")}
        for cid, line, direction in zip(canals["canal_id"], canals.geometry, canals["direction"]):
            g = by.get(cid)
            if g is None or len(g) < 2:
                continue
            s = g["station_m"].to_numpy(); z = g["z_land_m"].to_numpy()
            n = len(s)
            idx = np.empty(n, dtype=int)
            for i in range(n):
                p = line.interpolate(float(s[i]))
                if i == 0:
                    key = ("end", round(line.coords[0][0], 3), round(line.coords[0][1], 3))
                elif i == n - 1:
                    key = ("end", round(line.coords[-1][0], 3), round(line.coords[-1][1], 3))
                else:
                    key = ("st", cid, i)
                idx[i] = node_for(key, p.x, p.y, float(z[i]), cid)
            order = idx[::-1] if direction == "forward" else idx          # downstream -> upstream
            for a, b in zip(order[:-1], order[1:]):
                if b not in up[a]:
                    up[a].append(int(b))
            lookup[cid] = (s, idx)
        z_land = np.array([zs / zc if zc else np.nan for zs, zc in zip(z_sum, z_cnt)])
        return cls(z_land, up, np.array(xy), np.array(canal_of, dtype=object), lookup)

    def node_at(self, canal_id, chainage_m: float) -> Optional[int]:
        """Node of the station nearest to a chainage along a canal (digitised direction)."""
        if canal_id not in self.lookup:
            return None
        s, idx = self.lookup[canal_id]
        return int(idx[int(np.argmin(np.abs(s - chainage_m)))])

    def levels(self, base: np.ndarray, blocks: dict) -> np.ndarray:
        """Water level per node after building ``blocks`` ({node: crest level}). A block raises its own node and every
        node upstream of it whose level is lower than the crest (the Urzainki rule, on the directed network). The level is
        capped at the land surface: where the land upstream lies below the crest (flat ground, a local low) water above the
        surface is ponding, not water held in the peat, so it is not counted; the water still passes on upstream."""
        wt = base.copy()
        for node, crest in blocks.items():
            if not (crest > wt[node]):
                continue
            seen, q = {node}, deque([node])
            while q:
                k = q.popleft()
                if wt[k] < crest:
                    wt[k] = max(wt[k], self.held(k, crest))
                    for u in self.up[k]:
                        if u not in seen:
                            seen.add(u)
                            q.append(u)
        return wt

    def held(self, k: int, crest: float) -> float:
        """Level a crest holds at node ``k``: the crest, but never above the land surface there."""
        z = self.z_land[k]
        return min(crest, z) if np.isfinite(z) else crest

    def owners(self, base: np.ndarray, blocks: list) -> tuple[np.ndarray, np.ndarray]:
        """Water level per node and the block that holds it, building ``blocks`` (``[(node, crest, label), ...]``) in that order
        with the rule of ``levels``. ``owner[k]`` is the label of the last block that raised node ``k`` (the one whose crest sets
        its final level), or None where no block raises the water."""
        wt, owner = base.copy(), np.full(self.n, None, dtype=object)
        for node, crest, label in blocks:
            if not (crest > wt[node]):
                continue
            seen, q = {node}, deque([node])
            while q:
                k = q.popleft()
                if wt[k] < crest:
                    h = self.held(k, crest)
                    if h > wt[k]:
                        wt[k], owner[k] = h, label
                    for u in self.up[k]:
                        if u not in seen:
                            seen.add(u)
                            q.append(u)
        return wt, owner


# ----------------------------------------------------------------------------- objectives (larger benefit is better)
def greedy_rank(net: CanalNet, base: np.ndarray, nodes: list, crest: np.ndarray, fixed: dict) -> list:
    """Order candidate blocks by the extra canal rise each adds to those chosen before it: ``[(index, gain), ...]``, largest
    first. The rise of a set is the canal-rise objective, so the k first entries are the greedy k-set. The gain of a block
    can only shrink as others are built (water levels only go up), so stale gains are upper bounds and a lazy priority queue
    gives the same order as the full greedy search at a fraction of the cost."""
    import heapq
    wt = net.levels(base, fixed)

    def gain(i: int, apply: bool = False) -> float:
        c, g = float(crest[i]), 0.0
        if not c > wt[nodes[i]]:
            return 0.0
        seen, q = {nodes[i]}, deque([nodes[i]])
        while q:
            k = q.popleft()
            if wt[k] < c:
                lv = net.held(k, c)
                if lv > wt[k] and np.isfinite(wt[k]):
                    g += lv - wt[k]
                    if apply:
                        wt[k] = lv
                for u in net.up[k]:
                    if u not in seen:
                        seen.add(u)
                        q.append(u)
        return g

    heap = [(-gain(i), i) for i in range(len(nodes))]
    heapq.heapify(heap)
    order = []
    while heap:
        _neg, i = heapq.heappop(heap)
        g = gain(i)
        if heap and g < -heap[0][0] - 1e-12:
            heapq.heappush(heap, (-g, i))                   # stale: its gain fell below the next best, look again later
            continue
        gain(i, apply=True)
        order.append((i, g))
    return order


class CanalRiseObjective:
    """Cheap objective: total canal level rise caused by the new blocks. The paper found that maximising canal rise tracks
    the full groundwater model, so this is a screening objective."""

    def __init__(self, net: CanalNet, base: np.ndarray, cand_nodes: list, cand_crest: np.ndarray, fixed: dict):
        self.net, self.base, self.nodes, self.crest, self.fixed = net, base, cand_nodes, cand_crest, fixed
        self.wt_fixed = net.levels(base, fixed)

    def blocks(self, sel) -> dict:
        b = dict(self.fixed)
        for i in sel:
            n = self.nodes[i]
            b[n] = max(b.get(n, -np.inf), float(self.crest[i]))
        return b

    def levels(self, sel) -> np.ndarray:
        return self.net.levels(self.base, self.blocks(sel))

    def benefit(self, sel) -> float:
        return float(np.nansum(self.levels(sel) - self.wt_fixed))


@dataclass
class Grid:
    surface: np.ndarray
    domain: np.ndarray
    peat: np.ndarray                    # bool, cells counted in the objective
    depth: np.ndarray                   # peat depth (m); 0 outside peat
    fixed_boundary: np.ndarray
    cell_of_node: np.ndarray            # flat cell index of each canal node (-1 outside the domain)
    dx: float
    shared_cells: int = 0               # cells holding nodes of more than one canal


class PdeObjective(CanalRiseObjective):
    """Dry peat volume after ``days`` of net drying from a saturated start, from the 2D Boussinesq model; benefit is the
    reduction compared with the existing structures only."""

    def __init__(self, net, base, cand_nodes, cand_crest, fixed, grid: Grid, table, days: int, et_mm_day: float, multiplier: float):
        super().__init__(net, base, cand_nodes, cand_crest, fixed)
        from repeat_neraca.groundwater import solve
        self._solve = solve
        self.g, self.table, self.days, self.et, self.mult = grid, table, int(days), et_mm_day, multiplier
        ny, nx = grid.surface.shape
        self.n_cells = ny * nx
        cells = grid.cell_of_node
        self.in_dom = cells >= 0
        self.cell_nodes: dict = {}
        for node in np.flatnonzero(self.in_dom):
            self.cell_nodes.setdefault(int(cells[node]), []).append(int(node))
        self.dry_fixed = self.dry_volume(self.wt_fixed)

    def dry_volume(self, wt: np.ndarray) -> float:
        g = self.g
        ny, nx = g.surface.shape
        fixed = g.fixed_boundary.copy().ravel()
        head = np.where(g.fixed_boundary, g.surface, 0.0).ravel()
        for cell, nodes in self.cell_nodes.items():
            if g.fixed_boundary.ravel()[cell]:
                continue                                                    # boundary cells win over canals
            fixed[cell] = True
            head[cell] = float(np.mean(wt[nodes]))
        fixed = fixed.reshape(ny, nx)
        head = head.reshape(ny, nx)
        surface = np.where(g.domain, g.surface, 0.0)
        depth = g.depth.ravel()
        table, mult = self.table, self.mult

        def trans(zeta, cells):
            return table.trans(zeta, depth[cells], mult)

        h = self._solve(surface, g.domain, g.dx, fixed, head, np.where(g.domain, surface, 0.0),
                        [-self.et * 1e-3] * self.days, table.sy, trans, dt=1.0)
        count = g.peat & ~fixed
        return float(np.sum((surface - h)[count]) * g.dx ** 2 / 1e4)       # ha m

    def benefit(self, sel) -> float:
        return self.dry_fixed - self.dry_volume(self.levels(sel))


# ----------------------------------------------------------------------------- the search
class BudgetExhausted(Exception):
    pass


class Evaluator:
    """Caches objective values by candidate set and counts distinct evaluations against ``max_evals``."""

    def __init__(self, fn: Callable, max_evals: Optional[int] = None, log: Optional[Callable[[str], None]] = None, name: str = ""):
        self.fn, self.max, self.log, self.name = fn, max_evals, log, name
        self.cache: dict = {}
        self.trace: list = []                     # (evaluations so far, best value so far)
        self.best: tuple = ()
        self.best_value = -math.inf

    @property
    def evals(self) -> int:
        return len(self.cache)

    def __call__(self, sel) -> float:
        key = tuple(sorted(int(i) for i in sel))
        if key in self.cache:
            return self.cache[key]
        if self.max is not None and len(self.cache) >= self.max:
            raise BudgetExhausted
        v = float(self.fn(key))
        self.cache[key] = v
        if v > self.best_value:
            self.best, self.best_value = key, v
            self.trace.append((len(self.cache), v))
            if self.log and (len(self.cache) <= 3 or len(self.cache) % 25 == 0):
                self.log(f"{self.name}: {len(self.cache)} evaluations, best benefit {v:.4g}")
        return v


@dataclass
class SearchResult:
    algo: str
    best: tuple
    value: float
    evaluations: int
    trace: list = field(default_factory=list)


def _random_set(rng, n: int, k: int):
    return tuple(sorted(int(i) for i in rng.choice(n, size=k, replace=False)))


def ga_search(ev: Evaluator, n: int, k: int, rng, population: int = 30, mutation: float = 0.1, elite: int = 2, tournament: int = 3):
    """Genetic algorithm [Holland1975] over k-subsets: tournament selection, crossover by sampling k genes from the union of
    two parents, per-gene replacement mutation, elitism. Stops when the evaluation budget is used."""
    try:
        pop = [_random_set(rng, n, k) for _ in range(population)]
        fit = [ev(p) for p in pop]
        stall = 0
        while stall < 30:                      # stops by itself when the space is exhausted and nothing new is evaluated
            before = ev.evals
            order = np.argsort(fit)[::-1]
            new = [pop[i] for i in order[:elite]]
            newfit = [fit[i] for i in order[:elite]]
            while len(new) < population:
                pa = [max(rng.choice(len(pop), size=min(tournament, len(pop)), replace=False), key=lambda j: fit[j]) for _ in range(2)]
                union = sorted(set(pop[pa[0]]) | set(pop[pa[1]]))
                child = list(rng.choice(union, size=k, replace=False))
                for gi in range(k):
                    if rng.random() < mutation:
                        free = [c for c in range(n) if c not in child]
                        if free:
                            child[gi] = int(rng.choice(free))
                child = tuple(sorted(int(c) for c in child))
                new.append(child)
                newfit.append(ev(child))
            pop, fit = new, newfit
            stall = stall + 1 if ev.evals == before else 0
    except BudgetExhausted:
        pass
    return SearchResult("ga", ev.best, ev.best_value, ev.evals, list(ev.trace))


def sa_search(ev: Evaluator, n: int, k: int, rng, t0_fraction: float = 0.01, cooling: float = 0.995):
    """Simulated annealing [Kirkpatrick1983]: swap one chosen site for an unchosen one, accept worse layouts with probability
    exp(delta/T), T falling geometrically from ``t0_fraction`` of the first value."""
    try:
        cur = _random_set(rng, n, k)
        fcur = ev(cur)
        scale = max(abs(fcur), 1e-12)
        t = t0_fraction * scale
        stall = 0
        while stall < 3000:
            before = ev.evals
            i = int(rng.integers(k))
            free = [c for c in range(n) if c not in cur]
            if not free:
                break
            cand = list(cur)
            cand[i] = int(rng.choice(free))
            cand = tuple(sorted(cand))
            f = ev(cand)
            if f >= fcur or rng.random() < math.exp((f - fcur) / max(t, 1e-300)):
                cur, fcur = cand, f
            t *= cooling
            stall = stall + 1 if ev.evals == before else 0
    except BudgetExhausted:
        pass
    return SearchResult("sa", ev.best, ev.best_value, ev.evals, list(ev.trace))


def greedy_search(ev: Evaluator, n: int, k: int):
    """Add, one by one, the site with the largest marginal benefit. Needs about n*k evaluations."""
    chosen: list = []
    try:
        for _ in range(k):
            best, bv = None, -math.inf
            for c in range(n):
                if c in chosen:
                    continue
                v = ev(chosen + [c])
                if v > bv:
                    best, bv = c, v
            chosen.append(best)
    except BudgetExhausted:
        pass
    sel = tuple(sorted(chosen))
    return SearchResult("greedy", sel, ev.cache.get(sel, ev.best_value), ev.evals, list(ev.trace))


def random_baseline(fn: Callable, n: int, k: int, draws: int, rng) -> np.ndarray:
    """Benefit of ``draws`` random k-subsets (the comparator of the paper)."""
    return np.array([float(fn(_random_set(rng, n, k))) for _ in range(draws)])


def optimise_subset(fn: Callable, n: int, k: int, algorithms: list, max_evals: int, seed: int, log=None, ga_kw=None, sa_kw=None) -> list:
    """Run the requested algorithms (each with its own cache and the same budget) and return their SearchResults."""
    out = []
    k = min(k, n)
    for name in algorithms:
        rng = np.random.default_rng(seed)
        ev = Evaluator(fn, max_evals, log, name)
        if k >= n:                                         # nothing to choose
            sel = tuple(range(n))
            out.append(SearchResult(name, sel, ev(sel), ev.evals, list(ev.trace)))
        elif name == "ga":
            out.append(ga_search(ev, n, k, rng, **(ga_kw or {})))
        elif name == "sa":
            out.append(sa_search(ev, n, k, rng, **(sa_kw or {})))
        elif name == "greedy":
            out.append(greedy_search(ev, n, k))
        else:
            raise ValueError(name)
    return out
