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

## Use
Processing Toolbox > **RE-PEAT Pompanisasi**. Policy parameters live in the YAML (start from
`configs/example_khg.yaml`; every `null` must be filled by a human before the stage that needs it).
Layers chosen in the dialog override the input paths and must be saved files (not temporary layers).
At a REVIEW stop (2, 6, 9) the algorithm finishes with a warning; inspect the QA layers, tick that stage
under *Review stages to accept* and run again.

## Status
Verified headless on QGIS 4.2.2 (OSGeo4W): plugin loads, six algorithms register, full pipeline and review-stop/resume run. Two issues found and fixed in that run: headless `qgis_process` calls `initProcessing()` (not `initGui()`), and QGIS's `PYTHON*`/`PATH` variables must be removed from the engine's environment. Not yet exercised: the GUI dialog.
