"""Processing provider "RE-PEAT Pompanisasi" (spec section 7), external-runner version.

Declares typed parameters, writes a run YAML and calls the repeat-pump CLI in a separate
Python environment. No analysis logic lives here and ``repeat_pump`` is never imported.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml
from qgis.core import (QgsProcessing, QgsProcessingAlgorithm, QgsProcessingContext, QgsProcessingException,
                       QgsProcessingParameterEnum, QgsProcessingParameterFeatureSource, QgsProcessingParameterFile,
                       QgsProcessingParameterFileDestination, QgsProcessingParameterRasterLayer, QgsProcessingProvider,
                       QgsVectorLayer)

from .runner import check_environment, ensure_environment, get_python, run_cli, split_source

SHOW_LAYERS = ["canal_segments", "sekat_proposed", "sekat_existing_assessed", "pump_routes", "pump_stations", "gates_required",
               "qa_topology_dangles", "qa_topology_gaps", "qa_unreachable_targets"]


def _vt(name: str):
    """Vector source type for QGIS 3 (QgsProcessing.TypeVectorX) and QGIS 4 (Qgis.ProcessingSourceType)."""
    try:
        from qgis.core import Qgis
        return getattr(Qgis.ProcessingSourceType, "Vector" + name)
    except Exception:
        return getattr(QgsProcessing, "TypeVector" + name)


# (parameter key, label, geometry type, config key, optional)
VECTOR_INPUTS = [
    ("SUBKHG", "Sub-KHG polygons", "Polygon", "subkhg", False),
    ("CANALS", "Canal lines", "Line", "canals", False),
    ("CANAL_EDITS", "Canal edits (lines with action add/delete, optional)", "Line", "canal_edits", True),
    ("SEKAT", "Existing sekat (points, may be empty)", "Point", "sekat_existing", True),
    ("RIVERS", "River polygons or lines (water sources)", "Polygon", "rivers", True),
    ("BURN", "Burn-scar polygons (burn frequency)", "Polygon", "burn_area", False),
    ("PEAT", "Peat-depth polygons", "Polygon", "peat_depth", False),
]


class _StageAlgorithm(QgsProcessingAlgorithm):
    NAME, DISPLAY, FIRST, LAST = "", "", 1, 11

    def name(self):
        return self.NAME

    def displayName(self):
        return self.DISPLAY

    def group(self):
        return "RE-PEAT Pompanisasi"

    def groupId(self):
        return "repeat_pump"

    def createInstance(self):
        return type(self)()

    def shortHelpString(self):
        return ("Runs stages %d-%d of the repeat-pump engine in a separate Python environment (set it under Plugins > RE-PEAT Pompanisasi). "
                "The YAML config holds the policy parameters; layers chosen here override the input paths." % (self.FIRST, self.LAST))

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile("CONFIG", "Run config (YAML with policy parameters)", extension="yaml"))
        if self.FIRST == 1:
            self.addParameter(QgsProcessingParameterRasterLayer("DTM", "Bare-earth DTM (metres)"))
            self.addParameter(QgsProcessingParameterRasterLayer("MOISTURE", "Moisture index raster"))
            self.addParameter(QgsProcessingParameterFile("PRIORITY", "Sub-KHG priority table (CSV)", extension="csv"))
            for key, label, geom, _, optional in VECTOR_INPUTS:
                self.addParameter(QgsProcessingParameterFeatureSource(key, label, [_vt(geom)], optional=optional))
        self.addParameter(QgsProcessingParameterFileDestination("OUTPUT_GPKG", "Output GeoPackage", fileFilter="GeoPackage (*.gpkg)", optional=True))
        self.addParameter(QgsProcessingParameterEnum("ACCEPT", "Review stages to accept", options=["2 topology", "6 prioritisation", "9 routing"],
                                                     allowMultiple=True, defaultValue=[], optional=True))
        self.addParameter(QgsProcessingParameterFileDestination("REPORT", "Run report (markdown)", fileFilter="Markdown (*.md)", optional=True))

    def _build_config(self, parameters, context, cfgfile):
        base = Path(cfgfile).parent
        data = yaml.safe_load(Path(cfgfile).read_text(encoding="utf8"))
        inp = data.setdefault("inputs", {})

        def absolute(v):
            return str(base / v) if isinstance(v, str) and not os.path.isabs(v) else v
        for sec in inp.values():
            if isinstance(sec, dict):
                if "path" in sec:
                    sec["path"] = absolute(sec["path"])
                if "paths" in sec:
                    sec["paths"] = [absolute(p) for p in sec["paths"]]
        out = self.parameterAsFileOutput(parameters, "OUTPUT_GPKG", context)
        run = data.setdefault("run", {})
        run["output_gpkg"] = out or absolute(run.get("output_gpkg", "out/run.gpkg"))
        if self.FIRST == 1:
            inp.setdefault("dtm", {})["path"] = self.parameterAsRasterLayer(parameters, "DTM", context).source()
            inp.setdefault("moisture", {})["paths"] = [self.parameterAsRasterLayer(parameters, "MOISTURE", context).source()]
            inp["subkhg_priority"] = {"path": self.parameterAsFile(parameters, "PRIORITY", context)}
            for key, _, _, cfgkey, optional in VECTOR_INPUTS:
                if self.parameterAsSource(parameters, key, context) is None:
                    continue
                layer = self.parameterAsVectorLayer(parameters, key, context)
                path, name = split_source(layer.source()) if layer is not None else ("", None)
                if not os.path.exists(path):
                    raise QgsProcessingException(f"{key}: the layer must be saved to a file (temporary layers cannot be passed to the engine)")
                entry = inp.setdefault(cfgkey, {})
                entry["path"] = path
                if name:
                    entry["layer"] = name
        return data

    def processAlgorithm(self, parameters, context, feedback):
        python = get_python()
        ok, msg = check_environment(python)
        if not ok:
            feedback.pushInfo("Engine environment not ready: " + msg)
            try:
                python = ensure_environment(feedback.pushInfo)
            except Exception as e:
                raise QgsProcessingException(f"Could not set up the engine environment automatically: {e}")
        cfgfile = self.parameterAsFile(parameters, "CONFIG", context)
        data = self._build_config(parameters, context, cfgfile)
        tmp = Path(tempfile.mkdtemp(prefix="repeat_pump_")) / "run.yaml"
        tmp.write_text(yaml.safe_dump(data), encoding="utf8")
        accept = [[2, 6, 9][i] for i in (self.parameterAsEnums(parameters, "ACCEPT", context) if parameters.get("ACCEPT") not in (None, "", []) else [])]
        code = run_cli(python, str(tmp), str(Path(cfgfile).parent), self.FIRST, self.LAST, accept, feedback)
        gpkg = data["run"]["output_gpkg"]
        if code == 1:
            raise QgsProcessingException("repeat-pump failed; see the log above")
        if code not in (0, 2):
            raise QgsProcessingException(f"repeat-pump exited with code {code}")
        if code == 2:
            feedback.pushWarning("A REVIEW stage finished. Inspect the QA layers, then re-run with that stage ticked under 'Review stages to accept'.")
        self._load_layers(gpkg, context, feedback)
        report = Path(gpkg).parent / "run_report.md"
        dest = self.parameterAsFileOutput(parameters, "REPORT", context)
        if dest and report.exists():
            Path(dest).write_text(report.read_text(encoding="utf8"), encoding="utf8")
        return {"OUTPUT_GPKG": gpkg, "REPORT": dest or str(report)}

    def _load_layers(self, gpkg, context, feedback):
        if not os.path.exists(gpkg):
            return
        for name in SHOW_LAYERS:
            try:
                lyr = QgsVectorLayer(f"{gpkg}|layername={name}", name, "ogr")
                if lyr.isValid() and lyr.featureCount() > 0:
                    context.temporaryLayerStore().addMapLayer(lyr)
                    context.addLayerToLoadOnCompletion(lyr.id(), QgsProcessingContext.LayerDetails(name, context.project(), "OUTPUT_GPKG"))
            except Exception as e:  # loading results must never fail the run
                feedback.pushInfo(f"Could not load layer {name}: {e}")


class SetupEnvironment(QgsProcessingAlgorithm):
    """Create or repair the plugin's own Python environment (needs internet once)."""

    def name(self):
        return "setup_environment"

    def displayName(self):
        return "Set up engine environment"

    def group(self):
        return "RE-PEAT Pompanisasi"

    def groupId(self):
        return "repeat_pump"

    def createInstance(self):
        return SetupEnvironment()

    def shortHelpString(self):
        return ("Creates a private Python environment in the QGIS profile and installs the bundled engine into it. "
                "Runs automatically on first use; use this to repair or update it. Needs internet and Python 3.11+.")

    def initAlgorithm(self, config=None):
        from qgis.core import QgsProcessingParameterBoolean
        self.addParameter(QgsProcessingParameterBoolean("FORCE", "Rebuild from scratch", defaultValue=False))

    def processAlgorithm(self, parameters, context, feedback):
        try:
            py = ensure_environment(feedback.pushInfo, force=self.parameterAsBool(parameters, "FORCE", context))
        except Exception as e:
            raise QgsProcessingException(str(e))
        return {"PYTHON": py}


def _make(name, display, first, last):
    return type(f"Alg_{name}", (_StageAlgorithm,), dict(NAME=name, DISPLAY=display, FIRST=first, LAST=last))


ALGORITHMS = [
    _make("prepare_canals", "1. Load, validate and clean canals (stages 1-2)", 1, 2),
    _make("hydrology_segments_profiles", "2. Hydro-conditioning, segments and profiles (stages 3-5)", 3, 5),
    _make("prioritise_segments", "3. Prioritise canal segments (stage 6)", 6, 6),
    _make("place_sekat", "4. Sekat gap analysis and placement (stage 7)", 7, 7),
    _make("route_and_size_pumps", "5. Network, routing, pumps and report (stages 8-11)", 8, 11),
    _make("run_full_pipeline", "Run full pipeline (stages 1-11)", 1, 11),
]


class RepeatPumpProvider(QgsProcessingProvider):
    def id(self):
        return "repeat_pump"

    def name(self):
        return "RE-PEAT Pompanisasi"

    def loadAlgorithms(self):
        self.addAlgorithm(SetupEnvironment())
        for alg in ALGORITHMS:
            self.addAlgorithm(alg())
