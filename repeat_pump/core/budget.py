"""Budget estimate per sub-KHG (part of stage 11, after the interventions): quantities from the run, priced from ``budget.*``.

Quantities, per sub-KHG and intervention class:

    sekat           the kept sekat of stage 7 (selected sub-KHGs), split by type: standard (wooden) and leaky/reinforced (concrete).
                    Elsewhere, for a class with sekat, the KLH IPG estimate of the sub-KHG prioritisation (``sekat_tambahan``), labelled so
    canal closure   km of canal to close or backfill in the close_canals class: canal density per km2 of peat (primary and secondary,
                    tertiary when the run analyses them) x peat area
    revegetation    ha ever burnt (burned_ever_frac x area) in the revegetate_fire class
    deep wells      the same burnt area, in revegetate_fire and block_wells, divided by the area one well covers (pi r2)
    pumps           the pump units of stage 10 and their fuel over the design period (when pumping is on)

Every price is a range ``[low, central, high]`` in rupiah of its own year (not adjusted for inflation). A price left null is not
guessed: its quantity is reported and its cost stays empty ("not priced"). The sources of the proposed prices are listed in the
register ``repeat_pump/data/budget_sources.csv`` (one row per figure, with its verification status); every run copies it next to
``budget.csv`` and marks which prices it took from the preset. Cost per m3 of water held uses the same water-held figure as the
interventions.
"""
from __future__ import annotations

import math
from importlib import resources

import numpy as np
import pandas as pd

ITEMS = {  # item -> (unit, budget price key)
    "sekat_standard": ("unit", "sekat_standard_idr"),
    "sekat_reinforced": ("unit", "sekat_reinforced_idr"),
    "sekat_ipg_estimate": ("unit", "sekat_standard_idr"),
    "canal_closure_km": ("km", "canal_closure_idr_per_km"),
    "revegetation_ha": ("ha", "revegetation_idr_per_ha"),
    "deep_wells": ("unit", "well_idr"),
    "pump_units": ("unit", "pump_idr"),
    "pump_fuel_l": ("L", "fuel_idr_per_l"),
}
SEKAT_CLASSES = {"block", "block_water", "block_wells"}


def budget_sources(cfg) -> list[dict]:
    """The source register, one row per figure, with ``run_value`` (the price the run used) and ``applies``: true when the run
    took that price from the proposed-defaults preset, so the row describes it; false when the run config set its own value."""
    import csv
    text = resources.files("repeat_pump.data").joinpath("budget_sources.csv").read_text(encoding="utf8")
    rows = list(csv.DictReader(text.splitlines()))
    keys = set(cfg.preset["keys"]) if cfg.preset else set()
    for r in rows:
        k = r["key"]
        r["run_value"] = getattr(cfg.budget, k, None) if hasattr(cfg.budget, k) else None
        r["applies"] = f"budget.{k}" in keys if hasattr(cfg.budget, k) else None
    return rows


def _price(bc, key: str):
    v = getattr(bc, key)
    if v is None:
        return None
    v = list(v) if isinstance(v, (list, tuple)) else [v, v, v]
    return v if len(v) == 3 else [v[0], v[0], v[0]]


def quantities(units: pd.DataFrame, kept: pd.DataFrame | None, pumps: list, cfg) -> pd.DataFrame:
    """One row per (sub-KHG, item) with the quantity and where it comes from."""
    bc = cfg.budget
    rows = []
    tertiary = "tersier" in [str(c).lower() for c in (cfg.topology.canal_classes or ["primer", "sekunder", "tersier"])]
    cover_ha = math.pi * (bc.well_radius_m or 0) ** 2 / 1e4 if bc.well_radius_m else None
    by_unit = kept.groupby(["subkhg_id", "sekat_type"]).size() if kept is not None and len(kept) and "subkhg_id" in kept else pd.Series(dtype=int)
    for _, u in units.iterrows():
        uid, cls = str(u["subkhg_id"]), u.get("intervention")
        area = float(u.get("area_km2") or 0)
        peat = float(u.get("peat_frac")) if pd.notna(u.get("peat_frac")) else 1.0
        if bool(u.get("sekat_analysed")):
            std = int(by_unit.get((uid, "standard"), 0))
            rein = int(sum(v for (k, t), v in by_unit.items() if k == uid and t != "standard"))
            rows += [(uid, cls, "sekat_standard", std, "stage 7 kept sekat"), (uid, cls, "sekat_reinforced", rein, "stage 7 kept sekat")]
        elif cls in SEKAT_CLASSES and pd.notna(u.get("sekat_tambahan")):
            rows.append((uid, cls, "sekat_ipg_estimate", float(u["sekat_tambahan"]), "KLH IPG estimate (sub-KHG prioritisation)"))
        if cls == "close_canals":
            dens = sum(float(u.get(c) or 0) for c in ("u_canal_primary", "u_canal_secondary") + (("u_canal_tertiary",) if tertiary else ()))
            rows.append((uid, cls, "canal_closure_km", round(dens * area * peat, 2), "canal density per km2 of peat x peat area"))
        burnt_ha = float(u.get("burned_ever_frac") or 0) * area * 100
        if cls == "revegetate_fire":
            rows.append((uid, cls, "revegetation_ha", round(burnt_ha, 1), "area ever burnt"))
        if cls in ("revegetate_fire", "block_wells") and cover_ha:
            rows.append((uid, cls, "deep_wells", math.ceil(burnt_ha / cover_ha) if burnt_ha > 0 else 0, f"area ever burnt / {cover_ha:.1f} ha per well"))
    if pumps and cfg.pumping.enabled:
        n = sum(int(p.get("units_needed") or 0) for p in pumps)
        rows.append(("all", "pumps", "pump_units", n, "stage 10"))
        if bc.pump_hours_per_day and bc.fuel_l_per_kwh and cfg.pumping.design_period_days:
            kwh = sum(float(p.get("p_kw") or 0) for p in pumps) * bc.pump_hours_per_day * cfg.pumping.design_period_days
            rows.append(("all", "pumps", "pump_fuel_l", round(kwh * bc.fuel_l_per_kwh), "power x hours x design period x L per kWh"))
    return pd.DataFrame(rows, columns=["subkhg_id", "intervention", "item", "quantity", "basis"])


def price(q: pd.DataFrame, cfg) -> pd.DataFrame:
    bc = cfg.budget
    out = q.copy()
    out["unit"] = [ITEMS[i][0] for i in out["item"]]
    for col, k in (("cost_low_idr", 0), ("cost_idr", 1), ("cost_high_idr", 2)):
        out[col] = [None if _price(bc, ITEMS[i][1]) is None else float(qty) * _price(bc, ITEMS[i][1])[k] for i, qty in zip(out["item"], out["quantity"])]
    out["priced"] = out["cost_idr"].notna()
    return out


def spend_curve(kept_all: pd.DataFrame, cfg) -> list:
    """Cumulative cost and cumulative share of the water held, sekat in order of benefit (kept and low-benefit together)."""
    bc = cfg.budget
    std, rein = _price(bc, "sekat_standard_idr"), _price(bc, "sekat_reinforced_idr")
    if std is None or kept_all is None or not len(kept_all) or "benefit_rank" not in kept_all:
        return []
    d = kept_all.sort_values("benefit_rank")
    unit = [(rein or std)[1] if t != "standard" else std[1] for t in d.get("sekat_type", ["standard"] * len(d))]
    return [{"n": int(r), "cost_idr": float(c), "cum": float(s)} for r, c, s in zip(d["benefit_rank"], np.cumsum(unit), d["cum_share"])]


def run(ctx, units: pd.DataFrame) -> dict | None:
    """Write the ``budget`` table and return the totals (None when the budget is switched off)."""
    cfg = ctx.cfg
    if not cfg.budget.enabled:
        return None
    kept = ctx.read_layer("sekat_proposed") if ctx.has_layer("sekat_proposed") else None
    if kept is not None and len(kept) and "subkhg_id" not in kept and ctx.has_layer("subkhg_selected"):
        import geopandas as gpd
        sel = ctx.read_layer("subkhg_selected")
        # blocks in the clip margin outside the selected sub-KHGs belong to the nearest one: they are part of its plan
        kept = gpd.sjoin_nearest(kept, sel[["subkhg_id", "geometry"]], how="left").drop(columns="index_right")
        kept = kept[~kept.index.duplicated()]
    q = quantities(units, kept, ctx.report.get("pumps", []), cfg)
    b = price(q, cfg)
    b.to_csv(ctx.out_dir / "budget.csv", index=False)
    src = budget_sources(cfg)
    pd.DataFrame(src).to_csv(ctx.out_dir / "budget_sources.csv", index=False)
    if any(r["applies"] for r in src):
        ctx.warn("Stage 11: the budget uses proposed prices from published sources that still need checking; see budget_sources.csv")
    ctx.write_layer("budget", b, "11")
    low = ctx.read_layer("sekat_low_benefit") if ctx.has_layer("sekat_low_benefit") else None
    allb = pd.concat([x for x in (kept, low) if x is not None and len(x)], ignore_index=True) if (kept is not None or low is not None) else None
    held = float(np.nansum(units.loc[units.get("sekat_analysed", False) == True, "held_m3"])) if "held_m3" in units else None   # noqa: E712
    sekat_cost = float(b.loc[b["item"].isin(["sekat_standard", "sekat_reinforced"]), "cost_idr"].sum(min_count=1) or 0)
    unpriced = sorted(set(b.loc[~b["priced"] & (b["quantity"] > 0), "item"]))
    if unpriced:
        ctx.warn("Stage 11: budget items with a quantity but no price (set budget.* to price them): " + ", ".join(unpriced))
    by_item = b.groupby("item").agg(quantity=("quantity", "sum"), cost_low_idr=("cost_low_idr", lambda s: s.sum(min_count=1)),
                                    cost_idr=("cost_idr", lambda s: s.sum(min_count=1)), cost_high_idr=("cost_high_idr", lambda s: s.sum(min_count=1)))
    by_class = b.groupby("intervention")["cost_idr"].sum(min_count=1)
    tot = lambda c: float(b[c].sum(min_count=1)) if b[c].notna().any() else None   # noqa: E731
    return dict(price_year=cfg.budget.price_year, total_low_idr=tot("cost_low_idr"), total_idr=tot("cost_idr"), total_high_idr=tot("cost_high_idr"),
                by_item={k: {kk: (None if pd.isna(vv) else float(vv)) for kk, vv in r.items()} for k, r in by_item.iterrows()},
                by_class={k: (None if pd.isna(v) else float(v)) for k, v in by_class.items()}, unpriced=unpriced,
                sekat_cost_idr=sekat_cost or None, idr_per_m3_held=(sekat_cost / held) if sekat_cost and held else None,
                spend_curve=spend_curve(allb, cfg))
