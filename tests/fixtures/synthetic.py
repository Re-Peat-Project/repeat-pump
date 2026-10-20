"""Synthetic test world built in code (no checked-in binaries).

Geometry (EPSG:32749, metres, origin X0,Y0): a tilted plane rising eastwards at
SLOPE m/m from a river on the west edge. Canal C1 runs west->east (digitised
*upstream*) at y=Y0+500; canal C2 branches north at x=X0+900 across flat ground.
The values below are TEST FIXTURE values, not policy values.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import yaml
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, box

X0, Y0 = 300000.0, 9700000.0
SLOPE = 0.001
RES = 5.0
CRS = "EPSG:32749"


def dtm_array(width_m=3100, height_m=1000, canals=(), depth=2.0, half_width=2.0, x_start=X0 - 100):
    nx, ny = int(width_m / RES), int(height_m / RES)
    xs = x_start + (np.arange(nx) + 0.5) * RES
    z = np.tile(2.0 + SLOPE * (xs - X0), (ny, 1)).astype("float32")
    tr = from_origin(x_start, Y0 + height_m, RES, RES)
    for line in canals:
        from rasterio.features import rasterize
        m = rasterize([(line.buffer(half_width), 1)], out_shape=(ny, nx), transform=tr, fill=0).astype(bool)
        z[m] -= depth
    return z, tr


def write_tif(path: Path, arr, tr, crs=CRS):
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype="float32",
                       crs=crs, transform=tr, nodata=-9999.0) as d:
        d.write(arr, 1)


def build_world(tmp: Path, dtm_crs=CRS) -> tuple[Path, dict]:
    tmp.mkdir(parents=True, exist_ok=True)
    c1 = LineString([(X0, Y0 + 500), (X0 + 1800, Y0 + 500)])
    c2 = LineString([(X0 + 900, Y0 + 500), (X0 + 900, Y0 + 900)])
    canals = gpd.GeoDataFrame({"canal_class": ["primer", "sekunder"], "depth_m": [2.0, 2.0], "width_m": [4.0, 4.0]},
                              geometry=[c1, c2], crs=CRS)
    canals.to_file(tmp / "canals.gpkg", driver="GPKG")
    z, tr = dtm_array(canals=[c1, c2])
    write_tif(tmp / "dtm.tif", z, tr, dtm_crs)
    m = np.tile(2.0 - 2.0 * (np.arange(z.shape[1]) * RES - 100) / 2000.0, (z.shape[0], 1)).astype("float32")
    write_tif(tmp / "moisture.tif", m, tr)
    gpd.GeoDataFrame({"subkhg_id": ["A", "B"]}, geometry=[box(X0, Y0, X0 + 2000, Y0 + 1000), box(X0 + 2500, Y0, X0 + 3000, Y0 + 1000)],
                     crs=CRS).to_file(tmp / "subkhg.gpkg", driver="GPKG")
    pd.DataFrame({"subkhg_id": ["A", "B"], "priority_rank": [1, 2], "deficit_mm": [200.0, 100.0],
                  "design_period_days": [90, 90]}).to_csv(tmp / "prio.csv", index=False)
    gpd.GeoDataFrame({"sekat_id": ["E1", "E2"], "has_gate": [False, True]},
                     geometry=[Point(X0 + 300, Y0 + 503), Point(X0 + 1000, Y0 + 497)], crs=CRS).to_file(tmp / "sekat.gpkg", driver="GPKG")
    gpd.GeoDataFrame({"perennial": [True], "dry_season_wl_m": [2.0]}, geometry=[box(X0 - 50, Y0, X0 + 20, Y0 + 1000)],
                     crs=CRS).to_file(tmp / "rivers.gpkg", driver="GPKG")
    gpd.GeoDataFrame({"BURN_FREQ": ["2x"]}, geometry=[box(X0 + 1000, Y0, X0 + 2000, Y0 + 1000)], crs=CRS).to_file(tmp / "burn.gpkg", driver="GPKG")
    gpd.GeoDataFrame({"PEAT_THICK": ["1,0 - 1,5 meter", "3,0 - 4,0 meter"]},
                     geometry=[box(X0, Y0, X0 + 1200, Y0 + 1000), box(X0 + 1200, Y0, X0 + 2000, Y0 + 1000)], crs=CRS).to_file(tmp / "peat.gpkg", driver="GPKG")
    cfg = {
        "run": {"name": "synthetic", "output_gpkg": str(tmp / "out" / "run.gpkg"), "crs": CRS, "auto_reproject": False,
                "vertical_datum": "TESTDATUM", "memory_budget_gb": 4, "subkhg_selection": {"mode": "top_n", "n": 1},
                "clip_margin_m": 100},
        "inputs": {"dtm": {"path": str(tmp / "dtm.tif"), "surface_type": "DTM", "vertical_rmse_m": 0.1},
                   "subkhg": {"path": str(tmp / "subkhg.gpkg")}, "subkhg_priority": {"path": str(tmp / "prio.csv")},
                   "canals": {"path": str(tmp / "canals.gpkg")}, "sekat_existing": {"path": str(tmp / "sekat.gpkg")},
                   "rivers": {"path": str(tmp / "rivers.gpkg"), "vertical_datum": "TESTDATUM"},
                   "burn_area": {"path": str(tmp / "burn.gpkg")}, "peat_depth": {"path": str(tmp / "peat.gpkg")},
                   "moisture": {"paths": [str(tmp / "moisture.tif")], "higher_is_wetter": True}},
        "topology": {"snap_tolerance_m": 2.0},
        "hydro": {"breach_max_dist_cells": 20},
        "sekat": {"max_spacing_m": 1000, "snap_tolerance_m": 10, "min_spacing_m": 50},
        "prioritise": {"criteria": {k: {"weight": 0.25, "direction": "higher_is_worse"} for k in ("burn_freq", "peat_depth", "dryness", "upstream_contrib")},
                       "feasibility": {"concession_mode": "ignore"}, "top_fraction": 0.3, "upstream_buffer_m": 15},
        "pumping": {"conveyance": "canal", "manning_n": 0.035, "pump_efficiency": 0.6, "max_head_per_station_m": 1.0,
                    "pump_capacity_m3s": 0.5, "uphill_penalty_lambda": 10, "influence_distance_m": 200},
    }
    return tmp / "cfg.yaml", cfg


def write_cfg(path: Path, cfg: dict) -> Path:
    path.write_text(yaml.safe_dump(cfg))
    return path
