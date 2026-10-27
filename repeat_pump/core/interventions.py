"""Interventions per sub-KHG (part of stage 11): which treatment suits each unit, beyond placing sekat.

Canal blocks keep water that would drain away; they do not supply the dry season, and they only act on land near the canals. So
every sub-KHG of the indicator table (``inputs.subkhg_indicators``: the sub-KHG prioritisation's ``unit_prioritas``) gets one primary
class and a yes/no flag for each reason, from fixed thresholds (``interventions.*``; the proposed defaults are POLICY values):

    close_canals     protected peat function (FEG) on at least ``protected_share`` of the unit: drainage in protected peat is closed
                     entirely, by full canal closure or backfilling (re-peat/docs, strategy assignment)
    revegetate_fire  dry (NDMI below ``ndmi_dry``) or burnt (``burned_min`` of the unit ever burnt) and canals reach less than
                     ``reach_min`` of the land: water held in canals does not reach it; revegetation and fire readiness (deep wells)
    block_water      blocks reach the land but hold less than ``held_target`` of the deficit, and permanent water lies within
                     ``water_max_dist_m`` on average: sekat plus water supply (gates or pumps; check the source holds water in the dry season)
    block_wells      as block_water, but no water nearby and the land is dry or burnt: sekat plus deep wells for fire readiness
    block            blocks reach the land: sekat (stage 7)
    maintain         none of the above: keep and monitor

The water held by blocks is computed for the selected sub-KHGs only (where stage 7 placed sekat), with the canal-rise objective of
stage 12 [Urzainki2020] capped at the land surface, times ``specific_yield`` (the neraca air value) and ``lateral_reach_m``
[Urzainki2023]. Elsewhere ``held_share`` is empty and the KHG deficit alone (``deficit_min_mm``) decides whether blocks fall short.
The neraca balance per unit is used only where its order is trustworthy (``balance_stable_ok`` = 1).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import geopandas as gpd

from . import blockopt as bo
from .config import resolve

CLASSES = {
    "close_canals": "Close or backfill canals (protected peat)",
    "revegetate_fire": "Revegetation and fire readiness",
    "block_water": "Sekat and water supply",
    "block_wells": "Sekat and deep wells",
    "block": "Sekat",
    "maintain": "Maintain and monitor",
}
NEEDED = ["protected_share", "reach_min", "ndmi_dry", "burned_min", "water_max_dist_m", "held_target", "deficit_min_mm",
          "specific_yield", "lateral_reach_m"]


def read_indicators(cfg) -> pd.DataFrame:
    sec = cfg.inputs.subkhg_indicators
    path = resolve(cfg, sec.path)
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        import pyogrio
        df = pyogrio.read_dataframe(path, layer=sec.layer, read_geometry=False)
    col = (sec.columns or {}).get("subkhg_id") or next((c for c in ("subkhg_id", "unit_id") if c in df), None)
    if col is None:
        raise ValueError("subkhg_indicators: no subkhg_id or unit_id column (map it under inputs.subkhg_indicators.columns)")
    return df.rename(columns={col: "subkhg_id"}).assign(subkhg_id=lambda d: d["subkhg_id"].astype(str))


def held_per_unit(ctx, units: gpd.GeoDataFrame, drawdown: float) -> dict:
    """Water (m x m of canal rise, before Sy and reach) the kept sekat hold in each unit, on the stage 5 canal network."""
    if not (ctx.has_layer("sekat_proposed") and ctx.has_layer("canal_profiles")):
        return {}
    canals, prof = ctx.read_layer("canals_clean"), ctx.read_layer("canal_profiles")
    net = bo.CanalNet.from_profiles(canals, prof)
    dA, step = ctx.cfg.sekat.dA_m, ctx.cfg.profiles.sample_step_m
    base = net.z_land - drawdown
    fixed = {}
    if ctx.has_layer("sekat_existing_assessed"):
        ex = ctx.read_layer("sekat_existing_assessed")
        for c, ch, ok in zip(ex.get("canal_id", []), ex.get("chainage_m", []), ex.get("snapped", [])):
            n = net.node_at(c, ch) if ok else None
            if n is not None:
                fixed[n] = max(fixed.get(n, -np.inf), float(net.z_land[n] - dA))
    pr = ctx.read_layer("sekat_proposed")
    nodes = [n for n in (net.node_at(c, ch) for c, ch in zip(pr["canal_id"], pr["chainage_m"])) if n is not None] if len(pr) else []
    obj = bo.CanalRiseObjective(net, base, nodes, np.array([net.z_land[n] - dA for n in nodes]), fixed)
    rise = (obj.levels(range(len(nodes))) - obj.wt_fixed) * step
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(net.xy[:, 0], net.xy[:, 1]), crs=units.crs)
    j = gpd.sjoin(pts, units[["subkhg_id", "geometry"]], how="left", predicate="within")
    j = j[~j.index.duplicated()]
    s = pd.Series(np.nan_to_num(rise), index=range(net.n)).groupby(j["subkhg_id"].reindex(range(net.n)).to_numpy()).sum()
    blocks = pd.Series(j["subkhg_id"].reindex(nodes).to_numpy()).value_counts() if nodes else pd.Series(dtype=int)
    return {u: (float(s.get(u, 0.0)), int(blocks.get(u, 0))) for u in units["subkhg_id"]}


def classify(df: pd.DataFrame, ic) -> pd.DataFrame:
    """Flags and the primary class per unit (``df`` holds the indicator columns, ``held_share`` and ``deficit_mm``)."""
    num = lambda c: pd.to_numeric(df.get(c, pd.Series(np.nan, index=df.index)), errors="coerce")  # noqa: E731
    out = df.copy()
    out["f_protected"] = num("i_protected") >= ic.protected_share
    out["f_dry"] = num("u_ndmi") < ic.ndmi_dry
    out["f_burnt"] = num("burned_ever_frac") >= ic.burned_min
    out["f_low_reach"] = num("f_reach") < ic.reach_min
    out["f_water_near"] = num("f_water_dist") <= ic.water_max_dist_m
    held = num("held_share")
    short_khg = num("deficit_mm") >= ic.deficit_min_mm
    out["f_blocks_short"] = np.where(held.notna(), held < ic.held_target, short_khg)
    dry_or_burnt = out["f_dry"] | out["f_burnt"]
    cls = np.select(
        [out["f_protected"], dry_or_burnt & out["f_low_reach"],
         ~out["f_low_reach"] & out["f_blocks_short"] & out["f_water_near"],
         ~out["f_low_reach"] & out["f_blocks_short"] & ~out["f_water_near"] & dry_or_burnt,
         ~out["f_low_reach"]],
        ["close_canals", "revegetate_fire", "block_water", "block_wells", "block"], default="maintain")
    out["intervention"] = cls
    out["intervention_label"] = [CLASSES[c] for c in cls]
    # what the unit would need without the protected-peat rule: for the canals that are not closed, and to show the other reasons
    alt = np.select(
        [dry_or_burnt & out["f_low_reach"], ~out["f_low_reach"] & out["f_blocks_short"] & out["f_water_near"],
         ~out["f_low_reach"] & out["f_blocks_short"] & ~out["f_water_near"] & dry_or_burnt, ~out["f_low_reach"]],
        ["revegetate_fire", "block_water", "block_wells", "block"], default="maintain")
    out["intervention_otherwise"] = np.where(out["intervention"] == "close_canals", alt, "")
    reasons = []
    for _, r in out.iterrows():
        why = [t for f, t in (("f_protected", "protected peat"), ("f_dry", "dry (NDMI)"), ("f_burnt", "burnt"), ("f_low_reach", "canals reach little land"),
                              ("f_water_near", "water nearby"), ("f_blocks_short", "blocks fall short of the deficit")) if bool(r[f])]
        reasons.append("; ".join(why) or "none")
    out["reasons"] = reasons
    return out


def run(ctx) -> dict | None:
    """Write the ``interventions`` layer and return the counts per class (None when there is no indicator table)."""
    cfg = ctx.cfg
    ic = cfg.interventions
    if not ic.enabled or cfg.inputs.subkhg_indicators is None:
        return None
    missing = [f"interventions.{k}" for k in NEEDED if getattr(ic, k) is None]
    if missing:
        ctx.warn("Stage 11: interventions skipped, missing " + ", ".join(missing))
        return None
    ind = read_indicators(cfg)
    sk_all = gpd.read_file(resolve(cfg, cfg.inputs.subkhg.path), layer=cfg.inputs.subkhg.layer)
    idcol = (cfg.inputs.subkhg.columns or {}).get("subkhg_id") or next(c for c in ("subkhg_id", "unit_id") if c in sk_all)
    units = sk_all.rename(columns={idcol: "subkhg_id"})[["subkhg_id", "geometry"]].assign(subkhg_id=lambda d: d["subkhg_id"].astype(str))
    units = units.to_crs(ctx.crs)
    sel = ctx.read_layer("subkhg_selected")
    deficit = float(sel["deficit_mm"].dropna().iloc[0]) if "deficit_mm" in sel and sel["deficit_mm"].notna().any() else np.nan
    df = units.merge(ind, on="subkhg_id", how="left")
    df["area_km2"] = df.geometry.area / 1e6
    df["deficit_mm"] = deficit
    df["deficit_m3"] = deficit / 1000 * df.geometry.area
    if "balance_stable_ok" in df:                       # the per-unit balance only where its order between units is trustworthy
        for c in ("u_wb_mean", "u_deficit_months", "p_minus_et_mean_mm"):
            if c in df:
                df[c] = df[c].where(df["balance_stable_ok"] == 1)
    selected = set(sel["subkhg_id"].astype(str))
    held = held_per_unit(ctx, units[units["subkhg_id"].isin(selected)], cfg.sekat.balance_drawdown_m or 1.0)
    df["sekat_analysed"] = df["subkhg_id"].isin(selected)
    df["sekat_new"] = [held.get(u, (np.nan, np.nan))[1] for u in df["subkhg_id"]]
    df["held_m3"] = [held[u][0] * ic.specific_yield * ic.lateral_reach_m if u in held else np.nan for u in df["subkhg_id"]]
    df["held_share"] = df["held_m3"] / df["deficit_m3"]
    out = classify(df, ic)
    keep = ["subkhg_id", "intervention", "intervention_label", "intervention_otherwise", "reasons", "sekat_analysed", "sekat_new", "held_m3", "deficit_m3", "held_share",
            "deficit_mm", "area_km2", "f_protected", "f_dry", "f_burnt", "f_low_reach", "f_water_near", "f_blocks_short",
            "i_protected", "u_ndmi", "burned_ever_frac", "f_reach", "f_water_dist", "u_canal_density", "u_ipg_gap", "i_forest",
            "u_wb_mean", "u_deficit_months", "balance_stable_ok", "geometry"]
    layer = gpd.GeoDataFrame(out[[c for c in keep if c in out]], geometry="geometry", crs=ctx.crs)
    for c in [c for c in layer if c.startswith("f_") and c not in ("f_reach", "f_water_dist")] + ["sekat_analysed"]:
        layer[c] = layer[c].astype(bool)
    ctx.write_layer("interventions", layer, "11")
    layer.drop(columns="geometry").to_csv(ctx.out_dir / "interventions.csv", index=False)
    counts = {k: int((layer["intervention"] == k).sum()) for k in CLASSES}
    otherwise = {k: int((layer["intervention_otherwise"] == k).sum()) for k in CLASSES if (layer["intervention_otherwise"] == k).any()}
    no_ind = int(layer["u_ndmi"].isna().sum()) if "u_ndmi" in layer else len(layer)
    if no_ind:
        ctx.warn(f"Stage 11: {no_ind} sub-KHG without indicator values; their class rests on the flags that could be read")
    return dict(counts=counts, closed_otherwise=otherwise, thresholds={k: getattr(ic, k) for k in NEEDED}, units=len(layer),
                held_share_selected={u: round(float(s), 4) for u, s in zip(layer["subkhg_id"], layer["held_share"]) if s == s})
