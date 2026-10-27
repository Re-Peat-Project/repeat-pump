# Sekat layouts against the neraca air deficit (2026-10-27)

Which sekat (canal block) layout suits the neraca air best: the most water held back per block against the dry-season deficit,
within the KLH spacing and budget limits. Two KHG, the three highest-ranked sub-KHG of each: Sugihan-Lumpur (S04, S22, S29;
795 km2) and Kampar-Gaung (71_S06, 71_S07, 71_S26; 580 km2).

Rerun: `python scripts/sekat_variants.py --config ../re-peat/sites/<khg>/sekat_variants.yaml` (from repeat-pump). Full tables:
`_khg/<khg>/05_pump/variants/variants.md`, `variants.csv` (every drawdown and reach), `variants_units.csv` (per sub-KHG).

## Rule, written before the runs

1. Spacing: no new sekat closer than 200 m along a canal to another sekat (KLH: too close is not wanted, for budget reasons).
2. Retained water per block: canal water-level rise (canal-rise objective of stage 12 [Urzainki2020]) x specific yield 0.15 (the
   neraca air value) x a 600 m lateral reach [Urzainki2023], m3.
3. Share of the neraca deficit of the selected sub-KHG that the layout holds back.
4. Stability: layouts placed on processed open DTMs, scored on the LiDAR network.

Every layout is scored on one reference network: LiDAR 25 m, all canal classes, existing sekat in place. BlueBook 2026 sekat are not
used as a reference (not validated). Robustness: the order of the variants by retained water per block is the same for drawdown
0.8, 1.0 and 1.2 m and reach 300 and 600 m (Spearman 0.99 to 1.0 against the main setting).

## Changes made during the investigation

- **Flow direction.** Canals that neither their slope nor a river connection can orient were taken as running in their digitised
  direction (375 of 499 at Sugihan-Lumpur). Stage 5 now orients them by flow accumulation (`profiles.direction_fallback: flow_acc`,
  default): downstream is the end where at least 1.5 times more water collects. Same blocks, 6.5 % more water held at
  Sugihan-Lumpur (5.73 against 5.37 million m3 for primary and secondary canals).
- **Water above the land is not storage.** The canal-rise objective let a block raise water above the land surface of a lower stretch
  upstream. It is now capped at the surface (the water still passes upstream). This lowered the Kampar-Gaung primary and secondary
  rise from 309,549 to 223,664 m2 and Sugihan-Lumpur's by under 1 %.
- **Budget cap.** `sekat.max_blocks` keeps at most that many new sekat, best first, next to `sekat.target_rise_share`.
- Profiles of canals that leave the DTM now get no data there instead of edge values (stage 5 crashed at Kampar-Gaung).

## Results (drawdown 1.0 m, reach 600 m)

Sugihan-Lumpur, neraca deficit 290 mm (230.7 million m3 over the three sub-KHG):

| Layout | Blocks | Retained, million m3 | m3 per block | Deficit closed | Gaps < 200 m |
|---|---|---|---|---|---|
| Primary + secondary, all head-rule blocks | 124 | 5.73 | 46,189 | 2.5 % | 27 |
| Primary + secondary, balance 90 % | 54 | 4.68 | 86,747 | 2.0 % | 0 |
| Primary + secondary, balance 80 % | 34 | 3.97 | 116,737 | 1.7 % | 0 |
| All classes, all head-rule blocks | 470 | 16.12 | 34,292 | 7.0 % | 118 |
| All classes, balance 90 % | 187 | 14.51 | 77,570 | 6.3 % | 2 |
| All classes, balance 80 % | 122 | 12.90 | 105,712 | 5.6 % | 1 |
| DeltaDTM (processed), P + S, balance 90 % | 52 | 4.91 | 94,377 | 2.1 % | 0 |
| KLHK modelled (processed), P + S, balance 90 % | 63 | 5.00 | 79,375 | 2.2 % | 0 |
| DEMNAS (processed), P + S, all head-rule blocks | 502 | 11.67 | 23,253 | 5.1 % | 341 |
| DEMNAS (processed), P + S, balance 90 % | 118 | 8.22 | 69,698 | 3.6 % | 2 |

Kampar-Gaung, neraca deficit 7.1 mm (4.1 million m3; the 2026 dry season had more rain than evaporation and the water table rose):

| Layout | Blocks | Retained, million m3 | m3 per block | Gaps < 200 m |
|---|---|---|---|---|
| Primary + secondary, all | 53 | 20.13 | 379,807 | 2 |
| Primary + secondary, balance 90 % | 29 | 19.58 | 675,111 | 0 |
| All classes, all | 549 | 36.01 | 65,591 | 204 |
| All classes, balance 90 % | 116 | 32.42 | 279,454 | 0 |

## What this shows

1. **Balancing is what suits the neraca.** At Sugihan-Lumpur the balanced layouts hold 1.9 to 2.5 times more water per block than
   the full head-rule layout and keep every gap above 200 m without a separate spacing rule (at most 2 pairs below 200 m with all
   classes). 34 blocks hold 69 % of what 124 hold. The share is a budget choice: 80 % or 90 % (`sekat.target_rise_share`), or a fixed
   number of blocks (`sekat.max_blocks`).
2. **Enforcing 200 m while placing changes little** (`min_new_spacing_m` and `min_spacing_m` 200 m): 113 instead of 124 blocks, the
   same water held. It is a safe guard to keep on.
3. **Tertiary canals hold most of the water.** With all classes the balanced layouts hold 2.8 to 3.3 times the water of primary and
   secondary alone, at a similar water per block (105,712 against 116,737 m3 at 80 %). The KLH guide analyses primary and secondary
   only; whether to include tertiary canals is a team decision.
4. **Sekat close only a small part of a large deficit.** At Sugihan-Lumpur the best layout closes 5.6 to 7.0 % of the 290 mm deficit
   (4.7 to 9.3 % over drawdown 0.8 to 1.2 m); with primary and secondary canals 1.7 to 2.5 %. Per sub-KHG, S04 gets one block on
   primary and secondary canals (0.6 % of its deficit) and 36 with tertiary canals (4.6 %). Blocking keeps water that would drain
   away; it does not supply the dry season, so every sub-KHG here also needs another treatment.
5. **Processed DeltaDTM and KLHK modelled DTMs place sekat that hold as much water as the LiDAR ones** when scored on the LiDAR
   network (4.91 and 5.00 against 4.68 million m3 at 90 %). Processed DEMNAS places four times too many blocks (341 gaps below 200 m)
   and only meets the spacing after balancing, at lower water per block.

## Limits

- The canal-rise objective has no flow or seepage: a block holds its crest level along every connected canal upstream that lies
  lower. On flat, connected networks (Kampar-Gaung) a few blocks then take most of the rise (3 blocks give 80 %).
- Reach (600 m), specific yield (0.15) and drawdown (1.0 m) set the volumes, not the order of the layouts.
- The DTM error of the LiDAR (0.3 m, suggested from [Meadows2024]) is not from the delivery.
- Kampar-Gaung's neraca run and sub-KHG use the id `71` (neraca area 7,114 km2); check the KHG ids of that folder.
