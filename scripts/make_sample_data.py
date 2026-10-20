"""Build the practice dataset in docs/sample_data (a tiny synthetic peat landscape, NOT real data).

    python scripts/make_sample_data.py

It reuses the synthetic world the tests use: a plane rising eastwards from a river, two canals, two sub-KHGs. Every number in the
practice config is a dummy value so trainees can finish a run. Real decisions come from your team, never from this file.
"""
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import rasterio
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.fixtures.synthetic import build_world  # noqa: E402

OUT = ROOT / "docs" / "sample_data"
DUMMY_DATUM = "DUMMY-DATUM"

# (file written by the fixture, name in the practice data)
VECTORS = {"canals.gpkg": "canals", "sekat.gpkg": "sekat_existing", "rivers.gpkg": "rivers", "burn.gpkg": "burn_area",
           "peat.gpkg": "peat_depth", "subkhg.gpkg": "subkhg"}

README = """# Practice data

A tiny synthetic landscape for learning the RE-PEAT wizard. It is **not real data** and every value in
`practice_run/run_config.yaml` is a dummy number. Do not reuse them for a real KHG: your team decides those.

- `data/`: the input layers (EPSG:32749). One river on the west edge, two canals, two sub-KHGs, two existing sekat.
- `practice_template.yaml`: a starting config with every decision left empty. Use it as the *Starting config* when you
  create a run, then type the dummy values from the guide.
- `practice_run/run_config.yaml`: the same run with all dummy decisions filled in. In the wizard choose
  *Open an existing run* and pick this file to skip the typing.

Rebuild everything with `python scripts/make_sample_data.py`.
"""


def main() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    data = OUT / "data"
    data.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        _, cfg = build_world(tmp)
        for old, new in VECTORS.items():
            gdf = gpd.read_file(tmp / old)
            gdf.to_file(data / f"{new}.gpkg", layer=new, driver="GPKG")
        for old, new in (("dtm.tif", "dtm.tif"), ("moisture.tif", "moisture.tif")):
            with rasterio.open(tmp / old) as src:
                prof = src.profile.copy()
                prof.update(compress="deflate", predictor=3, tiled=False)
                with rasterio.open(data / new, "w", **prof) as dst:
                    dst.write(src.read(1), 1)
        shutil.copy(tmp / "prio.csv", data / "subkhg_priority.csv")

    # starting config: the bundled example with every decision empty, pointing at the practice data
    tpl = yaml.safe_load((ROOT / "configs" / "example_khg.yaml").read_text(encoding="utf8"))
    tpl["run"].update(name="practice_run", output_gpkg="out/practice.gpkg", subkhg_selection={"mode": "top_n", "n": 1})
    inp = tpl["inputs"]
    inp["dtm"]["path"] = "data/dtm.tif"
    inp["moisture"]["paths"] = ["data/moisture.tif"]
    for key, file in (("subkhg", "subkhg"), ("canals", "canals"), ("sekat_existing", "sekat_existing"), ("rivers", "rivers"),
                      ("burn_area", "burn_area"), ("peat_depth", "peat_depth")):
        inp[key]["path"] = f"data/{file}.gpkg"
    inp["subkhg_priority"]["path"] = "data/subkhg_priority.csv"
    inp.pop("canal_edits", None)
    # the dummy sekat have no gates; without this, the proposed sekat would block the pumped water in the practice run
    tpl["pumping"]["allow_gate_addition"] = True
    header = ("# Practice starting config. Every `null` is a decision the wizard asks you for. Dummy data only.\n")
    (OUT / "practice_template.yaml").write_text(header + yaml.safe_dump(tpl, sort_keys=False), encoding="utf8")

    # the ready-made run: the same config with the dummy decisions filled in (paths relative to the run folder)
    run = yaml.safe_load(yaml.safe_dump(tpl))
    run["run"].update(clip_margin_m=100, vertical_datum=DUMMY_DATUM, output_gpkg="out/practice.gpkg")
    for sec in ("dtm", "subkhg", "subkhg_priority", "canals", "sekat_existing", "rivers", "burn_area", "peat_depth"):
        run["inputs"][sec]["path"] = "../" + run["inputs"][sec]["path"]
    run["inputs"]["moisture"]["paths"] = ["../" + p for p in run["inputs"]["moisture"]["paths"]]
    run["inputs"]["dtm"]["vertical_rmse_m"] = 0.1
    run["inputs"]["moisture"]["higher_is_wetter"] = True
    run["inputs"]["rivers"]["vertical_datum"] = DUMMY_DATUM
    run["topology"]["snap_tolerance_m"] = 2.0
    run["hydro"]["breach_max_dist_cells"] = 20
    for k in run["prioritise"]["criteria"]:
        run["prioritise"]["criteria"][k]["weight"] = 0.25
    run["prioritise"].update(upstream_buffer_m=15)
    run["prioritise"]["feasibility"]["concession_mode"] = "ignore"
    run["sekat"].update(max_spacing_m=1000, snap_tolerance_m=10, min_spacing_m=50)
    run["pumping"].update(conveyance="canal", manning_n=0.035, pump_efficiency=0.6, max_head_per_station_m=1.0,
                          pump_capacity_m3s=0.5, uphill_penalty_lambda=10, influence_distance_m=200, allow_gate_addition=True)
    (OUT / "practice_run").mkdir()
    (OUT / "practice_run" / "run_config.yaml").write_text("# Practice run, dummy values only.\n" + yaml.safe_dump(run, sort_keys=False), encoding="utf8")
    (OUT / "README.md").write_text(README, encoding="utf8")
    # one download for trainees: the folder as a zip (docs/practice_data.zip is linked from docs/wizard.html)
    zpath = OUT.parent / "practice_data.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(OUT.rglob("*")):
            if f.is_file() and "out" not in f.relative_to(OUT).parts:
                z.write(f, Path("practice_data") / f.relative_to(OUT))
    print("sample data written to", OUT, "and", zpath.name, f"({zpath.stat().st_size // 1024} KB)")
    for f in sorted(OUT.rglob("*")):
        if f.is_file():
            print(f"  {f.relative_to(OUT)}  {f.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
