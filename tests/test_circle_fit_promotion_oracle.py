# -*- coding: utf-8 -*-
"""Gate 0 REMEDIATE: circle_fit must preserve reviewed arc-promotion decisions."""
from __future__ import annotations

import hashlib
import json
import math
import random
from types import SimpleNamespace

from pdfcadcore.geometry_cleanup import promote_circular_primitives


def _seed_81011_case_143_points():
    rng = random.Random(81011)
    for _case_index in range(144):
        n = rng.randint(5, 65)
        cx = rng.uniform(-5000.0, 5000.0)
        cy = rng.uniform(-5000.0, 5000.0)
        radius = 10 ** rng.uniform(-1.0, 3.3)
        noise = max(0.05, radius * 0.005) * rng.uniform(0.98, 1.02)
        span = rng.uniform(math.radians(5.0), 2.0 * math.pi)
        points = []
        for point_index in range(n):
            angle = span * point_index / (n - 1)
            noisy_radius = radius + (rng.random() * 2.0 - 1.0) * noise
            points.append(
                (
                    cx + noisy_radius * math.cos(angle),
                    cy + noisy_radius * math.sin(angle),
                )
            )
    return points


def test_circle_fit_seed_81011_case_143_promotes_reviewed_arc():
    points = _seed_81011_case_143_points()
    encoded = json.dumps(points, separators=(",", ":"), allow_nan=False).encode()
    assert hashlib.sha256(encoded).hexdigest() == (
        "91b5073ecdb1acb5429b902661ae16aca7ef2e275d2378ec61f37b7b3c88291a"
    )
    primitive = SimpleNamespace(
        type="polyline",
        points=list(points),
        center=None,
        radius=None,
        start_angle=None,
        end_angle=None,
        closed=False,
        generic_tags=[],
    )
    stats = promote_circular_primitives(
        [primitive],
        arc_fit_tol_mm=0.05,
        min_arc_angle_deg=5.0,
        max_arc_segments=64,
    )
    assert stats == {"arcs": 1, "circles": 0}
    assert primitive.type == "arc"
    assert primitive.generic_tags == ["arc_fit"]
    assert primitive.center == (2196.483897339929, 3189.614339443953)
    assert primitive.radius == 10.308404119477688
    assert (primitive.start_angle, primitive.end_angle) == (
        359.92806671875985,
        163.13778455352616,
    )
