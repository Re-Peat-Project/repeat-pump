"""'Make map layout': a KLH-style print layout of the open run, added to the project and opened in the layout designer for editing."""
from __future__ import annotations

from pathlib import Path

from qgis.core import QgsProject, QgsSettings
from qgis.PyQt.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout

from .i18n import tr
from .widgets import file_widget

KEY_INSTITUTION = "repeat_pump/layout_institution"
KEY_TEMPLATE = "repeat_pump/layout_template"


class LayoutDialog(QDialog):
    def __init__(self, config_path: Path, parent=None):
        super().__init__(parent)
        from ..run_layout import INSTITUTION, TITLE, khg_title
        self.setWindowTitle(tr("Make map layout"))
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.paper = QComboBox()
        self.paper.addItems(["A0", "A1", "A2", "A3", "A4"])
        self.paper.setCurrentText("A3")
        self.orient = QComboBox()
        for code, text in (("landscape", "Landscape"), ("portrait", "Portrait")):
            self.orient.addItem(tr(text), code)
        self.title = QPlainTextEdit(TITLE)
        self.title.setFixedHeight(54)
        self.subtitle = QLineEdit(khg_title(config_path))
        self.institution = QPlainTextEdit(str(QgsSettings().value(KEY_INSTITUTION, INSTITUTION) or INSTITUTION))
        self.institution.setFixedHeight(54)
        self.template = file_widget("open", "QGIS layout template (*.qpt)")
        self.template.setFilePath(str(QgsSettings().value(KEY_TEMPLATE, "") or ""))
        form.addRow(tr("Paper"), self.paper)
        form.addRow(tr("Orientation"), self.orient)
        form.addRow(tr("Title"), self.title)
        form.addRow(tr("Subtitle"), self.subtitle)
        form.addRow(tr("Institution"), self.institution)
        form.addRow(tr("Own template (optional)"), self.template)
        lay.addLayout(form)
        note = QLabel(tr("The layout opens in the layout designer: move, restyle or add items there, then export it. "
                         "Save it as a template to reuse your changes."))
        note.setWordWrap(True)
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


def make_layout(iface, config_path: Path, parent=None) -> str | None:
    """Ask for the layout settings, build or fill the layout, add it to the project, open the designer. Returns an error text or None."""
    dlg = LayoutDialog(config_path, parent)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    from .. import maplayout as ML
    from ..run_layout import spec_for_run
    QgsSettings().setValue(KEY_INSTITUTION, dlg.institution.toPlainText())
    tpl = dlg.template.filePath().strip()
    QgsSettings().setValue(KEY_TEMPLATE, tpl)
    project = QgsProject.instance()
    spec = spec_for_run(config_path, project, dlg.paper.currentText(), dlg.orient.currentData(), dlg.title.toPlainText(),
                        dlg.subtitle.text(), dlg.institution.toPlainText())
    if not spec.layers:
        return tr("The run has no layers to map yet.")
    if tpl:
        if not Path(tpl).is_file():
            return tr("Template not found: {path}").format(path=tpl)
        layout = ML.load_template(project, tpl)
        missing = ML.fill_layout(layout, spec, project)
        if "map_main" in missing:
            return tr("The template has no map item with the id map_main.")
    else:
        layout = ML.build_layout(project, spec)
    manager = project.layoutManager()
    existing = manager.layoutByName(layout.name())
    if existing is not None:
        manager.removeLayout(existing)
    manager.addLayout(layout)
    if iface is not None:
        iface.openLayoutDesigner(layout)
    return None
