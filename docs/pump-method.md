# Rewetting interventions: the repeat-pump method

Methodological report, repeat-pump, 2026-10-27. Diagram: [figures/pump_method.drawio](figures/pump_method.drawio) (open in draw.io; rebuilt by `docs/figures/make_pump_method.py`; PNG copy [figures/pump_method.png](figures/pump_method.png)). Evidence for the sekat balance: [reports/sekat_neraca_investigation.md](reports/sekat_neraca_investigation.md). Proposed values and their sources: [proposed_defaults.md](proposed_defaults.md). Weights and thresholds are provisional and not agreed with the team.

## 1. What it delivers

For the highest-ranked sub-KHG of one KHG:

- **Sekat kanal (canal blocks):** where to build them on the primary and secondary canals, the fewest that hold 90 % of the canal water all head-rule blocks would hold, and the canal stretch each one holds back.
- **Interventions per sub-KHG:** for every sub-KHG of the KHG, the treatment that fits (close canals, revegetation and fire readiness, sekat with water supply or deep wells, sekat, maintain) and the reasons.
- **Budget estimate:** quantities from the run times proposed unit prices, low, central and high, with the price sources in a register to verify.
- **Pumping (optional):** routes from river intakes to the targets and pump stations, when the rivers carry a perennial flag or a dry-season level.
- **Report:** run_report.md/json, an interactive HTML page, and KLH-style print layouts A0 to A4.

## 2. Where it sits in the chain

| Step | Module | Gives repeat-pump |
|---|---|---|
| 1. KHG inputs | repeat-prioritisation `subkhg.prepare_inputs` | canals, rivers, existing sekat in `00_inputs/` |
| 2. DTM | repeat-dem | the DTM (LiDAR where it exists) |
| 3. Sub-KHG units | repeat-delineation | `02_delineation/subkhg_units.gpkg` |
| 4. Neraca air | repeat-neraca | KHG deficit, monthly balance and SiTMAT stations (`neraca_map.gpkg`) |
| 5. Sub-KHG ranking | repeat-prioritisation `subkhg` | order of the sub-KHG and the indicators (`unit_prioritas.gpkg`, `subkhg_priority.csv`) |
| 6. Interventions | repeat-pump | this report |

## 3. Inputs

| Input | Source | Gives |
|---|---|---|
| DTM | `01_dem` (LiDAR first, then DeltaDTM, DEMNAS); `inputs.dtm.source` | land profile along canals, flow accumulation; the suggested vertical error (lidar 0.3 m, deltadtm 0.49 m, demnas 4.97 m) |
| Canals | `00_inputs/canals.gpkg` (`KODE_KANAL` 1 primer, 2 sekunder, 3 tersier, via `topology.canal_class_map`) | the network; tertiary canals optional (`topology.canal_classes`) |
| Existing sekat | `00_inputs/blocks.gpkg` | blocks already in place |
| Rivers | `00_inputs/rivers.gpkg` | flow direction; pump intakes when perennial or with a dry-season level |
| Sub-KHG and ranking | `02_delineation`, `04_prioritisation/subkhg_priority.csv` | which sub-KHG are analysed (top n) |
| Moisture | latest NDMI in the KHG folder | dryness of each canal segment |
| Burn area, peat depth | `_data` (optional) | criteria of the segment need score |
| Sub-KHG indicators | `04_prioritisation/unit_prioritas.gpkg` | protected share, NDMI, burnt share, canal reach, distance to water, canal density |
| Neraca map | `03_neraca/runs/balance/neraca_map.gpkg` (`repeat-neraca-map`) | KHG deficit; monthly balance and stations for the report |
| Unit prices | `budget.*` in the preset; sources in `repeat_pump/data/budget_sources.csv` | the budget |

`scripts/khg_run_config.py <KHG folder>` writes the run config from what the folder holds; nothing is typed by hand.

## 4. Processing

Twelve stages (`repeat_pump/core`); the report is always the last. Each records a fingerprint of its settings and input files; a changed setting or input file reruns that stage and everything after it. The run stops for review after stages 2, 6 and 9.

**Stages 1 to 5. Network and terrain.** Stage 1 clips every input to the selected sub-KHG and checks CRS, DTM type and accuracy. Stage 2 keeps the chosen canal classes, snaps gaps and reports dangles. Stage 3 burns the canals into the DTM and computes flow accumulation (WhiteboxTools). Stages 4 and 5 cut canals into 500 m segments and sample the land profile along each. The flow direction of a canal comes from its slope, else its river connection, else flow accumulation (downstream is the end where at least 1.5 times more water collects).

**Stage 6. Need score per segment.** Dryness (moisture in a ring buffer outside the canal water), upstream contribution, burn frequency and peat depth, min-max normalised and weighted (direct or AHP, with a one-at-a-time sensitivity check). A criterion without its layer gets weight 0 and the others are rescaled. The KLH guide's 1-to-3 scoring is available as `weights_mode: klh`.

**Stage 7. Sekat.**

1. *Head rule.* Walking up a canal, a block goes where the land has risen dA = 0.40 m since the last block (PP 57/2016 water-table limit); spacing js = dA / slope, at most 500 m. Existing sekat within 30 m of an analysed canal count as built. A block on a slope of 5 % or more is marked reinforced.
2. *Balance.* Each block holds water at its land level minus dA and raises every canal station upstream that lies lower, from a dry-season level 1.0 m below the land, never above the land surface (canal-rise objective, Urzainki et al. 2020). Blocks are ranked by the extra rise each adds, and the fewest that give `target_rise_share` (0.9) of the rise of all of them are kept; `max_blocks` caps the number for a budget. The rest go to `sekat_low_benefit`.
3. *Reach.* For every kept block, the canal stretch whose final level that block sets, drawn from the block upstream, with its rise, depth below the land and share inside the burn area (`sekat_reach`).

**Stages 8 to 10. Pumping (optional).** A network of canals, rivers and sekat; head-aware least-cost routes from river intakes to the highest node of each target cluster (Steiner tree or one route per target), with gates where a route crosses a sekat; pump demand from the deficit and specific yield. Routes are drawn from the intake to the target.

**Stage 11. Optimisation (optional).** Chooses n of the kept sekat by genetic algorithm, simulated annealing or greedy search, scored by canal rise or by a 2D groundwater model. The peat properties of the groundwater model are a choice (`optimise.peat_table`): the boreal table of Urzainki et al. (2020), which needs a transmissivity multiplier, or the two tropical sets of Urzainki et al. (2023). `bracket_tables` re-scores the chosen layout with other tables, to report a range.

**Stage 12. Interventions, budget, report (always last).**

*Interventions.* Each sub-KHG gets the first class whose rule holds:

| Class | Rule |
|---|---|
| Close or backfill canals | protected peat function share ≥ 0.5 |
| Revegetation and fire readiness | dry (NDMI < 0.3) or burnt (share ≥ 0.25), and canals reach less than 0.4 of the unit |
| Sekat and water supply | canals reach ≥ 0.4, sekat hold less than 0.5 of the deficit, permanent water within 5 km |
| Sekat and deep wells | as above but water farther than 5 km, and dry or burnt |
| Sekat | canals reach ≥ 0.4 |
| Maintain | none of the above |

Water held by the sekat of a unit = canal rise × specific yield 0.15 (the neraca air value) × a lateral reach of 600 m (Urzainki et al. 2023). Units not analysed for sekat use the KHG deficit (at least 50 mm). For a closed-canal unit the class it would get without the protected-peat rule is also reported.

*Budget.* Quantities per sub-KHG: the kept sekat by type, or the KLH IPG estimate of missing blocks where no sekat were placed; km of canal to close (canal density × peat area); hectares ever burnt to revegetate; deep wells (burnt area ÷ π × 200²); pumps and fuel when pumping is on. Each is priced at low, central and high unit prices; an empty price leaves the quantity unpriced.

*Report.* run_report.md/json; `repeat-pump report-html` writes one self-contained page; the QGIS plugin and `scripts/make_layouts.py` write KLH print layouts.

## 5. Decisions and their evidence

**Decision 1. Balance at 90 %.** On the LiDAR network of Sugihan-Lumpur, past 90 % the water each extra block holds falls 2.4 to 5 times; balanced layouts hold 1.9 to 2.5 times more water per block than the full head-rule layout and keep every gap above 200 m without a separate spacing rule (investigation report, results and point 1). KLH asked for fewer, not closer, blocks for budget reasons; the share stays configurable.

**Decision 2. Primary and secondary canals by default, tertiary optional.** The KLH guide analyses primary and secondary canals. With tertiary canals the balanced layouts hold 2.8 to 3.3 times the water (investigation report, point 3); whether to include them is the team's choice per run (`topology.canal_classes`).

**Decision 3. Flow direction from flow accumulation.** 375 of 499 canals at Sugihan-Lumpur could be oriented neither by slope nor by a river. Orienting them by flow accumulation gives the same blocks 6.5 % more water held (5.73 against 5.37 million m³).

**Decision 4. BlueBook 2026 sekat are not a reference.** They are not validated; every layout is scored on one reference network instead (LiDAR, all classes, existing sekat in place).

**Decision 5. Tropical peat tables for the groundwater model.** No measured transmissivity exists for our KHG. The boreal table is 100 to 1,000 times below tropical values (repeat-neraca/docs/tropical-peat-hydraulic-parameters.md). Use `tropical-small` with `bracket_tables: [tropical-large]` and report a range.

## 6. Parameters

| Key | Value | Kind |
|---|---|---|
| `sekat.dA_m` | 0.40 m | PP 57/2016 |
| `sekat.max_spacing_m` | 500 m | KLH guide (`JARAK_MIN`) |
| `sekat.min_spacing_m` | 100 m | proposed |
| `sekat.target_rise_share` | 0.9 | policy, proposed |
| `sekat.balance_drawdown_m` | 1.0 m | proposed |
| `sekat.slope_reinforced_pct` | 5 % | KLH guide |
| `topology.canal_classes` | primer, sekunder | KLH guide |
| `profiles.direction_fallback` | flow_acc | decision 3 |
| `interventions.*` | 0.5, 0.4, NDMI 0.3, 0.25, 5,000 m, 0.5, 50 mm, Sy 0.15, 600 m | policy, proposed |
| `budget.*` | see proposed_defaults.md, "Budget unit prices" | proposed, sources to verify |
| `optimise.*` | n_blocks 10, max_evaluations 500, canal drawdown 1.0 m, grid 100 m, dry spell 30 days, ET from the KHG's MOD16 June-September (4.09 / 3.72 mm/day); peat table tropical-small, bracket tropical-large | proposed (stage 11 stays off until switched on) |

## 7. Outputs

In `_khg/<code>_<name>/05_pump/`:

| File or layer | Content |
|---|---|
| `<name>.gpkg` | every stage's layers: `canals_clean`, `canal_segments`, `sekat_proposed`, `sekat_low_benefit`, `sekat_reach`, `sekat_existing_assessed`, `interventions`, `budget`, and with pumping `pump_routes`, `pump_stations` |
| `interventions.csv` | class, reasons, class without the protected rule, held and deficit water per sub-KHG |
| `budget.csv`, `budget_sources.csv` | quantities and costs per sub-KHG and item; the price register with the run's values |
| `run_report.md`, `run_report.json` | counts, warnings, balance, interventions, budget, values taken from the preset |
| `report.html` | map (interventions or dry-season balance, sekat, reaches with an animation, burnt area, stations), rewetting curve against blocks or rupiah, budget with sources, neraca charts, sub-KHG table; English and Bahasa Indonesia |
| print layouts | KLH sheets A0 to A4, landscape and portrait, with a budget table; templates in `qgis_plugin/repeat_pump_qgis/resources/layouts/` |

## 8. Results (2026-10-27)

Both KHG on LiDAR, primary and secondary canals, sekat only (no river qualifies as a pump source), the three highest-ranked sub-KHG analysed.

| | Sugihan-Lumpur | Kampar-Gaung |
|---|---|---|
| Canals analysed | 499 | 192 |
| Head-rule sekat, kept at 90 % | 124, 54 | 53, 29 |
| Existing sekat on an analysed canal | 109 of 232 | 82 of 226 |
| Canal held back by the kept sekat | 108.6 km (55.5 km inside burnt area) | 64.8 km (9.4 km) |
| Water held / deficit of the selected sub-KHG | 3.27 / 230.7 million m³ (1.4 %) | 1.91 / 4.1 million m³ (46.7 %) |
| Interventions (sub-KHG) | 21 close canals, 3 revegetation, 3 sekat and water, 2 sekat and wells, 1 sekat | 10 close canals, 12 sekat, 4 maintain |
| Budget, billion Rp (low / central / high) | 406.1 / 636.3 / 769.8 | 4.2 / 6.4 / 6.4 |
| Largest budget item | revegetation, 45,088 ha (545.6) | KLH IPG sekat estimate, 324 blocks (5.8) |
| Canal closure, not priced | 2,176.5 km | 880.8 km |
| Sekat cost per m³ held | 297 Rp | 273 Rp |

Sources: `run_report.json`, `interventions.csv` and `budget.csv` of each run.

- **Sekat alone do not close a large deficit.** At Sugihan-Lumpur (290 mm deficit) the kept sekat hold 1.4 % of it. Blocking keeps water that would drain away; it does not supply the dry season, so most sub-KHG there get another treatment. At Kampar-Gaung the 2026 dry season left a deficit of only 7.1 mm.
- **Stage 11 bracket, Kampar-Gaung** (illustration in `variants/stage12_peat_bracket/`): the chosen 10-block layout keeps 170 to 235 ha m of peat from drying with the two tropical tables, 2.7 to 3.8 times a random layout; the boreal table at ×100 gives 31. The highest-need segments (rule-based) did as well as or better than the search (230 to 261), because `screen_then_pde` searches on canal rise.

## 9. Limits

- The canal-rise objective has no flow or seepage; on flat, connected networks a few blocks take most of the rise.
- Specific yield 0.15, reach 600 m and drawdown 1.0 m set the volumes, not the order of the blocks.
- The LiDAR vertical error (0.3 m) is suggested, not from the delivery.
- The lateral spread of held water toward burnt land is the fixed 600 m band, not modelled; the groundwater model of stage 11 depends on peat properties nobody has measured here.
- Budget prices come from news and journal search summaries; none is verified on its page, the KLH cost standard (Perdirjen PPKL P.4/2019) was not found online, and canal closure has no price.
- Pumping has not run on a real KHG.
- Kampar-Gaung's sub-KHG carry the id `71`; check the KHG ids of that folder.

## 10. How to run

```bash
# one KHG folder (writes 05_pump/run_config.yaml from what the folder holds; --tertiary adds tertiary canals)
python scripts/khg_run_config.py $REPEAT_KHG/16.02.01_sugihan_lumpur
repeat-pump run --config $REPEAT_KHG/16.02.01_sugihan_lumpur/05_pump/run_config.yaml --accept 2 --accept 6
repeat-pump report-html --config $REPEAT_KHG/16.02.01_sugihan_lumpur/05_pump/run_config.yaml
python-qgis.bat scripts/make_layouts.py --config <run_config.yaml> --out <folder> --papers A0 A3 --pdf

# every KHG folder under _khg
python scripts/khg_run_config.py --all $REPEAT_KHG
```

Set `REPEAT_DATA`, `REPEAT_KHG` and `REPEAT_HUB` first. In QGIS the wizard does the same: choose the KHG, Run to the next review, then Export HTML report and Make map layout.

## 11. Sources

Full references in [references.md](references.md). Main ones: Urzainki et al. (2020), Biogeosciences 17, 4769-4784 (canal-rise objective, groundwater model); Urzainki et al. (2023), Biogeosciences 20, 2099-2116 (tropical peat parameters, lateral reach); PP 57/2016 (0.4 m water-table limit); Panduan Teknis GIS Rewetting KLH (guide steps, spacing, scoring); Malczewski (2006), Saaty (1980), Chen, Yu and Khan (2010) (scoring, AHP, sensitivity). Price sources: `repeat_pump/data/budget_sources.csv`.
