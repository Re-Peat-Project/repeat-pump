"""Check the run setup form in the real wizard, offscreen: KHG picker, canal classes, tertiary and pump switches, save and load.

    python-qgis.bat scripts/check_wizard_setup.py <_khg folder> <KHG folder name> <output folder>

Fills the form from the KHG folder, prints what each widget holds, saves the setup to JSON, loads it into a fresh panel and compares,
and writes screenshots of the form to the output folder. Nothing is run and no file outside the output folder is written.
"""
import json
import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "qgis_plugin"))

from qgis.core import QgsApplication, QgsProject, QgsSettings  # noqa: E402
from qgis.PyQt.QtCore import QCoreApplication  # noqa: E402

app = QgsApplication([], True)
QgsApplication.initQgis()
sys.excepthook = lambda *a: traceback.print_exception(*a)
from repeat_pump_qgis.wizard.ui import WizardPanel  # noqa: E402


def pump(n=20):
    for _ in range(n):
        QCoreApplication.processEvents()


def state(w) -> dict:
    ex = w.extras
    return {"layers": {k: (cb.currentLayer().source() if cb.currentLayer() else None) for k, (cb, _o, _t) in w.combos.items()},
            "output": w.out_file.filePath(), "priority": w.priority.filePath(), "preset": w.use_preset.isChecked(),
            "columns": ex.columns(), "class_map": ex.class_map(), "pumps": ex.pumps.isChecked(), "tertiary": ex.tertiary.isChecked(),
            "mode": ex.mode.currentData(), "n": ex.n.value(), "params": {k: v for k, v in ex.params().items() if k != "topology.canal_class_map"}}


def main(root: str, khg: str, out: str):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    QgsSettings().setValue("repeat_pump/khg_root", root)
    w = WizardPanel(None)
    w.resize(1280, 1600)
    w.show()
    pump()
    w._refresh_khg_list()
    i = w.khg_combo.findText(khg)
    print("KHG folders listed:", w.khg_combo.count() - 1, "| chosen index:", i)
    w.khg_combo.setCurrentIndex(i)
    w._fill_from_khg(w.khg_combo.currentData())
    pump(50)
    s1 = state(w)
    print(json.dumps(s1, indent=1, default=str))
    print("message:", w.setup_msg.text())
    print("findings:", w.extras.findings.text()[:600])
    w.grab().save(str(out / "setup_filled.png"))
    data, cfg_path = w._build_setup()
    print("build_setup ok ->", cfg_path)
    from repeat_pump_qgis.runconfig import write_setup
    write_setup(data, out / "setup.json")
    QgsProject.instance().removeAllMapLayers()
    w2 = WizardPanel(None)
    w2.resize(1280, 1600)
    w2.show()
    pump()
    w2._fill_setup(str(out / "setup.json"))
    pump(50)
    s2 = state(w2)
    diff = {k: (s1[k], s2[k]) for k in s1 if s1[k] != s2[k]}
    print("after save and load, differences:", json.dumps(diff, indent=1, default=str) if diff else "none")
    w2.grab().save(str(out / "setup_loaded.png"))


if __name__ == "__main__":
    main(*sys.argv[1:4])
    QgsApplication.exitQgis()
