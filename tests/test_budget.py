"""Budget estimate: quantities from the run per intervention class, priced from budget.* ranges; null prices stay unpriced."""
import math
from types import SimpleNamespace

import pandas as pd

from repeat_pump.core import budget


def _cfg(**prices):
    b = dict(enabled=True, price_year=2026, sekat_standard_idr=[12e6, 18e6, 18e6], sekat_tertiary_idr=None, sekat_reinforced_idr=[70e6] * 3, canal_closure_idr_per_km=None,
             revegetation_idr_per_ha=[8e6, 12e6, 15e6], well_idr=[3e6, 8.5e6, 10e6], well_radius_m=200, pump_idr=None, fuel_idr_per_l=None,
             fuel_l_per_kwh=None, pump_hours_per_day=None)
    b.update(prices)
    return SimpleNamespace(budget=SimpleNamespace(**b), topology=SimpleNamespace(canal_classes=["primer", "sekunder"]),
                           pumping=SimpleNamespace(enabled=False, design_period_days=None))


UNITS = pd.DataFrame({
    "subkhg_id": ["A", "B", "C", "D"], "intervention": ["block", "close_canals", "revegetate_fire", "block_wells"],
    "area_km2": [10.0, 20.0, 5.0, 8.0], "peat_frac": [1.0, 0.5, 1.0, 1.0], "sekat_analysed": [True, False, False, False],
    "sekat_tambahan": [None, None, None, 7], "u_canal_primary": [0, 1.0, 0, 0], "u_canal_secondary": [0, 2.0, 0, 0], "u_canal_tertiary": [0, 9.0, 0, 0],
    "burned_ever_frac": [0.0, 0.0, 0.5, 0.1],
})
KEPT = pd.DataFrame({"subkhg_id": ["A", "A", "A"], "sekat_type": ["standard", "standard", "leaky/reinforced"]})


def test_quantities_follow_the_classes():
    q = budget.quantities(UNITS, KEPT, [], _cfg()).set_index(["subkhg_id", "item"])["quantity"]
    assert q[("A", "sekat_standard")] == 2 and q[("A", "sekat_reinforced")] == 1
    assert q[("B", "canal_closure_km")] == (1.0 + 2.0) * 20 * 0.5            # tertiary left out: the run analyses primer and sekunder
    assert q[("C", "revegetation_ha")] == 250 and q[("C", "deep_wells")] == math.ceil(250 / (math.pi * 200 ** 2 / 1e4))
    assert q[("D", "sekat_ipg_estimate")] == 7 and q[("D", "deep_wells")] == math.ceil(80 / (math.pi * 200 ** 2 / 1e4))


def test_prices_give_ranges_and_null_stays_unpriced():
    b = budget.price(budget.quantities(UNITS, KEPT, [], _cfg()), _cfg()).set_index(["subkhg_id", "item"])
    a = b.loc[("A", "sekat_standard")]
    assert (a.cost_low_idr, a.cost_idr, a.cost_high_idr) == (24e6, 36e6, 36e6)
    assert b.loc[("A", "sekat_reinforced"), "cost_idr"] == 70e6
    assert pd.isna(b.loc[("B", "canal_closure_km"), "cost_idr"]) and not b.loc[("B", "canal_closure_km"), "priced"]


def test_totals_split_between_the_cost_standard_and_the_rest():
    b = budget.price(budget.quantities(UNITS, KEPT, [], _cfg()), _cfg())
    s = budget.by_basis(b)
    reveg = b[b["item"] == "revegetation_ha"].cost_idr.sum()
    assert s["outside_standard"]["idr"] == reveg
    assert s["standard"]["idr"] + s["outside_standard"]["idr"] == b.cost_idr.sum()
    assert {"revegetation_ha", "pump_units", "pump_fuel_l"}.isdisjoint(budget.STANDARD_ITEMS)


def test_blank_quantities_are_unknown_except_units_without_burn_polygons():
    u = pd.DataFrame({"subkhg_id": ["A", "B", "C"], "intervention": ["revegetate_fire"] * 3, "area_km2": [10.0, 10.0, 10.0], "peat_frac": [1.0] * 3,
                      "burned_ever_frac": [float("nan"), float("nan"), 0.5], "u_fire_freq": [0.0, 0.02, 0.1]})
    q = budget.quantities(u, None, [], _cfg()).set_index(["subkhg_id", "item"])["quantity"]
    assert q[("A", "revegetation_ha")] == 0 and q[("A", "deep_wells")] == 0     # no burn polygon: nothing burnt
    assert pd.isna(q[("B", "revegetation_ha")]) and pd.isna(q[("B", "deep_wells")])   # fire seen but extent unknown: not priced
    assert q[("C", "revegetation_ha")] == 500


def test_tertiary_blocks_have_their_own_price_and_fall_back_to_the_standard_one():
    kept = pd.DataFrame({"subkhg_id": ["A", "A", "A"], "sekat_type": ["standard"] * 3, "canal_class": ["Kanal Sekunder", "Kanal Tersier", "Kanal Primer"]})
    q = budget.quantities(UNITS, kept, [], _cfg()).set_index(["subkhg_id", "item"])["quantity"]
    assert q[("A", "sekat_standard")] == 2 and q[("A", "sekat_tertiary")] == 1
    own = budget.price(budget.quantities(UNITS, kept, [], _cfg(sekat_tertiary_idr=[5e6, 6e6, 7e6])), _cfg(sekat_tertiary_idr=[5e6, 6e6, 7e6])).set_index(["subkhg_id", "item"])
    assert own.loc[("A", "sekat_tertiary"), "cost_idr"] == 6e6
    fb = budget.price(budget.quantities(UNITS, kept, [], _cfg()), _cfg()).set_index(["subkhg_id", "item"])
    assert fb.loc[("A", "sekat_tertiary"), "cost_idr"] == 18e6                      # no tertiary price: the standard one


def test_concrete_primary_blocks_and_the_switch_back_to_wooden():
    kept = pd.DataFrame({"subkhg_id": ["A"] * 4, "sekat_type": ["standard"] * 3 + ["leaky/reinforced"], "canal_class": ["primer", "sekunder", "Kanal Primer", "primer"]})
    con = _cfg(primary_block="concrete", sekat_primary_idr=[100e6, 130e6, 150e6])
    b = budget.price(budget.quantities(UNITS, kept, [], con), con).set_index(["subkhg_id", "item"])
    assert b.loc[("A", "sekat_primary"), "quantity"] == 2 and b.loc[("A", "sekat_primary"), "cost_idr"] == 260e6
    assert b.loc[("A", "sekat_standard"), "quantity"] == 1 and b.loc[("A", "sekat_reinforced"), "quantity"] == 1
    wood = _cfg(primary_block="wooden", sekat_primary_idr=[100e6, 130e6, 150e6])
    q = budget.quantities(UNITS, kept, [], wood).set_index(["subkhg_id", "item"])["quantity"]
    assert q[("A", "sekat_standard")] == 3 and ("A", "sekat_primary") not in q.index      # the 1 Nov 2026 pricing


def test_ipg_estimate_is_split_by_primary_and_secondary_canal_length():
    u = UNITS.copy()
    u.loc[u.subkhg_id == "D", ["u_canal_primary", "u_canal_secondary"]] = [1.0, 3.0]
    con = _cfg(primary_block="concrete", sekat_primary_idr=[100e6] * 3)
    q = budget.quantities(u, None, [], con).set_index(["subkhg_id", "item"])["quantity"]
    assert q[("D", "sekat_ipg_estimate_primary")] == 1.8 and q[("D", "sekat_ipg_estimate")] == 5.2      # 7 x 1/4 and 7 x 3/4 (rounded)


def test_canal_closure_priced_by_infill_segments():
    c = _cfg(canal_closure_segment_idr=[70e6, 80e6, 90e6], canal_closure_spacing_m=500, canal_closure_idr_per_km=[1e9] * 3)
    b = budget.price(budget.quantities(UNITS, None, [], c), c).set_index(["subkhg_id", "item"])
    km = (1.0 + 2.0) * 20 * 0.5
    assert b.loc[("B", "canal_infill_segments"), "quantity"] == math.ceil(km * 1000 / 500)
    assert b.loc[("B", "canal_infill_segments"), "cost_idr"] == math.ceil(km * 1000 / 500) * 80e6
    assert pd.isna(b.loc[("B", "canal_closure_km"), "cost_idr"])          # not priced twice
