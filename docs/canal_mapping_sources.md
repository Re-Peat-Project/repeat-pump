# Mapping drainage canals from imagery: sources and caveats

Research note, 2026-11-05. Purpose: where better canal lines could come from, to improve the canal inputs of repeat-pump (block placement, network) and repeat-neraca (canal cells by class), which now rely on the national canal layer and OpenStreetMap. Gathered by the project owner in a separate session with another agent and recorded here as given; nothing below was re-read in this workspace. Labels: *as given* (from that discussion, not re-checked here), *unverified* (that discussion itself said to verify).

Related: `repeat-neraca/research_notes/canal_levels_evidence.md` (canal water levels; the Hooijer/Vernimmen 2026 ICESat-2 canal crossings use the Dadap map, and include only "canals that present open water surfaces of considerable width and without vegetation cover").

## Dadap et al. 2021: the regional canal map

Dadap, N. C., Hoyt, A. M., Cobb, A. R., Oner, D., Kozinski, M., Fua, P. V., Rao, K., Harvey, C. F., & Konings, A. G. (2021). Drainage canals in Southeast Asian peatlands increase carbon emissions. *AGU Advances*, 2(1), e2020AV000321. https://doi.org/10.1029/2020AV000321. Open access, CC BY 4.0 (the paper). Earlier conference version: EGU General Assembly 2020, EGU2020-12505. *as given*

- Method: a fully convolutional neural network on 5 m RGB Planet Basemap imagery, trained on canals hand-labelled from satellite images; canal density validated against independently labelled maps.
- Findings: described as the first regional map of drainage canals; drainage in at least 65% of peatlands, across all land-use types. Subsidence 3.2 times higher in intensively drained than in undrained areas; adding canals to a subsidence prediction model improved it by 30%. The authors suggest using the map to target hydrologic restoration.
- Data: a 5 m raster of canals and roads for Borneo, Sumatra and Peninsular Malaysia, from July-September 2017 imagery, Stanford Digital Repository, https://purl.stanford.edu/yj761xk5815.
- **Licence: CC BY-ND 3.0** (the dataset, unlike the paper). The no-derivatives term may limit publishing anything derived from it (edited canal lines, maps or block layouts built on it). Check before any RE-PEAT output that ships the lines or a product made from them; using it internally as a prior to compare against is a separate question from redistributing it.
- Epoch: 2017. Canals dug since, and blocks or infilling since, are not in it.

## Caveats and later work

Haidar, M., & Takeuchi, W. (2022). Tropical peatlands canal segmentation from high resolution optical image using U-Net architecture. *Proc. OHOW 2022*. https://doi.org/10.3390/ohow2022-13655 *as given*

- Their criticism of the Dadap map: the IoU of 0.85 counted a detection as correct within 25 m of a true canal, and roads were labelled as canals (on peat, roads run beside canals because of the low load-bearing capacity, so the two are hard to separate in RGB).
- Their method: U-Net with a ResNet-34 backbone on 1.5 m pan-sharpened SPOT-6/7 (from LAPAN), 660 km^2 in Indragiri Hilir, Riau. Canal IoU on test data 0.59 (a stricter test than Dadap's 25 m tolerance, so the two IoU are not comparable).

Cloud-free (SAR) follow-ups from the same group:
- a deep-learning canal detector on ALOS-2 PALSAR-2 HH at 25 m, JpGU 2023, STT39-P14 (https://confit.atlas.jp/guide/event/jpgu2023/subject/STT39-P14/date); *as given*
- an ensemble classifier testing PALSAR-2 polarisation modes and resolution (https://openaccess.library.uitm.edu.my/find/Record/doaj-art-e388a601cf7547619a122d0c6b7691a2); only title and abstract found; *unverified* authors and venue, check before citing.

U-Net reference: Ronneberger, O., Fischer, P., & Brox, T. (2015). U-Net: Convolutional networks for biomedical image segmentation. MICCAI. https://doi.org/10.1007/978-3-319-24574-4_28

Sources listed in that discussion: DSpace@MIT https://dspace.mit.edu/handle/1721.1/132970; EPFL Infoscience https://infoscience.epfl.ch/record/289945; EGU2020-12505 https://meetingorganizer.copernicus.org/EGU2020/EGU2020-12505.html; NSF PAR dataset record https://par.nsf.gov/biblio/10556931-drainage-canals-southeast-asian-peatland; Sciforum https://sciforum.net/paper/view/13655.

## Use in RE-PEAT (suggestion, not decided)

1. Dadap raster as a first-pass regional prior: compare it with the national canal layer and OSM per KHG (length by class, missing and extra lines), to flag where our canal inputs are incomplete. Licence permitting for anything published.
2. Refine inside a KHG with a U-Net trained on SPOT-6/7 or on a LiDAR DTM (or the planned drone surface, `repeat-dem/docs/drone-photogrammetry-notes.md`). Elevation separates canals (a trough) from roads (a ridge) far better than RGB, which is the main weakness noted above.
3. Canal class (primary, secondary, tertiary) is not in any of these maps; both modules need it (repeat-neraca canal levels by class, D24). Width from the 5 m raster or the DTM trough could stand in, to be checked against the national layer's classes.
4. Whatever source is used, keep the canal date: block placement and canal levels depend on what is open now.

## Tested: canals in raw DEMNAS (2026-11-05)

Step 1 of suggestion 2 above, at Pulau Padang (`repeat-dem/benchmark/canal_visibility.yaml`, `repeat-dem/runs/checks/canal_visibility.md`): no canal class is visible in raw DEMNAS by the pre-set rule (primary auc 0.58, tertiary 0.43). DEMNAS holds troughs about 1 m deep 100 m from any mapped canal, so canals do not stand out; detection from DEMNAS was dropped. A 2 m LiDAR shows primary canals clearly; at 8 m only primary canals remain. Detection from elevation needs a surface of a few metres or finer (LiDAR, or the planned drone survey).
