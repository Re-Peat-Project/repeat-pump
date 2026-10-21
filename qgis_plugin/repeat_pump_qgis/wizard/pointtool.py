"""One-click map tool shared by the wizard's map interactions (delete a canal, explain a segment)."""
from __future__ import annotations

from typing import Callable

from qgis.core import QgsPointXY
from qgis.gui import QgsMapToolEmitPoint


class PointTool(QgsMapToolEmitPoint):
    """Calls ``callback(point)`` with the clicked point (map canvas CRS). Keep a Python reference to it: QGIS does not own it."""

    def __init__(self, canvas, callback: Callable[[QgsPointXY], None]):
        super().__init__(canvas)
        self._callback = callback

    def canvasReleaseEvent(self, event) -> None:
        self._callback(event.mapPoint())
