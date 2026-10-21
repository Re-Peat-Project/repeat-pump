"""Peatland wetness indices from satellite composites: the maths only (no network, no files).

Ports the Composite Peatland Wetness Index (CPWI v2) of the team's Google Earth Engine script, ``legacy/gee_code.txt``
(Sentinel-2 NDWI and NDMI [McFeeters1996] [Gao1996] plus a Sentinel-1 VV wetness proxy). The constants below are that
script's values, not new choices; they live in ``CpwiParams`` so they are visible and testable.

Masked pixels are NaN. Rules copied from the script:
* each component is normalised to 0..1 with an explicit clamp;
* a component with no data is replaced by 0.5 (neutral) before the weighted sum;
* NDVI, used only to scale the SAR term, falls back to 0.1 and is floored at 0.01;
* the result is masked only where both Sentinel-2 *and* Sentinel-1 have no data.

``s2_wetness`` is the no-radar variant used with open Sentinel-2 data: the same NDWI and NDMI terms with the weights
renormalised. It is a different index from CPWI and must be labelled as such.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CpwiParams:
    """Values of ``legacy/gee_code.txt``."""
    w_ndwi: float = 0.30
    w_ndmi: float = 0.35
    w_sar: float = 0.35
    ndwi_range: tuple[float, float] = (-0.3, 0.4)
    ndmi_range: tuple[float, float] = (-0.2, 0.5)
    sar_range: tuple[float, float] = (0.01, 0.15)     # clamp of VV (linear) / NDVI, tuned on sigma0
    ndvi_fallback: float = 0.1
    ndvi_floor: float = 0.01
    neutral: float = 0.5
    cloud_score_min: float = 0.60                     # Cloud Score+ cs_cdf, Earth Engine backend only
    max_scene_cloud_pct: float = 80.0                 # coarse scene pre-filter


LEGACY = CpwiParams()


def normalized_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(a - b) / (a + b); NaN where either is NaN or the sum is zero."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (a - b) / (a + b)
    return np.where(np.isfinite(out), out, np.nan).astype("float32")


def normalise(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Clamp to [lo, hi] and rescale to 0..1 (NaN stays NaN)."""
    return ((np.clip(x, lo, hi) - lo) / (hi - lo)).astype("float32")


def s2_indices(b3: np.ndarray, b4: np.ndarray, b8: np.ndarray, b11: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """NDWI (green, NIR), NDMI (NIR, SWIR1), NDVI (NIR, red) from surface reflectance."""
    return normalized_difference(b3, b8), normalized_difference(b8, b11), normalized_difference(b8, b4)


def sar_wetness(vv_linear: np.ndarray, ndvi: np.ndarray, p: CpwiParams = LEGACY) -> np.ndarray:
    """VV backscatter (linear power) divided by NDVI, clamped and normalised to 0..1; NaN where there is no radar."""
    ndvi_safe = np.clip(np.where(np.isnan(ndvi), p.ndvi_fallback, ndvi), p.ndvi_floor, 1.0)
    return normalise(vv_linear / ndvi_safe, *p.sar_range)


def cpwi(ndwi: np.ndarray, ndmi: np.ndarray, ndvi: np.ndarray, vv_linear: np.ndarray, p: CpwiParams = LEGACY) -> np.ndarray:
    """CPWI v2, continuous 0 (very dry) to 1 (very wet); NaN where neither Sentinel-2 nor Sentinel-1 has data."""
    s2_ok = np.isfinite(ndwi) | np.isfinite(ndmi)
    s1_ok = np.isfinite(vv_linear)
    parts = [(normalise(ndwi, *p.ndwi_range), p.w_ndwi), (normalise(ndmi, *p.ndmi_range), p.w_ndmi), (sar_wetness(vv_linear, ndvi, p), p.w_sar)]
    out = sum(np.where(np.isnan(x), p.neutral, x) * w for x, w in parts)
    return np.where(s2_ok | s1_ok, out, np.nan).astype("float32")


def s2_wetness(ndwi: np.ndarray, ndmi: np.ndarray, p: CpwiParams = LEGACY) -> np.ndarray:
    """NDWI and NDMI terms of CPWI with weights renormalised to sum to 1 (0.30/0.35 becomes 0.46/0.54); NaN where Sentinel-2 has no data."""
    w = p.w_ndwi + p.w_ndmi
    out = (normalise(ndwi, *p.ndwi_range) * p.w_ndwi + normalise(ndmi, *p.ndmi_range) * p.w_ndmi) / w
    return np.where(np.isfinite(ndwi) & np.isfinite(ndmi), out, np.nan).astype("float32")


def median_composite(stack: list[np.ndarray]) -> np.ndarray:
    """Per-pixel median over scenes, ignoring NaN (masked) values; NaN where no scene is valid.

    The Earth Engine median returns one of the two middle values for an even count; ``nanmedian`` averages them.
    """
    if not stack:
        raise ValueError("no scenes to composite")
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)       # "All-NaN slice" is the expected masked case
            return np.nanmedian(np.stack(stack), axis=0).astype("float32")
