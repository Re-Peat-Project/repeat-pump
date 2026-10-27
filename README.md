# repeat-pump: rewetting with pompanisasi

RE-PEAT (World Bank, KLH), GIS workstream, Departemen Teknik Geodesi UGM.

Given a bare-earth DTM, canals and peat/burn data, this module prioritises canal segments inside priority sub-KHGs, places canal blocks (sekat) by hydraulic head, finds water sources and routes pumped water to the highest pools, then sizes pump stations. The operator guide for the manual QGIS workflow is in `docs/`. A beginner-friendly guide to this tool in English and Bahasa Indonesia (steps, input data, outputs per stage, diagrams) is [docs/index.html](docs/index.html) (also the GitHub Pages entry point), with a hands-on wizard walkthrough using dummy data in [docs/wizard.html](docs/wizard.html) and installation steps in [docs/install.html](docs/install.html), a one-slide overview diagram is in `docs/diagrams/` (`workflow_slide.svg` and `.png`), and three technical slides in Bahasa Indonesia (`algoritma_1_alur_data`, `algoritma_2_sekat_skoring`, `algoritma_3_routing_pompa`, each `.svg` and `.png`) show the analyses and data flow. Regenerate the SVGs with `python scripts/make_algorithm_slides.py`.

Layout: the engine is a QGIS-free Python package (`repeat_pump/core`), run from a command line, and a thin QGIS plugin (`qgis_plugin/repeat_pump_qgis`) that starts that command in a separate Python environment.

Installing the QGIS plugin step by step (English and Bahasa Indonesia, one page): [docs/install.html](docs/install.html).

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

Paths are relative to the config file and may use environment variables (`${REPEAT_KHG}/...`).

Inputs (all in the same projected CRS in metres, or set `run.auto_reproject: true`):

| Input | Notes |
|---|---|
| `dtm` | Bare-earth DTM. `surface_type: DSM` is refused. |
| `subkhg`, `subkhg_priority` (optional) | Polygons with `subkhg_id` (or `unit_id`, as the RE-PEAT delineation writes it); CSV with `subkhg_id` or `unit_id`, `priority_rank, deficit_mm, design_period_days` (each column optional; `subkhg_priority.csv` of repeat-prioritisation has exactly these). Without them all sub-KHGs get equal priority and pump demand uses specific yield and `pumping.design_period_days`. |
| `canals` | Lines with `canal_class`, optional `depth_m`, `width_m`. Values such as `Kanal Primer` count as `primer`; codes (KODE_KANAL 1/2/3) need `topology.canal_class_map`, e.g. `{"1": primer, "2": sekunder, "3": tersier}`. |
| `canal_edits` (optional) | Lines with `action` = `add` or `delete`: reproducible manual topology fixes. |
| `sekat_existing` (optional) | Points with `sekat_id`, `has_gate`. |
| `rivers` (optional) | Optional `perennial`, `dry_season_wl_m` (then both datums must be declared). |
| `burn_area`, `peat_depth` (optional) | Text attributes such as `2x` and `3,0 - 4,0 meter` are parsed. Without one, its stage 6 criterion gets weight 0 and the others are rescaled (the KLH scoring needs peat depth). |
| `moisture` | Raster(s); declare `higher_is_wetter`. |

**Balance:** `sekat.target_rise_share` (for example 0.9) keeps the fewest head-rule sekat that give that share of the canal rewetting; the rest go to the `sekat_low_benefit` layer with their rank and gain. The `sekat_reach` layer shows the canal stretch in which each kept sekat holds the water: lines drawn from the block upstream, with the rise, the water level below the land and the share inside the burn area. `scripts/sekat_spacing_check.py --config RUN.yaml` compares minimum spacings and writes the rewetting curve of a finished run.

**From a RE-PEAT KHG folder:** `python scripts/khg_run_config.py ../_khg/<code>_<name> [...]` (or `--all ../_khg`) writes `05_pump/run_config.yaml` for each KHG from its work folder, as the wizard's KHG picker does: LiDAR DTM first, the latest NDMI, the BRGM peat raster named in `re-peat/sites/<folder>/subkhg.yaml`, guessed columns and canal classes, and the proposed defaults.

**Interventions per sub-KHG (stage 11):** with `inputs.subkhg_indicators` (the sub-KHG prioritisation's `unit_prioritas.gpkg`) every sub-KHG gets a treatment class and the reasons for it: close or backfill canals (protected peat), revegetation and fire readiness (canals reach little of a dry or burnt unit), sekat and water supply, sekat and deep wells, sekat, or maintain. For the selected sub-KHGs it also reports the water the kept sekat hold against the neraca deficit. Thresholds are in `interventions:` (policy values; proposed in the preset). Layer `interventions`, table `interventions.csv`. Method: `repeat_pump/core/interventions.py`; evidence: `docs/reports/sekat_neraca_investigation.md`.

**Tertiary canals:** off by default (`topology.canal_classes: [primer, sekunder]`, as in the KLH guide). Add `tersier` to include them; the wizard has a tick box and `scripts/khg_run_config.py` a `--tertiary` flag.

**HTML report:** `repeat-pump report-html --config run.yaml` writes `report.html` next to the GeoPackage: one self-contained page (D3 and MapLibre vendored; the basemap needs internet, the run layers draw without it) with the key numbers, an interactive map (interventions or dry-season water balance per sub-KHG, canals, kept and low-benefit sekat, existing sekat, SiTMAT stations in the KLH water-table classes, burnt area, the water each kept sekat holds back and, with pumping on, the pump routes from the river intake to the target; an Animate button builds the sekat one by one in order of benefit and moves dashes along the reaches and routes in the direction the water moves), the rewetting curve, interventions per class, the monthly water balance, the station water table and a searchable, sortable sub-KHG table. English and Bahasa Indonesia, light and dark. It only re-states the run's files; `inputs.neraca_map` (repeat-neraca's `neraca_map.gpkg`) adds the water balance and stations.

**Budget estimate (stage 11):** with the interventions, every sub-KHG gets quantities (kept sekat by type, or the KLH IPG estimate where no sekat were placed; km of canal to close; ha to revegetate; deep wells; pumps and fuel) priced from `budget.*` as low, central and high. Prices are proposals with sources; a price left null is reported as quantity only. Every source figure is in the register `repeat_pump/data/budget_sources.csv` (figure quoted, URL, date accessed, how it was retrieved, status, and empty `verified_by`, `verified_on`, `verified_figure` columns to fill when someone checks it); each run copies it to `budget_sources.csv` with the price it used and whether that price came from the preset. Outputs: `budget.csv`, `budget_sources.csv`, layer `budget`, a section in run_report.md, and in the HTML report a budget chart, the list of price sources with their status, and the rewetting curve against rupiah spent.

**Map layouts (QGIS):** the wizard's *Make map layout* builds a print layout in the style of the KLH peat maps (A0 to A4, landscape or portrait): map with a lat/long border, title with north arrow, scale and scale bar, the legend in columns, data sources from `re-peat/sites/data_catalog.csv`, institution, logo placeholder and a locator inset from `_data/batas_khg_indonesia.gpkg`. It opens in the layout designer for manual changes. Empty templates are in `qgis_plugin/repeat_pump_qgis/resources/layouts/klh_<paper>_<orientation>.qpt`; edit one in the designer, save it, and choose it as *Own template*: the wizard fills it by item id. Batch, with QGIS's Python: `python-qgis.bat scripts/make_layouts.py --config run.yaml --out folder --papers A0 A3 --pdf`.

**Sekat only:** `pumping.enabled: false` skips stages 8-10 (network, routing, pumps) and asks none of their parameters. Use it when no river in the analysis extent can serve as a water source (stage 9 needs a river with `perennial` or `dry_season_wl_m`). A worked example: `re-peat/sites/16.02.01_sugihan_lumpur/pump.yaml`.

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
4. **Guided wizard** (best for training): toolbar water-drop button, or *Plugins > RE-PEAT Pompanisasi > Guided wizard*. It walks through the stages one at a time (11, plus an optional 12th: canal blocking optimisation after Urzainki et al. 2020), shows what each does, blocks a stage until its required decisions are filled, and stops at the review stages for you to accept. See [docs/qgis_plugin.md](docs/qgis_plugin.md).
5. Or use Processing Toolbox > **RE-PEAT Pompanisasi** > *Run full pipeline* (or a stage group). Choose the YAML config, then the layers; layers must be saved files, not temporary layers. At a review stop the algorithm ends with a warning: inspect the QA layers, tick the stage under *Review stages to accept*, run again.

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
