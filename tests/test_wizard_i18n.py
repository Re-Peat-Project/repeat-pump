"""English / Bahasa Indonesia: every user-facing wizard string has a translation with the same placeholders."""
import ast
import re
import sys
from pathlib import Path

import pytest

from repeat_pump.core.config import load_config
from repeat_pump.core.requirements import check

PLUGIN = Path(__file__).parents[1] / "qgis_plugin" / "repeat_pump_qgis"
sys.path.insert(0, str(PLUGIN.parent))
from repeat_pump_qgis.wizard import i18n, viewmodel as vm  # noqa: E402

EXAMPLE = Path(__file__).parents[1] / "configs" / "example_khg.yaml"
# literals in the Qt code that are not shown to people (QGIS message levels, file filters, brand name, language codes)
NOT_UI = {"RE-PEAT", "QGIS layout template (*.qpt)", "YAML (*.yaml *.yml)", "JSON (*.json);;YAML (*.yaml *.yml)", "GeoPackage (*.gpkg)", "CSV (*.csv)", "EN", "ID", "Info", "Success", "Warning", "Critical",
          "Engine ready", "Hazen-Williams C", "Segoe UI", "Single Box", "PDF (*.pdf);;PNG (*.png)", "GeoTIFF (*.tif)", "Canal edits (yours)", "Sekat edits (yours)", "Route edits (yours)"}


@pytest.fixture(autouse=True)
def english_after():
    yield
    i18n.set_language("en")


def _source_strings() -> set[str]:
    """Every English string the wizard can show: view-model content plus literals in the Qt code."""
    out: set[str] = set()
    for title, purpose, what, why, _ref in vm.STAGE_TEXT.values():
        out |= {title, purpose, what, why}
    for tiles in vm.STAGE_TILES.values():
        for _k, label, note, _w in tiles:
            out |= {label} | ({note} if note else set())
    out |= set(vm.REVIEW_HINT.values())
    for f in vm.FIELDS.values():
        out |= set(f.labels) | {f.label} | ({f.help} if f.help else set()) | ({f.unit} if f.unit and f.kind in ("float", "int") and f.unit not in ("m", "m3/s") else set())
    from repeat_pump_qgis.wizard import maptools
    out |= set(maptools.LEGEND_NAMES.values()) | set(maptools.STAGE_QUESTION.values()) | {"RE-PEAT Interventions"}
    out |= {"Weight: {name}", "burn frequency", "peat depth", "dryness", "upstream contribution", "AHP pairwise matrix",
            "Relative importance of this criterion. Weights are normalised.",
            "Edit this in the YAML file (a matrix cannot be typed here)."}
    for fname in ("ui.py", "controller.py", "setup_form.py", "cloud_dialog.py", "cloudload.py", "canal_edit.py", "explain.py", "explain_tool.py", "preflight.py", "maptools.py", "widgets.py", "summary.py", "diagrams.py"):
        tree = ast.parse((PLUGIN / "wizard" / fname).read_text(encoding="utf8"))
        skip = {id(c) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for c in ast.walk(n)}
        skip |= {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr)}          # docstrings
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip:
                v = n.value.strip("\n")
                if len(v) > 3 and (v[0].isupper() or v.startswith((" ·", "..."))) and (" " in v or v.endswith("...")) and v not in NOT_UI \
                        and not v.startswith(("YAML (", "Qt.", "background", "RE-PEAT")) and "(" not in v[:2]:
                    out.add(v.strip("\n"))
    return out


def test_every_ui_string_has_an_indonesian_translation():
    missing = sorted(s for s in _source_strings() if s not in i18n.ID)
    assert not missing, "add these to wizard/i18n.py:\n" + "\n".join(missing)


def test_translations_keep_the_same_placeholders():
    ph = lambda s: sorted(re.findall(r"\{(\w+)\}", s))
    bad = [k for k, v in i18n.ID.items() if ph(k) != ph(v)]
    assert not bad, bad


def test_no_empty_or_identical_translations_for_sentences():
    same = [k for k, v in i18n.ID.items() if k == v and len(k) > 25]
    empty = [k for k, v in i18n.ID.items() if not v.strip()]
    assert not same and not empty, (same, empty)


def test_tr_switches_language_and_falls_back_to_the_key():
    assert i18n.tr("Back") == "Back"
    i18n.set_language("id")
    assert i18n.tr("Back") == "Kembali" and i18n.language() == "id"
    assert i18n.tr("text the engine wrote") == "text the engine wrote"        # engine messages stay as they are
    assert i18n.tr("Stage {n} of {total}").format(n=2, total=11) == "Tahap 2 dari 11"
    i18n.set_language("xx")
    assert i18n.language() == "en"


def test_default_language_follows_the_locale():
    assert i18n.default_language("id_ID") == "id" and i18n.default_language("id") == "id"
    assert i18n.default_language("en_US") == "en" and i18n.default_language("") == "en"


def test_the_model_is_built_in_the_active_language():
    chk = check(load_config(EXAMPLE))
    state = {"stages": {"1": {"status": "done"}, "2": {"status": "awaiting_review"}}, "warnings": [],
             "report": {"counts": {"2": {"canals_in": 4, "canals_clean": 5, "dangles": 2}}}}
    en = vm.WizardModel(chk, state)
    i18n.set_language("id")
    idm = vm.WizardModel(chk, state)
    assert en.stage(2).title == "Canal topology" and idm.stage(2).title == "Topologi kanal"
    assert idm.stage(2).sub == "Perlu tinjauan Anda" and idm.stage(3).sub == "Terkunci"
    assert [t.label for t in idm.stage(2).tiles][:3] == ["Fitur kanal masuk", "Fitur kanal keluar", "Dangle ditemukan"]
    assert idm.stage(2).review_hint.startswith("Buka layer dangle")
    assert "nilai wajib masih kosong" in idm.stage(1).blocking or idm.stage(1).blocking.startswith("1 nilai")
    f = vm.field_for("prioritise.criteria.burn_freq.weight")
    assert f.label == "Bobot: frekuensi kebakaran"
    assert vm.field_for("topology.snap_tolerance_m").label == "Toleransi penyambungan"
    assert vm.field_for("pumping.conveyance").options == ("canal", "pipe")     # option values are config values: never translated


def test_plan_and_state_logic_do_not_depend_on_language():
    i18n.set_language("id")
    assert vm.WizardModel.plan("accept", 2) == vm.RunPlan(None, 2, (2,), False)
