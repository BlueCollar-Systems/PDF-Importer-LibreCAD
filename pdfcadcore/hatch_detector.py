# -*- coding: utf-8 -*-
# hatch_detector.py — Detect hatching patterns in PyMuPDF drawing groups
# BlueCollar Systems — BUILT. NOT BOUGHT.
"""
Hatching = dense clusters of parallel lines at regular spacing.
Modes: "import" (default), "skip" (remove), "group" (separate hidden group)
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Set, Tuple

MIN_HATCH_LINES = 6
ANGLE_TOL_DEG = 3.0
SPACING_REGULARITY = 0.35
LENGTH_CV_MAX = 0.50


def _parse_line_segment(item_data) -> Optional[Tuple[float, float, float, float]]:
    if len(item_data) >= 2:
        p0, p1 = item_data[0], item_data[1]
        if hasattr(p0, 'x') and hasattr(p1, 'x'):
            return (p0.x, p0.y, p1.x, p1.y)
    return None


def _angle_diff(a: float, b: float) -> float:
    d = abs(a - b)
    if d > 90.0:
        d = 180.0 - d
    return d


def _angle_bin_count() -> int:
    return max(1, int(math.ceil(180.0 / ANGLE_TOL_DEG)))


def _build_angle_bins(lines: List[dict]) -> Dict[int, List[int]]:
    """Map quantized angle bins to line indices for O(n) neighbor lookup."""
    bins: Dict[int, List[int]] = {}
    for index, line in enumerate(lines):
        bucket = int(line["angle"] // ANGLE_TOL_DEG)
        bins.setdefault(bucket, []).append(index)
    return bins


def _neighbor_bin_ids(seed_bin: int) -> Tuple[int, ...]:
    count = _angle_bin_count()
    return tuple((seed_bin + delta) % count for delta in (-1, 0, 1))


def _group_parallel_lines(
    lines: List[dict],
    used: List[bool],
    seed_index: int,
    angle_bins: Dict[int, List[int]],
) -> List[dict]:
    """Collect unused lines within ANGLE_TOL of the seed (same rule as all-pairs)."""
    seed = lines[seed_index]
    group = [seed]
    used[seed_index] = True
    seed_bin = int(seed["angle"] // ANGLE_TOL_DEG)
    for bucket in _neighbor_bin_ids(seed_bin):
        for j in angle_bins.get(bucket, ()):
            if j <= seed_index or used[j]:
                continue
            other = lines[j]
            if _angle_diff(seed["angle"], other["angle"]) < ANGLE_TOL_DEG:
                group.append(other)
                used[j] = True
    return group


def _accept_hatch_group(group: List[dict], id_key: str) -> Set:
    """Apply spacing/length regularity checks; return accepted ids."""
    accepted: Set = set()
    if len(group) < MIN_HATCH_LINES:
        return accepted
    ref_rad = math.radians(group[0]["angle"])
    perp_x = -math.sin(ref_rad)
    perp_y = math.cos(ref_rad)
    projections = sorted(
        [{"proj": line["mx"] * perp_x + line["my"] * perp_y, "line": line} for line in group],
        key=lambda item: item["proj"],
    )
    spacings = []
    for index in range(1, len(projections)):
        spacings.append(abs(projections[index]["proj"] - projections[index - 1]["proj"]))
    if not spacings:
        return accepted
    mean_sp = sum(spacings) / len(spacings)
    if mean_sp < 0.3:
        return accepted
    variance = sum((spacing - mean_sp) ** 2 for spacing in spacings) / len(spacings)
    std_dev = math.sqrt(variance)
    if mean_sp > 0 and (std_dev / mean_sp) < SPACING_REGULARITY:
        lengths = [line["len"] for line in group]
        mean_len = sum(lengths) / len(lengths)
        len_var = sum((length - mean_len) ** 2 for length in lengths) / len(lengths)
        len_cv = math.sqrt(len_var) / mean_len if mean_len > 0 else 1.0
        if len_cv < LENGTH_CV_MAX:
            for line in group:
                accepted.add(line[id_key])
    return accepted


def detect(drawings: List[dict]) -> Set[int]:
    """Detect hatch patterns. Returns set of drawing-group indices."""
    if not drawings or len(drawings) < MIN_HATCH_LINES:
        return set()

    lines: List[dict] = []
    for idx, pg in enumerate(drawings):
        items = pg.get("items", [])
        if len(items) < 1:
            continue
        segs = []
        cur = None
        for item in items:
            kind = item[0]
            data = item[1:]
            if kind == "m":
                pt = data[0] if data else None
                if pt and hasattr(pt, 'x'):
                    cur = (pt.x, pt.y)
            elif kind == "l" and cur is not None:
                parsed = _parse_line_segment(data)
                if parsed:
                    segs.append(parsed)
                else:
                    pt = data[0] if data else None
                    if pt and hasattr(pt, 'x'):
                        segs.append((cur[0], cur[1], pt.x, pt.y))
                        cur = (pt.x, pt.y)
            elif kind == "c":
                break
        if len(segs) == 1:
            x0, y0, x1, y1 = segs[0]
            dx, dy = x1 - x0, y1 - y0
            length = math.hypot(dx, dy)
            if length < 0.5:
                continue
            angle = math.degrees(math.atan2(dy, dx))
            if angle < 0:
                angle += 180.0
            mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            lines.append({"idx": idx, "angle": angle, "len": length, "mx": mx, "my": my})

    if len(lines) < MIN_HATCH_LINES:
        return set()

    hatch_indices: Set[int] = set()
    used = [False] * len(lines)
    angle_bins = _build_angle_bins(lines)

    for i, line in enumerate(lines):
        if used[i]:
            continue
        group = _group_parallel_lines(lines, used, i, angle_bins)
        hatch_indices.update(_accept_hatch_group(group, "idx"))

    return hatch_indices


# ── Post-extraction hatch detection on Primitive objects ────────────

def tag_hatch_primitives(primitives) -> Set[int]:
    """Detect hatch patterns among extracted Primitive objects.

    Works on the already-extracted primitives (post-extraction) rather
    than raw PyMuPDF drawings.  Uses the same algorithm as :func:`detect`
    but operates on :class:`Primitive` ``points`` instead of raw path items.

    Parameters
    ----------
    primitives:
        List of :class:`Primitive` objects from a :class:`PageData`.

    Returns
    -------
    set[int]
        Set of Primitive ``.id`` values that form hatch patterns.
    """
    if not primitives or len(primitives) < MIN_HATCH_LINES:
        return set()

    # Step 1: filter to simple line primitives (type=="line", exactly 2 points)
    lines = []
    for p in primitives:
        if p.type != "line" or not p.points or len(p.points) != 2:
            continue
        x0, y0 = p.points[0]
        x1, y1 = p.points[1]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length < 0.5:
            continue
        angle = math.degrees(math.atan2(dy, dx))
        if angle < 0:
            angle += 180.0
        mx = (x0 + x1) / 2.0
        my = (y0 + y1) / 2.0
        lines.append({
            "pid": p.id,
            "angle": angle,
            "len": length,
            "mx": mx,
            "my": my,
        })

    if len(lines) < MIN_HATCH_LINES:
        return set()

    hatch_ids: Set[int] = set()
    used = [False] * len(lines)
    angle_bins = _build_angle_bins(lines)

    for i, line in enumerate(lines):
        if used[i]:
            continue
        group = _group_parallel_lines(lines, used, i, angle_bins)
        hatch_ids.update(_accept_hatch_group(group, "pid"))

    return hatch_ids
