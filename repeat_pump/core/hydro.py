"""Stage 3: hydro-conditioning for flow routing ONLY.

Canals are burned into a *copy* of the DTM, depressions are breached
(least-cost breaching with fill fallback, Lindsay2016a; burn artefacts per
Lindsay2016b; flats per Garbrecht1997) and flow accumulation is computed with
D-infinity (Tarboton1997), MFD (Holmgren1994) or D8. The unconditioned DTM stays
the only source for elevation, slope and profile work (Stages 5 and 7).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize

from .config import require
from .io import check_memory


class WhiteboxError(RuntimeError):
    pass


def _wbt(workdir: Path):
    try:
        from whitebox import WhiteboxTools
    except Exception as e:  # pragma: no cover
        raise WhiteboxError(f"whitebox package not importable: {e}")
    wbt = WhiteboxTools()
    wbt.set_verbose_mode(False)
    wbt.set_working_dir(str(workdir))
    return wbt


def _ok(rc, what: str) -> None:
    if rc != 0:
        raise WhiteboxError(f"WhiteboxTools {what} failed (return code {rc})")


def burn_canals(dtm_path: Path, canals, default_depth: float, out_path: Path) -> float:
    """Burn canals into a copy of the DTM. Returns the share of canal length using the default depth."""
    with rasterio.open(dtm_path) as src:
        z = src.read(1).astype("float64")
        nd = src.nodata
        prof = src.profile
        tr = src.transform
    valid = np.ones(z.shape, bool) if nd is None else z != nd
    depth = canals["depth_m"].fillna(default_depth).astype(float).where(canals["depth_m"].notna() & (canals["depth_m"] > 0), default_depth)
    shapes = [(g, float(d)) for g, d in zip(canals.geometry, depth)]
    burn = rasterize(shapes, out_shape=z.shape, transform=tr, fill=0.0, dtype="float64") if shapes else np.zeros(z.shape)
    z = np.where(valid, z - burn, z)
    prof.update(dtype="float64", compress="deflate")
    with rasterio.open(out_path, "w", **prof) as dst:
        dst.write(z, 1)
    L = canals.geometry.length
    used_default = ~(canals["depth_m"].notna() & (canals["depth_m"] > 0))
    return float(L[used_default].sum() / L.sum()) if L.sum() > 0 else 0.0


def condition_dem(dem: Path, out: Path, breach_dist_cells: int, workdir: Path) -> None:
    """Least-cost breaching with fill fallback (Lindsay2016a)."""
    wbt = _wbt(workdir)
    _ok(wbt.breach_depressions_least_cost(str(dem), str(out), int(breach_dist_cells), fill=True), "breach_depressions_least_cost")


def flow_accumulation(cond: Path, out: Path, algorithm: str, workdir: Path) -> None:
    """Flow accumulation in cells: D-inf (Tarboton1997), MFD (Holmgren1994) or D8."""
    wbt = _wbt(workdir)
    if algorithm == "dinf":
        rc = wbt.d_inf_flow_accumulation(str(cond), str(out), out_type="cells")
    elif algorithm == "mfd":
        rc = wbt.fd8_flow_accumulation(str(cond), str(out), out_type="cells")
    else:
        rc = wbt.d8_flow_accumulation(str(cond), str(out), out_type="cells")
    _ok(rc, f"flow accumulation ({algorithm})")


def run(ctx) -> None:
    cfg = ctx.cfg
    require(cfg.hydro, ["breach_max_dist_cells"], "Stage 3", "hydro")
    dtm = Path(ctx.report["inputs"]["dtm"])
    with rasterio.open(dtm) as d:
        check_memory(cfg, d.width * d.height, 8, 5, "DTM for hydro-conditioning")
    canals = ctx.read_layer("canals_clean")
    burned = ctx.work / "dtm_burned_tmp.tif"
    cond = ctx.work / "dtm_conditioned.tif"
    acc = ctx.work / "flow_acc.tif"
    ctx.progress(0.05, "burning the canals into the DTM")
    share_default = burn_canals(dtm, canals, cfg.hydro.burn_depth_default_m, burned)
    if share_default > 0:
        ctx.warn(f"Stage 3: {share_default:.0%} of canal length burned with the default depth {cfg.hydro.burn_depth_default_m} m (canals.depth_m missing)")
    ctx.progress(0.15, "removing depressions (breaching)")
    condition_dem(burned, cond, cfg.hydro.breach_max_dist_cells, ctx.work)
    ctx.progress(0.6, "accumulating flow")
    flow_accumulation(cond, acc, cfg.hydro.flow_algorithm, ctx.work)
    burned.unlink(missing_ok=True)
    ctx.report["inputs"].update(dtm_conditioned=str(cond), flow_acc=str(acc))
    ctx.report["hydro"] = {"flow_algorithm": cfg.hydro.flow_algorithm, "share_canal_length_default_depth": share_default,
                           "note": "burn artefacts are expected along canals (Lindsay2016b); conditioned DTM is used for flow routing only"}
    ctx.set_counts("3", canals_burned=int(len(canals)))
