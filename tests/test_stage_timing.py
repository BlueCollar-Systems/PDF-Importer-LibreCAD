# -*- coding: utf-8 -*-
# Tests for split stage timing (AGREED roadmap N2: extract_ms vs host_build_ms).
# BlueCollar Systems — BUILT. NOT BOUGHT.
#
# The point of these timers is to stop guessing which stage is slow. So the tests care
# most about the two properties that make a timing report trustworthy:
#   * it must not change what the pipeline produces, and
#   * it must report what it has NOT attributed, rather than appearing complete.
from __future__ import annotations

import math

import pytest

from pdfcadcore import stage_timing
from pdfcadcore.stage_timing import SCHEMA, StageTimer
from pdfcadcore.streaming import iter_pages

fitz = pytest.importorskip("pymupdf", reason="PyMuPDF required to build a test PDF")


def _pdf(tmp_path, pages=2):
    """A small multi-page PDF with real vector content to extract."""
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page(width=300, height=200)
        page.draw_line(fitz.Point(10, 10), fitz.Point(290, 10))
        page.draw_rect(fitz.Rect(20, 30, 120, 90))
        page.draw_circle(fitz.Point(200, 120), 40)
        page.insert_text(fitz.Point(30, 180), f"PAGE {index + 1}")
    path = tmp_path / "stage_timing.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


# --- StageTimer arithmetic -----------------------------------------------------

def test_add_accumulates_across_calls():
    timer = StageTimer()
    timer.add("extract_ms", 10.0)
    timer.add("extract_ms", 5.5)
    assert timer.get("extract_ms") == pytest.approx(15.5)
    assert timer.as_dict()["stage_counts"]["extract_ms"] == 2


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf"), float("-inf"), None, "abc", object()])
def test_add_drops_values_that_could_make_a_stage_look_faster(bad):
    # Instrumentation must never be able to fabricate a speed win.
    timer = StageTimer()
    timer.add("extract_ms", 12.0)
    timer.add("extract_ms", bad)
    assert timer.get("extract_ms") == pytest.approx(12.0)


def test_measure_records_even_when_the_block_raises():
    # A failing page still consumed time; dropping it would make a broken import
    # look cheap.
    timer = StageTimer()
    with pytest.raises(ValueError):
        with timer.measure("extract_ms"):
            raise ValueError("boom")
    assert timer.get("extract_ms") > 0.0


def test_get_is_zero_for_unrecorded_stage():
    assert StageTimer().get("never_ran_ms") == 0.0


# --- reporting honesty ---------------------------------------------------------

def test_unaccounted_ms_is_absent_when_no_total_is_supplied():
    # A fabricated zero would assert complete attribution that was never measured.
    timer = StageTimer()
    timer.add("extract_ms", 5.0)
    assert "unaccounted_ms" not in timer.as_dict()


def test_unaccounted_ms_reports_the_residual():
    timer = StageTimer()
    timer.add("extract_ms", 200.0)
    timer.add("host_build_ms", 300.0)
    out = timer.as_dict(total_ms=1000.0)
    assert out["total_ms"] == pytest.approx(1000.0)
    assert out["unaccounted_ms"] == pytest.approx(500.0)


def test_unaccounted_ms_clamps_at_zero_rather_than_reporting_negative_time():
    timer = StageTimer()
    timer.add("extract_ms", 900.0)
    assert timer.as_dict(total_ms=100.0)["unaccounted_ms"] == pytest.approx(0.0)


def test_shares_are_reported_against_the_total():
    timer = StageTimer()
    timer.add("extract_ms", 250.0)
    timer.add("host_build_ms", 500.0)
    out = timer.as_dict(total_ms=1000.0)
    assert out["extract_share_pct"] == pytest.approx(25.0)
    assert out["host_build_share_pct"] == pytest.approx(50.0)


def test_unknown_stage_names_are_flagged_not_silently_summed():
    # An unrecognized stage might be an enclosing one; summing it as a leaf would
    # understate unaccounted_ms, which is the field's whole purpose.
    timer = StageTimer()
    timer.add("extract_ms", 10.0)
    timer.add("mystery_ms", 5.0)
    out = timer.as_dict()
    assert out["stage_unclassified"] == ["mystery_ms"]


def test_declared_parents_are_excluded_from_the_leaf_total(monkeypatch):
    # Parents are declared, never inferred from the name -- an earlier SketchUp version
    # guessed from a "_total_ms" suffix and got it wrong on the third case.
    monkeypatch.setattr(stage_timing, "DECLARED_PARENTS", frozenset({"page_total_ms"}))
    timer = StageTimer()
    timer.add("page_total_ms", 900.0)
    timer.add("extract_ms", 200.0)
    timer.add("host_build_ms", 300.0)
    assert timer.leaf_total_ms() == pytest.approx(500.0)
    out = timer.as_dict(total_ms=1000.0)
    # 500 unattributed, NOT 900-summed-twice down to a misleading near-zero.
    assert out["unaccounted_ms"] == pytest.approx(500.0)
    assert out["stage_parents"] == ["page_total_ms"]


def test_schema_is_reported():
    assert StageTimer().as_dict()["schema"] == SCHEMA


def test_values_are_finite_and_rounded():
    timer = StageTimer()
    timer.add("extract_ms", 1.23456789)
    value = timer.as_dict()["extract_ms"]
    assert math.isfinite(value) and value == pytest.approx(1.235)


# --- iter_pages integration ----------------------------------------------------

def test_iter_pages_records_extract_and_host_build(tmp_path):
    path = _pdf(tmp_path, pages=2)
    timer = StageTimer()
    for _page_number, _page_data in iter_pages(path, stage_timing=timer):
        # Stand in for host-object construction so the gap is measurable.
        busy = 0
        for _ in range(20000):
            busy += 1
    assert timer.get("extract_ms") > 0.0
    assert timer.get("host_build_ms") > 0.0
    assert timer.pages == 2
    out = timer.as_dict()
    assert out["pages"] == 2
    assert "stage_unclassified" not in out  # both stages are known keys


def test_timer_does_not_change_what_iter_pages_yields(tmp_path):
    # The load-bearing property: measurement must be observationally inert.
    path = _pdf(tmp_path, pages=3)
    without = [
        (num, len(data.primitives), len(data.text_items), data.width, data.height)
        for num, data in iter_pages(path)
    ]
    with_timer = [
        (num, len(data.primitives), len(data.text_items), data.width, data.height)
        for num, data in iter_pages(path, stage_timing=StageTimer())
    ]
    assert without == with_timer
    assert len(without) == 3


def test_host_build_time_grows_with_time_spent_in_the_consumer(tmp_path):
    # Proves host_build_ms really measures the consumer, not extraction.
    path = _pdf(tmp_path, pages=1)
    quick = StageTimer()
    for _ in iter_pages(path, stage_timing=quick):
        pass
    slow = StageTimer()
    for _ in iter_pages(path, stage_timing=slow):
        total = 0
        for _ in range(400000):
            total += 1
    assert slow.get("host_build_ms") > quick.get("host_build_ms")


def test_iter_pages_without_a_timer_still_works(tmp_path):
    path = _pdf(tmp_path, pages=1)
    assert len(list(iter_pages(path))) == 1
