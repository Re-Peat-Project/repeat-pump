import numpy as np
import pytest

from repeat_pump.core.groundwater import PeatTable, solve


def const_fns(sy, T):
    return (lambda zeta: np.full_like(zeta, sy)), (lambda zeta, cells: np.full_like(zeta, T))


def test_steady_state_matches_analytic_parabola():
    # 1D strip between two canals at head 0, uniform net recharge R: h(x) = R x (L - x) / (2 T)
    nx, dx, T, sy, R = 21, 10.0, 100.0, 0.2, -0.003
    ny = 3
    z = np.zeros((ny, nx))
    domain = np.ones((ny, nx), bool)
    fixed = np.zeros((ny, nx), bool)
    fixed[:, 0] = fixed[:, -1] = True
    sy_fn, tr_fn = const_fns(sy, T)
    h = solve(z, domain, dx, fixed, np.zeros((ny, nx)), np.zeros((ny, nx)), [R] * 150, sy_fn, tr_fn)
    x = np.arange(nx) * dx
    L = (nx - 1) * dx
    expected = R * x * (L - x) / (2 * T)
    assert np.allclose(h[1], expected, atol=1e-4)
    assert h[1, nx // 2] == pytest.approx(R * L**2 / (8 * T), rel=1e-3)


def test_closed_domain_conserves_mass():
    ny, nx, dx, sy = 6, 7, 20.0, 0.25
    z = np.full((ny, nx), 5.0)
    domain = np.ones((ny, nx), bool)
    fixed = np.zeros((ny, nx), bool)
    h0 = np.full((ny, nx), 4.0)
    sy_fn, tr_fn = const_fns(sy, 10.0)
    h = solve(z, domain, dx, fixed, h0, h0, [-0.004] * 3, sy_fn, tr_fn)
    assert np.allclose(h, 4.0 - 3 * 0.004 / sy, atol=1e-9)


def test_symmetry_and_domain_mask():
    n, dx = 15, 25.0
    z = np.zeros((n, n))
    domain = np.ones((n, n), bool)
    fixed = np.zeros((n, n), bool)
    fixed[0, :] = fixed[-1, :] = fixed[:, 0] = fixed[:, -1] = True
    sy_fn, tr_fn = const_fns(0.2, 50.0)
    h = solve(z, domain, dx, fixed, np.zeros((n, n)), np.zeros((n, n)), [-0.003] * 20, sy_fn, tr_fn)
    assert np.allclose(h, h[::-1, :]) and np.allclose(h, h[:, ::-1]) and np.allclose(h, h.T)
    # a cell outside the domain does not exchange water and keeps its value
    dom2 = domain.copy()
    dom2[7, 7] = False
    h0 = np.full((n, n), -0.5)
    h2 = solve(z, dom2, dx, fixed, np.zeros((n, n)), h0, [-0.003] * 2, sy_fn, tr_fn)
    assert h2[7, 7] == -0.5


def test_ponded_water_is_removed():
    z = np.zeros((4, 4))
    domain = np.ones((4, 4), bool)
    fixed = np.zeros((4, 4), bool)
    sy_fn, tr_fn = const_fns(0.2, 10.0)
    h = solve(z, domain, 10.0, fixed, np.zeros((4, 4)), np.full((4, 4), 0.3), [0.0], sy_fn, tr_fn)
    assert (h <= 0).all()


def test_peat_table_properties():
    t = PeatTable.urzainki2020()
    zeta = np.array([0.0, -0.1, -0.5, -1.0, -2.0])
    sy = t.sy(zeta)
    assert (sy > 0.05).all() and (sy < 0.5).all()
    tr = t.trans(zeta, depth=np.full(5, 4.0))
    assert (np.diff(tr) < 0).all()                                   # transmissivity falls as the water table drops
    assert t.trans(np.array([-4.0]), np.array([4.0]))[0] == pytest.approx(t.t_floor)   # nothing above the bottom
    assert t.trans(np.array([-0.5]), np.array([4.0]), multiplier=0.0)[0] == pytest.approx(t.t_floor)


def test_peat_table_ships_as_package_data():
    """Guards the packaging trap: the CSV must be found through importlib.resources, not a source-tree path (the plugin
    installs the engine non-editable)."""
    from importlib import resources
    f = resources.files("repeat_pump.data").joinpath("urzainki2020_peat_tables.csv")
    assert f.is_file() and PeatTable.urzainki2020().zeta.size > 100
    import tomllib
    from pathlib import Path
    cfg = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf8"))
    assert "*.csv" in cfg["tool"]["setuptools"]["package-data"]["repeat_pump.data"]
