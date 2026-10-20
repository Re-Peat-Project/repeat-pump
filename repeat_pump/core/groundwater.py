"""2D nonlinear Boussinesq groundwater solver on a regular grid (SI units). Used by Stage 12 (optional block optimisation).

    S(zeta) dh/dt = div( T(zeta) grad h ) + R

h is the head (m above datum), zeta = h - surface (m, negative below ground), R is net recharge
(precipitation minus evapotranspiration, m/day). Cells are either free, fixed-head (canals,
outer boundary) or outside the domain (no flow). Implicit Euler in time with Picard iteration
for the nonlinearity, arithmetic-mean face transmissivity, ponded water removed each step.

Provenance: ported from the ``watershare`` testbed of the re-peat repository (same author), which wrote this
SI-unit sparse solver after finding that the original code was not unit-consistent. The scheme and the peat
tables follow Urzainki et al. (2020, Biogeosciences 17, 4769-4784, [Urzainki2020]; MIT code LukeEcomod/blopti,
Copyright (c) 2019 Inaki Urzainki). See ``repeat_pump/data/NOTICE-urzainki2020.md``. Numerical method: implicit
Euler with Picard iteration (standard finite-volume practice); no new algorithm is introduced here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from typing import Callable, Sequence

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

SyFn = Callable[[np.ndarray], np.ndarray]
TransFn = Callable[[np.ndarray, np.ndarray], np.ndarray]


@dataclass
class PeatTable:
    """Storage and transmissivity of a layered peat profile as functions of water table depth.

    ``zeta`` ascends from deep negative values to 0. ``storage`` is the profile water storage (m),
    ``tra`` the transmissivity (m2/day) of the layers below the water table. Specific yield is
    d storage / d zeta; transmissivity above an impermeable bottom at depth d is
    tra(zeta) - tra(-d).
    """

    zeta: np.ndarray
    storage: np.ndarray
    tra: np.ndarray
    sy_floor: float = 0.02
    t_floor: float = 1e-6
    _sy: np.ndarray = field(init=False, repr=False)

    def __post_init__(self):
        self._sy = np.maximum(np.gradient(self.storage, self.zeta), self.sy_floor)

    @classmethod
    def urzainki2020(cls) -> "PeatTable":
        """Woody peat, von Post 1-8 over 0.5 m on sapric peat (Paivanen 1973 retention), K adjust 1."""
        with resources.files("repeat_pump.data").joinpath("urzainki2020_peat_tables.csv").open("r", encoding="utf8") as fh:
            a = np.loadtxt(fh, delimiter=",", skiprows=1)
        return cls(a[:, 0], a[:, 1], a[:, 2])

    def sy(self, zeta: np.ndarray) -> np.ndarray:
        return np.interp(np.minimum(zeta, 0.0), self.zeta, self._sy)

    def trans(self, zeta: np.ndarray, depth: np.ndarray, multiplier: np.ndarray | float = 1.0) -> np.ndarray:
        t = np.interp(np.minimum(zeta, 0.0), self.zeta, self.tra) - np.interp(-np.asarray(depth), self.zeta, self.tra)
        return np.maximum(t * multiplier, self.t_floor)


def solve(
    surface: np.ndarray,
    domain: np.ndarray,
    dx: float,
    fixed: np.ndarray,
    fixed_head: np.ndarray,
    h0: np.ndarray,
    net_recharge: Sequence[float] | np.ndarray,
    sy_fn: SyFn,
    trans_fn: TransFn,
    dt: float = 1.0,
    picard_max: int = 10,
    picard_tol: float = 1e-5,
    remove_ponding: bool = True,
    keep_history: bool = False,
):
    """Advance h over len(net_recharge) steps of dt days (each step a scalar or an (ny, nx) field of net recharge, m/day).

    surface, domain (bool), fixed (bool, inside the domain), fixed_head and h0 are (ny, nx).
    sy_fn(zeta) and trans_fn(zeta, ...) are vectorised; trans_fn is called as trans_fn(zeta, cells)
    where cells are the flat indices of the evaluated cells, so it can look up per-cell attributes.
    Returns the final head, and the list of daily heads if keep_history.
    """
    ny, nx = surface.shape
    n = ny * nx
    idx = np.arange(n).reshape(ny, nx)
    domain = domain.astype(bool)
    fixed = fixed.astype(bool) & domain
    free = domain & ~fixed
    pos = -np.ones(n, dtype=int)
    free_flat = np.flatnonzero(free.ravel())
    pos[free_flat] = np.arange(free_flat.size)
    z = surface.ravel()
    head = np.where(fixed, fixed_head, h0).astype(float).ravel()
    fixed_flat = fixed.ravel()
    dom_flat = domain.ravel()
    history = []

    # face lists (cell a, cell b) for right and down neighbours inside the domain
    a_r, b_r = idx[:, :-1].ravel(), idx[:, 1:].ravel()
    a_d, b_d = idx[:-1, :].ravel(), idx[1:, :].ravel()
    fa = np.concatenate([a_r, a_d])
    fb = np.concatenate([b_r, b_d])
    ok = dom_flat[fa] & dom_flat[fb] & ~(fixed_flat[fa] & fixed_flat[fb])
    fa, fb = fa[ok], fb[ok]

    for r in np.atleast_1d(np.asarray(net_recharge, dtype=float)):
        h_old = head.copy()
        h_it = head.copy()
        for _ in range(picard_max):
            zeta = h_it - z
            cells = np.flatnonzero(dom_flat)
            sy = np.zeros(n)
            tr = np.zeros(n)
            sy[cells] = sy_fn(zeta[cells])
            tr[cells] = trans_fn(zeta[cells], cells)
            g = 0.5 * (tr[fa] + tr[fb])                       # face conductance (dx cancels in 2D)
            pa, pb = pos[fa], pos[fb]
            diag = np.zeros(free_flat.size)
            r_free = r.ravel()[free_flat] if np.ndim(r) == 2 else r                    # a step may carry a (ny, nx) recharge field
            rhs = sy[free_flat] * dx * dx / dt * h_old[free_flat] + r_free * dx * dx
            ia = pa >= 0
            ib = pb >= 0
            np.add.at(diag, pa[ia], g[ia])
            np.add.at(diag, pb[ib], g[ib])
            # fixed neighbours move to the right-hand side
            fa_fixed = ia & (pb < 0)
            fb_fixed = ib & (pa < 0)
            np.add.at(rhs, pa[fa_fixed], g[fa_fixed] * head[fb[fa_fixed]])
            np.add.at(rhs, pb[fb_fixed], g[fb_fixed] * head[fa[fb_fixed]])
            both = ia & ib
            rows = np.concatenate([pa[both], pb[both]])
            cols = np.concatenate([pb[both], pa[both]])
            vals = -np.concatenate([g[both], g[both]])
            diag += sy[free_flat] * dx * dx / dt
            A = sp.csr_matrix((np.concatenate([vals, diag]),
                               (np.concatenate([rows, np.arange(free_flat.size)]),
                                np.concatenate([cols, np.arange(free_flat.size)]))),
                              shape=(free_flat.size, free_flat.size))
            h_new = h_it.copy()
            h_new[free_flat] = spla.spsolve(A.tocsc(), rhs)
            delta = np.max(np.abs(h_new[free_flat] - h_it[free_flat])) if free_flat.size else 0.0
            h_it = h_new
            if delta < picard_tol:
                break
        if remove_ponding:
            h_it = np.where(dom_flat, np.minimum(h_it, z), h_it)
            h_it = np.where(fixed_flat, head, h_it)
        head = h_it
        if keep_history:
            history.append(head.reshape(ny, nx).copy())
    out = head.reshape(ny, nx)
    return (out, history) if keep_history else out
