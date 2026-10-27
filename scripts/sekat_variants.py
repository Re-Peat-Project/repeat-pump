"""Compare sekat layouts by how much of the neraca air deficit they can hold back, all scored on one reference canal network.

    python scripts/sekat_variants.py --config ../re-peat/sites/16.02.01_sugihan_lumpur/sekat_variants.yaml

The variants file names a base run config, the variants (dotted overrides of that config), the reference variant and the scoring
values. Each variant runs stages 1-7 into its own folder (``<out>/<name>/``; a finished one is reused unless --force). Every layout
is then placed on the reference network (snapped within ``snap_m``) and scored with the canal-rise objective of stage 12
[Urzainki2020] with the existing sekat in place:

    rise      sum over canal stations of the water-level rise, times the station step       (m x m of canal)
    retained  rise x specific_yield x lateral_reach_m                                        (m3 held in the peat beside the canals)
    deficit   neraca KHG deficit (mm) x area of the selected sub-KHGs                        (m3 the dry season takes)

and reports blocks, retained water per block, share of the deficit closed, spacing, and the smallest set (greedy by extra rise
on the reference) that gives 80 / 90 % of the layout's rise. Writes variants.csv and variants.md in ``out``.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import yaml

from repeat_pump.core import blockopt as bo
from repeat_pump.core.config import resolve  # noqa: F401
from repeat_pump.core.pipeline import ReviewRequired, run_pipeline


def _set(d: dict, key: str, value) -> None:
    node = d
    *head, last = key.split(".")
    for k in head:
        node = node.setdefault(k, {})
    node[last] = value


def load_base(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf8"))
    base = path.parent
    for sec in data.get("inputs", {}).values():                 # absolute paths: the variant configs live elsewhere
        if isinstance(sec, dict):
            if sec.get("path"):
                sec["path"] = str((base / os.path.expandvars(sec["path"])).resolve())
            if sec.get("paths"):
                sec["paths"] = [str((base / os.path.expandvars(p)).resolve()) for p in sec["paths"]]
    if data.get("preset"):
        data["preset"] = str((base / os.path.expandvars(data["preset"])).resolve())
    return data


def run_variant(base: dict, name: str, overrides: dict, out: Path, force: bool, rerun_from=None) -> Path:
    d = copy.deepcopy(base)
    folder = out / name
    gpkg = folder / "run.gpkg"
    for k, v in {**overrides, "run.output_gpkg": str(gpkg), "run.name": name, "pumping.enabled": False, "optimise.enabled": False,
                 "sekat.target_rise_share": 1.0}.items():
        _set(d, k, v)
    folder.mkdir(parents=True, exist_ok=True)
    cfg_path = folder / "run_config.yaml"
    cfg_path.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf8")
    done = json.loads((folder / "run_state.json").read_text())["stages"].get("7", {}).get("status") == "done" \
        if (folder / "run_state.json").exists() else False
    from repeat_pump.core.config import load_config
    from repeat_pump.core.pipeline import reset_run
    if done and not force:
        if rerun_from:                                   # e.g. 7: redo the sekat stage only, after a change in the scoring
            run_pipeline(load_config(cfg_path), stop_after=7, resume_from=int(rerun_from), accept=[2, 6])
        return gpkg
    cfg = load_config(cfg_path)
    reset_run(cfg)
    try:
        run_pipeline(cfg, stop_after=7, accept=[2, 6])
    except ReviewRequired:
        run_pipeline(cfg, stop_after=7, accept=[2, 6])
    return gpkg


def reference_net(gpkg: Path, cfg_dict: dict):
    canals = pyogrio.read_dataframe(gpkg, layer="canals_clean")
    prof = pyogrio.read_dataframe(gpkg, layer="canal_profiles")
    ex = pyogrio.read_dataframe(gpkg, layer="sekat_existing_assessed")
    ex = ex[ex["snapped"].astype(bool)] if len(ex) else ex
    sk = pyogrio.read_dataframe(gpkg, layer="subkhg_selected")
    return canals, bo.CanalNet.from_profiles(canals, prof), ex, sk


def snap(points, canals, tol: float) -> list:
    """(canal_id, chainage) on the reference canals for each point within ``tol``, else None."""
    from shapely import STRtree
    tree = STRtree(list(canals.geometry))
    out = []
    for p in points.geometry:
        idx = tree.query(p.buffer(tol))
        if not len(idx):
            out.append(None)
            continue
        j = min(idx, key=lambda i: canals.geometry.iloc[i].distance(p))
        ln = canals.geometry.iloc[j]
        out.append((canals["canal_id"].iloc[j], float(ln.project(p))) if ln.distance(p) <= tol else None)
    return out


def gaps(locs: list, ex_locs: list) -> np.ndarray:
    """Along-canal distance from each new block to the nearest other block (new or existing) on the same reference canal."""
    by: dict = {}
    for c, ch in ex_locs:
        by.setdefault(c, []).append(("old", ch))
    for c, ch in locs:
        by.setdefault(c, []).append(("new", ch))
    g = []
    for items in by.values():
        pos = sorted(ch for _k, ch in items)
        for k, ch in items:
            if k == "new":
                others = [abs(q - ch) for q in pos if q != ch] or [np.inf]
                g.append(min(others))
    return np.array(g)


def md_table(df: pd.DataFrame) -> str:
    rows = [list(map(str, df.columns))] + [["" if v is None or (isinstance(v, float) and v != v) else f"{v:,}" if isinstance(v, (int, np.integer)) else str(v)
                                            for v in r] for r in df.itertuples(index=False)]
    return "\n".join(["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])] + ["| " + " | ".join(r) + " |" for r in rows[1:]])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="variants YAML")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--rerun-from", type=int, help="re-run finished variants from this stage (7 = sekat only)")
    a = ap.parse_args()
    vpath = Path(a.config).resolve()
    spec = yaml.safe_load(vpath.read_text(encoding="utf8"))
    base = load_base((vpath.parent / os.path.expandvars(spec["base"])).resolve())
    out = (vpath.parent / os.path.expandvars(spec["out"])).resolve()
    sc = spec["scoring"]
    for ov in spec["variants"].values():               # paths in the overrides are relative to the variants file
        for k, v in list((ov or {}).items()):
            if k.endswith(".path") and isinstance(v, str):
                ov[k] = str((vpath.parent / os.path.expandvars(v)).resolve())
    gpkgs = {name: run_variant(base, name, ov or {}, out, a.force, a.rerun_from) for name, ov in spec["variants"].items()}

    ref = spec["reference"]
    canals, net, ex, sk = reference_net(gpkgs[ref], base)
    dA, step = base.get("sekat", {}).get("dA_m", 0.4), base.get("profiles", {}).get("sample_step_m", 5)
    dA = dA or 0.4
    ex_locs = [(c, ch) for c, ch in zip(ex["canal_id"], ex["chainage_m"])]
    fixed = {}
    for c, ch in ex_locs:
        n = net.node_at(c, ch)
        if n is not None:
            fixed[n] = max(fixed.get(n, -np.inf), float(net.z_land[n] - dA))
    area = float(sk.geometry.area.sum())
    deficit_mm = float(sk["deficit_mm"].dropna().iloc[0]) if "deficit_mm" in sk and sk["deficit_mm"].notna().any() else np.nan
    deficit_m3 = deficit_mm / 1000 * area
    import geopandas as gpd
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(net.xy[:, 0], net.xy[:, 1]), crs=sk.crs)
    unit_of = gpd.sjoin(pts, sk[["subkhg_id", "geometry"]], how="left", predicate="within")["subkhg_id"]
    unit_of = unit_of[~unit_of.index.duplicated()].reindex(range(net.n)).to_numpy()
    unit_area = dict(zip(sk["subkhg_id"], sk.geometry.area))
    rows, unit_rows = [], []

    def score(name, label, locs, dd, base_lv):
        ok = [l for l in locs if l is not None and net.node_at(*l) is not None]
        nodes = [net.node_at(*l) for l in ok]
        crest = np.array([net.z_land[n] - dA for n in nodes])
        order = bo.greedy_rank(net, base_lv, nodes, crest, fixed)
        gains = np.array([g for _i, g in order]) * step
        total = float(gains.sum())
        cum = np.cumsum(gains) / total if total > 0 else np.zeros(len(gains))
        k = {q: int(np.searchsorted(cum, q - 1e-9) + 1) if total > 0 else 0 for q in (0.8, 0.9)}
        g = gaps(ok, ex_locs)
        for reach in sc["lateral_reach_m"]:
            ret = total * sc["specific_yield"] * reach
            rows.append(dict(variant=label, drawdown_m=dd, lateral_reach_m=reach, blocks=len(locs), snapped=len(ok),
                             rise_m2=round(total), retained_m3=round(ret), retained_per_block_m3=round(ret / max(len(ok), 1)),
                             deficit_closed_pct=round(100 * ret / deficit_m3, 2) if deficit_m3 == deficit_m3 else None,
                             blocks_for_80pct=k[0.8], blocks_for_90pct=k[0.9],
                             gap_median_m=round(float(np.median(g[np.isfinite(g)]))) if np.isfinite(g).any() else None,
                             gaps_below_200m=int((g < 200).sum()), alone_on_canal=int((~np.isfinite(g)).sum())))
        if dd == sc["drawdown_m"][0]:                   # per sub-KHG: water held against that unit's deficit volume
            obj = bo.CanalRiseObjective(net, base_lv, nodes, crest, fixed)
            rise = (obj.levels(range(len(nodes))) - obj.wt_fixed) * step
            for u in sk["subkhg_id"]:
                r_u = float(np.nansum(rise[unit_of == u]))
                for reach in sc["lateral_reach_m"][:1]:
                    unit_rows.append(dict(variant=label, subkhg_id=u, blocks=int(sum(1 for n in nodes if unit_of[n] == u)),
                                          retained_m3=round(r_u * sc["specific_yield"] * reach),
                                          deficit_m3=round(deficit_mm / 1000 * unit_area[u]),
                                          deficit_closed_pct=round(100 * r_u * sc["specific_yield"] * reach / (deficit_mm / 1000 * unit_area[u]), 2)))

    for dd in sc["drawdown_m"]:
        base_lv = net.z_land - dd
        for name, gpkg in gpkgs.items():
            pr = pyogrio.read_dataframe(gpkg, layer="sekat_proposed")
            low = pyogrio.read_dataframe(gpkg, layer="sekat_low_benefit") if "sekat_low_benefit" in [l[0] for l in pyogrio.list_layers(gpkg)] else pr.iloc[0:0]
            allp = pd.concat([pr, low], ignore_index=True)
            locs = snap(allp, canals, sc["snap_m"])
            score(name, name, locs, dd, base_lv)
            if "cum_share" in allp:                         # what stage 7 keeps with the balance on: ranked on the variant's own network
                for share in sc.get("balance_shares", [0.9]):
                    reach_i = allp.loc[allp["cum_share"] >= share - 1e-9, "benefit_rank"].min()
                    keep = (allp["benefit_rank"] <= reach_i).to_numpy()
                    score(name, f"{name} @{int(share * 100)}%", [l for l, kp in zip(locs, keep) if kp], dd, base_lv)
    t = pd.DataFrame(rows)
    t.to_csv(out / "variants.csv", index=False)
    tu = pd.DataFrame(unit_rows)
    tu.to_csv(out / "variants_units.csv", index=False)
    main_rows = t[(t.drawdown_m == sc["drawdown_m"][0]) & (t.lateral_reach_m == sc["lateral_reach_m"][0])]
    ref_rise = float(main_rows.loc[main_rows.variant == ref, "rise_m2"].iloc[0])
    main_rows = main_rows.assign(rise_vs_reference_pct=(100 * main_rows["rise_m2"] / ref_rise).round(1))
    md = [f"# Sekat variants: {spec.get('title', vpath.stem)}", "",
          f"Generated by `scripts/sekat_variants.py --config {vpath.name}`. Do not edit; rerun.", "",
          "## Selection rule (written before the runs)", "", spec["rule"].strip(), "",
          f"Reference network: `{ref}`. Selected sub-KHGs: {', '.join(map(str, sk['subkhg_id']))} ({area / 1e6:,.0f} km2). "
          f"Neraca KHG deficit {deficit_mm:g} mm, so {deficit_m3 / 1e6:,.1f} million m3 over the selected sub-KHGs.", "",
          f"Main table: drawdown {sc['drawdown_m'][0]} m, lateral reach {sc['lateral_reach_m'][0]} m, specific yield {sc['specific_yield']}. "
          "All combinations are in variants.csv.", "",
          md_table(main_rows.drop(columns=["drawdown_m", "lateral_reach_m"])), "",
          "## Per sub-KHG (main setting)", "", md_table(tu), ""]
    (out / "variants.md").write_text("\n".join(md), encoding="utf8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
