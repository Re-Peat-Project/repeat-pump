# References

Keys cited in module docstrings (from AGENTS.md section 12). Verify volume and page details against the originals before formal citation.

- **Barnes2014**: Barnes, Lehman & Mulla (2014). Priority-flood. Computers & Geosciences 62, 117-127.
- **Chen2010**: Chen, Yu & Khan (2010). Spatial sensitivity analysis of multi-criteria weights. Environmental Modelling & Software 25(12), 1582-1591.
- **Chow1959**: Chow (1959). Open-Channel Hydraulics. McGraw-Hill.
- **Dijkstra1959**: Dijkstra (1959). Numerische Mathematik 1, 269-271.
- **Dohong2018**: Dohong, Aziz & Dargusch (2018). Wetlands 38, 275-292.
- **Garbrecht1997**: Garbrecht & Martz (1997). Journal of Hydrology 193, 204-213.
- **Holmgren1994**: Holmgren (1994). Hydrological Processes 8, 327-334.
- **Karassik2008**: Karassik et al. (2008). Pump Handbook, 4th ed. McGraw-Hill.
- **Kou1981**: Kou, Markowsky & Berman (1981). Acta Informatica 15, 141-145.
- **Lindsay2016a**: Lindsay (2016). Hydrological Processes 30(6), 846-857.
- **Lindsay2016b**: Lindsay (2016). Earth Surface Processes and Landforms 41(5), 658-668.
- **Malczewski2006**: Malczewski (2006). IJGIS 20(7), 703-726.
- **Mays2011**: Mays (2011). Water Resources Engineering, 2nd ed. Wiley.
- **Mehlhorn1988**: Mehlhorn (1988). Information Processing Letters 27(3), 125-128.
- **Neteler2008**: Neteler & Mitasova (2008). Open Source GIS: A GRASS GIS Approach, 3rd ed. Springer.
- **Ritzema2014**: Ritzema et al. (2014). Catena 114, 11-20.
- **Saaty1980**: Saaty (1980). The Analytic Hierarchy Process. McGraw-Hill.
- **Takahashi1980**: Takahashi & Matsuyama (1980). Mathematica Japonica 24(6), 573-577.
- **Tarboton1997**: Tarboton (1997). Water Resources Research 33(2), 309-319.
- **McFeeters1996**: McFeeters (1996). The use of the Normalized Difference Water Index (NDWI) in the delineation of open water features. International Journal of Remote Sensing 17(7), 1425-1432.
- **Gao1996**: Gao (1996). NDWI, a normalized difference water index for remote sensing of vegetation liquid water from space. Remote Sensing of Environment 58(3), 257-266 (the NIR/SWIR1 index used here as NDMI).
- **Giglio2018**: Giglio, Boschetti, Roy, Humber & Justice (2018). The Collection 6 MODIS burned area mapping algorithm and product. Remote Sensing of Environment 217, 72-85 (MCD64A1).
- **Holland1975**: Holland (1975). Adaptation in Natural and Artificial Systems. University of Michigan Press.
- **Kirkpatrick1983**: Kirkpatrick, Gelatt & Vecchi (1983). Science 220(4598), 671-680.
- **Urzainki2020**: Urzainki et al. (2020). Biogeosciences 17, 4769-4784, doi:10.5194/bg-17-4769-2020. Peat tables and scheme from LukeEcomod/blopti (MIT); see `repeat_pump/data/NOTICE-urzainki2020.md`.
- **PP57-2016**, **KHG-SKSS-2021**: see the spec.

- **Urzainki2023**: Urzainki et al. (2023). A process-based model for quantifying the effects of canal blocking on water table and CO2 emissions in tropical peatlands. Biogeosciences 20, 2099-2116, doi:10.5194/bg-20-2099-2023. Used for the ~600 m reach of block effects.
- **Hooijer2005**: Hooijer (2005). Hydrology of tropical wetland forests: recent research results from Sarawak peatswamps. In Bonell & Bruijnzeel (eds), Forests, Water and People in the Humid Tropics, CUP, 447-461. Specific yield 0.29 / 0.71, read through a later citation (Sci. Rep. 2026, s41598-026-64641-2), not the original.
- **Cobb2019**: Cobb & Harvey (2019). Scalar simulation and parameterization of water table dynamics in tropical peatlands. Water Resources Research 55, 9351-9377, doi:10.1029/2019WR025411. Specific yield below 0.15 under a deep water table.
- **Haman2017**: Haman (2017). Pumps for Florida Irrigation and Drainage Systems, UF/IFAS CIR832 (WI001). Pump efficiency normally 65-80 %.
- **IPEX-PVC**: IPEX. Hydraulics of PVC Pipe (bulletin). Hazen-Williams C = 150 for PVC.
- **Meadows2024**: Meadows et al. (2024). Vertical accuracy assessment of freely available global DEMs (FABDEM, Copernicus DEM, NASADEM, AW3D30, SRTM) in flood-prone environments. LiDAR vertical RMSE well within 0.3 m.
- **PanduanKLH**: Panduan Teknis GIS Rewetting KLH and Workflow GIS Rewetting KLH (`docs/`). Source of the 500 m sekat spacing, 50 m extraction buffer, 30 m river-canal buffer and equal-weight scoring.

Chow1959 Table 5-6 (Manning n) was read through drainagecalculators.com, which reproduces it, not from the book. `configs/proposed_defaults.yaml` uses these; its values are proposals, see `docs/proposed_defaults.md`.

Stage 12 (optional) adds Urzainki2020, Holland1975 and Kirkpatrick1983. Verify volume and page details against the originals before formal citation.

"Load moisture from the cloud" (`core/cpwi.py`, `core/cloudfetch.py`, `core/ee_fetch.py`) ports the team's CPWI v2 Earth Engine script (`legacy/gee_code.txt`); its clamps and weights are that script's, not new choices. NDWI and NDMI follow McFeeters1996 and Gao1996. Cloud Score+ and Sentinel-1 GRD exist only in Earth Engine, so the open backend is an approximation, labelled as such in the provenance file and the run report.
