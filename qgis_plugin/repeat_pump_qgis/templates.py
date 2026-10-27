"""Make the bundled KLH layout templates (resources/layouts/*.qpt) show in QGIS: Layout Manager, "Create from template", lists the
templates of every folder in the layout template search paths. The plugin adds its folder there on load and takes it out on unload;
the user's own paths are left as they are. The templates carry the KLH/BPLH logo and the inset style (resources/context)."""
from __future__ import annotations

from pathlib import Path

TEMPLATES = Path(__file__).parent / "resources" / "layouts"
OLD_KEY = "Layout/searchPathsForTemplates"          # QGIS before the settings tree (section Core)


def _entry():
    """The settings-tree entry (QGIS 3.30 and later, QGIS 4), or None."""
    try:
        from qgis.core import QgsSettingsTree
        node = QgsSettingsTree.node("layout")
        return node.childSetting("search-paths-for-templates") if node is not None else None
    except Exception:
        return None


def _as_list(v) -> list[str]:
    if not v:
        return []
    return [v] if isinstance(v, str) else [str(x) for x in v]


def search_paths() -> list[str]:
    e = _entry()
    if e is not None:
        return _as_list(e.valueAsVariant())
    from qgis.core import QgsSettings
    return _as_list(QgsSettings().value(OLD_KEY, [], section=QgsSettings.Section.Core))


def _set(paths: list[str]) -> None:
    e = _entry()
    if e is not None:
        e.setVariantValue(paths)
        return
    from qgis.core import QgsSettings
    QgsSettings().setValue(OLD_KEY, paths, section=QgsSettings.Section.Core)


def register() -> None:
    folder = str(TEMPLATES)
    paths = search_paths()
    if TEMPLATES.is_dir() and folder not in paths:
        _set(paths + [folder])


def unregister() -> None:
    folder = str(TEMPLATES)
    paths = search_paths()
    if folder in paths:
        _set([p for p in paths if p != folder])
