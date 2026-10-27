"""A print layout for a finished run: its layers with the plugin's styles, legend names, data sources and the locator inset.

Used by the wizard ("Make map layout") and by ``scripts/make_layouts.py``. The layout itself is built by ``maplayout``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from qgis.core import QgsCoordinateReferenceSystem, QgsFillSymbol, QgsLineSymbol, QgsProject, QgsSingleSymbolRenderer, QgsVectorLayer

from . import maplayout as ML
from .layout_sources import source_lines
from .runconfig import read_setup
from .wizard import styling

# drawn top first
RUN_LAYERS = ["neraca_stations", "pump_routes", "sekat_proposed", "sekat_low_benefit", "sekat_existing_assessed", "sekat_reach", "canals_clean",
              "subkhg_selected", "inputs_clipped_burn_area", "interventions"]
LEGEND_NAMES = {"interventions": "Intervensi per sub-KHG", "subkhg_selected": "Sub-KHG terpilih (analisis sekat)", "canals_clean": "Kanal primer dan sekunder",
                "sekat_existing_assessed": "Sekat kanal terbangun (existing)", "sekat_low_benefit": "Sekat kanal usulan, manfaat rendah",
                "sekat_proposed": "Sekat kanal usulan (perencanaan)", "neraca_stations": "Pemantauan TMAT (SiTMAT, akhir musim kemarau)",
                "sekat_reach": "Air kanal yang ditahan sekat (dari sekat ke hulu)", "pump_routes": "Jalur pompa (dari sungai ke target)",
                "inputs_clipped_burn_area": "Area bekas terbakar",
                "rivers": "Sungai", "khg": "Batas KHG"}
INSTITUTION = "Proyek RE-PEAT (KLH - Bank Dunia)\nDepartemen Teknik Geodesi, Universitas Gadjah Mada"
TITLE = "Peta\nIntervensi Pembasahan di Lahan Gambut"


def khg_title(config_path: str | Path) -> str:
    """'KHG Sugihan - Lumpur' from a run in a RE-PEAT KHG work folder (``_khg/<code>_<name>/05_pump``), else the run folder name."""
    p = Path(config_path).resolve()
    k = p.parent.parent if p.parent.name == "05_pump" else p.parent
    name = k.name.split("_", 1)[-1] if "_" in k.name and k.name[0].isdigit() else k.name
    return "KHG " + name.replace("_", " - ").title()


def _workspace(config_path: Path) -> Optional[Path]:
    for parent in config_path.resolve().parents:
        if (parent / "_data").is_dir() and (parent / "re-peat").is_dir():
            return parent
    return None


BUDGET_ITEMS = {"sekat_standard": ("Sekat kayu", "unit"), "sekat_reinforced": ("Sekat beton", "unit"),
                "sekat_ipg_estimate": ("Sekat, perkiraan IPG KLH", "unit"), "canal_closure_km": ("Penutupan/penimbunan kanal", "km"),
                "revegetation_ha": ("Revegetasi", "ha"), "deep_wells": ("Sumur bor", "unit"), "pump_units": ("Unit pompa", "unit"),
                "pump_fuel_l": ("Solar pompa", "L")}


def _id_num(v: float, d: int = 0) -> str:
    """Indonesian number format: 1.234,5"""
    s = f"{v:,.{d}f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def budget_rows(budget: Optional[dict]) -> list:
    """The budget estimate of run_report.json as table rows (Indonesian): item, quantity, central cost with the low-high range."""
    if not budget or not budget.get("by_item"):
        return []
    bn = lambda v: "belum ada harga" if v is None else _id_num(v / 1e9, 1)   # noqa: E731
    rows = [["Perkiraan anggaran" + (f" (harga {budget['price_year']})" if budget.get("price_year") else ""), "Jumlah", "Miliar Rp (rendah-tinggi)"]]
    items = sorted(((k, v) for k, v in budget["by_item"].items() if (v.get("quantity") or 0) > 0), key=lambda kv: -(kv[1].get("cost_idr") or 0))
    for k, v in items:
        name, unit = BUDGET_ITEMS.get(k, (k, ""))
        rng = f" ({bn(v['cost_low_idr'])}-{bn(v['cost_high_idr'])})" if v.get("cost_idr") is not None and v.get("cost_low_idr") != v.get("cost_high_idr") else ""
        rows.append([name, f"{_id_num(v['quantity'], 0 if unit != 'km' else 1)} {unit}", bn(v.get("cost_idr")) + rng])
    if budget.get("total_idr") is not None:
        rows.append(["Total", "", f"{bn(budget['total_idr'])} ({bn(budget['total_low_idr'])}-{bn(budget['total_high_idr'])})"])
    rows.append(["Harga usulan dari sumber terbitan, belum diverifikasi (budget_sources.csv)"])
    return rows


def _scale_symbols(lyr, k: float) -> None:
    """Point sizes and line widths times ``k`` (fills keep their outlines): larger marks on large paper."""
    if k == 1.0:
        return
    from qgis.core import QgsLineSymbol as _L, QgsMarkerSymbol as _M, QgsRenderContext
    for sym in lyr.renderer().symbols(QgsRenderContext()):
        if isinstance(sym, _M):
            sym.setSize(sym.size() * k)
        elif isinstance(sym, _L):
            sym.setWidth(sym.width() * k)


def run_layers(data: dict, project: QgsProject, symbol_k: float = 1.0) -> list:
    """The run's layers from its GeoPackage (and the neraca stations), styled, added to ``project`` without a tree entry; top first.
    The rivers and the KHG boundary of the KHG work folder come last, as quiet context."""
    gpkg = Path(data["run"]["output_gpkg"])
    layers = []
    for name in RUN_LAYERS:
        if name == "neraca_stations":
            nm = ((data.get("inputs") or {}).get("neraca_map") or {}).get("path")
            if not nm:
                continue
            lyr = QgsVectorLayer(f"{nm}|layername=neraca_stations", name, "ogr")
        else:
            lyr = QgsVectorLayer(f"{gpkg}|layername={name}", name, "ogr")
        if not lyr.isValid() or lyr.featureCount() == 0:
            continue
        styling.style_layer(lyr)
        if name == "subkhg_selected":                    # an outline over the intervention colours
            lyr.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({"color": "0,0,0,0", "outline_color": "11,11,11", "outline_width": "0.8"})))
        _scale_symbols(lyr, symbol_k)
        project.addMapLayer(lyr, False)
        layers.append(lyr)
    kf = gpkg.parent.parent / "00_inputs"
    for fname, name, sym in (("rivers.gpkg", "rivers", QgsLineSymbol.createSimple({"color": "92,160,214", "width": "0.6"})),
                             ("khg.gpkg", "khg", QgsFillSymbol.createSimple({"color": "0,0,0,0", "outline_color": "60,60,60", "outline_width": "0.5",
                                                                             "outline_style": "dash"}))):
        lyr = QgsVectorLayer(str(kf / fname), name, "ogr")
        if lyr.isValid() and lyr.featureCount():
            lyr.setRenderer(QgsSingleSymbolRenderer(sym))
            project.addMapLayer(lyr, False)
            layers.append(lyr)
    return layers


def inset_layers(data_dir: Optional[Path], khg_gpkg: Path, project: QgsProject):
    """The national KHG boundaries (grey) and this KHG (red) for the locator inset; ([], None) when the national layer is not found."""
    if data_dir is None or not (data_dir / "batas_khg_indonesia.gpkg").is_file():
        return [], None
    nat = QgsVectorLayer(str(data_dir / "batas_khg_indonesia.gpkg"), "KHG Indonesia", "ogr")
    if not nat.isValid():
        return [], None
    nat.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({"color": "220,218,210", "outline_color": "150,148,140", "outline_width": "0.1"})))
    project.addMapLayer(nat, False)
    hl = QgsVectorLayer(str(khg_gpkg), "KHG", "ogr") if khg_gpkg.is_file() else None
    if hl is not None and hl.isValid():
        hl.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({"color": "208,59,59", "outline_color": "120,20,20", "outline_width": "0.2"})))
        project.addMapLayer(hl, False)
    else:
        hl = None
    return [nat], hl


def spec_for_run(config_path: str | Path, project: QgsProject, paper: str = "A3", orientation: str = "landscape", title: str = TITLE,
                 subtitle: Optional[str] = None, institution: str = INSTITUTION, data_dir: Optional[str | Path] = None) -> ML.LayoutSpec:
    """Everything a layout of this run shows. ``data_dir`` (the RE-PEAT _data folder) gives the data sources and the inset; it is
    found next to the workspace, or from REPEAT_DATA, when not given."""
    cfg_path = Path(config_path).resolve()
    data = read_setup(cfg_path)
    ws = _workspace(cfg_path)
    data_dir = Path(data_dir) if data_dir else (Path(os.environ["REPEAT_DATA"]) if os.environ.get("REPEAT_DATA") else (ws / "_data" if ws else None))
    catalog = (ws / "re-peat" / "sites" / "data_catalog.csv") if ws else Path("nonexistent")
    layers = run_layers(data, project, ML.symbol_scale(paper))
    rep = Path(data["run"]["output_gpkg"]).parent / "run_report.json"
    budget = json.loads(rep.read_text(encoding="utf8")).get("budget") if rep.is_file() else None
    gpkg = Path(data["run"]["output_gpkg"])
    ins, hl = inset_layers(data_dir, gpkg.parent.parent / "00_inputs" / "khg.gpkg", project)
    whole = next((l for l in layers if l.name() == "interventions"), None) or next((l for l in layers if l.name() == "subkhg_selected"), None)
    return ML.LayoutSpec(title=title, subtitle=subtitle if subtitle is not None else khg_title(cfg_path), layers=layers,
                         legend_names={l.id(): LEGEND_NAMES[l.name()] for l in layers if l.name() in LEGEND_NAMES},
                         extent=whole.extent() if whole is not None else None, crs=QgsCoordinateReferenceSystem(data["run"]["crs"]),
                         paper=paper, orientation=orientation, sources=source_lines(data["inputs"], data_dir or Path("."), catalog),
                         institution=institution, inset_layers=ins, inset_highlight=hl, name=f"RE-PEAT {data['run'].get('name', '')} {paper} {orientation}",
                         budget_rows=budget_rows(budget))
