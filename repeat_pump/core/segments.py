"""Stage 4: split cleaned canals into analysis segments.

Pieces are at most ``segments.max_length_m`` long, cut from the canal start vertex
(like QGIS *Split lines by maximum length*, Neteler2008 for the cleaned input).
``seg_id`` is deterministic: canal_id, then along-line position, never row order.
"""
from __future__ import annotations

import math

import geopandas as gpd
import numpy as np
from shapely.ops import substring


def split_canal(line, max_len: float) -> list[tuple[float, float]]:
    """Return (start_m, end_m) chainage pieces covering ``line``."""
    L = line.length
    n = max(1, math.ceil(L / max_len - 1e-9))
    return [(i * max_len, min((i + 1) * max_len, L)) for i in range(n)]


def run(ctx) -> None:
    cfg = ctx.cfg.segments
    clean = ctx.read_layer("canals_clean").sort_values("canal_id").reset_index(drop=True)
    rows = []
    for _, r in clean.iterrows():
        for k, (a, b) in enumerate(split_canal(r.geometry, cfg.max_length_m)):
            d = {c: r[c] for c in clean.columns if c not in ("geometry", "run_name", "stage", "length_m")}
            d.update(seg_id=f"{r['canal_id']}_{k + 1:03d}", seg_idx=k + 1, chain_start_m=float(a), chain_end_m=float(b),
                     length_m=float(b - a), status_mcda=0 if (b - a) < cfg.min_length_m else 1,
                     geometry=substring(r.geometry, a, b))
            rows.append(d)
    seg = gpd.GeoDataFrame(rows, geometry="geometry", crs=ctx.crs)
    ctx.write_layer("canal_segments", seg, "4")
    short = int((seg["status_mcda"] == 0).sum())
    ctx.set_counts("4", segments=int(len(seg)), short_flagged=short)
    if short:
        ctx.report.setdefault("notes", []).append(f"Stage 4: {short} segment(s) shorter than {cfg.min_length_m} m flagged status_mcda=0 (kept in network, excluded from scoring)")
