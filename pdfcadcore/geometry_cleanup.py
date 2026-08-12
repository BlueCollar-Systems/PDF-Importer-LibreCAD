# -*- coding: utf-8 -*-
# geometry_cleanup.py — Geometry cleanup on primitives
# BlueCollar Systems — BUILT. NOT BOUGHT.
from __future__ import annotations
import math
from typing import List, Tuple

_ZERO_TOL = 1e-9


def circle_fit(points: List[Tuple[float, float]]):
    """Kasa algebraic circle fit -> (cx, cy, radius, rms) or None."""
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


def promote_circular_primitives(
    primitives,
    *,
    arc_fit_tol_mm: float = 0.05,
    min_arc_angle_deg: float = 5.0,
    max_arc_segments: int = 64,
) -> dict:
    """Promote circular polylines to true arc/circle primitives in-place.

    Original sampled points are retained on each primitive so adapters can still
    fall back to polyline output. Returns simple stats for tests/QA.
    """
    stats = {"arcs": 0, "circles": 0}
    for prim in primitives:
        if prim.type not in {"polyline", "closed_loop"}:
            continue
        pts = list(prim.points or [])
        if len(pts) < 5:
            continue

        fit_pts = _dedupe_closing_point(pts)
        if len(fit_pts) < 5:
            continue
        fit = circle_fit(fit_pts)
        if not fit:
            continue
        cx, cy, radius, rms = fit
        if radius <= 0.1:
            continue

        tol = max(float(arc_fit_tol_mm), radius * 0.005)
        if rms > tol:
            continue
        max_err = max(abs(math.hypot(x - cx, y - cy) - radius) for x, y in fit_pts)
        if max_err > max(tol * 1.8, radius * 0.008):
            continue

        angles = [math.degrees(math.atan2(y - cy, x - cx)) for x, y in pts]
        unwrapped = _unwrap_angles(angles)
        if not unwrapped:
            continue
        span = abs(unwrapped[-1] - unwrapped[0])

        if _closed_enough(pts, radius) and span >= 350.0:
            if len(fit_pts) < 10:
                continue
            prim.type = "circle"
            prim.center = (cx, cy)
            prim.radius = radius
            prim.start_angle = 0.0
            prim.end_angle = 360.0
            prim.closed = True
            if "circle_fit" not in prim.generic_tags:
                prim.generic_tags.append("circle_fit")
            stats["circles"] += 1
            continue

        if prim.closed:
            continue
        if len(fit_pts) > max_arc_segments + 1:
            continue
        if span < min_arc_angle_deg:
            continue
        if not _polyline_run_is_smooth(fit_pts):
            continue
        if not _midpoint_matches_minor_sweep(fit_pts, cx, cy):
            continue

        start, end = _dxf_arc_angles(unwrapped[0], unwrapped[-1])
        prim.type = "arc"
        prim.center = (cx, cy)
        prim.radius = radius
        prim.start_angle = start
        prim.end_angle = end
        prim.closed = False
        if "arc_fit" not in prim.generic_tags:
            prim.generic_tags.append("arc_fit")
        stats["arcs"] += 1
    return stats


def _det3(m):
    return (m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
           -m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
           +m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]))


def _dedupe_closing_point(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    if (
        len(points) >= 2
        and math.hypot(points[0][0] - points[-1][0], points[0][1] - points[-1][1]) <= 1e-6
    ):
        return points[:-1]
    return points


def _closed_enough(points: List[Tuple[float, float]], radius: float) -> bool:
    if len(points) < 2:
        return False
    close_tol = max(0.25, radius * 0.01)
    return math.hypot(points[0][0] - points[-1][0], points[0][1] - points[-1][1]) <= close_tol


def _unwrap_angles(values: List[float]) -> List[float]:
    if not values:
        return []
    unwrapped = [values[0]]
    for angle in values[1:]:
        candidate = angle
        prev = unwrapped[-1]
        while candidate - prev > 180.0:
            candidate -= 360.0
        while candidate - prev < -180.0:
            candidate += 360.0
        unwrapped.append(candidate)
    return unwrapped


def _wrap_angle(value: float) -> float:
    value = value % 360.0
    return value + 360.0 if value < 0.0 else value


def _dxf_arc_angles(first_unwrapped: float, last_unwrapped: float) -> Tuple[float, float]:
    if last_unwrapped >= first_unwrapped:
        return _wrap_angle(first_unwrapped), _wrap_angle(last_unwrapped)
    return _wrap_angle(last_unwrapped), _wrap_angle(first_unwrapped)


def _normalize_radians(angle: float) -> float:
    while angle <= -math.pi:
        angle += 2.0 * math.pi
    while angle > math.pi:
        angle -= 2.0 * math.pi
    return angle


def _midpoint_matches_minor_sweep(points: List[Tuple[float, float]], cx: float, cy: float) -> bool:
    p0 = points[0]
    pn = points[-1]
    pm = points[len(points) // 2]
    a0 = math.atan2(p0[1] - cy, p0[0] - cx)
    an = math.atan2(pn[1] - cy, pn[0] - cx)
    am = math.atan2(pm[1] - cy, pm[0] - cx)
    sweep = _normalize_radians(an - a0)
    expected_mid = _normalize_radians(a0 + sweep * 0.5)
    return abs(_normalize_radians(am - expected_mid)) <= (math.pi / 2.0)


def _polyline_run_is_smooth(points: List[Tuple[float, float]], max_turn_deg: float = 60.0) -> bool:
    if len(points) < 5:
        return False
    max_turn = math.radians(max_turn_deg)
    prev_sign = 0
    valid_turns = 0
    for i in range(1, len(points) - 1):
        ax = points[i][0] - points[i - 1][0]
        ay = points[i][1] - points[i - 1][1]
        bx = points[i + 1][0] - points[i][0]
        by = points[i + 1][1] - points[i][1]
        la = math.hypot(ax, ay)
        lb = math.hypot(bx, by)
        if la <= _ZERO_TOL or lb <= _ZERO_TOL:
            continue
        cross = ax * by - ay * bx
        dot = ax * bx + ay * by
        turn = abs(math.atan2(cross, dot))
        if turn > max_turn:
            return False
        sign = 1 if cross > 1e-9 else (-1 if cross < -1e-9 else 0)
        if sign != 0:
            if prev_sign != 0 and sign != prev_sign:
                return False
            prev_sign = sign
        valid_turns += 1
    return valid_turns >= 2


def cleanup_primitives(primitives, config=None, cleanup_level=None):
    """Run cleanup on primitive list. Returns stats dict."""
    from .primitives import RecognitionConfig
    if config is None:
        config = RecognitionConfig()

    min_seg = config.min_segment_len
    if cleanup_level:
        from .import_config import CLEANUP_PRESETS
        preset = CLEANUP_PRESETS.get(cleanup_level.lower(),
                                     CLEANUP_PRESETS.get("balanced", {}))
        if "min_seg" in preset:
            min_seg = preset["min_seg"]

    stats = {"merged": 0, "removed_micro": 0, "removed_dupes": 0}
    before = len(primitives)
    primitives[:] = [p for p in primitives
                     if not (p.type == "line" and p.points and len(p.points) == 2
                             and math.hypot(p.points[1][0]-p.points[0][0],
                                            p.points[1][1]-p.points[0][1]) < min_seg)]
    stats["removed_micro"] = before - len(primitives)
    return stats
