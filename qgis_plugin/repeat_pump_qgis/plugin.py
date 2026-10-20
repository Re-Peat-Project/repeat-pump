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

    def initProcessing(self):
        """Called alone by headless qgis_process (no GUI interface available)."""
        if self.provider is None:
            self.provider = RepeatPumpProvider()
            QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()
        self.action = QAction("Set Python environment (advanced)...", self.iface.mainWindow())
        self.action.triggered.connect(self.choose_python)
        self.iface.addPluginToMenu("RE-PEAT Pompanisasi", self.action)
        self.setup_action = QAction("Set up engine environment", self.iface.mainWindow())
        self.setup_action.triggered.connect(self.setup_environment)
        self.iface.addPluginToMenu("RE-PEAT Pompanisasi", self.setup_action)

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
        for a in (self.action, self.setup_action):
            if a is not None:
                self.iface.removePluginMenu("RE-PEAT Pompanisasi", a)

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
