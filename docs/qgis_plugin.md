# QGIS plugin: RE-PEAT Pompanisasi (external-runner design)

The plugin never imports the engine. It collects inputs, writes a run YAML and starts
`python -m repeat_pump.cli run ...` in a separate Python environment, streaming the log into the
Processing dialog. Dependency clashes with QGIS's own Python are therefore impossible.

## Setup (automatic)
1. Install the plugin: `python scripts/install_plugin.py` (QGIS 4 default profile), or `--profile-dir <profile>`, or
   `--zip` and use *Plugins > Install from ZIP*. The zip and the installed folder carry a copy of the engine.
2. Enable **RE-PEAT Pompanisasi**. The first time you run any of its algorithms, the plugin builds a private Python
   environment in the QGIS profile (`<profile>/repeat_pump_env`) from a system Python 3.11+ and installs the bundled
   engine into it. It needs internet once and takes a couple of minutes. You can also trigger or repair it with
   *Processing Toolbox > RE-PEAT Pompanisasi > Set up engine environment* (or the Plugins menu entry).
3. Updating the plugin updates the environment automatically (it compares the engine version).

If no suitable Python is found (Python 3.11+ with pip and SSL, e.g. from python.org), the plugin says so; install one and run
the setup again. Advanced: pick your own interpreter with *Plugins > RE-PEAT Pompanisasi > Set Python environment (advanced)*, or
set `REPEAT_PUMP_PYTHON`. Precedence: `REPEAT_PUMP_PYTHON`, then the chosen interpreter, then the auto-managed environment.

Installation step by step, in English and Bahasa Indonesia: [install.html](install.html).

## Guided wizard (recommended for training)
The wizard speaks English and Bahasa Indonesia. Use the **EN** and **ID** buttons at the top right; it starts in Indonesian when
QGIS is set to Indonesian. Messages written by the engine (warnings, the log) stay in English.

Click the water-drop button in the toolbar, or *Plugins > RE-PEAT Pompanisasi > Guided wizard*. It opens a floating panel
(dock it to the side if you like; the stage list then collapses to icons).

1. **Stage 1 > Run setup:** pick the output GeoPackage, a starting config, the priority CSV and each layer (layers must be
   saved files). *Create run* writes `run_config.yaml` in the output folder. *Open an existing run* resumes one.
2. Each stage card shows what the stage does (turn on *Learn mode* for the why and the references), the **decisions** that stage
   needs, and a **Run** button. A stage whose required values are empty cannot run; the empty fields are highlighted. The wizard
   never fills these in. Values are saved into `run_config.yaml`.
3. After a run the result tiles appear and the stage's layers are loaded into a `RE-PEAT <run name>` group on the map.
4. **Review stages (2, 6, 9)** stop for you: inspect the layers, then *Accept and continue* or *Re-run this stage*.
5. *Re-run* on an earlier stage clears all later stages, because they depend on it (you are asked first). Their layers leave the map too.
6. If you change a decision after a stage ran, that stage and the ones after it are marked **Out of date** and you cannot accept
   them until you re-run (the button says *Re-run to apply your change*).
7. *Cancel run* stops the engine and anything it started, even if it is silent (for example a long download).

The wizard never imports the engine. It runs the same command as the Processing algorithms and reads `run_state.json`,
the logs and the GeoPackage; `repeat-pump check --config X` (JSON) tells it which parameters each stage still needs.

## Use (Processing algorithms)
Processing Toolbox > **RE-PEAT Pompanisasi**. Policy parameters live in the YAML (start from
`configs/example_khg.yaml`; every `null` must be filled by a human before the stage that needs it).
Layers chosen in the dialog override the input paths and must be saved files (not temporary layers).
At a REVIEW stop (2, 6, 9) the algorithm finishes with a warning; inspect the QA layers, tick that stage
under *Review stages to accept* and run again.

## Status
Verified headless on QGIS 4.2.2 (OSGeo4W): plugin loads, six algorithms register, full pipeline and review-stop/resume run. Two issues found and fixed in that run: headless `qgis_process` calls `initProcessing()` (not `initGui()`), and QGIS's `PYTHON*`/`PATH` variables must be removed from the engine's environment. The wizard was driven end to end (setup from project layers, all 11 stages including the three review stops, re-run, parameter editing, narrow/docked layout) in QGIS 4.2.2's own Python with `QT_QPA_PLATFORM=offscreen`. Not yet exercised: the wizard on a real desktop session by a person, and the Processing dialogs.
