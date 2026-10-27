"""The 'Sumber Data' lines of a map layout come from the data catalogue, traced through the KHG work folder."""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "qgis_plugin"
sys.path.insert(0, str(PLUGIN))
from repeat_pump_qgis.layout_sources import source_lines  # noqa: E402


def _touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")
    return p


def test_sources_are_traced_to_the_catalogue(tmp_path):
    data, khg = tmp_path / "_data", tmp_path / "_khg" / "16.02.01_x"
    cat = tmp_path / "catalog.csv"
    cat.write_text("path,layer,description,source,year\n"
                   "kanal_osgm_khg_existing_Indonesia.gpkg,kanal,Existing canal network in KHG. Notes for analysts,OSM-derived,2025\n"
                   "lidar/OKI25.tif,,LiDAR DEM of OKI. More notes,KLHK LiDAR archive,\n"
                   "peat/*,[vector: ESRI Shapefile],Peat mask polygons,KLHK,\n"
                   "peat/*,[raster: HFA],Modelled peat depth per KHG,KLHK,\n", encoding="utf8")
    canals = _touch(khg / "00_inputs" / "canals.gpkg")
    dem = _touch(khg / "01_dem" / "inputs" / "lidar_oki25.tif")
    (khg / "01_dem" / "inputs" / "manifest.csv").write_text("product,file,sources\nlidar_oki25,lidar_oki25.tif,lidar/OKI25.tif\n", encoding="utf8")
    peat = _touch(data / "peat" / "model.img")
    units = _touch(khg / "02_delineation" / "subkhg_units.gpkg")
    other = _touch(tmp_path / "elsewhere" / "thing.gpkg")
    inputs = {"canals": {"path": str(canals)}, "dtm": {"path": str(dem)}, "peat_depth": {"path": str(peat)}, "subkhg": {"path": str(units)},
              "moisture": {"paths": [str(khg / "cache" / "x" / "annual" / "ndmi_2023.tif")]}, "concession": {"path": str(other)}}
    lines = source_lines(inputs, data, cat)
    assert lines[0] == "Existing canal network in KHG, OSM-derived, 2025"          # first sentence of the description
    assert "LiDAR DEM of OKI, KLHK LiDAR archive" in lines
    assert "Modelled peat depth per KHG, KLHK" in lines                            # the raster row of a collapsed folder, not the vector one
    assert any("repeat-delineation" in l for l in lines) and any("Sentinel-2" in l for l in lines)
    assert "thing.gpkg" in lines and len(lines) == len(set(lines))
