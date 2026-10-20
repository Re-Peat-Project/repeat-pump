"""Drive the real wizard through the practice data and save the screenshots used in docs/index.html and docs/wizard.html.

Run it with QGIS's own Python (OSGeo4W shell or python-qgis.bat), from anywhere:

    python-qgis.bat scripts/make_doc_screenshots.py

It needs the engine in a Python environment (default: .venv in the repo; override with REPEAT_PUMP_PYTHON) and the practice data
(python scripts/make_sample_data.py). Everything is built from dummy data in a temporary folder; only PNG files are written
to docs/img. Set QT_QPA_PLATFORM=offscreen to avoid any window (text then uses fallback fonts).
"""
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("QT_QPA_PLATFORM", "windows" if sys.platform == "win32" else "xcb")
os.environ.setdefault("REPEAT_PUMP_PYTHON", str(ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")))
sys.path.insert(0, str(ROOT / "qgis_plugin"))

from qgis.core import (QgsApplication, QgsFillSymbol, QgsMapRendererParallelJob, QgsMapSettings, QgsProject, QgsRasterLayer,  # noqa: E402
                       QgsSingleSymbolRenderer, QgsVectorLayer)
from qgis.PyQt.QtCore import QCoreApplication, QSize, Qt  # noqa: E402
from qgis.PyQt.QtGui import QColor  # noqa: E402

app = QgsApplication([], False)
QgsApplication.initQgis()
sys.excepthook = lambda *a: traceback.print_exception(*a)

from repeat_pump_qgis.wizard.ui import WizardPanel  # noqa: E402

IMG = ROOT / "docs" / "img"
SAMPLE = ROOT / "docs" / "sample_data"
DUMMY = {   # dummy values for the practice data only (same as practice_run/run_config.yaml)
    "run.clip_margin_m": "100", "inputs.dtm.vertical_rmse_m": "0.1", "inputs.moisture.higher_is_wetter": True,
    "run.vertical_datum": "DUMMY-DATUM", "inputs.rivers.vertical_datum": "DUMMY-DATUM", "topology.snap_tolerance_m": "2.0",
    "hydro.breach_max_dist_cells": "20", "prioritise.upstream_buffer_m": "15", "prioritise.feasibility.concession_mode": "ignore",
    "sekat.max_spacing_m": "1000", "sekat.snap_tolerance_m": "10", "sekat.min_spacing_m": "50", "pumping.uphill_penalty_lambda": "10",
    "pumping.conveyance": "canal", "pumping.manning_n": "0.035", "pumping.pump_efficiency": "0.6", "pumping.max_head_per_station_m": "1.0",
    "pumping.pump_capacity_m3s": "0.5", "pumping.influence_distance_m": "200",
}
DUMMY.update({"optimise.n_blocks": "1", "optimise.max_evaluations": "40", "optimise.canal_drawdown_m": "1.0"})
for _c in ("burn_freq", "peat_depth", "dryness", "upstream_contrib"):
    DUMMY[f"prioritise.criteria.{_c}.weight"] = "0.25"


def pump(cond=lambda: False, timeout=0.0):
    t0 = time.time()
    while not cond():
        QCoreApplication.processEvents()
        time.sleep(0.03)
        if time.time() - t0 > (timeout or 0.01):
            break
    for _ in range(6):
        QCoreApplication.processEvents()


def wait(cond, timeout=300, what=""):
    t0 = time.time()
    while not cond():
        QCoreApplication.processEvents()
        time.sleep(0.05)
        if time.time() - t0 > timeout:
            raise TimeoutError(what)
    pump()


w = WizardPanel(None)
w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
w.resize(1280, 900)
w.show()
c = w.controller
wait(lambda: c.engine_ready is not None and not c.busy, 90, "engine")
print("engine ready:", c.engine_ready)
IMG.mkdir(parents=True, exist_ok=True)
for f in IMG.glob("*.png"):
    f.unlink()


def snap(name, size=None, both=True):
    """Save the wizard as <name>_en.png and <name>_id.png (the same screen in both languages)."""
    if size:
        w.resize(*size)
    for lang in (("en", "id") if both else ("en",)):
        w._set_language(lang)
        pump(timeout=0.4)
        w.scroll.verticalScrollBar().setValue(0)
        pump()
        img = w.grab().toImage()
        if img.width() > 1200:
            img = img.scaledToWidth(1200, Qt.TransformationMode.SmoothTransformation)
        img.save(str(IMG / f"{name}_{lang}.png"))
    w._set_language("en")
    pump(timeout=0.2)
    print("shot", name)
    if size:
        w.resize(1280, 900)
        pump()


def set_value(key, value):
    ed = w._editors[key]
    if hasattr(ed, "setCurrentIndex"):          # combo box: bool -> Yes, enum -> its option
        fld_opts = {"prioritise.feasibility.concession_mode": ("exclude", "flag", "ignore"), "pumping.conveyance": ("canal", "pipe")}
        idx = 1 if value is True else (fld_opts[key].index(value) + 1 if key in fld_opts else 1)
        ed.setCurrentIndex(idx)
    else:
        ed.setText(str(value))
        ed.editingFinished.emit()
    wait(lambda: key not in c.model.all_missing and all(not p.missing for st in c.model.stages for p in st.params if p.key == key), 90, key)


def fill(stage):
    w.selected = stage
    w.render()
    pump()
    for _ in range(6):      # choosing a value can add fields (e.g. Manning's n appears once the conveyance is "canal")
        todo = [p for p in c.model.stage(stage).params if p.missing and p.key in DUMMY]
        if not todo:
            break
        set_value(todo[0].key, DUMMY[todo[0].key])
        w.render()
        pump()


def run(action, stage):
    c.run(action, stage)
    wait(lambda: c.running is None, 400, f"{action} {stage}")
    pump(timeout=0.3)
    st = c.model.stage(stage)
    if st.status == "failed":
        raise RuntimeError(f"stage {stage} failed: {st.error}\n" + "\n".join(c.log[-12:]))


work = Path(tempfile.mkdtemp(prefix="repeat_pump_doc_"))
shutil.copytree(SAMPLE, work / "sample")
data = work / "sample" / "data"

# ---- practice layers in the project (what a trainee would have loaded)
proj = QgsProject.instance()


def vec(name):
    lyr = QgsVectorLayer(str(data / f"{name}.gpkg"), name, "ogr")
    assert lyr.isValid(), name
    proj.addMapLayer(lyr)
    return lyr


layers = {"dtm": QgsRasterLayer(str(data / "dtm.tif"), "dtm"), "moisture": QgsRasterLayer(str(data / "moisture.tif"), "moisture")}
for k in layers.values():
    proj.addMapLayer(k)
for n in ("subkhg", "canals", "sekat_existing", "rivers", "burn_area", "peat_depth"):
    layers[n] = vec(n)

# ---- 1. run setup, filled in
w.out_file.setFilePath(str(work / "run" / "practice.gpkg"))
w.template.setFilePath(str(work / "sample" / "practice_template.yaml"))
w.priority.setFilePath(str(data / "subkhg_priority.csv"))
for key, lyr in layers.items():
    w.combos[key][0].setLayer(lyr)
pump(timeout=0.3)
snap("setup", size=(1280, 1350))
w._create_run()
wait(lambda: c.model is not None, 120, "model")

# ---- 2. stage 1: decisions needed, then run
w.selected = 1
w._setup_open = False
w.render()
pump(timeout=0.3)
snap("decisions_blocked", size=(1280, 760))
fill(1)
run("run", 1)
w.selected = 1
w.render()
snap("stage1_done")

# ---- 3. stage 2: needs a snap tolerance (blocked), then review
w.selected = 2
w.render()
pump(timeout=0.3)
snap("stage2_blocked", size=(1280, 760))
fill(2)
run("run", 2)
w.learn_box.setChecked(True)
w.selected = 2
w.render()
snap("review_learn")
w.learn_box.setChecked(False)

# ---- 4. a decision changed after the stage ran -> out of date; changing it back restores the review
set_value("topology.snap_tolerance_m", "3.5")
wait(lambda: c.model.stage(2).status == "stale", 90, "stale")
w.render()
snap("stale", size=(1280, 760))
set_value("topology.snap_tolerance_m", "2.0")
wait(lambda: c.model.stage(2).status == "needs_review", 90, "restored")
run("accept", 2)

# ---- 5. the rest of the run
for stage in range(3, 12):
    st = c.model.stage(stage)
    if stage == 6:
        w.selected = 6
        w.render()
        pump(timeout=0.3)
        snap("decisions_stage6", size=(1280, 1000))
    fill(stage)
    run("run", stage)
    if c.model.stage(stage).status == "needs_review":
        w.selected = stage
        w.render()
        if stage == 9:
            snap("review_stage9")
        run("accept", stage)
    if stage in (7, 10):
        w.selected = stage
        w.render()
        snap(f"stage{stage}_done")
print("final:", [(v.id, v.status) for v in c.model.stages])

# ---- 5b. the optional stage 12: switched off, then switched on, filled in and run
w.selected = 12
w.render()
pump(timeout=0.3)
assert c.model.stage(12).status == "skipped", c.model.stage(12).status
snap("stage12_off", size=(1280, 760))
w._editors["optimise.enabled"].setCurrentIndex(1)                       # Yes
wait(lambda: c.model.stage(12).status == "ready", 90, "stage 12 switched on")
w.render()
pump(timeout=0.3)
snap("stage12_decisions", size=(1280, 1000))
fill(12)
run("run", 12)
w.selected = 12
w.render()
snap("stage12_done", size=(1280, 900))
print("stage 12:", c.model.stage(12).status, [t.label + "=" + t.value for t in c.model.stage(12).tiles])

# ---- 6. docked (narrow) layout
w.selected = 7
w.render()
snap("compact", size=(430, 820))

# ---- 7. the result on a map (dummy landscape)
run_name = c.check_json["run_name"]
group = proj.layerTreeRoot().findGroup(f"RE-PEAT {run_name}")
res = {n.layer().name(): n.layer() for n in group.findLayers()}
for key, color, outline in (("subkhg", "#00000000", "#8A948F"), ("rivers", "#9ccfe0", "#5aa5bd"), ("peat_depth", "#e7dcc6", "#c9b997")):
    lyr = layers[key]
    sym = QgsFillSymbol.createSimple({"color": color, "outline_color": outline, "outline_width": "0.4"})
    lyr.setRenderer(QgsSingleSymbolRenderer(sym))
order = [res[n] for n in ("pump_stations", "gates_required", "pump_targets", "pump_sources", "sekat_proposed", "sekat_existing_assessed",
                           "pump_routes", "canal_segments") if n in res] + [layers["rivers"], layers["peat_depth"], layers["subkhg"]]
settings = QgsMapSettings()
settings.setLayers(order)
ext = res["canal_segments"].extent()
ext.combineExtentWith(layers["rivers"].extent())
ext.scale(1.15)
settings.setExtent(ext)
settings.setOutputSize(QSize(1100, 520))
settings.setBackgroundColor(QColor("#F4F1EA"))
job = QgsMapRendererParallelJob(settings)
job.start()
job.waitForFinished()
job.renderedImage().save(str(IMG / "map.png"))
print("shot map")
shutil.rmtree(work, ignore_errors=True)
print("DONE", len(list(IMG.glob("*.png"))), "images")
