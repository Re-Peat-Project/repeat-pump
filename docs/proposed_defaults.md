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

Stage 12 prices the quantities of the run (core/budget.py). Each price is `[low, central, high]` in rupiah of its own year, **not adjusted for inflation**, found by web search on 2026-10-27. The figures come from the search summaries of the linked pages; the pages were not all re-read, so check a figure on its page before citing it. They are proposals for trial runs: replace them with KLH's own standard (Perdirjen PPKL P.4/PPKL/PKG/PKL.0/6/2019, *Standar Biaya Pembangunan Infrastruktur Pembasahan untuk Pemulihan Ekosistem Gambut*, which BPK audits against but whose figures were not found online) or contract values.

**Register for checking.** Every figure below, plus the two that were found but not used, is a row of `repeat_pump/data/budget_sources.csv`: the figure as quoted, place and period, source, URL, date accessed, how it was retrieved (all from search summaries) and a status (`to verify`, `unconfirmed`, `assumption`, `obtain from KLH`). Whoever checks a figure on its page fills `verified_by`, `verified_on` and `verified_figure`, and changes the price in the preset if the figure differs. Each run copies the register next to its `budget.csv`, and the HTML report lists it under the budget chart.

| Key | Proposed | Confidence | Source |
|---|---|---|---|
| `sekat_standard_idr` | 12, 18, 18 million per block | LOW-MED | Wooden block about Rp 12 juta ([Kompas, Timbunan Kanal Efektif Basahi Gambut](https://www.kompas.id/artikel/timbunan-kanal-efektif-basahi-gambut)); Rp 18 juta per block through community groups, Riau 2022 ([CyberNKRI](https://cybernkri.com/pemerintah-pusat-bangun-120-sekat-kanal-di-riau/)); 176 blocks for Rp 3 miliar at TN Sebangau, about Rp 17 juta each ([KSDAE](https://ksdae.menlhk.go.id/berita/9235/Pembuatan-176-Unit-Sekat-Kanal-Di-Taman-Nasional-Sebangau.html)) |
| `sekat_reinforced_idr` | 70 million per block | LOW | Concrete block "at least Rp 70 juta" (Kompas, same article) |
| `canal_closure_idr_per_km` | not priced | none | No published price per km of backfilled canal was found; BRG staff call backfilling more expensive than blocking ([detik](https://news.detik.com/berita/d-4002033/brg-berjibaku-timbun-kanal-di-lahan-gambut-warisan-orba)). The quantity (km) is reported |
| `revegetation_idr_per_ha` | 8, 12.1, 15 million per ha | LOW-MED | BRG: Rp 8-10 juta/ha ([ANTARA](https://www.antaranews.com/berita/552739/brg-biaya-restorasi-gambut-rp12-juta-per-hektar)); village cost study Rp 12,1 juta/ha ([Jurnal Hutan Tropis, ULM](https://ppjp.ulm.ac.id/journal/index.php/jht/article/download/11297/7270)); Sumsel first year Rp 15 juta/ha without labour ([Tempo](https://www.tempo.co/arsip/sumatera-selatan-revegetasi-gambut-di-lahan-1-000-hektare-nbsp--1272253)) |
| `well_idr` | 3, 8.5, 9 million per well | LOW | BRG 2017-2018 Rp 3 juta per well (news reports: [Kompas, Evaluasi Sumur Bor di Kalteng](https://www.kompas.id/artikel/evaluasi-sumur-bor-di-kalteng), [ANTARA Kalteng](https://kalteng.antaranews.com/berita/260788/brg-kalteng-bangun-2000-sumur-bor-di-lahan-gambut)); Kubu Raya Rp 8-9 juta at 16-20 m ([VOA](https://www.voaindonesia.com/a/kado-kecil-mahasiswa-ugm-untuk-pemukim-gambut/5026134.html)). A Rp 10 juta swamp-well figure could not be confirmed (the page was not readable) and is not used |
| `well_radius_m` | 200 m | LOW | re-peat docs/05-parameters.md (BRG module) |
| `pump_idr` | 15.5 million per unit | LOW | 6-inch diesel irrigation pump, marketplace listing 2026 ([Tokopedia](https://www.tokopedia.com/find/diesel-pompa-air-sawah)) |
| `fuel_idr_per_l` | 23,554 to 24,886 per L | MED | Industrial diesel, MyPertamina reference, 1-14 and 15-31 October 2026 ([solardistro.com](https://solardistro.com/artikel/arsip-harga/)) |
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
| `DEDUP_TOL` | 50 m | `sekat.dedup_tol_m`, opt-in |
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
