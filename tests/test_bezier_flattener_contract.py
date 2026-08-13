# -*- coding: utf-8 -*-
# Fast, corpus-free contract for the cubic-Bezier flattener.
# BlueCollar Systems — BUILT. NOT BOUGHT.
#
# WHY THIS LIVES IN tests/
# CI runs `python -m pytest tests/ -v`. It does NOT run tests/, which is
# how two guards there sat red against correct code for four weeks without turning CI red.
# A guard CI does not execute is decoration.
#
# WHY THESE ASSERTIONS AND NOT PINNED COUNTS
# The corpus A/B (tools/ in pdf-test-corpus) is the thorough check, but it takes ~40
# minutes over 33 PDFs and needs the corpus, so it cannot gate a push. This file encodes
# the INVARIANTS instead: properties that survive a re-implementation of the flattener.
# Pinning "N arcs" would go stale the moment the sampler legitimately changes -- the exact
# failure mode that produced the stale rotation guards and my own stale stage-timing pins.
#
# THE LOAD-BEARING TEST IS test_flattener_actually_runs_on_cubic_curves.
# An A/B of this flattener once reported "555 arcs, 128 circles, unchanged" over 6 PDFs.
# It was a vacuous pass: _append_linearized_cubic fired ZERO times, because those PDFs were
# line-and-arc shop drawings with no cubics. A census then found 1,933,851 invocations
# across 33 of 108 corpus PDFs. If a future refactor routes curves around this function,
# every curve-related test in the suite silently becomes vacuous and nothing else notices.
from __future__ import annotations

import math

import pymupdf
import pytest

from pdfcadcore import primitive_extractor as PE


@pytest.fixture
def cubic_pdf(tmp_path):
    """A one-page PDF whose content stream contains real cubic Bezier operators."""
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    page.draw_bezier(
        pymupdf.Point(20, 150), pymupdf.Point(80, 20),
        pymupdf.Point(220, 280), pymupdf.Point(280, 150),
    )
    path = tmp_path / "cubic.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def circle_pdf(tmp_path):
    """PyMuPDF renders circles as four cubic Beziers, so this exercises promotion."""
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    page.draw_circle(pymupdf.Point(150, 150), 60)
    path = tmp_path / "circle.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def _extract(path, **kw):
    doc = pymupdf.open(path)
    try:
        return PE.extract_page(doc.load_page(0), 1, **kw)
    finally:
        doc.close()


def _instrument(monkeypatch):
    """Wrap the flattener, recording each call's control points and emitted points."""
    real = PE._append_linearized_cubic
    calls = []

    def spy(current_pts, p0, p1, p2, p3, *a, **k):
        before = len(current_pts)
        result = real(current_pts, p0, p1, p2, p3, *a, **k)
        calls.append({
            "ctrl": (p0, p1, p2, p3),
            "emitted": list(current_pts[before:]),
            "kwargs": k,
        })
        return result

    monkeypatch.setattr(PE, "_append_linearized_cubic", spy)
    return calls


# --- the gate ------------------------------------------------------------------

def test_flattener_actually_runs_on_cubic_curves(cubic_pdf, monkeypatch):
    calls = _instrument(monkeypatch)
    _extract(cubic_pdf, detect_arcs=True)
    assert calls, (
        "_append_linearized_cubic was never invoked for a PDF containing cubic Bezier "
        "operators. Either the extractor now reaches curves by another route, or curve "
        "handling regressed. Until this passes, every curve-related assertion in this "
        "suite is vacuous -- that is exactly how a 6-PDF A/B once reported 'unchanged' "
        "while testing nothing."
    )


def test_flattener_is_module_level_and_patchable():
    # The gate above depends on being able to see the call. If the function is inlined or
    # bound at import time elsewhere, the gate silently stops gating.
    assert callable(getattr(PE, "_append_linearized_cubic", None))


# --- accuracy invariants (properties, not pinned numbers) ----------------------

def _cubic_point(p0, p1, p2, p3, t):
    mt = 1.0 - t
    return (
        mt**3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t**3 * p3[0],
        mt**3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t**3 * p3[1],
    )


def _point_segment_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    if L2 < 1e-18:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def test_emitted_polyline_tracks_the_analytic_curve(cubic_pdf, monkeypatch):
    # The accuracy guarantee, stated as a property so it survives any re-implementation of
    # the sampler: every point of the true curve must lie close to the emitted polyline.
    calls = _instrument(monkeypatch)
    _extract(cubic_pdf, detect_arcs=True)
    assert calls

    for call in calls:
        p0, p1, p2, p3 = call["ctrl"]
        poly = [tuple(p0)] + [tuple(p) for p in call["emitted"]]
        if len(poly) < 2:
            continue
        chord = math.hypot(p3[0] - p0[0], p3[1] - p0[1])
        worst = max(
            min(_point_segment_distance(_cubic_point(p0, p1, p2, p3, i / 200.0),
                                        poly[j], poly[j + 1])
                for j in range(len(poly) - 1))
            for i in range(201)
        )
        # Generous absolute bound plus a chord-relative one: this is a smoke contract, not
        # a tolerance pin. It catches "the flattener stopped subdividing", which is the
        # failure that would silently coarsen every curve in every drawing.
        assert worst <= max(1.0, chord * 0.05), (
            f"emitted polyline deviates {worst:.4f} from the analytic curve "
            f"(chord {chord:.2f}); the sampler is no longer tracking the curve"
        )


def test_emitted_output_is_bounded(monkeypatch):
    # A pathological curve must not produce unbounded points. Adaptive subdivision without
    # a cap is an OOM waiting for the right input, and this machine has met OOM before.
    pts = []
    PE._append_linearized_cubic(
        pts, (0.0, 0.0), (10000.0, 100000.0), (-10000.0, -100000.0), (1.0, 0.0)
    )
    assert 0 < len(pts) <= 4096, f"unbounded flattener output: {len(pts)} points"


def test_endpoint_is_always_emitted(monkeypatch):
    # Dropping the final point silently shortens every curve.
    pts = []
    end = (40.0, 0.0)
    PE._append_linearized_cubic(pts, (0.0, 0.0), (13.0, 0.02), (27.0, -0.02), end)
    assert pts, "flattener emitted nothing"
    assert math.hypot(pts[-1][0] - end[0], pts[-1][1] - end[1]) < 1e-9


# --- behavioural invariants -----------------------------------------------------

def test_extraction_is_deterministic(cubic_pdf):
    # Two identical extractions must agree exactly. Non-determinism here would make every
    # A/B and every golden meaningless.
    a = _extract(cubic_pdf, detect_arcs=True)
    b = _extract(cubic_pdf, detect_arcs=True)
    assert len(a.primitives) == len(b.primitives)
    for pa, pb in zip(a.primitives, b.primitives):
        assert pa.type == pb.type
        assert pa.points == pb.points
        assert pa.radius == pb.radius
        assert pa.center == pb.center


def test_bezier_approximated_circle_is_promoted(circle_pdf, monkeypatch):
    # PyMuPDF emits circles as four cubics, so this proves the flattener feeds circle_fit
    # points good enough to promote. Asserted as "at least one arc or circle" rather than
    # an exact count, which would pin the sampler.
    calls = _instrument(monkeypatch)
    page = _extract(circle_pdf, detect_arcs=True)
    assert calls, "a drawn circle did not reach the cubic flattener"
    promoted = [p for p in page.primitives if p.type in ("arc", "circle")]
    assert promoted, (
        "a Bezier-approximated circle produced no arc or circle primitive; either "
        "promotion regressed or the flattener now emits points too coarse to fit"
    )


def test_detect_arcs_false_does_not_promote(circle_pdf):
    # The opposite guarantee: promotion must stay opt-in, so a caller that asked for raw
    # geometry is never handed synthesised arcs.
    page = _extract(circle_pdf, detect_arcs=False)
    assert not [p for p in page.primitives if p.type in ("arc", "circle")]
