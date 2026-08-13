# -*- coding: utf-8 -*-
# Guard: circle_fit's accumulators must stay builtin sum() calls.
# BlueCollar Systems — BUILT. NOT BOUGHT.
#
# This guard exists because the rewrite it blocks has already landed once (564f983) and
# been reverted once (5f0be3b), and because circle_fit had no test of its own either time.
# Nothing currently stops a third attempt: the single-pass version is genuinely faster and
# reads like an obvious cleanup.
#
# Why a SOURCE-level guard rather than a numeric one: the accuracy difference only exists
# on CPython >= 3.12, where sum() applies Neumaier compensated summation to floats
# (gh-100425). FreeCAD 0.21 bundles Python 3.11, where sum() is uncompensated and an
# explicit += loop is numerically identical -- so a numeric assertion would pass on the
# FreeCAD host while the regression shipped to Blender (3.13) and LibreCAD. A source check
# fires on every interpreter, which is the only way this actually holds.
#
# See test_circle_fit_promotion_oracle.py for the complementary check: that oracle verifies
# arc/circle promotion OUTCOMES, which is what the perturbation would ultimately corrupt.
# This file guards the input to that; neither replaces the other.
import ast
import inspect
import re

from pdfcadcore import geometry_cleanup

ACCUMULATORS = ("sx", "sy", "sx2", "sy2", "sxy", "sz", "sxz", "syz")

_REASON = (
    "math.fsum is exactly rounded, so the fit is identical on every CPython version and "
    "platform. builtin sum() is compensated only on >=3.12 and a += loop never is; on the "
    "ill-conditioned oracle case (seed 81011 case 143) that difference shifts radius by "
    "5.3e-2 and flips the promotion decision -- FreeCAD 3.11 and Blender 3.13 disagreed "
    "about the same drawing. Landed as sum() twice; fsum ends the class."
)


def _source() -> str:
    return inspect.getsource(geometry_cleanup.circle_fit)


def test_every_accumulator_uses_fsum():
    body = _source()
    for name in ACCUMULATORS:
        assert re.search(rf"^\s*{re.escape(name)}\s*=\s*math\.fsum\(", body, re.M), (
            f"circle_fit accumulator {name!r} is no longer math.fsum(). {_REASON}"
        )


def test_builtin_sum_is_not_reintroduced():
    # builtin sum() is compensated only on >=3.12, so it reintroduces the version
    # dependence fsum exists to kill. Proven host-visible: oracle case 143 promotes on
    # 3.12 and not on 3.11 under sum().
    body = _source()
    for name in ACCUMULATORS:
        assert not re.search(rf"^\s*{re.escape(name)}\s*=\s*sum\(", body, re.M), (
            f"circle_fit accumulator {name!r} regressed from math.fsum() to builtin "
            f"sum(), which is version-dependent. {_REASON}"
        )


def test_no_manual_accumulation_loop_reintroduced():
    body = _source()
    assert not re.search(r"^\s*sx\s*=\s*sy\s*=", body, re.M), (
        f"circle_fit re-introduced the chained zero-init of the single-pass rewrite. {_REASON}"
    )
    for name in ACCUMULATORS:
        assert not re.search(rf"^\s*{re.escape(name)}\s*\+=", body, re.M), (
            f"circle_fit accumulates {name!r} with += instead of sum(). {_REASON}"
        )


def test_rms_pass_uses_sum_too():
    # The rewrite replaced the RMS generator with its own accumulation loop; guarding only
    # the eight moment accumulators would let half of it back in.
    body = _source()
    assert re.search(r"rms\s*=\s*math\.sqrt\(\s*math\.fsum\(", body), (
        f"the RMS pass must stay a math.fsum() generator. {_REASON}"
    )
    assert not re.search(r"^\s*rms\s*\+=", body, re.M), (
        f"circle_fit accumulates rms with += instead of sum(). {_REASON}"
    )


def test_guard_would_actually_fire_on_the_rewrite():
    # A guard nobody has proven can fail is indistinguishable from a vacuous one, and this
    # repo has shipped a vacuous source guard before (see TestRotatedPageGeometry in
    # test_fc_style_fixes.py). So exercise the patterns against the real rewritten form.
    rewritten = (
        "def circle_fit(points):\n"
        "    sx = sy = sx2 = sy2 = sxy = sz = sxz = syz = 0.0\n"
        "    for x, y in points:\n"
        "        sx += x\n"
        "        sy += y\n"
        "    rms = 0.0\n"
        "    for x, y in points:\n"
        "        rms += (x - y) ** 2\n"
        "    rms = math.sqrt(rms / n)\n"
    )
    assert re.search(r"^\s*sx\s*=\s*sy\s*=", rewritten, re.M), "chained-init pattern is broken"
    assert re.search(r"^\s*sx\s*\+=", rewritten, re.M), "+= accumulator pattern is broken"
    assert re.search(r"^\s*rms\s*\+=", rewritten, re.M), "+= rms pattern is broken"
    assert not re.search(r"^\s*sx\s*=\s*sum\(", rewritten, re.M), "sum() pattern is broken"
    assert not re.search(r"rms\s*=\s*math\.sqrt\(\s*sum\(", rewritten), "rms sum() pattern is broken"


def test_docstring_records_why_so_the_next_reader_does_not_repeat_it():
    # The rewrite was proposed in good faith twice. Without the reason in the source, the
    # single-pass version reads like an obvious improvement.
    doc = geometry_cleanup.circle_fit.__doc__ or ""
    lowered = doc.lower()
    assert "sum()" in lowered or "sum(" in lowered
    assert "compensat" in lowered, "the docstring must say WHY sum() is required"
    assert "3.12" in doc, "the docstring must name the CPython version that changed sum()"


def test_still_fits_an_exact_circle():
    # So the summation rule cannot be satisfied by a function that no longer fits circles.
    import math

    cx, cy, radius = 12.5, -3.25, 7.0
    points = [
        (cx + radius * math.cos(i * math.tau / 16), cy + radius * math.sin(i * math.tau / 16))
        for i in range(16)
    ]
    got = geometry_cleanup.circle_fit(points)
    assert got is not None
    fx, fy, fr, rms = got
    assert abs(fx - cx) < 1e-9
    assert abs(fy - cy) < 1e-9
    assert abs(fr - radius) < 1e-9
    assert rms < 1e-9


def test_returns_none_below_three_points():
    assert geometry_cleanup.circle_fit([(0.0, 0.0), (1.0, 1.0)]) is None


def test_circle_fit_parses_and_defines_exactly_one_function():
    # Cheap structural sanity so a malformed edit fails here rather than at import time
    # somewhere deep in a host.
    tree = ast.parse(_source())
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert len(funcs) == 1 and funcs[0].name == "circle_fit"
