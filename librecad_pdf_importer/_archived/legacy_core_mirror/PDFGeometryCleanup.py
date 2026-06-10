# -*- coding: utf-8 -*-
# PDFGeometryCleanup.py — Geometry cleanup on primitives
# BlueCollar Systems — BUILT. NOT BOUGHT.
from __future__ import annotations
import math
from typing import List, Tuple


def circle_fit(points: List[Tuple[float, float]]):
    """Kasa algebraic circle fit → (cx, cy, radius, rms) or None."""
    n = len(points)
    if n < 3:
        return None
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sx2 = sum(p[0]**2 for p in points)
    sy2 = sum(p[1]**2 for p in points)
    sxy = sum(p[0]*p[1] for p in points)
    sz = sum(p[0]**2 + p[1]**2 for p in points)
    sxz = sum(p[0]*(p[0]**2 + p[1]**2) for p in points)
    syz = sum(p[1]*(p[0]**2 + p[1]**2) for p in points)
    A = [[sx, sy, n], [sx2, sxy, sx], [sxy, sy2, sy]]
    B = [sz, sxz, syz]
    D = _det3(A)
    if abs(D) < 1e-12:
        return None
    A1 = [[B[0],A[0][1],A[0][2]],[B[1],A[1][1],A[1][2]],[B[2],A[2][1],A[2][2]]]
    A2 = [[A[0][0],B[0],A[0][2]],[A[1][0],B[1],A[1][2]],[A[2][0],B[2],A[2][2]]]
    A3 = [[A[0][0],A[0][1],B[0]],[A[1][0],A[1][1],B[1]],[A[2][0],A[2][1],B[2]]]
    a = _det3(A1)/D; b = _det3(A2)/D; c = _det3(A3)/D
    cx, cy = 0.5*a, 0.5*b
    r = math.sqrt(max(0, c + cx*cx + cy*cy))
    rms = math.sqrt(sum((math.hypot(p[0]-cx, p[1]-cy) - r)**2 for p in points) / n)
    return (cx, cy, r, rms)


def _det3(m):
    return (m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
           -m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
           +m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]))


def cleanup_primitives(primitives, config=None, cleanup_level=None):
    """Run cleanup on primitive list. Returns stats dict.

    If *cleanup_level* is provided (e.g. "conservative", "balanced", "aggressive"),
    tolerance values are resolved from ``PDFImportConfig.CLEANUP_PRESETS``.
    """
    from .PDFPrimitives import RecognitionConfig
    if config is None:
        config = RecognitionConfig()

    # Resolve cleanup_level preset (Phase 2)
    min_seg = config.min_segment_len
    if cleanup_level:
        try:
            from .PDFImportConfig import CLEANUP_PRESETS
            preset = CLEANUP_PRESETS.get(cleanup_level.lower(),
                                         CLEANUP_PRESETS.get("balanced", {}))
            if "min_seg" in preset:
                min_seg = preset["min_seg"]
        except ImportError:
            pass

    stats = {"merged": 0, "removed_micro": 0, "removed_dupes": 0}
    # Remove micro segments
    before = len(primitives)
    primitives[:] = [p for p in primitives
                     if not (p.type == "line" and p.points and len(p.points) == 2
                             and math.hypot(p.points[1][0]-p.points[0][0],
                                            p.points[1][1]-p.points[0][1]) < min_seg)]
    stats["removed_micro"] = before - len(primitives)
    return stats

