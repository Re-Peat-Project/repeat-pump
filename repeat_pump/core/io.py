"""Loading, validation and clipping of inputs (spec section 3, Stage 1).

Stage 1 refuses DSM input, enforces one projected CRS, checks overlap and vertical
datum, parses the text attributes (burn frequency, peat thickness class), selects
the priority sub-KHGs and clips everything to them.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import rasterio
from pyproj import CRS
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.vrt import WarpedVRT
from shapely import make_valid
from shapely.geometry import box, shape

from .config import (Config, CRSMismatchError, InputError, NeedsHuman, SurfaceTypeError, require_many, resolve, snake_name)
from .context import RunContext


class MemoryBudgetExceeded(RuntimeError):
    pass


# ----------------------------------------------------------------------------- helpers
def check_memory(cfg: Config, n_cells: int, bytes_per_cell: int = 8, copies: int = 4, what: str = "raster") -> None:
    """Guard against loading a raster that does not fit ``run.memory_budget_gb``."""
    budget = cfg.run.memory_budget_gb
    if budget is None:
        return
    need = n_cells * bytes_per_cell * copies / 1e9
    if need > budget:
        raise MemoryBudgetExceeded(
            f"{what} needs about {need:.1f} GB but run.memory_budget_gb is {budget}. "
            "Tiled processing is not implemented for this stage; clip to fewer sub-KHGs or raise the budget."
        )


def find_col(gdf: pd.DataFrame, candidates: list[str], layer: str) -> str:
    low = {c.lower(): c for c in gdf.columns}
    for cand in candidates:
        if cand.lower() in low:
            return low[cand.lower()]
    raise InputError(f"{layer}: none of the columns {candidates} found (have {list(gdf.columns)})")


def apply_columns(df: pd.DataFrame, columns: Optional[dict[str, str]], name: str, ctx: Optional[RunContext] = None, geom: str = "geometry") -> pd.DataFrame:
    """Rename the columns the user mapped (``{expected name: name in the data}``). The data's name is matched the way the engine
    normalises names (case, spaces and punctuation ignored). A mapped column wins over a column that already has the expected
    name, and says so."""
    if not columns:
        return df
    have = {snake_name(c): c for c in df.columns if c != geom}
    for want, src in columns.items():
        actual = have.get(snake_name(src))
        if actual is None:
            raise InputError(f"{name}: the column {src!r} (mapped to {want!r}) is not in the data; it has {sorted(have.values())}")
        if actual == want:
            continue
        if want in df.columns:
            msg = f"{name}: column {src!r} is used as {want!r}; the data's own {want!r} column is ignored"
            ctx.warn(msg) if ctx is not None else None
            df = df.drop(columns=[want])
        df = df.rename(columns={actual: want})
        have = {snake_name(c): c for c in df.columns if c != geom}
    return df


def read_vector(cfg: Config, path: str, name: str, ctx: Optional[RunContext] = None, layer: Optional[str] = None,
                columns: Optional[dict[str, str]] = None) -> gpd.GeoDataFrame:
    p = resolve(cfg, path)
    if not p.exists():
        raise InputError(f"{name}: file not found: {p}")
    gdf = pyogrio.read_dataframe(p, layer=layer)
    gdf.columns = _snake(list(gdf.columns), gdf.geometry.name)
    gdf = apply_columns(gdf, columns, name, ctx, gdf.geometry.name)
    gdf = _rename_source_fid(gdf, name, ctx)
    return check_vector_crs(gdf, name, cfg, ctx)


def _rename_source_fid(gdf: gpd.GeoDataFrame, name: str, ctx: Optional[RunContext] = None) -> gpd.GeoDataFrame:
    """An attribute called ``fid`` (common in shapefiles saved from a GeoPackage) clashes with the GeoPackage row id when the layer is
    written to the run GeoPackage: a Real, empty or repeated value makes the write fail. Keep it under another name."""
    if "fid" not in gdf.columns:
        return gdf
    new = "src_fid"
    while new in gdf.columns:
        new += "_x"
    if ctx is not None:
        ctx.warn(f"{name}: attribute column 'fid' renamed to '{new}' (GeoPackage reserves 'fid' for its row id)")
    return gdf.rename(columns={"fid": new})


def read_priority_table(cfg: Config, ctx: Optional[RunContext] = None) -> pd.DataFrame:
    """The optional priority CSV with its columns mapped. Its own names are kept as they are (not snake-cased)."""
    sec = cfg.inputs.subkhg_priority
    df = pd.read_csv(resolve(cfg, sec.path))
    return apply_columns(df, sec.columns, "subkhg_priority", ctx)


def _unit_id_alias(df):
    """The RE-PEAT delineation and prioritisation name the sub-KHG `unit_id`; this module calls it `subkhg_id`. `subkhg_id` wins if both exist."""
    if "subkhg_id" not in df and "unit_id" in df:
        return df.rename(columns={"unit_id": "subkhg_id"})
    return df


def _snake(cols: list[str], geom: str) -> list[str]:
    out: list[str] = []
    for c in cols:
        if c == geom:
            out.append(c); continue
        n = snake_name(c)
        while n in out:
            n = n[:27] + "_x"
        out.append(n)
    return out


def check_vector_crs(gdf: gpd.GeoDataFrame, name: str, cfg: Config, ctx: Optional[RunContext] = None) -> gpd.GeoDataFrame:
    target = CRS.from_user_input(cfg.run.crs)
    if gdf.crs is None:
        raise CRSMismatchError(f"{name}: layer has no CRS; expected {cfg.run.crs}")
    if CRS.from_user_input(gdf.crs) != target:
        if not cfg.run.auto_reproject:
            raise CRSMismatchError(f"{name}: CRS {gdf.crs.to_string()} differs from run.crs {cfg.run.crs} and auto_reproject is false")
        if ctx is not None:
            ctx.warn(f"{name}: reprojected from {gdf.crs.to_string()} to {cfg.run.crs}")
        gdf = gdf.to_crs(target)
    return gdf


@contextmanager
def open_raster(cfg: Config, path: str, name: str, resampling=Resampling.bilinear, ctx: Optional[RunContext] = None) -> Iterator[rasterio.DatasetReader]:
    """Open a raster, checking its CRS explicitly (legacy runs mixed EPSG:32748 and 32749)."""
    p = resolve(cfg, path)
    if not p.exists():
        raise InputError(f"{name}: file not found: {p}")
    target = CRS.from_user_input(cfg.run.crs)
    src = rasterio.open(p)
    try:
        if src.crs is None:
            raise CRSMismatchError(f"{name}: raster has no CRS; expected {cfg.run.crs}")
        if CRS.from_user_input(src.crs.to_wkt()) != target:
            if not cfg.run.auto_reproject:
                raise CRSMismatchError(f"{name}: CRS {src.crs.to_string()} differs from run.crs {cfg.run.crs} and auto_reproject is false")
            if ctx is not None:
                ctx.warn(f"{name}: reprojected on the fly from {src.crs.to_string()} to {cfg.run.crs}")
            vrt = WarpedVRT(src, crs=rasterio.crs.CRS.from_user_input(cfg.run.crs), resampling=resampling)
            try:
                yield vrt
            finally:
                vrt.close()
        else:
            yield src
    finally:
        src.close()


def crop_rasters(cfg: Config, paths: list[str], name: str, bounds: tuple, dst: Path, resampling=Resampling.bilinear,
                 ctx: Optional[RunContext] = None) -> Path:
    """Mosaic and crop raster(s) to ``bounds`` into ``dst`` (single GeoTIFF)."""
    from contextlib import ExitStack

    if len(paths) == 1:   # windowed block copy: memory use independent of the crop size
        from rasterio.windows import Window, from_bounds
        with open_raster(cfg, paths[0], name, resampling, ctx) as s:
            win = from_bounds(*bounds, transform=s.transform).round_offsets().round_lengths()
            try:
                win = win.intersection(Window(0, 0, s.width, s.height))
            except rasterio.errors.WindowError:
                raise InputError(f"{name}: raster does not overlap the analysis extent (check its CRS)")
            prof = dict(driver="GTiff", height=int(win.height), width=int(win.width), count=s.count, dtype=s.dtypes[0],
                        crs=rasterio.crs.CRS.from_user_input(cfg.run.crs), transform=s.window_transform(win), nodata=s.nodata,
                        compress="deflate", tiled=True, blockxsize=256, blockysize=256)
            dst.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(dst, "w", **prof) as out:
                for r0 in range(0, int(win.height), 1024):
                    h = min(1024, int(win.height) - r0)
                    src_w = Window(win.col_off, win.row_off + r0, win.width, h)
                    out.write(s.read(window=src_w), window=Window(0, r0, win.width, h))
        return dst

    with ExitStack() as stack:
        dss = [stack.enter_context(open_raster(cfg, p, name, resampling, ctx)) for p in paths]
        res = dss[0].res
        n = int(np.ceil((bounds[2] - bounds[0]) / res[0])) * int(np.ceil((bounds[3] - bounds[1]) / res[1]))
        check_memory(cfg, n, 4, 3, name)
        arr, tr = merge(dss, bounds=bounds, nodata=dss[0].nodata, resampling=resampling)
        prof = dict(driver="GTiff", height=arr.shape[1], width=arr.shape[2], count=arr.shape[0], dtype=arr.dtype,
                    crs=rasterio.crs.CRS.from_user_input(cfg.run.crs), transform=tr, nodata=dss[0].nodata, compress="deflate")
    dst.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(dst, "w", **prof) as out:
        out.write(arr)
    return dst


def _note_cloud_inputs(cfg: Config, ctx: RunContext) -> None:
    """Rasters and layers built by ``repeat-pump fetch-moisture`` / ``fetch-burn`` carry a ``<file>.provenance.json``: put it in the
    report and warn about every deviation, so an approximation is never mistaken for the team's own data."""
    for key, paths in (("moisture", cfg.inputs.moisture.paths), ("burn_area", [cfg.inputs.burn_area.path] if cfg.inputs.burn_area else [])):
        found = []
        for path in paths:
            sidecar = Path(str(resolve(cfg, path)) + ".provenance.json")
            if not sidecar.is_file():
                continue
            prov = json.loads(sidecar.read_text(encoding="utf8"))
            found.append({"file": str(path), **prov})
            for d in prov.get("deviations", []):
                ctx.warn(f"{key} {Path(path).name} ({prov.get('product')}): {d}")
            if key == "moisture" and prov.get("higher_is_wetter") is not None and prov["higher_is_wetter"] != cfg.inputs.moisture.higher_is_wetter:
                ctx.warn(f"moisture {Path(path).name}: built with higher_is_wetter={prov['higher_is_wetter']} but the config says {cfg.inputs.moisture.higher_is_wetter}")
        if found:
            ctx.report[f"{key}_provenance"] = found


# ----------------------------------------------------------------------------- attribute parsing
_BURN = re.compile(r"(\d+)")


def parse_burn_freq(values: pd.Series) -> tuple[pd.Series, list[str]]:
    """Normalise burn frequency such as ``'2x'`` to an int; return unparsed raw values."""
    out, bad = [], []
    for v in values:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            out.append(pd.NA); bad.append("<null>"); continue
        if isinstance(v, (int, np.integer)):
            out.append(int(v)); continue
        if isinstance(v, (float, np.floating)) and float(v).is_integer():
            out.append(int(v)); continue
        m = _BURN.search(str(v))
        if m:
            out.append(int(m.group(1)))
        else:
            out.append(pd.NA); bad.append(str(v))
    return pd.Series(out, index=values.index, dtype="Int64"), sorted(set(bad))


_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def parse_peat_class(values: pd.Series) -> tuple[pd.DataFrame, list[str]]:
    """Parse peat thickness class strings like ``'3,0 - 4,0 meter'`` (comma decimal)."""
    lo, hi, bad = [], [], []
    for v in values:
        nums = [float(x.replace(",", ".")) for x in _NUM.findall(str(v))] if v is not None else []
        if not nums:
            lo.append(np.nan); hi.append(np.nan); bad.append(str(v)); continue
        lo.append(nums[0]); hi.append(nums[1] if len(nums) > 1 else nums[0])
    return pd.DataFrame({"depth_min_m": lo, "depth_max_m": hi}, index=values.index), sorted(set(bad))


def _to_bool(s: pd.Series) -> pd.Series:
    def f(v):
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "t", "yes", "ya", "y")
        return bool(v) if v == v and v is not None else False
    return s.map(f)


def peat_depth_raster(cfg: Config, ctx: RunContext, bounds: tuple, extent, clip_dir: Path, val: dict, clip) -> Path:
    """Crop a peat depth raster, convert it to metres and write ``peat_depth.tif`` (float32, NaN no-data). The file's no-data, the extra
    ``nodata`` values (the BRGM Betara clip holds -8888 cells) and negative depths are dropped. The peat area (depth > 0) becomes the
    polygon layer ``inputs_clipped_peat_depth`` that stage 10 reads; stages 6 and 12 read the raster itself."""
    from rasterio import features

    sec = cfg.inputs.peat_depth
    src = crop_rasters(cfg, [sec.path], "peat_depth", bounds, clip_dir / "peat_depth_src.tif", Resampling.nearest, ctx)
    with rasterio.open(src) as r:
        check_memory(cfg, r.width * r.height, 8, 3, "peat_depth")
        arr, prof = r.read(1).astype("float64"), r.profile
        bad = ~np.isfinite(arr) | (arr == r.nodata) if r.nodata is not None else ~np.isfinite(arr)
    extra = np.isin(arr, sec.nodata or []) & ~bad
    negative = (arr < 0) & ~bad & ~extra
    arr[bad | extra | negative] = np.nan
    arr *= 0.01 if sec.units == "cm" else 1.0
    if extra.any() or negative.any():
        ctx.warn(f"peat_depth: {int(extra.sum())} cell(s) with an extra no-data value {sec.nodata} and {int(negative.sum())} negative cell(s) dropped")
    v = arr[np.isfinite(arr)]
    if not v.size:
        raise InputError("peat_depth: the raster has no valid cell inside the analysis extent (check its CRS and no-data)")
    med = float(np.median(v))
    if (sec.units == "m" and med > 30) or (sec.units == "cm" and float(v.max()) < 0.3):     # tropical peat is centimetres to ~20 m deep
        ctx.warn(f"peat_depth: the values (median {med:g} after conversion to m) do not look like {sec.units}; check inputs.peat_depth.units")
    val["peat_depth_raster"] = dict(units=sec.units, valid_cells=int(v.size), min_m=float(v.min()), median_m=med, max_m=float(v.max()),
                                    extra_nodata_cells=int(extra.sum()), negative_cells=int(negative.sum()))
    dst = clip_dir / "peat_depth.tif"
    prof.update(dtype="float32", nodata=np.nan, compress="deflate")
    with rasterio.open(dst, "w", **prof) as out:
        out.write(arr.astype("float32"), 1)
    peat = np.isfinite(arr) & (arr > 0)
    polys = [shape(g) for g, _ in features.shapes(peat.astype("uint8"), mask=peat, transform=prof["transform"])]
    gdf = gpd.GeoDataFrame({"peat_class": ["raster"] * len(polys), "depth_min_m": np.nan, "depth_max_m": np.nan}, geometry=polys,
                           crs=cfg.run.crs)
    check_overlap(ctx, "peat_depth", gdf.geometry.union_all() if len(gdf) else box(*bounds), extent)
    ctx.write_layer("inputs_clipped_peat_depth", clip(gdf), "1")
    return dst


def _footprint(obj) -> "box":
    if isinstance(obj, gpd.GeoDataFrame) and (obj.geom_type.isin(["Polygon", "MultiPolygon"]).all()):
        return obj.geometry.union_all()
    b = obj.total_bounds if isinstance(obj, gpd.GeoDataFrame) else obj
    return box(*b)


def check_overlap(ctx: RunContext, name: str, footprint, extent) -> float:
    frac = footprint.intersection(extent).area / extent.area if extent.area > 0 else 0.0
    ctx.report.setdefault("validation", {}).setdefault("coverage", {})[name] = round(frac, 4)
    if frac < 0.9:
        ctx.warn(f"{name} covers only {frac:.0%} of the analysis extent (< 90%)")
    return frac


# ----------------------------------------------------------------------------- Stage 1
def _require_features(ctx: RunContext, name: str, gdf: gpd.GeoDataFrame, extent) -> None:
    """Lines/points cannot 'cover' an extent; warn only when none fall inside it."""
    n = int(gdf.geometry.intersects(extent).sum())
    ctx.report.setdefault("validation", {}).setdefault("features_in_extent", {})[name] = n
    if n == 0:
        ctx.warn(f"{name}: no features inside the analysis extent")
        if name == "rivers" and ctx.cfg.pumping.enabled:
            ctx.warn("Stage 1: no river in the analysis extent, so stage 9 will find no water source. "
                     "For a sekat-only plan set pumping.enabled: false (stages 8-10 are skipped)")


def run_stage1(ctx: RunContext) -> None:
    """Stage 1: load, validate, select sub-KHGs, clip inputs (spec section 5, Stage 1)."""
    cfg = ctx.cfg
    require_many([(cfg.run, ["clip_margin_m"], "run"), (cfg.inputs.dtm, ["vertical_rmse_m"], "inputs.dtm")], "Stage 1")
    val = ctx.report.setdefault("validation", {})

    dtm_cfg = cfg.inputs.dtm
    if str(dtm_cfg.surface_type).upper() != "DTM":
        raise SurfaceTypeError(f"inputs.dtm.surface_type is {dtm_cfg.surface_type!r}; the module needs a bare-earth DTM, refusing to run on a DSM")
    crs = CRS.from_user_input(cfg.run.crs)
    if not crs.is_projected or crs.axis_info[0].unit_name not in ("metre", "meter"):
        raise InputError(f"run.crs {cfg.run.crs} must be a projected CRS in metres")
    if cfg.sekat.dA_m < 2 * dtm_cfg.vertical_rmse_m:
        ctx.warn(f"ACCURACY: sekat.dA_m ({cfg.sekat.dA_m} m) < 2 x DTM vertical RMSE ({dtm_cfg.vertical_rmse_m} m); "
                 "head-based sekat placement is dominated by DTM noise")
        val["accuracy_warning"] = True

    with open_raster(cfg, dtm_cfg.path, "dtm", Resampling.bilinear, ctx) as d:  # fail fast on CRS
        dtm_bounds, dtm_res = d.bounds, d.res

    # --- vectors
    subkhg = _unit_id_alias(read_vector(cfg, cfg.inputs.subkhg.path, "subkhg", ctx, cfg.inputs.subkhg.layer, cfg.inputs.subkhg.columns))
    if "subkhg_id" not in subkhg or subkhg["subkhg_id"].duplicated().any():
        raise InputError("subkhg: needs a unique 'subkhg_id' column (or 'unit_id', as the RE-PEAT delineation names it)")
    subkhg = subkhg.assign(geometry=make_valid(subkhg.geometry.values))
    # The priority table (neraca air + prioritisation) is optional. Without it, or without some of its columns, the
    # neutral fallbacks apply: equal priority for every selected sub-KHG, and (stage 10) demand from specific yield.
    subkhg["subkhg_id"] = subkhg["subkhg_id"].astype(str)
    prio = None
    if cfg.inputs.subkhg_priority is not None:
        prio = _unit_id_alias(read_priority_table(cfg, ctx))
        if "subkhg_id" not in prio:
            raise InputError("subkhg_priority: needs a 'subkhg_id' column (or 'unit_id', as the RE-PEAT prioritisation names it)")
        prio["subkhg_id"] = prio["subkhg_id"].astype(str)
        for col, note in (("priority_rank", "all sub-KHGs get equal priority"),
                          ("deficit_mm", "pump demand will use specific yield instead of the water deficit"),
                          ("design_period_days", "the design period must be given as pumping.design_period_days")):
            if col not in prio:
                prio[col] = np.nan
                ctx.warn(f"subkhg_priority has no '{col}' column: {note}")
    has_rank = prio is not None and prio["priority_rank"].notna().any()
    sel = cfg.run.subkhg_selection
    if sel.mode == "top_n" and not has_rank:
        ctx.warn("No priority ranking available (no subkhg_priority table or no priority_rank): every sub-KHG in the layer is "
                 "selected, with equal priority")
        ids = subkhg["subkhg_id"].tolist()
    elif sel.mode == "top_n":
        if sel.n is None:
            raise InputError("run.subkhg_selection.n is required for mode top_n")
        ids = prio.sort_values(["priority_rank", "subkhg_id"]).head(sel.n)["subkhg_id"].tolist()
    elif sel.mode == "all":
        ids = subkhg["subkhg_id"].tolist()
    else:
        if not sel.ids:
            raise InputError("run.subkhg_selection.ids is required for mode ids")
        ids = list(sel.ids)
    ids = [str(i) for i in ids]
    missing = [i for i in ids if i not in set(subkhg["subkhg_id"]) or (prio is not None and i not in set(prio["subkhg_id"]))]
    if missing:
        raise InputError(f"selected sub-KHG ids not in subkhg layer{' and subkhg_priority' if prio is not None else ''}: {missing}")
    selected = subkhg[subkhg["subkhg_id"].isin(ids)]
    if prio is not None:
        selected = selected.merge(prio, on="subkhg_id", how="left")
    else:
        selected = selected.assign(priority_rank=np.nan, deficit_mm=np.nan, design_period_days=np.nan)
    if not has_rank:                                   # equal distribution of priority among the selected sub-KHGs
        selected = selected.assign(priority_rank=1.0)
    selected = selected.assign(priority_weight=1.0 / len(selected) if not has_rank else np.nan)
    val["priority_source"] = "table" if has_rank else "equal"
    have_deficit = bool(selected[["deficit_mm", "design_period_days"]].notna().all().all())
    val["demand_source"] = "deficit_table" if have_deficit else "specific_yield"
    ctx.write_layer("subkhg_selected", selected, "1")
    area = selected.geometry.union_all()
    extent = area.buffer(cfg.run.clip_margin_m)
    val["selected_subkhg"] = ids

    def clip(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
        if gdf.geom_type.isin(["Polygon", "MultiPolygon"]).any():
            gdf["geometry"] = make_valid(gdf.geometry.values)
        out = gpd.clip(gdf, extent)
        return out[~out.geometry.is_empty].reset_index(drop=True)

    # canals
    canals = read_vector(cfg, cfg.inputs.canals.path, "canals", ctx, cfg.inputs.canals.layer, cfg.inputs.canals.columns)
    if "canal_class" not in canals:
        raise InputError("canals: needs a 'canal_class' column (primer/sekunder/tersier)")
    for c in ("depth_m", "width_m"):
        canals[c] = pd.to_numeric(canals[c], errors="coerce") if c in canals else np.nan
    _require_features(ctx, "canals", canals, extent)
    ctx.write_layer("inputs_clipped_canals", clip(canals), "1")

    # canal edits: reproducible manual fixes applied in Stage 2
    if cfg.inputs.canal_edits is not None:
        ed = read_vector(cfg, cfg.inputs.canal_edits.path, "canal_edits", ctx, cfg.inputs.canal_edits.layer)
        if "action" not in ed:
            raise InputError("canal_edits: needs an 'action' column with values add or delete")
        ed["action"] = ed["action"].astype(str).str.strip().str.lower()
        bad = sorted(set(ed["action"]) - {"add", "delete"})
        if bad:
            raise InputError(f"canal_edits: unknown action value(s) {bad}; use add or delete")
        if not ed.geom_type.isin(["LineString", "MultiLineString"]).all():
            raise InputError("canal_edits: all features must be lines")
        for c in ("depth_m", "width_m"):
            ed[c] = pd.to_numeric(ed[c], errors="coerce") if c in ed else np.nan
        if "canal_class" not in ed:
            ed["canal_class"] = "edit"
        import hashlib
        val["canal_edits"] = {"features": int(len(ed)), "sha256": hashlib.sha256(
            "|".join(sorted(f"{a}:{g.wkb_hex}" for a, g in zip(ed["action"], ed.geometry))).encode()).hexdigest()}
        ctx.write_layer("inputs_clipped_canal_edits", clip(ed), "1")

    # sekat (may be empty / absent)
    if cfg.inputs.sekat_existing is not None:
        sk = read_vector(cfg, cfg.inputs.sekat_existing.path, "sekat_existing", ctx, cfg.inputs.sekat_existing.layer, cfg.inputs.sekat_existing.columns)
        if len(sk):
            if "sekat_id" not in sk:
                raise InputError("sekat_existing: needs a 'sekat_id' column")
            sk["has_gate"] = _to_bool(sk["has_gate"]) if "has_gate" in sk else False
            sk["crest_elev_m"] = pd.to_numeric(sk["crest_elev_m"], errors="coerce") if "crest_elev_m" in sk else np.nan
            sk = clip(sk)
    else:
        sk = gpd.GeoDataFrame({"sekat_id": [], "has_gate": [], "crest_elev_m": []}, geometry=[], crs=cfg.run.crs)
    ctx.write_layer("inputs_clipped_sekat_existing", sk, "1")

    # rivers
    if cfg.inputs.rivers is not None:
        rv = read_vector(cfg, cfg.inputs.rivers.path, "rivers", ctx, cfg.inputs.rivers.layer, cfg.inputs.rivers.columns)
        rv["perennial"] = _to_bool(rv["perennial"]) if "perennial" in rv else False
        if "dry_season_wl_m" in rv and rv["dry_season_wl_m"].notna().any():
            rv["dry_season_wl_m"] = pd.to_numeric(rv["dry_season_wl_m"], errors="coerce")
            rd, dd = cfg.inputs.rivers.vertical_datum, cfg.run.vertical_datum
            if rd is None or dd is None:
                raise NeedsHuman("rivers.dry_season_wl_m is present but the vertical datum of the DTM (run.vertical_datum) "
                                 "or of the river levels (inputs.rivers.vertical_datum) is unknown. Stop and ask (spec section 11.1).")
            if rd != dd:
                raise NeedsHuman(f"vertical datum mismatch: DTM {dd!r} vs river water levels {rd!r}")
        else:
            rv["dry_season_wl_m"] = np.nan
        _require_features(ctx, "rivers", rv, extent)
        ctx.write_layer("inputs_clipped_rivers", clip(rv), "1")

    # burn area (optional: an empty layer keeps the later stages simple; stage 6 then gives burn_freq weight 0)
    if cfg.inputs.burn_area is not None:
        ba = read_vector(cfg, cfg.inputs.burn_area.path, "burn_area", ctx, cfg.inputs.burn_area.layer, cfg.inputs.burn_area.columns)
        col = find_col(ba, ["burn_freq", "burn_frequency"], "burn_area")
        ba["burn_freq_n"], bad = parse_burn_freq(ba[col])
        if bad:
            ctx.warn(f"burn_area: {len(bad)} unparsed burn_freq value(s): {bad[:10]}")
        val["burn_freq_unparsed"] = bad
        ctx.write_layer("inputs_clipped_burn_area", clip(ba), "1")
    else:
        ctx.warn("burn_area: no burn-scar layer; the burn_freq criterion gets weight 0 in stage 6")
        ctx.write_layer("inputs_clipped_burn_area", gpd.GeoDataFrame({"burn_freq_n": pd.Series(dtype=float)}, geometry=[], crs=ctx.crs), "1")

    # peat depth: thickness-class polygons here; a depth raster is cropped with the other rasters below
    if cfg.inputs.peat_depth is None:
        ctx.warn("peat_depth: no peat depth layer; the peat_depth criterion gets weight 0 in stage 6 and pump demand counts the whole served area")
        ctx.write_layer("inputs_clipped_peat_depth", gpd.GeoDataFrame({"peat_class": pd.Series(dtype=str), "depth_min_m": pd.Series(dtype=float),
                                                                       "depth_max_m": pd.Series(dtype=float)}, geometry=[], crs=ctx.crs), "1")
    elif not cfg.inputs.peat_depth.is_raster:
        pd_ = read_vector(cfg, cfg.inputs.peat_depth.path, "peat_depth", ctx, cfg.inputs.peat_depth.layer, cfg.inputs.peat_depth.columns)
        col = find_col(pd_, ["peat_thick", "peat_depth", "peat_class"], "peat_depth")
        parsed, bad = parse_peat_class(pd_[col])
        pd_["peat_class"] = pd_[col].astype(str)
        pd_[["depth_min_m", "depth_max_m"]] = parsed
        if bad:
            ctx.warn(f"peat_depth: {len(bad)} unparsed thickness class(es): {bad[:10]}")
        val["peat_class_unparsed"] = bad
        check_overlap(ctx, "peat_depth", _footprint(pd_), extent)
        ctx.write_layer("inputs_clipped_peat_depth", clip(pd_), "1")
    elif cfg.inputs.peat_depth.units is None:
        raise NeedsHuman("inputs.peat_depth.units must be declared for a peat depth raster: m or cm (the BRGM rasters are in cm)")

    for key, name in (("concession", "inputs_clipped_concession"), ("tma_obs", "inputs_clipped_tma_obs")):
        sec = getattr(cfg.inputs, key)
        if sec is not None:
            g = read_vector(cfg, sec.path, key, ctx, sec.layer, sec.columns)
            ctx.write_layer(name, clip(g), "1")

    # --- rasters
    if cfg.inputs.moisture.higher_is_wetter is None:
        raise NeedsHuman("inputs.moisture.higher_is_wetter must be declared (true/false)")
    clip_dir = ctx.work / "inputs_clipped"
    bounds = extent.bounds
    check_overlap(ctx, "dtm", box(*dtm_bounds), extent)
    if dtm_res[0] != dtm_res[1]:
        ctx.warn(f"dtm has non-square cells {dtm_res}")
    val["dtm_resolution_m"] = float(dtm_res[0])
    ctx.report["inputs"] = {
        "dtm": str(crop_rasters(cfg, [dtm_cfg.path], "dtm", bounds, clip_dir / "dtm.tif", Resampling.bilinear, ctx)),
        "moisture": str(crop_rasters(cfg, cfg.inputs.moisture.paths, "moisture", bounds, clip_dir / "moisture.tif", Resampling.bilinear, ctx)),
    }
    if cfg.inputs.peat_depth is not None and cfg.inputs.peat_depth.is_raster:
        ctx.report["inputs"]["peat_depth"] = str(peat_depth_raster(cfg, ctx, bounds, extent, clip_dir, val, clip))
    _note_cloud_inputs(cfg, ctx)
    ctx.set_counts("1", subkhg_selected=len(ids), canals=int(len(ctx.read_layer("inputs_clipped_canals"))))
