# -*- coding: utf-8 -*-
"""DXF strokes stay on the sheet plane when source points leak Z."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dxf_builder import _xy_points  # noqa: E402


def test_xy_points_remap_orthogonal_z_fence():
    pts = _xy_points([(12.0, 0.0, 12.0), (12.0, 0.0, 600.0)])
    assert pts == [(12.0, 12.0), (12.0, 600.0)]


def test_xy_points_keep_true_sheet_y():
    pts = _xy_points([(12.0, 40.0, 0.1), (80.0, 40.0, 0.1)])
    assert pts == [(12.0, 40.0), (80.0, 40.0)]
