"""Interactive HTML report of a finished run: one self-contained page (D3 and MapLibre vendored; the basemap needs internet).

    repeat-pump report-html --config run_config.yaml [--out report.html]

Everything on the page is read from the run's files: the GeoPackage layers, ``run_report.json``, ``interventions.csv`` and, when the
run names it (``inputs.neraca_map``), repeat-neraca's ``neraca_map.gpkg``. Nothing is recomputed. Geometry is reprojected to
EPSG:4326, rounded to 5 decimals (about 1 m) and the sub-KHG polygons simplified by ``SIMPLIFY_M`` for display only.
"""
from __future__ import annotations

import datetime
import json
from importlib import resources
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import shapely

from .config import load_config, resolve

SIMPLIFY_M = 15.0
ASSETS = "report_assets"
TEMPLATE_VERSION = 1


def _asset(name: str) -> str:
    return resources.files("repeat_pump.data").joinpath(ASSETS, name).read_text(encoding="utf8")


def _layers(gpkg: Path) -> set:
    return {l[0] for l in pyogrio.list_layers(gpkg)} if gpkg.exists() else set()


def _geojson(gdf, props: list[str], simplify: float = 0.0) -> dict:
    """FeatureCollection in EPSG:4326 with the listed properties (missing ones skipped, NaN as null)."""
    if gdf is None or not len(gdf):
        return {"type": "FeatureCollection", "features": []}
    g = gdf.copy()
    if simplify:
        g["geometry"] = g.geometry.simplify(simplify, preserve_topology=True)
    g = g.to_crs(4326)
    g["geometry"] = shapely.set_precision(g.geometry.values, 1e-5)
    cols = [c for c in props if c in g.columns]
    feats = []
    for row, geom in zip(g[cols].itertuples(index=False), g.geometry):
        if geom is None or geom.is_empty:
            continue
        p = {}
        for c, v in zip(cols, row):
            if isinstance(v, (np.floating, float)):
                p[c] = None if not np.isfinite(v) else round(float(v), 4)
            elif isinstance(v, (np.integer,)):
                p[c] = int(v)
            elif isinstance(v, (np.bool_, bool)):
                p[c] = bool(v)
            else:
                p[c] = None if v is None or (isinstance(v, float) and v != v) else str(v)
        feats.append({"type": "Feature", "properties": p, "geometry": shapely.geometry.mapping(geom)})
    return {"type": "FeatureCollection", "features": feats}


def _read(gpkg: Path, layer: str, have: set):
    return pyogrio.read_dataframe(gpkg, layer=layer) if layer in have else None


def tmat_class(depth_cm) -> str:
    """KLH water-table classes (TMAT = -depth): tergenang > 0 m, normal -0.4 to 0, rawan -0.8 to -0.4, sangat rawan < -0.8."""
    if depth_cm is None or not np.isfinite(depth_cm):
        return ""
    return "flooded" if depth_cm < 0 else "normal" if depth_cm <= 40 else "at_risk" if depth_cm <= 80 else "high_risk"


def collect(config_path: str | Path) -> dict:
    """All the numbers and shapes the page shows, read from the run's outputs."""
    cfg = load_config(config_path)
    gpkg = resolve(cfg, cfg.run.output_gpkg)
    out_dir = gpkg.parent
    rep = json.loads((out_dir / "run_report.json").read_text(encoding="utf8"))
    have = _layers(gpkg)
    counts = rep.get("counts", {})
    c7 = counts.get("7", {})

    # sub-KHG polygons: every unit when the interventions ran, else the selected ones
    units = _read(gpkg, "interventions", have)
    sel = _read(gpkg, "subkhg_selected", have)
    selected = [str(x) for x in sel["subkhg_id"]] if sel is not None else []
    if units is None and sel is not None:
        units = sel[["subkhg_id", "geometry"]].copy()
    neraca = {"units": {}, "stations": None, "order_ok": None, "khg_deficit_mm": None, "window": None, "et_source": None}
    if cfg.inputs.neraca_map is not None:
        nm = resolve(cfg, cfg.inputs.neraca_map.path)
        nh = _layers(nm)
        if "neraca_units" in nh:
            nu = pyogrio.read_dataframe(nm, layer="neraca_units", read_geometry=False)
            mcols = [f"wb_m{m:02d}" for m in range(1, 13)]
            for r in nu.itertuples(index=False):
                d = r._asdict()
                neraca["units"][str(d["unit_id"])] = {"clim": [None if pd.isna(d.get(c)) else round(float(d[c]), 1) for c in mcols],
                                                       "wb_dry": None if pd.isna(d.get("wb_dry_mm")) else round(float(d["wb_dry_mm"]), 1),
                                                       "wb_mean": None if pd.isna(d.get("u_wb_mean")) else round(float(d["u_wb_mean"]), 1),
                                                       "deficit_months": None if pd.isna(d.get("u_deficit_months")) else round(float(d["u_deficit_months"]), 2)}
            ok = nu["order_ok"].dropna() if "order_ok" in nu else pd.Series(dtype=float)
            neraca["order_ok"] = int(ok.iloc[0]) if len(ok) else None
            if "khg_deficit_mm" in nu and nu["khg_deficit_mm"].notna().any():
                neraca["khg_deficit_mm"] = round(float(nu["khg_deficit_mm"].dropna().iloc[0]), 1)
                neraca["window"] = str(nu["khg_deficit_window"].dropna().iloc[0]) if "khg_deficit_window" in nu else None
            neraca["et_source"] = str(nu["et_source"].dropna().iloc[0]) if "et_source" in nu and nu["et_source"].notna().any() else None
        if "neraca_stations" in nh:
            st = pyogrio.read_dataframe(nm, layer="neraca_stations")
            st["tmat_class"] = [tmat_class(v) for v in st["depth_end_cm"]]
            neraca["stations"] = _geojson(st, ["station_id", "unit_id", "depth_start_cm", "depth_end_cm", "change_cm", "depth_max_cm",
                                               "share_deeper_40cm", "n_days", "first_date", "last_date", "tmat_class"])
    if units is not None:
        units = units.copy()
        units["selected"] = units["subkhg_id"].astype(str).isin(selected)
        units["wb_dry"] = [neraca["units"].get(str(u), {}).get("wb_dry") for u in units["subkhg_id"]]
    unit_props = ["subkhg_id", "selected", "intervention", "intervention_label", "intervention_otherwise", "reasons", "sekat_new", "held_m3",
                  "deficit_m3", "held_share", "area_km2", "f_reach", "u_ndmi", "burned_ever_frac", "f_water_dist", "i_protected",
                  "u_canal_density", "u_ipg_gap", "i_forest", "wb_dry"]

    kept = _read(gpkg, "sekat_proposed", have)
    low = _read(gpkg, "sekat_low_benefit", have)
    sekat_props = ["sekat_pro_id", "canal_id", "benefit_rank", "gain_m2", "cum_share", "js_m", "z_land_m", "i_lahan_pct", "sekat_type"]
    curve = []
    if kept is not None and "benefit_rank" in kept:
        allb = pd.concat([kept.assign(kept=True), (low.assign(kept=False) if low is not None else None)], ignore_index=True) \
            .sort_values("benefit_rank")
        curve = [{"n": int(r), "cum": round(float(c), 4), "gain": round(float(g), 1), "kept": bool(k)}
                 for r, c, g, k in zip(allb["benefit_rank"], allb["cum_share"], allb["gain_m2"], allb["kept"])]
    ex = _read(gpkg, "sekat_existing_assessed", have)
    canals = _read(gpkg, "canals_clean", have)

    iv = rep.get("interventions") or {}
    bal = rep.get("sekat_balance") or {}
    held = float(np.nansum(units["held_m3"])) if units is not None and "held_m3" in units else None
    deficit_sel = float(np.nansum(units.loc[units["selected"], "deficit_m3"])) if units is not None and "deficit_m3" in units else None
    data = {
        "meta": {"run": cfg.run.name, "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "config": str(Path(config_path).name),
                 "template_version": TEMPLATE_VERSION, "crs": cfg.run.crs, "preset_values": len(cfg.preset["keys"]),
                 "canal_classes": cfg.topology.canal_classes, "pumping": cfg.pumping.enabled, "warnings": len(rep.get("warnings", []))},
        "tiles": {"head_rule": c7.get("head_rule", c7.get("proposed")), "kept": c7.get("proposed"), "low_benefit": c7.get("low_benefit"),
                  "existing": c7.get("existing"), "unsnapped": c7.get("unsnapped"), "target_share": bal.get("target_rise_share"),
                  "share_kept": bal.get("share_kept"), "held_m3": held, "deficit_m3_selected": deficit_sel,
                  "selected": selected, "units": int(len(units)) if units is not None else 0},
        "interventions": {"counts": iv.get("counts", {}), "closed_otherwise": iv.get("closed_otherwise", {}), "thresholds": iv.get("thresholds", {})},
        "curve": curve,
        "neraca": {k: v for k, v in neraca.items() if k != "stations"},
        "geo": {"units": _geojson(units, unit_props, SIMPLIFY_M),
                "canals": _geojson(canals, ["canal_id", "canal_class", "direction", "direction_method", "length_m", "n_req", "n_existing", "ipg"]),
                "kept": _geojson(kept, sekat_props), "low": _geojson(low, sekat_props),
                "existing": _geojson(ex, ["sekat_id", "snapped", "snap_dist_m"]),
                "stations": neraca["stations"] or {"type": "FeatureCollection", "features": []}},
        "files": {"gpkg": gpkg.name, "report": "run_report.md", "interventions": "interventions.csv" if (out_dir / "interventions.csv").exists() else None},
    }
    return data


def build(config_path: str | Path, out: str | Path | None = None) -> Path:
    data = collect(config_path)
    cfg = load_config(config_path)
    out = Path(out) if out else resolve(cfg, cfg.run.output_gpkg).parent / "report.html"
    data["style"] = json.loads(_asset("basemap-positron.json"))
    safe = lambda o: json.dumps(o, separators=(",", ":"), default=str).replace("</", "<\\/")   # noqa: E731
    html = (_asset("report.html")
            .replace("/*MLCSS*/", _asset("maplibre-gl.v5.24.0.css"))
            .replace("/*CSS*/", _asset("report.css"))
            .replace("/*D3*/", _asset("d3.v7.9.0.min.js"))
            .replace("/*ML*/", _asset("maplibre-gl.v5.24.0.js"))
            .replace("/*JS*/", _asset("report.js"))
            .replace("/*DATA*/", safe(data))
            .replace("{{TITLE}}", f"RE-PEAT · {cfg.run.name}"))
    out.write_text(html, encoding="utf8")
    return out
