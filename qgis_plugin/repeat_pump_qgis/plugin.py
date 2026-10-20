"""Plugin shell: registers the Processing provider and a settings action."""
from qgis.core import QgsApplication
from qgis.PyQt.QtGui import QAction
from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox

from .provider import RepeatPumpProvider
from .runner import check_environment, get_python, set_python


class RepeatPumpPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.action = None
        self.setup_action = None
        self.wizard_action = None
        self.dock = None

    def initProcessing(self):
        """Called alone by headless qgis_process (no GUI interface available)."""
        if self.provider is None:
            self.provider = RepeatPumpProvider()
            QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()
        from qgis.PyQt.QtGui import QIcon
        from .wizard import theme
        from .wizard.ui import svg_pixmap
        self.wizard_action = QAction(QIcon(svg_pixmap(theme.DROP_SVG, theme.TEAL_DARK, 24)), "Guided wizard (stage by stage)", self.iface.mainWindow())
        self.wizard_action.triggered.connect(self.show_wizard)
        self.iface.addPluginToMenu("RE-PEAT Pompanisasi", self.wizard_action)
        self.iface.addToolBarIcon(self.wizard_action)
        self.action = QAction("Set Python environment (advanced)...", self.iface.mainWindow())
        self.action.triggered.connect(self.choose_python)
        self.iface.addPluginToMenu("RE-PEAT Pompanisasi", self.action)
        self.setup_action = QAction("Set up engine environment", self.iface.mainWindow())
        self.setup_action.triggered.connect(self.setup_environment)
        self.iface.addPluginToMenu("RE-PEAT Pompanisasi", self.setup_action)

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.wizard_action is not None:
            self.iface.removeToolBarIcon(self.wizard_action)
        for a in (self.action, self.setup_action, self.wizard_action):
            if a is not None:
                self.iface.removePluginMenu("RE-PEAT Pompanisasi", a)

    def show_wizard(self):
        if self.dock is None:
            from qgis.PyQt.QtCore import Qt
            from .wizard.ui import WizardDock
            self.dock = WizardDock(self.iface, self.iface.mainWindow())
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
            self.dock.setFloating(True)          # roomy by default; dock it to the side if you prefer (the rail collapses)
            self.dock.resize(1120, 760)
        self.dock.show()
        self.dock.raise_()

    def choose_python(self):
        path, _ = QFileDialog.getOpenFileName(self.iface.mainWindow(), "python.exe of the environment where repeat-pump is installed",
                                              get_python() or "", "Python (python.exe python);;All files (*)")
        if not path:
            return
        ok, msg = check_environment(path)
        if ok:
            set_python(path)
        (QMessageBox.information if ok else QMessageBox.warning)(self.iface.mainWindow(), "RE-PEAT Pompanisasi", msg)

    def setup_environment(self):
        import processing
        processing.execAlgorithmDialog("repeat_pump:setup_environment")
