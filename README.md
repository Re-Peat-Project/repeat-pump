# repeat-pump: rewetting with pompanisasi

RE-PEAT (World Bank, KLH), GIS workstream, Departemen Teknik Geodesi UGM.

Given a bare-earth DTM, canals and peat/burn data, this module prioritises canal segments inside priority sub-KHGs, places canal blocks (sekat) by hydraulic head, finds water sources and routes pumped water to the highest pools, then sizes pump stations. The operator guide for the manual QGIS workflow is in `docs/`. A beginner-friendly guide to this tool (steps, input data, outputs per stage, diagrams) is [docs/user_guide.html](docs/user_guide.html), a one-slide overview diagram is in `docs/diagrams/` (`workflow_slide.svg` and `.png`), and three technical slides in Bahasa Indonesia (`algoritma_1_alur_data`, `algoritma_2_sekat_skoring`, `algoritma_3_routing_pompa`, each `.svg` and `.png`) show the analyses and data flow. Regenerate the SVGs with `python scripts/make_algorithm_slides.py`.

Layout: the engine is a QGIS-free Python package (`repeat_pump/core`), run from a command line, and a thin QGIS plugin (`qgis_plugin/repeat_pump_qgis`) that starts that command in a separate Python environment.

## 1. Install the engine

Requires Python 3.11 or newer.

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m repeat_pump.cli --version
```

The first run of Stage 3 downloads the WhiteboxTools binary, so it needs internet once.

## 2. Prepare a config

Copy [configs/example_khg.yaml](configs/example_khg.yaml) and fill in your paths. **Every `null` is a policy decision a human must make** (vertical RMSE, weights, pump specs, snap tolerances, and so on; see section 11 of the spec). The module never guesses these: each stage stops with one message listing the keys it still needs.

Inputs (all in the same projected CRS in metres, or set `run.auto_reproject: true`):

| Input | Notes |
|---|---|
| `dtm` | Bare-earth DTM. `surface_type: DSM` is refused. |
| `subkhg`, `subkhg_priority` | Polygons with `subkhg_id`; CSV with `subkhg_id, priority_rank, deficit_mm, design_period_days`. |
| `canals` | Lines with `canal_class`, optional `depth_m`, `width_m`. |
| `canal_edits` (optional) | Lines with `action` = `add` or `delete`: reproducible manual topology fixes. |
| `sekat_existing` (optional) | Points with `sekat_id`, `has_gate`. |
| `rivers` (optional) | Optional `perennial`, `dry_season_wl_m` (then both datums must be declared). |
| `burn_area`, `peat_depth` | Text attributes such as `2x` and `3,0 - 4,0 meter` are parsed. |
| `moisture` | Raster(s); declare `higher_is_wetter`. |

## 3. Run from the command line

```powershell
.venv\Scripts\python -m repeat_pump.cli run --config my_khg.yaml
```

Options: `--stop-after N`, `--resume-from N`, `--accept N` (repeatable).

Stages 2 (topology), 6 (prioritisation) and 9 (routing) are **review stops**. The run ends with exit code 2 after each; inspect the QA layers in the output GeoPackage, then continue with the stage accepted:

```powershell
... run --config my_khg.yaml --accept 2
... run --config my_khg.yaml --accept 2 --accept 6 --accept 9
```

Exit codes: 0 finished, 1 error (including missing parameters), 2 waiting for review.

Outputs go to the GeoPackage named in `run.output_gpkg`, with `run_report.md` and `run_report.json` beside it. Rasters (`dtm_conditioned.tif`, `flow_acc.tif`) and stage logs are in the `<name>_work` folder. Re-running resumes from `run_state.json`.

## 4. Use it from QGIS

The plugin never imports the engine: it writes a run config and starts the command above in the environment from step 1.

1. Install the plugin: `python scripts/install_plugin.py` (QGIS 4 default profile), or `--profile-dir <profile>`, or `--zip` and use *Plugins > Install from ZIP* with `dist/repeat_pump_qgis.zip`.
2. Enable **RE-PEAT Pompanisasi** in the Plugin Manager.
3. Run any of its Processing algorithms. The first run builds a private Python environment in the QGIS profile and installs the engine bundled in the plugin (needs internet once, a few minutes, and a system Python 3.11+ with pip). *Set up engine environment* in the Processing Toolbox does the same on demand. You do not need to do step 1 of "Install the engine" for QGIS use.
4. Processing Toolbox > **RE-PEAT Pompanisasi** > *Run full pipeline* (or a stage group). Choose the YAML config, then the layers; layers must be saved files, not temporary layers. At a review stop the algorithm ends with a warning: inspect the QA layers, tick the stage under *Review stages to accept*, run again.

Advanced: to use your own interpreter instead, set `REPEAT_PUMP_PYTHON` or use *Plugins > RE-PEAT Pompanisasi > Set Python environment (advanced)*.

More detail: [docs/qgis_plugin.md](docs/qgis_plugin.md). Tested headless with QGIS 4.2.2 (OSGeo4W) via `qgis_process`: the full pipeline and a review stop followed by `--accept` both ran. The dialog (GUI) itself has not been exercised yet. Headless example:

```powershell
& "$env:LOCALAPPDATA\Programs\OSGeo4Win\qgis_process-qgis.bat" plugins enable repeat_pump_qgis
& "$env:LOCALAPPDATA\Programs\OSGeo4Win\qgis_process-qgis.bat" run repeat_pump:run_full_pipeline -- CONFIG=cfg.yaml DTM=dtm.tif ... ACCEPT=0,1,2
```

## 5. Tests

```powershell
.venv\Scripts\python -m pytest -q
```

Test fixtures are built in code. One test (the pilot regression against the legacy routes) is skipped until a pilot sub-KHG fixture exists.

## Known limits

- Stage 3 (WhiteboxTools) loads the whole DTM into memory; there is no tiled processing yet (`run.memory_budget_gb` guards it).
- `legacy/` holds the original console scripts for reference and is read-only.
- References for every algorithm are in [docs/references.md](docs/references.md).
