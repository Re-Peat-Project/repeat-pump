"""Copy the plugin into a QGIS profile, or build a zip.

    python scripts/install_plugin.py                      # QGIS 4 default profile on Windows
    python scripts/install_plugin.py --profile-dir DIR    # any profile folder (contains python/plugins)
    python scripts/install_plugin.py --zip                # dist/repeat_pump_qgis.zip
"""
import argparse
import os
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "qgis_plugin" / "repeat_pump_qgis"


def engine_files():
    """(source, relative path inside the plugin) for the bundled engine."""
    yield ROOT / "pyproject.toml", Path("engine/pyproject.toml")
    for p in (ROOT / "repeat_pump").rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
            yield p, Path("engine") / p.relative_to(ROOT)


def extra_files():
    """The example config the wizard offers as a starting point."""
    yield ROOT / "configs" / "example_khg.yaml", Path("resources/example_khg.yaml")
    yield ROOT / "configs" / "proposed_defaults.yaml", Path("resources/proposed_defaults.yaml")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile-dir")
    ap.add_argument("--zip", action="store_true")
    a = ap.parse_args()
    if a.zip:
        out = SRC.parents[1] / "dist" / "repeat_pump_qgis.zip"
        out.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in SRC.rglob("*"):
                if p.is_file() and "__pycache__" not in p.parts:
                    z.write(p, Path("repeat_pump_qgis") / p.relative_to(SRC))
            for src, rel in list(engine_files()) + list(extra_files()):
                z.write(src, Path("repeat_pump_qgis") / rel)
        print(out)
        return
    prof = Path(a.profile_dir) if a.profile_dir else Path(os.environ["APPDATA"]) / "QGIS" / "QGIS4" / "profiles" / "default"
    dst = prof / "python" / "plugins" / "repeat_pump_qgis"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(SRC, dst, ignore=shutil.ignore_patterns("__pycache__", "engine"))
    for src, rel in list(engine_files()) + list(extra_files()):
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst / rel)
    print("installed to", dst)


if __name__ == "__main__":
    main()
