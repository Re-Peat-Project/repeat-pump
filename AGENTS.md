# Agent Instructions: Build the "Rewetting with Pompanisasi" Module

**Project:** RE-PEAT (World Bank – KLH), GIS workstream, Departemen Teknik Geodesi UGM
**Module:** `repeat_pump`, the *Rewetting with pompanisasi* intervention
**Audience:** a local coding agent (e.g., Claude Code). Rename this file to `CLAUDE.md` / `AGENTS.md` at the repo root if your agent expects that.

---

## 0. How to work

1. **Read this whole file before writing code.** Then read everything in `legacy/` (the QGIS console scripts `alt_shortest_path.py`, `sekat_kontur_klh_try1.py`, `sekat_kontur_klh_try2.py`, and the workflow PDF if present). Port behaviour that is correct and **do not port the known bugs listed in §9**.
2. **Never invent physical or policy parameter values.** If a value is not in this file or in the config, add it to the config as `null` with a `# TODO(human):` comment and make the pipeline fail with a clear message if it is still `null` at runtime. Section 11 lists the open questions.
   **Exception, opt-in only:** `configs/proposed_defaults.yaml` holds researched *proposed* values, each with a confidence level and source (`docs/proposed_defaults.md`). A run config uses it only by naming it in a top-level `preset:` key. It fills nulls, never overrides, never sets data facts (datums, RMSE, `higher_is_wetter`, paths), and every value taken from it is a per-stage warning and a report section. The config models, `example_khg.yaml` and the wizard still treat these keys as null/required. Do not add values to the preset without a source or an explicit LOW label.
3. **Build in the milestone order of §10.** Each milestone must have passing tests before the next starts.
4. **Every algorithm you implement must cite its reference in the docstring** (use the keys in §12). If you choose an algorithm not listed here, add a reference for it to §12 and to `docs/references.md`, and flag it in your summary.
5. Commit in small steps. Summarise what you did, what you assumed, and what is still TODO at the end of each milestone.

---

## 1. Context and scope

The module sits at the end of a larger pipeline:

```
DEM (LiDAR / DEMNAS / FABDEM) ─► [DSM?] ─► DEM correction & smoothing ─► Sub-KHG delineation
                                                                               │
Project data + Open data ─────────────────► Neraca air (water-sharing) ◄───────┘
                                                     │
                                         Sub-KHG prioritisation
                                                     │
                                              Interventions
                                     ┌───────────────┼───────────────┐
                                    ...   ► Rewetting with pompanisasi ◄   ...
```

**In scope (this module):**
- Hydro-conditioning the *already-corrected* DTM **for flow routing only**.
- Canal network cleaning, segmentation, and graph construction.
- Canal-segment prioritisation **inside priority sub-KHGs** (need score and feasibility filter).
- Gap analysis of existing canal blocks (sekat) and placement of new sekat by hydraulic head.
- Identifying water sources (river–canal intersections) and pump targets.
- Head-aware routing of pumped water, pump station siting, and pump sizing.
- Outputs for QGIS users and for the downstream dashboard.

**Out of scope (consume, do not recompute):**
- DEM correction and smoothing, and the DSM→DTM decision. The module receives a bare-earth DTM.
- Sub-KHG delineation.
- Neraca air and sub-KHG prioritisation. The module receives their outputs as an **optional** table (§3). Where it is not available (for example no TMA stations to build a water balance), neutral fallbacks apply (§5, Stages 1 and 10).

LiDAR DTM is the primary input. DEMNAS/FABDEM-derived DTMs must still work, with accuracy warnings (§5, Stage 1).

---

## 2. Architecture and stack

**Pattern: core library + thin adapters.**

```
repeat_pump/
  core/
    config.py        # pydantic models for the YAML config; validation
    io.py            # loading, CRS/extent/resolution checks, tiling helpers
    topology.py      # Stage 2
    hydro.py         # Stage 3
    segments.py      # Stage 4
    profiles.py      # Stage 5 (along-canal land profiles)
    prioritise.py    # Stage 6
    sekat.py         # Stage 7
    network.py       # Stage 8 (graph build)
    routing.py       # Stage 9
    pumps.py         # Stage 10
    report.py        # run report, QA layers
    pipeline.py      # stage orchestration, checkpoints, resume
  cli.py             # `repeat-pump run --config khg.yaml [--stop-after S] [--resume-from S]`
qgis_plugin/repeat_pump_qgis/   # QGIS plugin (outside the engine package; never imports repeat_pump)
  plugin.py, provider.py, runner.py   # Processing provider + external runner (M8a, done)
  runconfig.py       # shared run-YAML builder (provider and wizard), no qgis imports
  wizard/            # stage-by-stage wizard (§7b): viewmodel.py (pure Python), controller.py (QgsTask + runner),
                     #   ui.py (Qt widgets), setup_form.py (run-setup parts that read the chosen layers), widgets.py (shared helpers),
                     #   preflight.py (early layer checks, pure core), maptools.py (which layers to show, zoom, map export),
                     #   summary.py (final-screen results, pure), diagrams.py (Learn-card SVGs, pure),
                     #   theme.py (QSS), styling.py (layer symbology in code)
  resources/         # example_khg.yaml, proposed_defaults.yaml (copied in by scripts/install_plugin.py)
tests/
  fixtures/          # small synthetic + one pilot sub-KHG
legacy/              # original console scripts (read-only reference)
docs/
  references.md
configs/
  example_khg.yaml
```

**Rules**
- `core/` must **not import `qgis`**. It uses: Python ≥3.11, numpy, scipy, rasterio, geopandas, shapely ≥2, pyogrio, networkx, pydantic, pyyaml, plus **one hydro backend** (see below). Add others only with justification.
- **Hydro backend (deferred):** Stage 3 uses WhiteboxTools (`whitebox`). Whitebox Workflows (WbW) is a possible later alternative behind a backend interface; it would be installed in the engine's venv, never in QGIS's Python. Before adopting it, check that the free tier has the needed tools (least-cost breaching, D-inf/MFD accumulation, flat resolution) and its licence, and run the Stage 3 tests against both. Do not add a `hydro.backend` config key until then (the config models forbid unknown keys).
- The QGIS plugin only declares typed parameters / UI and talks to the engine **as an external process** (`runner.run_cli`) and through files. **Target QGIS 4.x** (Qt6); write UI imports through `qgis.PyQt` so QGIS 3.x LTR is not ruled out later.
- All outputs go to a single GeoPackage per run plus `run_report.md` and `run_report.json`.
- Every stage writes its output layer and a stage log, and records completion in `run_state.json` so runs can resume.
- Large rasters (1 m LiDAR over a full KHG): use windowed reads and tiling. Never load a full KHG raster into memory unless it fits the configured memory budget.

---

## 3. Input contract

All inputs are listed in the config. `io.py` validates them before any processing.

| Key | Type | Required fields / notes |
|---|---|---|
| `dtm` | GeoTIFF | Bare-earth DTM, metres. Config must declare `surface_type: DTM`; **refuse to run if `DSM`**. Config also declares `vertical_rmse_m`. |
| `subkhg` | Polygon layer | `subkhg_id` (unique); `unit_id` is accepted as an alias (RE-PEAT delineation output). |
| `subkhg_priority` | CSV / table, **optional** | `subkhg_id` or its alias `unit_id` (required if the table is given); `priority_rank` (int, 1 = highest), `deficit_mm` (water deficit for the design period, from neraca air), `design_period_days` are each optional. Produced by the neraca air module. Missing table or column: all selected sub-KHGs get equal priority (`priority_weight = 1/n`), and pump demand uses specific yield (Stage 10). Warn, never invent a value. |
| `canals` | Line layer | `canal_class` (primer/sekunder/tersier), optional `depth_m`, `width_m`. |
| `sekat_existing` | Point layer | `sekat_id`, optional `type`, `has_gate` (bool), `crest_elev_m`. May be empty. |
| `rivers` | Polygon or line layer | Optional `dry_season_wl_m` (dry-season water level, m, same vertical datum as DTM), `perennial` (bool). |
| `burn_area` | Polygon layer | `burn_freq` (int count of burn years; normalise from text like "2x" in `io.py` and log every unparsed value). |
| `peat_depth` | Polygon layer **or** raster | Polygons: peat thickness class. Parse class strings such as `'3,0 - 4,0 meter'` to numeric `depth_min_m`, `depth_max_m` (note the comma decimal separator). Raster (`.tif`, `.img`, `.vrt`, `.asc`): peat depth, with `units: m \| cm` required (never guessed: the BRGM models are in cm, the neraca class-midpoint raster in m) and optional extra `nodata` values (e.g. `[-8888]`). Stage 1 crops it, drops no-data and negative cells, converts to metres (`inputs_clipped/peat_depth.tif`) and writes the peat area (depth > 0) as `inputs_clipped_peat_depth` for Stage 10; it warns when the values do not look like the stated unit. Stage 6 takes the median within one cell of each segment as `peat_depth_mid_m` (score) and the minimum as `peat_depth_min_m` (KLH 3 m / 1 m rule), team decision 26 Oct 2026; Stage 12 averages the raster onto its grid. |
| `moisture` | GeoTIFF(s) | Satellite moisture index from upstream (e.g., NDMI/OPTRAM-type). Config declares `higher_is_wetter: true/false`. |
| `concession` | Polygon layer | Optional. Used only as a feasibility filter (§5, Stage 6). |
| `tma_obs` | Point layer | Optional water-table/canal level observations for validation. |

**Column names.** The engine ignores case, spaces and punctuation in column names (`BURN_FREQ` is `burn_freq`). When a layer names a column differently, `inputs.<input>.columns` maps the expected name to the user's (`canal_class: Kelas Kanal`); the names that can be mapped are `CANONICAL_COLUMNS` in `core/config.py`. One helper (`io.apply_columns`) does the renaming for vectors and for the priority CSV, and `requirements` reads the same mapping when it decides whether river levels or a water deficit exist, so a check and a run cannot disagree. A mapped column wins over a column that already has the expected name, and says so.

**Validation rules (fail fast, with a clear message):**
- All layers must be reprojected to `config.crs` (projected, metres). Check the DTM's CRS explicitly. Legacy runs mixed EPSG:32748 and EPSG:32749 by mistake. **Raise an error if any input's CRS differs from `config.crs` and `auto_reproject: false`.** If `auto_reproject: true`, reproject and log it.
- Check that every input overlaps the analysis extent (selected sub-KHGs). Warn when an input covers <90% of it.
- Check that the vertical datum of `rivers.dry_season_wl_m` matches the DTM's (config field `vertical_datum`). If unknown, stop and ask.

---

## 4. Config (YAML)

Validate with pydantic. Example skeleton (`configs/example_khg.yaml`):

```yaml
run:
  name: khg_kahayan_sebangau_pilot
  output_gpkg: out/pilot.gpkg
  crs: EPSG:32749
  auto_reproject: false
  vertical_datum: null            # TODO(human)
  memory_budget_gb: 8
  subkhg_selection: {mode: top_n, n: 3}   # or {mode: ids, ids: [...]}

inputs:
  dtm: {path: ..., surface_type: DTM, vertical_rmse_m: null}   # TODO(human)
  # ... other inputs per §3

hydro:
  breach_max_dist_cells: null     # TODO(human); passed to Whitebox BreachDepressionsLeastCost
  burn_depth_default_m: 2.0       # used only where canals.depth_m is missing
  flow_algorithm: dinf            # dinf | mfd | d8

segments:
  max_length_m: 500
  min_length_m: 25                # shorter pieces flagged, excluded from scoring

profiles:
  bank_offsets_m: [6, 10]         # lateral sampling beyond canal edge, both sides
  sample_step_m: 5
  smoothing_window_m: 50          # median filter along profile

sekat:
  dA_m: 0.40                      # max water-table depth below surface, PP 57/2016
  max_spacing_m: null             # TODO(human); upper bound on spacing
  slope_reinforced_pct: 5.0       # legacy SLOPE_MIN_PCT; flags leaky/reinforced type

prioritise:
  ring_buffer_m: [15, 100]        # inner, outer, for moisture extraction
  criteria:                       # need criteria only
    burn_freq:   {weight: null, direction: higher_is_worse}
    peat_depth:  {weight: null, direction: higher_is_worse}
    dryness:     {weight: null, direction: higher_is_worse}
    upstream_contrib: {weight: null, direction: higher_is_worse}
  weights_mode: direct            # direct | ahp
  ahp_matrix: null                # required if weights_mode == ahp
  feasibility:
    concession_mode: null         # TODO(human): exclude | flag | ignore
  top_fraction: 0.2               # share of segments selected as targets

pumping:
  conveyance: null                # TODO(human): canal | pipe
  manning_n: null                 # TODO(human), canal mode
  hazen_williams_c: null          # TODO(human), pipe mode
  pipe_diameter_m: null           # pipe mode
  pump_efficiency: null           # TODO(human)
  max_head_per_station_m: null    # TODO(human)
  pump_capacity_m3s: null         # TODO(human), per unit
  uphill_penalty_lambda: null     # TODO(human); cost weight per metre of lift
  demand_mode: deficit            # deficit | specific_yield
  specific_yield: null            # required if demand_mode == specific_yield
  influence_distance_m: null      # TODO(human); canal-to-peat rewetting reach, calibrate with tma_obs
  routing: steiner                # steiner | per_target (legacy-equivalent baseline)

optimise:                         # OPTIONAL Stage 12 (off by default). Every physical value is a human decision.
  enabled: false
  objective: canal_rise           # canal_rise | pde | screen_then_pde
  algorithms: [ga, sa]            # ga | sa | greedy
  n_blocks: null                  # TODO(human): new blocks to choose among the proposed sekat
  max_evaluations: null           # TODO(human): distinct layouts each algorithm may score
  canal_drawdown_m: null          # TODO(human): dry-season canal level below the surrounding land
  grid_m: null                    # TODO(human), pde objectives
  dry_days: null                  # TODO(human), pde objectives
  et_mm_day: null                 # TODO(human), pde objectives
  transmissivity_multiplier: null # TODO(human), pde objectives (results depend strongly on it)
  seed: 0
  random_baseline_draws: 10
```

---

## 5. Pipeline stages

Each stage lists its purpose, method, references, outputs, and human checkpoint. Stages marked **[REVIEW]** stop by default and write a QA layer. They continue only when `--accept STAGE` is passed or `review.auto_accept` lists the stage.

### Stage 1: Load and validate
- Apply all checks in §3.
- **Accuracy warning:** if `sekat.dA_m < 2 × dtm.vertical_rmse_m`, emit a prominent warning in the run report. Head-based sekat placement is then dominated by DTM noise. Do not block the run.
- Clip all inputs to the selected sub-KHGs (by `subkhg_priority` + `subkhg_selection`) plus a configurable margin. `subkhg_selection.mode`: `top_n` (needs `priority_rank`), `ids`, or `all`. **No ranking available** (no table, or no `priority_rank`): `top_n` falls back to every sub-KHG in the layer with equal priority, with a warning; the report records `priority_source` (`table` or `equal`) and `demand_source` (`deficit_table` or `specific_yield`).
- **Output:** `inputs_clipped/*`, validation section of the report.

### Stage 2: Canal topology **[REVIEW]**
- Snap endpoints within tolerance, break lines at intersections, remove duplicates, and report dangles. Equivalent to GRASS `v.clean tool=snap,break,rmdupl` (Neteler & Mitasova, 2008). Implement with shapely (`unary_union` + `line_merge` + noding) **or** call GRASS if available. Keep the core path GRASS-free.
- **Do not silently delete dangles.** Write them to `qa_topology_dangles` with the distance to the nearest other segment. Snapping above the tolerance needs human review.
- Assign stable `canal_id` per cleaned feature.
- **Output:** `canals_clean`, `qa_topology_dangles`, `qa_topology_gaps`.

- **Canal classes (optional):** `topology.canal_classes` keeps only the listed `canal_class` values (the KLH guide, step 1.2: primer and sekunder), case-insensitive, counted per class in the report. The full set stays in `inputs_clipped_canals`. River mouths follow guide step 8.2: found on the full set within `topology.river_buffer_m` (30 m), then moved onto the kept network within `topology.source_snap_m` (50 m); points with no kept canal that close are dropped and counted in `report.river_sources`. Both keys are null (off) by default, which keeps the exact river-canal crossing.

### Stage 3: Hydro-conditioning (flow routing only)
- Input is the corrected DTM. Produce a **separate** conditioned raster. **The unconditioned DTM is used for all elevation/slope/profile work in Stages 5 and 7** (legacy rule: slope from DTM_smooth, never from the burned DTM).
- Depression handling: least-cost breaching with fill fallback (`BreachDepressionsLeastCost`, Lindsay, 2016a), or priority-flood (Barnes et al., 2014).
- Canal burning: burn using `canals.depth_m` where present, else `burn_depth_default_m`; log the share of canal length using the default. Document burn artefacts (Lindsay, 2016b).
- Flats: ensure drainage over flats is resolved (Garbrecht & Martz, 1997; Whitebox handles this in breaching/flow tools; verify in tests).
- Flow accumulation: D-infinity by default (Tarboton, 1997); MFD (Holmgren, 1994) or D8 configurable.
- **Output:** `dtm_conditioned.tif`, `flow_acc.tif` (both as files referenced in the report, not inside the GPKG).

### Stage 4: Segmentation
- Split cleaned canals into ≤ `max_length_m` pieces. Assign unique, stable `seg_id` (deterministic ordering: by `canal_id` then along-line position, **not** row order).
- Flag pieces `< min_length_m` with `status_mcda = 0`. Keep them in the network and exclude them only from scoring.
- **Output:** `canal_segments`.

### Stage 5: Along-canal land profiles
- For each canal, sample the **unconditioned** DTM every `sample_step_m` along lines offset by `bank_offsets_m` on both sides. The canal centreline in LiDAR is water/canal bed, not land surface. Take the median across offsets at each station, then apply a median filter of `smoothing_window_m`.
- Derive per station: `z_land`, local slope `i_lahan` (m/m and %).
- Determine downstream direction of each canal from the profile trend and network position relative to river intersections. Where flat (|Δz| below RMSE over the canal), mark `direction = ambiguous` and resolve by network distance to the nearest river node.
- **Output:** `canal_profiles` (station points), per-segment `z_up`, `z_down`, `i_lahan_mean` on `canal_segments`.

### Stage 6: Segment prioritisation **[REVIEW]**
Run only inside the selected priority sub-KHGs.

**Attribute transfer (polygon → segment), length-weighted:** for categorical polygon attributes (burn frequency, peat depth class), the value assigned to a segment is the one covering the **largest total length** of that segment. **Do not use feature-count "majority"** (legacy bug). Implement as: intersect, compute piece lengths, group by (`seg_id`, value), sum the lengths, and take the argmax per `seg_id`. Also store `share_dominant` (dominant length ÷ segment length).

**Raster extraction:**
- Dryness: mean of `moisture` within a **ring buffer** (`ring_buffer_m` inner/outer) on both sides of the segment, excluding the canal water surface. Respect `higher_is_wetter`.
- Upstream contribution: max of `flow_acc` within a narrow buffer, then log-transform. Alternatively, compute upstream canal length via the network graph (Stage 8). Make this a config option and document which was used.

**Scoring (need score):**
- Normalise each criterion to [0, 1] (min–max on the analysis extent, with direction applied); store raw values too.
- Weighted linear combination (Malczewski, 2006). Weights come from `direct` config **or** an AHP pairwise matrix (Saaty, 1980). For AHP, compute the consistency ratio and **fail if CR > 0.10**.
- If any weight is `null`, stop and ask (§0 rule 2).
- **Sensitivity analysis:** one-at-a-time perturbation of each weight by ±10% and ±20% (renormalised). Report Spearman rank correlation of segment ranks against the baseline, and the share of top-fraction segments that remain selected (Chen et al., 2010).

**KLH scoring (opt-in, `weights_mode: klh`):** reproduces steps 7.1 and 7.2 of the KLH guide so trainees can compare with it: burn count (2 or more = 3, 1 = 2), shallowest peat depth of the class (3 m or more = 3, 1 m or more = 2), moisture mean in the full `upstream_buffer_m` buffer against `klh_cpwi_breaks`, flow accumulation maximum against `klh_flow_breaks`; total 4 to 12 (0 for slivers), `klh_score` and per-criterion columns, `need_score` = total / 12, selected where the total reaches `klh_min_score`. The two break pairs and the minimum are required nulls (no defaults: the guide says to fit them to each KHG). It needs `upstream_method: flow_acc`, writes an empty `qa_sensitivity`, and the report warns that the mode keeps fixed class breaks and the canal-water buffer (section 9, bugs 4 and 5) because the guide does. The default method is unchanged.

**Feasibility (kept separate from need):** concession and accessibility are applied **after** scoring as filters or flags according to `feasibility.concession_mode`. Never add them into the need score.

- **Output:** `canal_segments` gains `need_score`, `need_rank`, `feasible`, criterion raw/normalised fields; `qa_sensitivity` table.

### Stage 7: Sekat gap analysis and placement
Head-based design following the team's 2021 KHG Kahayan–Sebangau report, Ritzema et al. (2014), and Dohong et al. (2018):

- **Required spacing:** `js = dA / i_lahan` per canal reach (report eq.; dA from PP 57/2016). Clip to `max_spacing_m`.
- **Required count per canal:** `n_req = ceil((z_up − z_down) / dA)`.
- **Gap analysis (existing sekat first):** snap `sekat_existing` to canals (tolerance in config; log unsnapped points). Compute the IPG metric = `n_existing / n_req` per canal (report §5.3.4; > 1 = adequate).
- **Placement of new sekat:** walk each canal from downstream to upstream. Starting from the downstream end or the last existing sekat, place a new sekat where the cumulative land-elevation rise since the previous sekat reaches `dA` (equivalent to crossing a `dA`-interval contour, without generating vector contours). Never place within `min_spacing` of an existing sekat (config).
- **Sekat height:** `ts = dk + js·tan α − dA` (report eq. 4.18); requires `canals.depth_m` (`dk`), else leave null and flag.
- **Manual edits (opt-in):** `sekat.edits` (points with an `action` of add or delete, e.g. drawn in the wizard) changes the proposals after placement. A delete drops the proposal nearest to the point within `snap_tolerance_m` (matched before adds are made, so a file never deletes its own additions); an add snaps onto the nearest canal within the same distance and is marked `manual` (never refused for spacing). `js_m` and `ts_m` are recomputed for the final layout. Unmatched edits are warned about and counted in `report.sekat_edits`. `sekat_proposed` carries a `manual` column; stages 8 and 12 use the edited layer. The file lives outside `inputs` on purpose, so adding it does not make stage 1 out of date; stage 7's fingerprint carries its content hash.
- **Spacing options (opt-in):** `sekat.min_new_spacing_m` (legacy `JARAK_MIN`) keeps new sekat at least that far apart along a canal, which overrides the head rule on steep land. `sekat.dedup_tol_m` (legacy `DEDUP_TOL`) drops a proposal within that distance of an existing sekat or of an earlier proposal on another canal.
- **Type flag:** `leaky/reinforced` if local slope ≥ `slope_reinforced_pct`, else `standard` (legacy rule).
- **Output:** `sekat_existing_assessed` (with IPG per canal), `sekat_proposed` (with `ts`, type, `z_land`, chainage).

### Stage 8: Network graph
- Build a **directed** networkx graph from `canal_segments`. Nodes are segment endpoints, sekat locations (existing and proposed), and river–canal intersection points. Each edge stores `seg_id`, `length_m`, `z_from`, `z_to` (land elevation at ends, from Stage 5), `dz = z_to − z_from`.
- Add both directions for each segment; edge cost is direction-dependent (Stage 9).
- Mark edges crossing a sekat. A sekat without a gate (`has_gate = false`) **blocks** pumped flow unless config allows a gate to be added; record needed gates as outputs.
- **Output:** pickled/serialised graph in the run folder; `network_nodes`, `network_edges` layers for inspection.

- **Manual sources and targets (opt-in, `pumping.route_edits`):** points with `action` (add | delete) and `kind` (source | target), plus `z_src_m` for the water level of an added source. Stage 8 is the only reader (deletes travel inside the graph, so stage 9 never applies a newer file than the graph was built from). Adds snap onto the nearest canal within `sekat.snap_tolerance_m` (documented reuse of stage 7's tolerance, no preset value; the stage needs it) and become graph nodes: a source is a `river` node marked `manual` and usable as the person says; a target a `manual_target` node. A source level is never guessed: without `z_src_m`, stage 10 stops as it does for a river without a level, and with one stage 8 needs `run.vertical_datum`. A delete of a source excludes the computed river nodes within the tolerance. The edits file's content hash (every column, so a changed level counts) is in stage 8's fingerprint.

### Stage 9: Sources, targets, and routing **[REVIEW]**
**Sources:** river–canal intersection nodes. Keep only rivers with `perennial = true` or known `dry_season_wl_m` (otherwise flag). Each source carries its source water level `z_src`.

**Manual edits in stage 9:** excluded sources stay in `pump_sources` with status `excluded_by_user` (manual ones `manual`; both layers carry `manual`); excluding every source is an error that says so. A manual target on a selected cluster replaces that cluster's computed target and takes over its segments (one manual target per cluster; demand is never counted twice); on an unselected segment it serves only the segment(s) it sits on, with a warning. A deleted computed target takes its segments out of service, which is reported (`report.route_edits.selected_segments_no_longer_served`) and warned about; removing every target is an error.

**Targets:** for each connected cluster of selected priority segments (top `top_fraction` of feasible segments), the target node is the **highest** pool (upstream-most node by `z_land`). Do not use segment centroids (legacy), because water must reach the top of the reach.

**Edge cost (head-aware):**
`cost(u→v) = length_m + λ · max(0, z_to − z_from)`, with λ = `uphill_penalty_lambda`. Downhill/flat edges cost length only. This is a proxy for pumping energy (P ∝ H; Karassik et al., 2008).

**Routing modes:**
- `per_target` (baseline, reproduces legacy): multi-source Dijkstra (Dijkstra, 1959) from all sources to each target independently.
- `steiner` (default): directed Steiner arborescence via the shortest-path heuristic (Takahashi & Matsuyama, 1980). Start from a virtual super-source connected to all sources at zero cost. Repeatedly connect the cheapest unconnected target to the current tree with Dijkstra. For an undirected comparison, networkx's `steiner_tree` (Kou et al., 1981; Mehlhorn, 1988) may be reported as a secondary result only.
- Report total length, total lift, and the number of targets unreachable (e.g., blocked by ungated sekat).

- **Sekat scope:** once the routes are known, every proposed sekat is labelled `target` (on a segment served by a target), `route` (on a pump route, within 0.5 m) or `other`, in `sekat_scope`. `pumping.sekat_scope` decides which are in the plan (`planned`): `all` (default, every proposal, as before) or `selected` (`target` and `route`). The guide's order is area, then route, then the sekat along it; Stage 7 places sekat on every kept canal by the head rule, so the scope is applied here rather than there. The sekat on a route stay in the plan with either setting, because they hold the pumped water and need gates (team decision, 26 Oct 2026). A target whose selected canals got no sekat (the land rises less than `dA_m` along them) is a warning, not an error. Stage 7 results do not depend on the setting, so changing it makes Stage 9 out of date, not Stage 7.
- **Output:** `pump_sources`, `pump_targets`, `pump_routes` (with mode, cost, cumulative lift), `qa_unreachable_targets`, `sekat_scope`.

### Stage 10: Water demand, pump stations, and sizing
**Demand per target:**
- `deficit` mode: `V = deficit_mm / 1000 × A_served`, where `deficit_mm` comes from `subkhg_priority` and `A_served` is the peat area within `influence_distance_m` of the target's served segments (clipped to the sub-KHG).
- `specific_yield` mode: `V = Δh × Sy × A_served`, with `Δh` = required water-table rise (config) and `Sy` from config.
- `Q_required = V / (design_period_days × 86400)`. If `Q_required` > installed capacity, report the shortfall. Do not silently cap.
- **No water deficit** (no table, or no `deficit_mm`/`design_period_days` for the selected sub-KHGs): `deficit` mode switches to `specific_yield` with a warning, which needs `pumping.specific_yield` and `pumping.water_table_rise_m`. `design_period_days` comes from the table when it has it, else from `pumping.design_period_days`. These are human decisions: if null, the stage stops and lists them (§0 rule 2).

**Head along each route:**
- Static lift: `H_static = z_target_pool − z_src`, where the target pool water level = `z_land − dA` at the target.
- Friction loss: `canal` mode uses Manning, `h_f = L · (n·Q / (A·R^(2/3)))²` (Chow, 1959), requiring canal cross-section from `width_m`/`depth_m`. `pipe` mode uses Hazen–Williams (Mays, 2011).
- `H = H_static + Σ h_f`.

**Station siting:** walk each route from source. Place a pump station where cumulative `H` since the last station would exceed `max_head_per_station_m`. Snap stations to the nearest sekat node where possible, since a lift station is naturally co-located with a block/gate.

**Power:** `P = ρ g Q H / η` per station (Karassik et al., 2008), with ρ = 1000 kg/m³, g = 9.81 m/s².

**Gates:** every existing or proposed sekat on a route must be gated/spillway type. List the ones needing a gate.

- **Output:** `pump_stations` (Q, H, P, units needed), `pump_routes` updated with demand, `gates_required`.

### Stage 11: Report
- `run_report.md` / `.json`: config echo, input validation results, warnings (accuracy, defaults used, unparsed attributes), per-stage counts, IPG table per canal, sensitivity summary, routing summary, pump table, and the list of TODO/null parameters.
- If `tma_obs` is provided, report observed vs. modelled canal/pool levels where comparable (validation only, no calibration in v1).

### Stage 12: Canal blocking optimisation (optional)
Off by default (`optimise.enabled: false`): the stage records `skipped` and asks for no parameters, so existing runs are unchanged. It follows Urzainki et al. (2020) [Urzainki2020]: score layouts of canal blocks with a groundwater model and search for the best layout with a genetic algorithm [Holland1975] and simulated annealing [Kirkpatrick1983].

- **This is an alternative plan.** Stages 8 to 10 still assume every proposed sekat is built, and nothing in Stage 12 feeds back into them. Say so in the report and in every guide. The benefit is relative to the existing structures only and is not a field-validated water table change (the paper itself notes there is no field validation).
- **Candidates:** the Stage 7 proposed sekat (`sekat_proposed`). Existing sekat are always in place and do not count towards `optimise.n_blocks`. Choose `n_blocks` of them.
- **Canal water level (deliberately not Urzainki's rule):** the original raises "upstream" cells by comparing neighbouring DEM values, which the authors note is non-monotonic and resolution-bound. Here the base level is land minus `optimise.canal_drawdown_m`; a block holds water at its own land level minus `sekat.dA_m` and raises every station upstream of it along the Stage 5 direction and the connected canal network, up to that level.
- **Objectives** (`optimise.objective`): `canal_rise` (cheap: total canal level rise; the paper found it tracks the full model), `pde` (dry peat volume after `dry_days` of net loss `et_mm_day` from a saturated start, from a 2D nonlinear Boussinesq model on a `grid_m` grid, `repeat_neraca.groundwater`, a dependency, peat tables of Urzainki et al.), or `screen_then_pde` (search with canal rise, re-score the winners with the groundwater model). The sub-KHG boundary is held at the surface, as in the paper. Peat depth is the mid-point of the parsed class.
- **Search:** genetic algorithm and simulated annealing (`optimise.algorithms`, optionally `greedy`), each with its own cache and the same budget `optimise.max_evaluations` of distinct layouts, deterministic for `optimise.seed`. Comparators scored with the same objective: the mean of `random_baseline_draws` random layouts and a rule-based layout (the highest `need_score` segments). Report gains **relative to these comparators**, not as absolute water table numbers.
- **Null parameters (§0 rule 2).** Always required when enabled: `n_blocks`, `max_evaluations`, `canal_drawdown_m`. Additionally for `pde` objectives: `grid_m`, `dry_days`, `et_mm_day`, `transmissivity_multiplier`. The result depends strongly on transmissivity (the re-peat benchmark found almost no block effect with the boreal tables and a realistic effect at about 100 times), so never default it. GA/SA settings (`optimise.ga`, `optimise.sa`) have documented implementation defaults that are not taken from the paper.
- **Output:** `sekat_optimised` (all candidates, `selected_best`, `selected_<method>`, crest level), `qa_optimisation` (table: method, evaluations, benefit, benefit versus random), `qa_optimisation_trace` (table). The stage appends its own section to `run_report.md` and `run_report.json`, because Stage 11 has already run.
- **Provenance:** the solver and peat tables come from the `watershare` testbed of the re-peat repository, which reimplemented the scheme of blopti (MIT, Copyright (c) 2019 Iñaki Urzainki) in SI units. Since repeat-neraca 0.2.0 both live only in `repeat_neraca.groundwater` (with the notice in its `data/`), which this package installs from a GitHub archive pinned in `pyproject.toml`; the canal level rule and the search stay here.

---

## 6. Output contract (GeoPackage layers)

`canals_clean`, `qa_topology_dangles`, `qa_topology_gaps`, `canal_segments`, `canal_profiles`, `sekat_existing_assessed`, `sekat_proposed`, `network_nodes`, `network_edges`, `pump_sources`, `pump_targets`, `pump_routes`, `sekat_scope`, `pump_stations`, `gates_required`, `qa_unreachable_targets`, `qa_sensitivity` (table), and, only when Stage 12 is enabled, `sekat_optimised`, `qa_optimisation` (table), `qa_optimisation_trace` (table).

Every layer includes `run_name` and `stage` fields. Field names are lower_snake_case and ≤ 30 characters. Units go in names where ambiguous (`_m`, `_m3s`, `_kw`).

---

## 7. QGIS Processing provider

- One provider ("RE-PEAT Pompanisasi") with one algorithm per stage group plus a "Run full pipeline" algorithm.
- Parameters are typed (`QgsProcessingParameterRasterLayer`, `...VectorLayer` with geometry type, `...File` for config). Layer roles must be explicit and named (e.g., *River polygons (water sources)*). This avoids the legacy start/muara swap.
- The provider writes a temporary YAML from the dialog values and calls `core.pipeline`. No logic in the provider.
- Must work with `qgis_process run` headless.

## 7b. QGIS plugin: stage-by-stage wizard (training UI)

Purpose: train KLH staff. The plugin registers the §7 provider and adds a dock-widget wizard. **The wizard contains no analysis logic and never imports `repeat_pump`.** It reaches the engine only through (a) `runner.run_cli` (one stage at a time) and (b) files: `run_state.json`, `<name>_work/logs/`, the output GPKG and `run_report.json`; plus `repeat-pump check --config X` (JSON: stages, review flags, null parameters each stage still needs).

**Engine contract (tested in `tests/test_wizard_engine.py`)**
- Stage status in `run_state.json`: `running | awaiting_review | done | failed` (+ `error`); absent = not run. Re-running a stage deletes the state of all later stages and the warnings that stage or later ones raised.
- On completion each stage stores a `fingerprint` (the config sections that determine its results, `core/requirements.py`). `repeat-pump check` returns the current fingerprints; if they differ the wizard marks the stage and every later one **out of date**: Accept is disabled and the primary action is "Re-run to apply your change".
- Run next = `last=N`; Accept = `last=N, accept=[N]` (no `first`); Re-run / Back = `first=N`.
- Tiles read `report.counts[stage]`; callouts read `warnings`.
- `check` also returns, per stage, `options`: the settings that have a default (`requirements.OPTIONS_BY_STAGE`), never counted as missing. `review.auto_accept` is deliberately not an option. A front end offers every option, so no engine setting needs a text editor.
- Stage 1 needs both vertical datums as soon as the rivers layer carries `dry_season_wl_m` (read with pyogrio), so CLI, provider and wizard agree. The two must be equal; the wizard asks for one datum and writes both.
- Progress: with `REPEAT_PUMP_PROGRESS=1` the engine prints `@@progress|<stage>|<0..1>|<text>` lines (the runner sets it; plain CLI output is unchanged). `runner.report_progress` hands them to `feedback.progress(stage, fraction, text)` or `setProgress(percent)`.
- `repeat-pump reset --config X` deletes the GeoPackage, work folder, `run_state.json` and the report, and refuses to touch anything outside the run folder. Config, preset and inputs stay.

**Structure**
- **Stepper rail** (left): the 12 stages (stage 12 is optional), each with status `locked | ready | running | done | needs_review | failed | stale | skipped`, taken from `run_state.json`. [REVIEW] stages have a distinct "your turn" accent.
- **Stage card** (main): one-line purpose; "What this does" and "Why it matters" text (plain language; English and Bahasa Indonesia, switched with the EN/ID buttons, default from the QGIS locale; every string goes through `tr()` in `wizard/i18n.py` and `tests/test_wizard_i18n.py` fails when a string has no Indonesian text; messages written by the engine stay English); a typed, named input form; Run button with Cancel (kills the engine process tree, works even when the engine is silent). A small diagram for key ideas (sekat head rule, ring buffer, head-aware cost) sits in the Learn card of stages 7, 6 and 9 (inline SVG, `wizard/diagrams.py`, translated).
- **Result tiles** after each run: key counts and totals from the stage log (e.g. segments, dangles, sekat needed, unreachable targets, total lift). Warnings (DTM accuracy, defaults used, unparsed attributes) appear as friendly callouts, never buried in a log.
- **Review panel** for [REVIEW] stages: auto-load the QA layers with bundled QML styles, then offer *Accept*, *Re-run with changes*, *Back*. Accept writes to `review.auto_accept`/`--accept` equivalent in the state file.
- **Learn toggle:** expands explanations, formulas and §12 references per stage.
- **Null parameters (§0 rule 2):** missing keys come from `repeat-pump check`, shown as required, highlighted fields. The wizard writes them into the run YAML; Run stays disabled until filled; never prefill physical values.
- **Advanced settings:** every stage lists its options (above) in a folded card; an emptied field removes the key so the engine default applies again. Choices show readable names while the YAML keeps the codes.
- **Run setup reads the layers:** the run CRS comes from the DTM; a layer in another CRS blocks *Create run* unless reprojection is ticked; required columns, coverage and the DTM's vertical datum (when it names one) are checked early; sub-KHGs can be picked (including "use the features selected on the map"); concession and water-level layers and extra moisture tiles are chosen in the form. The engine still validates everything in stage 1.
- **Load moisture from the cloud:** a button next to the moisture layer runs `repeat-pump fetch-moisture` (engine `core/cpwi.py`, `cloudfetch.py`, `ee_fetch.py`; wizard `cloud_dialog.py`, pure `cloudload.py`). Source `stac`: open Sentinel-2 (Earth Search), an NDWI+NDMI wetness index, an approximation of CPWI v2 (no radar, SCL cloud mask). Source `ee`: exact CPWI v2 of `legacy/gee_code.txt` through the optional `earthengine-api`. The date windows have no defaults (§0 rule 2). The raster gets a `<file>.provenance.json`; stage 1 puts it in the report and warns about each deviation, and the wizard sets `higher_is_wetter` from it.
- **Load burn scars from the cloud:** a second button next to the burn-scar picker runs `repeat-pump fetch-burn` (engine `core/burnfetch.py`, dialog `BurnLoadDialog`). It counts, per cell, the years in which MODIS MCD64A1 [Giglio2018] mapped a fire, and writes `burn_area` polygons with an integer `burn_freq`. It is coarse (about 460 m) and misses small and smouldering peat fires, so it is a fallback for the burn-scar layer KLH provides; the limits are in the provenance file and become stage 1 warnings. The year window has no default.
- **Column names:** the run setup lists, for each chosen layer, the expected columns it does not carry under a recognised name and offers a field picker per column (preflight uses the engine's name rule, so it never asks about a column the engine already finds); the choices are written to `inputs.<input>.columns`. `preflight.COLUMNS` mirrors ``CANONICAL_COLUMNS`` and a test keeps them equal.
- **Fix the network on the map** (`wizard/canal_edit.py`, `pointtool.py`): stage 2 offers *Draw a canal to add* and *Click a canal to delete* (writes `canal_edits.gpkg` in the run folder, read by stages 1 and 2 as `inputs.canal_edits`); stage 7 offers *Add a sekat* and *Remove a proposed sekat* (`sekat_edits.gpkg`, `sekat.edits`). A deleted canal is the whole line of the user's canal layer that was clicked (the engine removes lines that lie inside it). The edits layer sits in its own layer group so a re-run or *Start over* never removes it, snapping to the canals is switched on while drawing and restored afterwards, and the file's content hash is part of the stage fingerprint, so editing the file marks the stage out of date however it was edited. The wizard never changes data itself: the engine reads the files and reports what it applied.
- **Water sources and targets on the map** (stage 9, `RouteEditor` in `canal_edit.py`): *Add a water source* (asks for the dry-season level in the DTM's datum, never prefilled, may be left empty), *Exclude a water source* (click again to bring it back), *Add a target*, *Remove a target*; saved to `route_edits.gpkg`. Removing a source or target that an earlier edit added drops that edit. Saving selects stage 8.
- **Explain a segment** (`wizard/explain.py` pure, `explain_tool.py`): from stage 6 on, click a canal segment to see each criterion's value, score, weight and contribution (or the KLH class), why it was or was not selected, and concession notes. Weights come from the stage's own record in `run_state.json`, never from the config, and the breakdown is labelled out of date when stage 6 is stale. A test checks that the rows add up to the stored score for every segment of a real run, for both scoring methods.
- **Demo view:** a *Demo view* checkbox next to *Learn mode* shows every stage's cards at once: the decisions and options (read from the bundled template config through `repeat-pump check`, read-only when no run is open) and the map tools, which stay disabled until the stage has results. Running still follows the order of the stages; nothing is run or written.
- **Map handling:** after a stage its layers load, the stage's own layers and their context are shown, the rest hidden, and the canvas zooms to them. Draw order is fixed (`styling.DRAW_ORDER`). Styling stays in code. Stage cards have *Show this stage on the map* and *Show every layer*; the final stage can export an A4 map (PDF or PNG) with legend, scale bar and notes. Logic that decides what to show is pure (`maptools.visibility_plan`); Qt calls do nothing without an `iface`.
- **Progress and control:** a bar with the step, elapsed time and stages done while a stage runs; *Start over* clears a run after closing its layers.
- **Final screen:** "Results at a glance" from `run_report.json` (segments, sekat and IPG, routes, pump table, honest notes about shortfalls, unreachable targets, preset values and warnings; `wizard/summary.py`, pure Python), links to the run folder and report, and the map export.

**Implementation rules**
- Run stages off the UI thread (`QgsTask`, or a subprocess if `core` runs in a separate environment). QGIS must not freeze during Stage 3, 5 or 9.
- Native Qt widgets styled with one QSS theme that paints its own backgrounds (same look in QGIS light and dark themes); one accent colour; inline SVG icons. **Do not embed a web view** (WebEngine is not reliable in QGIS builds).
- Output and QA layers are styled in code when loaded (`wizard/styling.py`; see the `qgis-cartography` skill for design principles).
- Dependencies: the existing private-venv mechanism in `runner.py` (`ensure_environment`) is reused; the wizard shows its status and offers "Set up / repair".
- Shared code: the provider's config builder lives in a shared module used by both the provider and the wizard.
- Tests: the view-model (status transitions, disabled Run on null params, command construction) is pure Python and tested in `.venv`; the Qt layer is smoke-tested with QGIS's own Python under `QT_QPA_PLATFORM=offscreen`.

---

## 8. Testing

Use pytest. Required tests:

1. **Tilted plane:** a synthetic DTM with known uniform slope `s` and a straight canal. Proposed sekat spacing must equal `dA / s` within one sample step; `n_req` must match analytically.
2. **Length-weighted dominance:** a 500 m segment crossing two polygons (400 m class A, 100 m class B) must get A. A three-piece case (A 150, B 200, A 150) must also get A.
3. **No summed means:** after any split/aggregate step, per-segment values extracted from rasters must be unchanged (regression on legacy bug §9).
4. **CRS mismatch:** a DTM in EPSG:32748 with config EPSG:32749 and `auto_reproject: false` must raise.
5. **DSM refusal:** `surface_type: DSM` must raise.
6. **Routing:** toy graph with known optimal Steiner arborescence; the heuristic cost must be ≤ 2× optimal and equal on trivial cases. Ungated sekat must make a target unreachable.
7. **Head-aware cost:** on a graph with a short uphill path and a longer flat path, a large λ must select the flat path.
8. **AHP:** a known consistent matrix gives CR ≈ 0; an inconsistent one fails.
9. **Pump sizing:** hand-calculated P for a single station matches within 1%.
10. **Pilot regression:** on the pilot sub-KHG fixture, `per_target` mode must reproduce legacy route geometries (Hausdorff distance below tolerance) once legacy bugs are excluded. Document any intentional differences.

---

## 9. Known legacy bugs: do not port

1. **Mixed CRS** (EPSG:32748 vs 32749) between DTM and vectors.
2. **Feature-count `majority`** used as if length-weighted (QGIS Aggregate).
3. **Summing per-segment means/max** (`cpwi_mean`, `flow_max` set to `sum` in the peat-depth Aggregate), which inflates values for split segments.
4. **Fixed flow-accumulation thresholds (1.5 / 3.0)** applied to cell counts. Use normalisation (§5, Stage 6).
5. **Full buffer including canal water** for moisture extraction. Use the ring buffer.
6. **Equal-score ties** in burn frequency (2x and 3x+ both scored 3). Use the numeric count.
7. **Concession mixed into need score.** Keep it as a feasibility filter.
8. **Centroid targets** instead of the upstream-most pool.
9. **Console globals and layer-role swaps** (`start` vs `muara`). All inputs are explicit, named parameters.
10. **0.5 m contour interval.** Use `dA_m` (default 0.40 per PP 57/2016) consistently.

---

## 10. Milestones

1. **M1:** Skeleton, config models, I/O validation, Stage 1 + tests 4–5.
2. **M2:** Stages 2 and 4 (topology, segmentation) + QA layers.
3. **M3:** Stage 3 (hydro-conditioning) on a tiled pilot DTM.
4. **M4:** Stage 5 profiles + Stage 7 sekat (gap analysis + placement) + test 1.
5. **M5:** Stage 6 prioritisation + sensitivity + tests 2, 3, 8.
6. **M6:** Stages 8–9 network and routing + tests 6–7, 10.
7. **M7:** Stage 10 pumps + test 9; Stage 11 report.
8. **M8a (done):** QGIS Processing provider + headless `qgis_process` run.
10. **M9:** Stage 12, optional canal blocking optimisation (Urzainki et al. 2020): solver port with packaged data, canal-level model, GA/SA/greedy search, optional stage with `skipped` status, wizard card, tests. See §5.
9. **M8b:** QGIS plugin wizard (§7b): engine contract and tests, then view-model, UI, QML styles. Design reference: `docs/ui_prototype/Main.dc.html` (approved prototype).

At the end of each milestone: a short summary, a list of assumptions, and open TODOs.

---

## 11. Open questions: ask the human, do not guess

1. DTM vertical RMSE and vertical datum; datum of river water levels.
2. Source of dry-season river water levels (TMA stations? tidal influence?).
3. Conveyance mode: pumping into canals (open channel) or through pipe/hose?
4. Pump specifications: capacity, max head per unit, efficiency.
5. `uphill_penalty_lambda`: derive from energy cost, or set by KLH preference?
6. Canal-to-peat `influence_distance_m` (to be calibrated against `tma_obs` / dipwells).
7. Criterion weights, or the AHP matrix, and who signs off on them.
8. Concession handling: exclude, flag, or ignore?
9. Breach max distance and min/max sekat spacing.
10. ~~Target QGIS version~~ Decided: QGIS 4.x for training (LTR 3.x optional later). Still open: licence for the repository; whether KLH machines may `pip install` into QGIS's Python.
13. Stage 12: who sets `optimise.transmissivity_multiplier`, `et_mm_day`, `dry_days` and `canal_drawdown_m` for a real KHG, and is the Urzainki peat table (boreal Päivänen retention) acceptable as the starting table for tropical peat?
12. Hydro backend (deferred): is Whitebox Workflows' free tier sufficient (tools and licence), or do we keep WhiteboxTools?
11. Format and units of the neraca air output (confirm `deficit_mm` per sub-KHG and design period), when it is available. Where it is not, who sets `specific_yield`, `water_table_rise_m` and `pumping.design_period_days`?

---

## 11b. Proposed defaults (answers offered, not decisions)

`configs/proposed_defaults.yaml` offers a value for most of §11 questions 3, 4, 5, 8, 9 and the null parameters of Stages 2, 3, 6, 7, 9 and 10, so a trial run can proceed. Each is HIGH (already in a KLH document), MED (literature, site varies), LOW (engineering judgement) or POLICY (a choice, not a measurement); see `docs/proposed_defaults.md`. Still open and **not** proposed: questions 1 and 2 (datum, RMSE, river levels: facts about the data), 7 (sign-off on weights), 10 (licence, `pip install` on KLH machines), 11 (neraca air format), 12 (hydro backend), 13 (Stage 12 values; `transmissivity_multiplier` has no defensible default).

## 12. References

- **[Barnes2014]** Barnes, R., Lehman, C., & Mulla, D. (2014). Priority-flood: An optimal depression-filling and watershed-labeling algorithm for digital elevation models. *Computers & Geosciences*, 62, 117–127.
- **[Chen2010]** Chen, Y., Yu, J., & Khan, S. (2010). Spatial sensitivity analysis of multi-criteria weights in GIS-based land suitability evaluation. *Environmental Modelling & Software*, 25(12), 1582–1591.
- **[Chow1959]** Chow, V. T. (1959). *Open-Channel Hydraulics*. McGraw-Hill.
- **[Dijkstra1959]** Dijkstra, E. W. (1959). A note on two problems in connexion with graphs. *Numerische Mathematik*, 1, 269–271.
- **[Dohong2018]** Dohong, A., Aziz, A. A., & Dargusch, P. (2018). A review of techniques for effective tropical peatland restoration. *Wetlands*, 38, 275–292.
- **[Garbrecht1997]** Garbrecht, J., & Martz, L. W. (1997). The assignment of drainage direction over flat surfaces in raster digital elevation models. *Journal of Hydrology*, 193, 204–213.
- **[Holmgren1994]** Holmgren, P. (1994). Multiple flow direction algorithms for runoff modelling in grid based elevation models: an empirical evaluation. *Hydrological Processes*, 8, 327–334.
- **[Holland1975]** Holland, J. H. (1975). *Adaptation in Natural and Artificial Systems*. University of Michigan Press.
- **[Karassik2008]** Karassik, I. J., Messina, J. P., Cooper, P., & Heald, C. C. (2008). *Pump Handbook* (4th ed.). McGraw-Hill.
- **[Kirkpatrick1983]** Kirkpatrick, S., Gelatt, C. D., & Vecchi, M. P. (1983). Optimization by simulated annealing. *Science*, 220(4598), 671–680.
- **[Kou1981]** Kou, L., Markowsky, G., & Berman, L. (1981). A fast algorithm for Steiner trees. *Acta Informatica*, 15, 141–145.
- **[Lindsay2016a]** Lindsay, J. B. (2016). Efficient hybrid breaching-filling sink removal methods for flow path enforcement in digital elevation models. *Hydrological Processes*, 30(6), 846–857.
- **[Lindsay2016b]** Lindsay, J. B. (2016). The practice of DEM stream burning revisited. *Earth Surface Processes and Landforms*, 41(5), 658–668.
- **[Malczewski2006]** Malczewski, J. (2006). GIS-based multicriteria decision analysis: a survey of the literature. *International Journal of Geographical Information Science*, 20(7), 703–726.
- **[Mays2011]** Mays, L. W. (2011). *Water Resources Engineering* (2nd ed.). Wiley.
- **[Mehlhorn1988]** Mehlhorn, K. (1988). A faster approximation algorithm for the Steiner problem in graphs. *Information Processing Letters*, 27(3), 125–128.
- **[Neteler2008]** Neteler, M., & Mitasova, H. (2008). *Open Source GIS: A GRASS GIS Approach* (3rd ed.). Springer.
- **[Ritzema2014]** Ritzema, H., Limin, S., Kusin, K., Jauhiainen, J., & Wösten, H. (2014). Canal blocking strategies for hydrological restoration of degraded tropical peatlands in Central Kalimantan, Indonesia. *Catena*, 114, 11–20.
- **[Saaty1980]** Saaty, T. L. (1980). *The Analytic Hierarchy Process*. McGraw-Hill.
- **[Takahashi1980]** Takahashi, H., & Matsuyama, A. (1980). An approximate solution for the Steiner problem in graphs. *Mathematica Japonica*, 24(6), 573–577.
- **[Tarboton1997]** Tarboton, D. G. (1997). A new method for the determination of flow directions and upslope areas in grid digital elevation models. *Water Resources Research*, 33(2), 309–319.
- **[Urzainki2020]** Urzainki, I., Laurén, A., Palviainen, M., Haahti, K., Budiman, A., Basuki, I., Netzer, M., & Hökkä, H. (2020). Canal blocking optimization in restoration of drained peatlands. *Biogeosciences*, 17, 4769–4784. https://doi.org/10.5194/bg-17-4769-2020 (code: LukeEcomod/blopti, MIT).
- **[Urzainki2023]**, **[Hooijer2005]**, **[Cobb2019]**, **[Haman2017]**, **[IPEX-PVC]**, **[Meadows2024]**, **[PanduanKLH]**: sources of the proposed defaults, see `docs/references.md`.
- **[PP57-2016]** Peraturan Pemerintah No. 57 Tahun 2016 tentang Perubahan atas PP No. 71 Tahun 2014 tentang Perlindungan dan Pengelolaan Ekosistem Gambut.
- **[KHG-SKSS-2021]** Tim Departemen Teknik Geodesi UGM. *Laporan Akhir KHG Sungai Kahayan – Sungai Sebangau* (2021): sekat spacing `js = dA / i_lahan`, sekat height eq. 4.18, IPG metric (§5.3.4).

> Verify volume/page details against the originals before any formal citation.

## 13. Future improvements

- **Method comparison.** Run the default scoring and the KLH scoring on the same data and show how much of the selection they share (overlap as a map plus a short summary), so trainees see why the module differs from the guide. The settings fingerprints already say what changed between runs; what is missing is storing two result sets side by side.
- **Processing algorithms** for the moisture and burn-scar downloads, so they run in `qgis_process` and graphical models.
- **Before and after monitoring.** Re-run the moisture download after sekat are built and compare at the sekat sites.
- **Field package.** Export sekat, routes and gates for QField, GPX or KML.
