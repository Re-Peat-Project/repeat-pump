"""Write a pump run config for one or more RE-PEAT KHG work folders, the same one the wizard's KHG picker builds.

    python scripts/khg_run_config.py ../_khg/16.02.01_sugihan_lumpur ../_khg/14.02-04-05.01_kampar_gaung
    python scripts/khg_run_config.py --all ../_khg            # every KHG folder that has the inputs
    repeat-pump run --config ../_khg/<folder>/05_pump/run_config.yaml --accept 2 --accept 6 --accept 9

Each config goes to ``<folder>/05_pump/run_config.yaml`` with the proposed-defaults preset next to it (values marked as proposed in
the report). Columns are guessed by name and canal class values by text or code, as in the wizard. Pumps are planned only when the
river layer has a dry-season level or a perennial column. An existing run_config.yaml is kept unless --overwrite is given.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pyogrio

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "qgis_plugin"))
from repeat_pump_qgis import khgsetup, runconfig  # noqa: E402
from repeat_pump_qgis.wizard import preflight as pf  # noqa: E402

TEMPLATE = ROOT / "configs" / "example_khg.yaml"
PRESET = ROOT / "configs" / "proposed_defaults.yaml"


def fields(path: str, layer=None) -> list[str]:
    return list(pyogrio.read_info(path, layer=layer)["fields"])


def run_config(folder: Path, tertiary: bool = False) -> tuple[dict, list[str]]:
    setup, missing = khgsetup.setup_from_khg(folder)
    inp = setup["inputs"]
    if {"dtm", "moisture", "subkhg", "canals"} - set(inp):
        raise SystemExit(f"{folder.name}: required inputs not found: {', '.join(sorted({'dtm', 'moisture', 'subkhg', 'canals'} - set(inp)))}")
    vectors = {k: (v["path"], None) for k, v in inp.items() if k in ("subkhg", "canals", "sekat_existing", "rivers", "burn_area", "subkhg_indicators")}
    if "peat_depth" in inp:
        vectors["peat_depth"] = (inp["peat_depth"]["path"], None)
    columns, params = {}, {"inputs.dtm.source": inp["dtm"]["source"], "run.name": setup["run"]["name"], "run.auto_reproject": True,
                           "inputs.moisture.higher_is_wetter": True, "run.subkhg_selection.mode": "top_n", "run.subkhg_selection.n": 3,
                           "topology.canal_classes": ["primer", "sekunder", "tersier"] if tertiary else ["primer", "sekunder"]}
    if (setup.get("optimise") or {}).get("et_mm_day") is not None:     # MOD16 June-September of this KHG (khgsetup.dry_season_et)
        params["optimise.et_mm_day"] = setup["optimise"]["et_mm_day"]
    if inp.get("peat_depth", {}).get("units"):
        params["inputs.peat_depth.units"] = inp["peat_depth"]["units"]
    for role, (path, _l) in vectors.items():
        if Path(path).suffix.lower() in (".gpkg", ".shp"):
            f = fields(path)
            for col, req in pf.missing_columns(role, f):
                g = pf.guess_column(role, col, f) if req else ""
                if g:
                    columns.setdefault(role, {})[col] = g
    cls_col = columns.get("canals", {}).get("canal_class") or pf.find_field("canals", "canal_class", fields(inp["canals"]["path"]))
    if cls_col:
        vals = pyogrio.read_dataframe(inp["canals"]["path"], columns=[cls_col], read_geometry=False)[cls_col].dropna().astype(str).unique()
        cmap = {v: pf.guess_canal_class(v) for v in vals if pf.guess_canal_class(v) and v.strip().lower() != pf.guess_canal_class(v)}
        if cmap:
            params["topology.canal_class_map"] = cmap
    rv = inp.get("rivers", {}).get("path")
    params["pumping.enabled"] = bool(rv and (pf.find_field("rivers", "dry_season_wl_m", fields(rv)) or pf.find_field("rivers", "perennial", fields(rv))))
    # the CRS of the run is the DTM's (UTM); the engine reprojects the rest
    import rasterio
    with rasterio.open(inp["dtm"]["path"]) as d:
        params["run.crs"] = d.crs.to_string()
    drop = [k for k in ("subkhg_priority", "sekat_existing", "rivers", "burn_area", "peat_depth", "canal_edits") if k not in inp and k not in vectors]
    data = runconfig.build_run_config(TEMPLATE, output_gpkg=setup["run"]["output_gpkg"], dtm=inp["dtm"]["path"],
                                      moisture=inp["moisture"]["paths"], priority=inp.get("subkhg_priority", {}).get("path"),
                                      vectors=vectors, params=params, drop=drop + ["canal_edits"], columns=columns)
    data["inputs"]["dtm"]["vertical_rmse_m"] = None          # the preset suggests it for the DTM type; a delivery value wins
    data["inputs"]["moisture"]["higher_is_wetter"] = True
    if "neraca_map" in inp:                               # for the HTML report
        data["inputs"]["neraca_map"] = {"path": inp["neraca_map"]["path"]}
    return data, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="*")
    ap.add_argument("--all", metavar="KHG_ROOT")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--tertiary", action="store_true", help="include tertiary canals (off by default, as in the KLH guide)")
    a = ap.parse_args()
    folders = [Path(f) for f in a.folders] + (khgsetup.khg_folders(a.all) if a.all else [])
    for f in folders:
        out = f.resolve() / "05_pump" / "run_config.yaml"
        if out.exists() and not a.overwrite:
            print(f"{f.name}: kept the existing {out}")
            continue
        try:
            data, missing = run_config(f.resolve(), a.tertiary)
        except SystemExit as e:
            print(e)
            continue
        runconfig.attach_preset(data, out.parent, PRESET)
        runconfig.write_run_config(data, out)
        print(f"{f.name}: wrote {out}" + (f" (not found: {', '.join(missing)})" if missing else ""))


if __name__ == "__main__":
    main()
