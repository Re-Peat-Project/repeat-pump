"""How many sekat each minimum spacing gives, and how much canal rewetting they buy.

Re-places the Stage 7 sekat of a finished run with different ``sekat.min_new_spacing_m`` values (same profiles, same head
rule) and scores every layout with the Stage 12 canal-rise objective [Urzainki2020]: the canal water level rise summed over
the profile stations, times the station step, so in m x m of canal. Also writes the greedy curve (blocks added in order of
largest extra rise) for the run's own layout, which shows where more blocks stop paying.

    python scripts/sekat_spacing_check.py --config RUN.yaml --spacings 0 200 300 500 --drawdown 0.8 1.2

Writes ``sekat_spacing_check.csv`` and ``sekat_spacing_greedy.csv`` next to the run's GeoPackage.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
import pyogrio

from repeat_pump.core import blockopt as bo
from repeat_pump.core.config import load_config, resolve
from repeat_pump.core.sekat import canal_arrays, place_sekat


def layouts(gpkg, cfg, spacings):
    canals = pyogrio.read_dataframe(gpkg, layer="canals_clean")
    prof = pyogrio.read_dataframe(gpkg, layer="canal_profiles")
    ex = pyogrio.read_dataframe(gpkg, layer="sekat_existing_assessed")
    ex = ex[ex["snapped"].astype(bool)]
    by = {c: g for c, g in prof.groupby("canal_id")}
    dA, fine = cfg.sekat.dA_m, cfg.profiles.sample_step_m / 10.0
    out = {}
    for sp in spacings:
        rows = []
        for cid, line, direction in zip(canals["canal_id"], canals.geometry, canals["direction"]):
            if cid not in by:
                continue
            L = line.length
            d, z, _i = canal_arrays(by[cid], direction, L)
            e = ex[ex["canal_id"] == cid]["chainage_m"]
            ex_pos = [(L - c) if direction == "forward" else c for c in e]
            new = place_sekat(d, z, dA, ex_pos, cfg.sekat.min_spacing_m, fine, sp or None)
            allpos = sorted([p for p, _ in new] + ex_pos)
            for p, _zp in new:
                before = [q for q in allpos if q < p]
                rows.append(dict(canal_id=cid, chainage_m=(L - p) if direction == "forward" else p, gap_m=p - (before[-1] if before else 0.0)))
        out[sp] = pd.DataFrame(rows)
    return canals, prof, ex, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--spacings", nargs="+", type=float, default=[0, 200, 300, 500], help="min_new_spacing_m values; 0 = off")
    ap.add_argument("--drawdown", nargs="+", type=float, default=[0.8, 1.2], help="dry-season canal level below land (m)")
    a = ap.parse_args()
    cfg = load_config(a.config)
    gpkg = resolve(cfg, cfg.run.output_gpkg)
    canals, prof, ex, lay = layouts(gpkg, cfg, a.spacings)
    net = bo.CanalNet.from_profiles(canals, prof)
    dA, step = cfg.sekat.dA_m, cfg.profiles.sample_step_m
    rows, greedy = [], []
    for dd in a.drawdown:
        base = net.z_land - dd
        fixed = {}
        for c, ch in zip(ex["canal_id"], ex["chainage_m"]):
            n = net.node_at(c, ch)
            if n is not None:
                fixed[n] = max(fixed.get(n, -np.inf), float(net.z_land[n] - dA))
        for sp, df in lay.items():
            nodes = [net.node_at(c, ch) for c, ch in zip(df["canal_id"], df["chainage_m"])]
            ok = [i for i, n in enumerate(nodes) if n is not None]
            nodes = [nodes[i] for i in ok]
            obj = bo.CanalRiseObjective(net, base, nodes, np.array([net.z_land[n] - dA for n in nodes]), fixed)
            rise = obj.benefit(list(range(len(nodes)))) * step
            gaps = df["gap_m"]
            rows.append(dict(drawdown_m=dd, min_new_spacing_m=sp, n_sekat=len(df), rise_m2=round(rise),
                             rise_per_sekat_m2=round(rise / max(len(df), 1)), gap_min_m=round(gaps.min()) if len(df) else None,
                             gap_median_m=round(gaps.median()) if len(df) else None, n_gap_below_200m=int((gaps < 200).sum())))
            if sp == a.spacings[0]:
                chosen, total = [], 0.0
                left = set(range(len(nodes)))
                while left:
                    best = max(left, key=lambda c: obj.benefit(chosen + [c]))
                    chosen.append(best)
                    left.discard(best)
                    v = obj.benefit(chosen) * step
                    greedy.append(dict(drawdown_m=dd, k=len(chosen), rise_m2=round(v), gain_m2=round(v - total)))
                    total = v
    t = pd.DataFrame(rows)
    t.to_csv(gpkg.parent / "sekat_spacing_check.csv", index=False)
    pd.DataFrame(greedy).to_csv(gpkg.parent / "sekat_spacing_greedy.csv", index=False)
    print(t.to_string(index=False))


if __name__ == "__main__":
    main()
