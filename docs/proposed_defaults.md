# Proposed defaults for the open questions

**These are proposals, not team decisions.** They exist so a trial run can proceed. Nothing uses them unless a run
config opts in with `preset: proposed_defaults.yaml` (path relative to that config). The preset fills only values the run
config leaves null, so anything you type wins. Every value taken from it shows up as a warning on its stage and in
`run_report.md`.

Confidence: **HIGH** already in a KLH document; **MED** literature, varies by site; **LOW** engineering judgement with no
retrieved source (replace before real use); **POLICY** a choice, not a measurement.

## Values in the preset

| Key | Value | Conf. | Why |
|---|---|---|---|
| `run.clip_margin_m` | 600 | MED | Block effects reach about 600 m from a canal (Urzainki 2023); a margin of that size keeps edge effects out of the sub-KHG. |
| `topology.snap_tolerance_m` | 1.0 m | HIGH | Legacy `NODE_TOL`. Larger snaps appear in `qa_topology_dangles` for review. |
| `topology.canal_classes` | `[primer, sekunder]` | HIGH | KLH guide step 1.2: analyse primary and secondary canals only. The full canal set stays in `inputs_clipped_canals` because river mouths are found on it (step 8.2). |
| `topology.river_buffer_m` | 30 m | HIGH | KLH guide step 8.2: river mouths are found with a 30 m canal buffer, so a river that stops short of a canal still supplies it. |
| `topology.source_snap_m` | 50 m | HIGH | Legacy `SNAP_MUARA`: with the class filter, river points found on a left-out canal must lie within 50 m of the kept network. |
| `hydro.breach_max_dist_cells` | 100 | LOW | About 100 m at 1 m LiDAR cells. Use about 12 for 8 m DEMNAS cells. No source retrieved (the Whitebox manual page was unavailable). |
| `sekat.max_spacing_m` | 500 m | HIGH | KLH workflow: sekat spacing about 500 m. |
| `sekat.min_spacing_m` | 100 m | LOW | The legacy script used 500 m as the *minimum*. That overrides the head rule (`js = dA/i`) wherever the slope exceeds 0.08 %, so 100 m is proposed instead. The team should decide which rule governs. |
| `sekat.min_new_spacing_m` | 500 m | POLICY | KLH guide (JARAK_MIN): no two new sekat closer than 500 m along a canal. Adopted 2026-10-28 at users' request. On land steeper than dA/500 it overrides the head rule and gives fewer sekat. |
| `sekat.dedup_tol_m` | 100 m | POLICY | A proposal within 100 m of an existing sekat, or of one on another canal, is dropped. Adopted 2026-10-28 at users' request; the legacy script used 50 m. |
| `sekat.snap_tolerance_m` | 30 m | MED | The 30 m the KLH workflow uses to match river points to canals. |
| `sekat.target_rise_share` | 0.9 | POLICY | Balance between the number of sekat and the rewetting they give: keep the fewest head-rule sekat that give 90 % of the canal water-level rise of all of them [Urzainki2020 canal-rise objective]; the rest go to `sekat_low_benefit`. Sugihan-Lumpur 2026-10-27: 54 of 123 sekat. |
| `sekat.balance_drawdown_m` | 1.0 m | LOW | Dry-season canal level below the land, used only to rank the sekat. The ranking barely moved between 0.8 and 1.2 m at Sugihan-Lumpur (`scripts/sekat_spacing_check.py`). |
| `prioritise.criteria.*.weight` | 0.25 each | POLICY | Equal weights, as in legacy scoring. AHP is the alternative (`weights_mode: ahp`). Who signs off is still open. |
| `prioritise.upstream_buffer_m` | 50 m | HIGH | KLH workflow extraction buffer (step 6.1). |
| `prioritise.klh_min_score` | 10 | POLICY | KLH guide step 7.2 (score of 10 or more, marked temporary there). Used only with `weights_mode: klh`. The class breaks of that mode (`klh_cpwi_breaks`, `klh_flow_breaks`) are not proposed: the guide's 0.8/1.5 and 1.5/3.0 depend on the units of its own rasters and it says to fit them to the quartiles of each KHG. |
| `prioritise.feasibility.concession_mode` | `flag` | POLICY | Nothing is dropped silently; the reviewer decides. |
| `pumping.conveyance` | `canal` | POLICY | Uses the existing network; pipes need new infrastructure. |
| `pumping.manning_n` | 0.035 | MED | Earth canal, winding, dense weeds or aquatic plants: 0.030 to 0.040 (Chow 1959, Table 5-6). |
| `pumping.hazen_williams_c` | 140 | MED | HDPE, conservative; PVC is 150 (IPEX). Used only in pipe mode. |
| `pumping.pump_efficiency` | 0.65 | MED | Lower end of the normal 65 to 80 % range (Haman 2017). |
| `pumping.max_head_per_station_m` | 5.0 m | LOW | Typical of low-lift axial or mixed-flow pumps. Replace with the real pump curve. |
| `pumping.pump_capacity_m3s` | 0.10 | LOW | About 100 L/s per unit. Replace with the procurement specification. |
| `pumping.uphill_penalty_lambda` | 1000 | POLICY | One metre of lift costs as much as 1 km of canal. Compare 100, 1000 and 10000 in Stage 9 and see how the routes change. |
| `pumping.influence_distance_m` | 600 m | MED | Reach of block effects (Urzainki 2023). Effects on nearby wells are smaller, so calibrate with `tma_obs`. It scales the served area and therefore the pump demand. |
| `pumping.specific_yield` | 0.30 | MED | Near-surface peat 0.29 to 0.71 (Hooijer 2005, as cited), below 0.15 with a deep water table (Cobb 2019). The value matters most in `specific_yield` demand mode. |
| `pumping.water_table_rise_m` | 0.40 m | LOW | Restores a 0.8 m dry-season water table to the 0.4 m limit of PP 57/2016. Set per site. |
| `pumping.design_period_days` | 120 | MED | Dry season July to October (Ritzema 2014). Used only where the priority table has none. |

## Budget unit prices (`budget.*`)

Stage 12 prices the quantities of the run (core/budget.py). Each price is `[low, central, high]` in rupiah of its own year, **not adjusted for inflation**. Sekat, canal closure and wells follow the cost standard Perdirjen PPKL P.16/PPKL/PKEG/PKL.0/10/2022 (6 October 2022, replacing P.4/PPKL/SET/PKL.0/7/2021), read from `re-peat/docs/reference/Buku Perdirjen P.16 Tahun 2022 (Daftar Isi) 2.pdf` into `re-peat/docs/reference/perdirjen_p16_2022_unit_costs.csv` by `re-peat/tools/extract_perdirjen_p16.py`: low = self-managed (swakelola) price, high = contractual price, central = their midpoint (penimbunan has a contractual price only). Pasal 9 of the standard calls these estimates that local market prices may exceed. Revegetation, pumps and fuel are not in the standard; their prices come from news and listings (found by web search on 2026-10-27; from search summaries, not all pages re-read) and the run report totals them apart (`budget.by_basis`: `standard` and `outside_standard`).

**Register for checking.** Every figure below, plus the two that were found but not used, is a row of `repeat_pump/data/budget_sources.csv`: the figure as quoted, place and period, source, URL, date accessed, how it was retrieved (all from search summaries) and a status (`to verify`, `unconfirmed`, `assumption`, `obtain from KLH`). Whoever checks a figure on its page fills `verified_by`, `verified_on` and `verified_figure`, and changes the price in the preset if the figure differs. Each run copies the register next to its `budget.csv`, and the HTML report lists it under the budget chart.

| Key | Proposed | Confidence | Source |
|---|---|---|---|
| `sekat_standard_idr` | 76.5, 81.6, 86.7 million per block | STANDARD | Perdirjen PPKL P.16/2022, Lampiran I, code KSE-3L-P2 (wooden three-layer block with spillway, canal 9-11 m): Rp 76,495,000 self-managed (low), Rp 86,714,000 contractual (high), central = midpoint. The Direktorat prices secondary-canal blocks at the contractual value in its 2026 designs (Pelalawan-Riau, Mei 2026: Rp 86.714.000). Applies to primary and secondary canals and blocks of unknown class; no source prices a primary-canal block, so this is a lower bound there. Excludes equipment set, SMKK and mobilisation. Earlier news figures (Rp 12 and 18 juta) and the 2018 programme (Rp 19-29 juta) stay in the register as cross-checks |
| `sekat_tertiary_idr` | 41.8, 44.3, 46.7 million per block | STANDARD | P.16/2022 code KSE-2L-P-4 (wooden two-layer block with spillway, canal 5-7 m). The Direktorat uses Rp 46.694.000 per tertiary block in 2026. Used for blocks on tertiary canals; null falls back to `sekat_standard_idr` |
| `sekat_reinforced_idr` | 27.1, 30.8, 34.5 million per block | STANDARD | P.16/2022 code KSE-PK-P-1L (small concrete block with spillway, canal up to 3 m); larger concrete types Rp 75-169 juta. No run keeps a concrete block |
| `canal_closure_idr_per_km` | not priced | none | P.16/2022 prices penimbunan per fill segment of 50, 100, 150 or 300 m (Rp 70.9 juta to Rp 918 juta, contractual only), in protected and conservation areas (Pasal 1, 5). The quantity (km of canal in `close_canals` sub-KHG) is the whole canal length, not the stretches to be filled, so a per-km price would price every canal as one continuous fill. The 2019 conservation deck lists 143 fill points (2017-2018) without cost; the two 2026 Direktorat designs contain no backfilling. The quantity is reported unpriced until the stretches to fill are defined |
| `revegetation_idr_per_ha` | 8, 12.1, 15 million per ha | OUTSIDE THE STANDARD | BRG: Rp 8-10 juta/ha ([ANTARA](https://www.antaranews.com/berita/552739/brg-biaya-restorasi-gambut-rp12-juta-per-hektar)); village cost study Rp 12,1 juta/ha ([Jurnal Hutan Tropis, ULM](https://ppjp.ulm.ac.id/journal/index.php/jht/article/download/11297/7270)); Sumsel first year Rp 15 juta/ha without labour ([Tempo](https://www.tempo.co/arsip/sumatera-selatan-revegetasi-gambut-di-lahan-1-000-hektare-nbsp--1272253)) |
| `well_idr` | 3.19, 3.57, 3.94 million per well | STANDARD | P.16/2022 code SBO-20-1 (simple well, PVC 1.5 inch, 20 m): Rp 3,189,000 self-managed, Rp 3,944,000 contractual. Deeper or cased wells to Rp 11.1 juta (SBO-40-4). Excludes drilling equipment, SMKK and mobilisation. The news figures (Rp 3 and 8-9 juta) remain in the register as cross-checks |
| `well_radius_m` | 200 m | LOW | re-peat docs/05-parameters.md (BRG module) |
| `pump_idr` | 15.5 million per unit | OUTSIDE THE STANDARD | 6-inch diesel irrigation pump, marketplace listing 2026 ([Tokopedia](https://www.tokopedia.com/find/diesel-pompa-air-sawah)) |
| `fuel_idr_per_l` | 23,554 to 24,886 per L | OUTSIDE THE STANDARD | Industrial diesel, MyPertamina reference, 1-14 and 15-31 October 2026 ([solardistro.com](https://solardistro.com/artikel/arsip-harga/)) |
| `fuel_l_per_kwh` | 0.3 | LOW | Engineering assumption for small diesel pump sets; no source retrieved |
| `pump_hours_per_day` | 12 | POLICY | Operating hours in the dry season |

For scale: BRG put hydrological restoration at about Rp 12 juta per ha over five years (World Bank and CIFOR range Rp 6-36 juta) ([ANTARA](https://www.antaranews.com/berita/552739/brg-biaya-restorasi-gambut-rp12-juta-per-hektar)).

## KLH guide and legacy-script parameters, and where they went

From the technical guide (Panduan Teknis GIS Rewetting KLH, Appendix A) and the two legacy scripts. "Opt-in" means the key is empty by default, so existing runs do not change.

| Guide / script | Value | In the module |
|---|---|---|
| Segment length (3.3) | 500 m | `segments.max_length_m`, default 500 |
| Sliver threshold (3.4) | 25 m | `segments.min_length_m`, default 25 |
| Stream-burn depth (4.1) | 2 m | `hydro.burn_depth_default_m`, default 2 (used where a canal has no depth) |
| Extraction buffer (6.1) | 50 m | `prioritise.upstream_buffer_m` (preset). With `weights_mode: klh` the moisture mean is also read in this full buffer, as in the guide |
| Canal classes (1.2) | primer, sekunder | `topology.canal_classes`, opt-in, in the preset |
| River-mouth buffer (8.2) | 30 m | `topology.river_buffer_m`, opt-in, in the preset |
| `SNAP_MUARA` | 50 m | `topology.source_snap_m`, opt-in, in the preset |
| `NODE_TOL` | 1 m | `topology.snap_tolerance_m`, in the preset |
| `JARAK_MIN` | 500 m | `sekat.max_spacing_m` (the head rule `js = dA/i` capped at 500 m, in the preset) and, if you want the guide's behaviour of never placing two new sekat closer than that, `sekat.min_new_spacing_m` (opt-in, not in the preset: it overrides the head rule on steep land) |
| `DEDUP_TOL` | 50 m | `sekat.dedup_tol_m`; the preset uses 100 m (users' request, 2026-10-28) |
| `SLOPE_MIN_PCT`, mode "tandai" | 5 %, mark only | `sekat.slope_reinforced_pct`, default 5: the type is marked, never used as a filter |
| `SLOPE_OFFSETS` | 6 and 10 m | `profiles.bank_offsets_m`, default `[6, 10]` |
| `SLOPE_ALONG` | -40 to +40 m | Roughly `profiles.smoothing_window_m` (median over 50 m along the canal), not a separate key |
| Priority threshold (7.2) | score >= 10 | `prioritise.klh_min_score` (with `weights_mode: klh`) |
| CPWI breaks 0.8 / 1.5, flow breaks 1.5 / 3.0 (7.1) | fixed | `prioritise.klh_cpwi_breaks`, `klh_flow_breaks`, required, never defaulted |
| `SNAP_START` | 150 m | Not needed: routing targets are nodes of the canal network, there is nothing to snap |
| `ANGLE_MIN`, `OSC_DIST` | 30 degrees, 300 m | Not needed: both exist to reject contour lines that run along the canal; placement walks the land profile and only a net rise of `dA` counts |
| Contour interval (2.3, 10.3) | 0.5 m | Replaced by `sekat.dA_m` (0.40 m, PP 57/2016), without vector contours |

## Stage 11 (optional block optimisation)

The stage stays off (`optimise.enabled: false`) until switched on. The preset gives values to start from, so switching it on runs at once:

| Key | Proposed | Confidence | Why |
|---|---|---|---|
| `optimise.n_blocks` | 10 | POLICY | How many of the kept sekat the budget allows; read the cost per sekat off the stage 12 budget |
| `optimise.max_evaluations` | 500 | LOW | At least twice the GA population (30); more is slower and rarely better |
| `optimise.canal_drawdown_m` | 1.0 m | MED | The same dry-season canal level as `sekat.balance_drawdown_m` |
| `optimise.grid_m` | 100 m | LOW | Groundwater objectives only; 50 m is about 4 times slower |
| `optimise.dry_days` | 30 | LOW | Length of the dry spell simulated from a wet start |
| `optimise.et_mm_day` | 3.7 mm/day; per KHG from its data | MED | A KHG folder fills its own value: mean MOD16 evapotranspiration of June to September in `03_neraca/inputs/balance_mod16_dekad.csv` (4.09 Sugihan-Lumpur, 3.72 Kampar-Gaung, 2018-2025) |

The peat properties are engine defaults, not preset values: `peat_table: tropical-small` and `bracket_tables: [tropical-large]` (Urzainki et al. 2023), so a groundwater result is reported as a range. The objective stays `canal_rise` (minutes); `pde` and `screen_then_pde` use the groundwater model and take tens of minutes per KHG (40 minutes for the Kampar-Gaung bracket run).

## Not in the preset: facts about the data

Fill these from the dataset's metadata. The preset never sets the datums. It suggests the DTM error (for a declared `inputs.dtm.source`) and the moisture direction under `suggested_facts`; both are marked as proposed. A value from the delivery always wins.

| Key | What to put | Notes |
|---|---|---|
| `inputs.dtm.vertical_rmse_m` | LiDAR: 0.1 to 0.3 m; DEMNAS: several metres. Suggested by source: lidar 0.3, deltadtm 0.49 (NMAD against KLHK LiDAR at Sugihan-Lumpur, repeat-dem benchmark), demnas 4.97 | LiDAR is well within 0.3 m (Meadows 2024). One field comparison of DEMNAS gave RMSE 4.97 m. With `dA` = 0.40 m the Stage 1 accuracy warning fires for any source with RMSE above 0.2 m, so head-based placement on DEMNAS is noise. Take the RMSE from the LiDAR delivery report when there is one. |
| `run.vertical_datum`, `inputs.rivers.vertical_datum` | Ask the data provider | DEMNAS heights are tied to the EGM2008-based geoid (INAGEOID2020). Do not assume a LiDAR delivery uses the same one. The river levels must use the same datum. |
| `inputs.moisture.higher_is_wetter` | `true` for NDMI and OPTRAM-type indices | Depends on the index the upstream team delivered. |

## Not proposed

- **`optimise.transmissivity_multiplier`.** It changes the result about 100-fold and no measured transmissivity exists for any of our KHG. It only scales the boreal table (`peat_table: urzainki2020`); the default tropical tables do not use it.
- **Neraca air format, sign-off on weights, licence, `pip install` on KLH machines, hydro backend.** These are decisions, not values.

## Sources read

Ritzema et al. 2014 (head difference below dams under 0.5 m; dry season July to October); Urzainki et al. 2023 (about 600 m reach); the KLH Panduan Teknis and Workflow documents and the legacy scripts (500 m, 50 m, 30 m, 1 m, equal weights); Haman 2017 (pump efficiency); Chow 1959 Table 5-6 as reproduced on drainagecalculators.com; IPEX PVC hydraulics bulletin; specific yield through a 2026 Scientific Reports paper that cites Hooijer and Cobb; Meadows et al. 2024 (LiDAR accuracy); a DEMNAS accuracy study (RMSE 4.97 m). Full list in `docs/references.md`.
