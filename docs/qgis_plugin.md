# QGIS plugin: RE-PEAT Interventions (external-runner design)

The plugin never imports the engine. It collects inputs, writes a run YAML and starts
`python -m repeat_pump.cli run ...` in a separate Python environment, streaming the log into the
Processing dialog. Dependency clashes with QGIS's own Python are therefore impossible.

## Setup (automatic)
1. Install the plugin: `python scripts/install_plugin.py` (QGIS 4 default profile), or `--profile-dir <profile>`, or
   `--zip` and use *Plugins > Install from ZIP*. The zip and the installed folder carry a copy of the engine.
2. Enable **RE-PEAT Interventions**. The first time you run any of its algorithms, the plugin builds a private Python
   environment in the QGIS profile (`<profile>/repeat_pump_env`) from a system Python 3.11+ and installs the bundled
   engine into it. It needs internet once and takes a couple of minutes. You can also trigger or repair it with
   *Processing Toolbox > RE-PEAT Interventions > Set up engine environment* (or the Plugins menu entry).
3. Updating the plugin updates the environment automatically (it compares the engine version).

If no suitable Python is found (Python 3.11+ with pip and SSL, e.g. from python.org), the plugin says so; install one and run
the setup again. Advanced: pick your own interpreter with *Plugins > RE-PEAT Interventions > Set Python environment (advanced)*, or
set `REPEAT_PUMP_PYTHON`. Precedence: `REPEAT_PUMP_PYTHON`, then the chosen interpreter, then the auto-managed environment.

Installation step by step, in English and Bahasa Indonesia: [install.html](install.html). Hands-on walkthrough with dummy data and
screenshots: [wizard.html](wizard.html). Operator guide: [index.html](index.html).

## Guided wizard (recommended for training)
The wizard speaks English and Bahasa Indonesia. Use the **EN** and **ID** buttons at the top right; it starts in Indonesian when
QGIS is set to Indonesian. Messages written by the engine (warnings, the log) stay in English.

Click the water-drop button in the toolbar, or *Plugins > RE-PEAT Interventions > Guided wizard*. It opens a floating panel
(dock it to the side if you like; the stage list then collapses to icons).

1. **Stage 1 > Run setup:** choose the **KHG** at the top of the form: the wizard fills every input from the KHG's work folder
   (`_khg/<code>_<name>/`; set the `_khg` folder once with *KHG folders...*) and lists what it could not find. Or pick the output
   GeoPackage, the priority CSV and each layer yourself (layers must be saved files). Burn scars and peat depth are optional. The
   canal class column is guessed and each of its values is shown with its count and the class it is taken as (change any guess).
   *Plan pumps* is ticked only when a river layer has a dry-season level or a perennial flag. *Include tertiary canals* is off by
   default. With the sub-KHG indicator table chosen, stage 12 also proposes an intervention per sub-KHG (layer `interventions`). The starting config is under *Advanced*. *Create run* writes `run_config.yaml` in the output folder. *Open an existing run* resumes one.
   *Run name* names the map group, the reports and the `run_name` column of the outputs. It is filled in with the output folder's
   name and follows a new folder until you type a name of your own; *Open an existing run* shows the run's name. Left empty, a new
   run takes its folder's name and an open run keeps its own. The wizard reads `run_config.yaml` again when it is edited outside the wizard.
   *Save setup as...* writes the form (layers, columns, selection, datum) to a JSON or YAML file; *Load setup...* fills the form from
   such a file or from any run's `run_config.yaml`, adding layers that are not on the map yet. Change the output GeoPackage and
   *Create run* to repeat a run. *Open an existing run* also refills the form.
   The form also takes concession polygons, water-level observations and extra moisture tiles, and lets you choose which sub-KHGs to
   analyse (highest priority, ticked ones, or all; *Use the features selected on the map* ticks the ones you selected). The run's
   coordinate system comes from the DTM; a layer in another system blocks *Create run* unless *Reproject layers...* is ticked.
   Required columns, coverage and the DTM's vertical datum (when it names one) are checked before the run is created.
   *Start over* clears a run's results (after you confirm) and keeps its settings and data.
   *Run stage n* runs that stage only, so each stage's values can be set first; *Run on to the next review, with the values as set* runs on until the next review stop (2, 6, 9) or the end. *Accept and continue* accepts the review stage and opens the next stage's card without running it.
2. Each stage card shows what the stage does (turn on *Learn mode* for the why and the references), the **decisions** that stage
   needs, and a **Run** button. A stage whose required values are empty cannot run; the empty fields are highlighted. The wizard
   never fills these in on its own. Values are saved into `run_config.yaml`.
   **AHP:** on the Stage 6 card, set *Weighting method* to `ahp` to compare the criteria in pairs in a small grid (type the cells above
   the diagonal, 1 to 9 or a fraction such as 1/3). Weights and the consistency ratio update as you type; a ratio above 0.10 blocks Run.
   **Optional:** tick *Use the proposed defaults* in the run setup (before *Create run*, or later on an open run) to fill the
   empty decisions with the researched starting values of `docs/proposed_defaults.md`. They are meant for trial runs, are marked
   *Proposed default* on each card, and are listed in the run report. A value you type always wins. Datums, DTM RMSE and the
   moisture direction are never filled. The wizard copies `proposed_defaults.yaml` into the run folder, so the team can edit it.
   Settings that already have a default are in a folded **Advanced settings** card on each stage (empty a field to restore the default).
3. While a stage runs, a bar shows what it is doing, the elapsed time and the stages done. After a run the result tiles appear and
   the stage's layers are loaded into a `RE-PEAT <run name>` group on the map; that stage's layers are shown, the others hidden, and
   the map zooms to them (*Show this stage on the map*, *Show every layer*). The last stage can *Export the map* as an A4 PDF or PNG.
4. **Review stages (2, 6, 9)** stop for you: inspect the layers, then *Accept and continue* or *Re-run this stage*.
5. **Stages 8-10 (pumps) can be switched off** with *Plan pumps* = No on the Stage 8 card: a sekat-only plan, needed when no river in the area can be a water source.
5. **Stage 11 (block optimisation) is optional** and starts switched off (shown as *Optional, switched off* and counted as done). Choose *Yes* under *Decisions* to use it; it gives an alternative plan for which proposed sekat to build first and does not change the pump stages.
6. *Re-run* on an earlier stage clears all later stages, because they depend on it (you are asked first). Their layers leave the map too.
7. If you change a decision after a stage ran, that stage and the ones after it are marked **Out of date** and you cannot accept
   them until you re-run (the button says *Re-run to apply your change*).
8. *Cancel run* stops the engine and anything it started, even if it is silent (for example a long download).

The results card has *Export HTML report* (an interactive page next to the GeoPackage) and *Make map layout* (a KLH-style print layout, A0 to A4, opened in the layout designer; an edited layout saved as a template can be chosen as *Own template* next time). After stage 7 the map shows `sekat_reach`, the canal water each kept sekat holds back, with arrows pointing from the block upstream; with pumping on, `pump_routes` has arrows from the river intake to the target. The arrows move along the lines on the map canvas (QGIS symbol animation); in a layout export they stand still. The layout includes both, and the burnt area, when the run has them. With a budget estimate, a table of it (items, quantities, central cost with the low-high range, marked as proposed prices) sits in the map's top-right corner as item `budget_table`; move or delete it in the layout designer. Point and line symbols grow with the paper (A2 1.3, A1 1.6, A0 2.1 times their A3 size). The symbols follow the KLH map sheets (colours sampled from the Mendahara-Batanghari Intervensi Pembasahan sheet): water-drop TMAT stations, planned sekat as dark green and existing sekat as magenta squares with a white centre, burnt area pink, the KHG boundary blue dotted, canals light blue. The locator inset shows Indonesia's provinces (labelled) and the neighbouring countries over a sea colour, with the mapped KHG in dark red; its context and the KLH/BPLH logo are bundled in `resources/context/` (see the NOTICE there for sources and licences). Everything a layout needs ships with the plugin: the logo, the inset context and the ten KLH templates (A0 to A4, landscape and portrait, `resources/layouts/`). The plugin adds that folder to QGIS's layout template paths while it is loaded, so the templates also appear in *Layout Manager > Create from template*; a layout made that way is filled with *Make map layout* > *Own template*. The budget prices (`budget.*`) can be changed under stage 12 in the wizard.

When the plugin is updated, the wizard updates its engine environment by itself (it compares the engine hash written into the zip).

The wizard never imports the engine. It runs the same command as the Processing algorithms and reads `run_state.json`,
the logs and the GeoPackage; `repeat-pump check --config X` (JSON) tells it which parameters each stage still needs.

## Use (Processing algorithms)
Processing Toolbox > **RE-PEAT Interventions**. Policy parameters live in the YAML (start from
`configs/example_khg.yaml`; every `null` must be filled by a human before the stage that needs it).
Layers chosen in the dialog override the input paths and must be saved files (not temporary layers).
At a REVIEW stop (2, 6, 9) the algorithm finishes with a warning; inspect the QA layers, tick that stage
under *Review stages to accept* and run again.

## Status
Verified headless on QGIS 4.2.2 (OSGeo4W): plugin loads, six algorithms register, full pipeline and review-stop/resume run. Two issues found and fixed in that run: headless `qgis_process` calls `initProcessing()` (not `initGui()`), and QGIS's `PYTHON*`/`PATH` variables must be removed from the engine's environment. The wizard was driven end to end (setup from project layers, all 11 stages including the three review stops, re-run, parameter editing, narrow/docked layout) in QGIS 4.2.2's own Python with `QT_QPA_PLATFORM=offscreen`. Not yet exercised: the wizard on a real desktop session by a person, and the Processing dialogs.
