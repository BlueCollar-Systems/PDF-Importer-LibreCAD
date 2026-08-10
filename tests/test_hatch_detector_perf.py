# -*- coding: utf-8 -*-
"""Hatch detector keeps prior tagging results with angle-bin lookup."""
from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pdfcadcore import hatch_detector as hd


def _line(pid, x0, y0, x1, y1):
    return SimpleNamespace(id=pid, type="line", points=[(x0, y0), (x1, y1)])


def test_tag_hatch_primitives_matches_all_pairs_reference():
    # Dense parallel hatch-like set plus a wraparound near 0/180 pair seed.
    lines = []
    pid = 1
    for offset in range(12):
        y = offset * 2.0
        lines.append(_line(pid, 0.0, y, 20.0, y + 0.1))
        pid += 1
    # Near-horizontal wraparound neighbors (179° and 1°) should still group.
    lines.append(_line(pid, 0.0, 100.0, 20.0, 100.0 + math.tan(math.radians(1.0)) * 20.0))
    pid += 1
    lines.append(_line(pid, 0.0, 102.0, 20.0, 102.0 - math.tan(math.radians(1.0)) * 20.0))

    # Brute-force reference using the historical all-pairs loop.
    ref_lines = []
    for p in lines:
        x0, y0 = p.points[0]
        x1, y1 = p.points[1]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        angle = math.degrees(math.atan2(dy, dx))
        if angle < 0:
            angle += 180.0
        ref_lines.append({
            "pid": p.id,
            "angle": angle,
            "len": length,
            "mx": (x0 + x1) / 2.0,
            "my": (y0 + y1) / 2.0,
        })
    used = [False] * len(ref_lines)
    expected = set()
    for i, line in enumerate(ref_lines):
        if used[i]:
            continue
        group = [line]
        used[i] = True
        for j, other in enumerate(ref_lines):
            if j <= i or used[j]:
                continue
            if hd._angle_diff(line["angle"], other["angle"]) < hd.ANGLE_TOL_DEG:
                group.append(other)
                used[j] = True
        expected.update(hd._accept_hatch_group(group, "pid"))

    assert hd.tag_hatch_primitives(lines) == expected
