"""Build the KLH-style print layouts for a finished run with QGIS's own Python, export them, and (optionally) write the templates.

    python-qgis.bat scripts/make_layouts.py --config <run_config.yaml> --out <folder> [--papers A0 A3 A4] [--orient landscape portrait]
                                            [--pdf] [--from-template my_layout.qpt]
                                            [--templates]        # also write qgis_plugin/repeat_pump_qgis/resources/layouts/*.qpt

Layers, legend names, data sources and the inset come from ``repeat_pump_qgis.run_layout`` (the same code as the wizard's "Make map
layout"). The national KHG boundaries for the inset are read from the workspace ``_data`` (or ``--data`` / REPEAT_DATA). Writes
``layout_<paper>_<orientation>.png`` (and ``.pdf`` with --pdf) to ``--out``. Templates are generic: no layers, paths or run text.
"""
import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")       # set QT_QPA_PLATFORM=windows for real fonts in the PNGs
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "qgis_plugin"))

from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsProject, QgsRectangle  # noqa: E402

app = QgsApplication([], False)
QgsApplication.initQgis()

from repeat_pump_qgis import maplayout as ML  # noqa: E402
from repeat_pump_qgis.run_layout import spec_for_run  # noqa: E402
from repeat_pump_qgis.wizard import i18n  # noqa: E402

i18n.set_language("id")                              # legend labels in Indonesian, as on the KLH sheets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--papers", nargs="+", default=["A0", "A3", "A4"])
    ap.add_argument("--orient", nargs="+", default=["landscape", "portrait"])
    ap.add_argument("--data", default=None)
    ap.add_argument("--templates", action="store_true")
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--from-template", help="fill this template (.qpt, e.g. one edited in the layout designer) instead of building the layout")
    a = ap.parse_args()
    project = QgsProject.instance()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tdir = ROOT / "qgis_plugin" / "repeat_pump_qgis" / "resources" / "layouts"
    spec = spec_for_run(a.config, project, data_dir=a.data)
    for paper in a.papers:
        for orient in a.orient:
            spec.paper, spec.orientation = paper, orient
            if a.from_template:
                lay = ML.load_template(project, a.from_template)
                missing = ML.fill_layout(lay, spec, project)
                if missing:
                    print("  items not in the template:", ", ".join(missing))
            else:
                lay = ML.build_layout(project, spec)
            png = out / f"layout_{paper}_{orient}.png"
            print(paper, orient, "png:", ML.export_png(lay, str(png), dpi=60 if paper in ("A0", "A1") else 110), png)
            if a.pdf:
                print("  pdf:", ML.export_pdf(lay, str(png.with_suffix(".pdf"))))
            if a.templates:                                  # generic: no layers, no paths, placeholder text; filled by maplayout.fill_layout
                blank = ML.LayoutSpec(title="Peta\nJudul peta", subtitle="KHG nama KHG", paper=paper, orientation=orient, placeholder=True,
                                      sources=["Sumber data"], institution="Nama instansi", crs=QgsCoordinateReferenceSystem("EPSG:4326"),
                                      extent=QgsRectangle(105.0, -3.4, 106.2, -2.4), name=f"RE-PEAT {paper} {orient}")
                tdir.mkdir(parents=True, exist_ok=True)
                ML.save_template(ML.build_layout(project, blank), str(tdir / f"klh_{paper}_{orient}.qpt"))


if __name__ == "__main__":
    main()
    QgsApplication.exitQgis()
