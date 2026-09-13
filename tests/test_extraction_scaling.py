"""Lossless text scaling: historical predicate/order, synthetic source data only."""
from pathlib import Path
import random
import pytest
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / 'PDFVectorImporter', ROOT / 'pdf_vector_importer', ROOT):
    if (candidate / 'pdfcadcore').is_dir():
        sys.path.insert(0, str(candidate))
        break
from pdfcadcore import primitive_extractor as pe
from pdfcadcore.primitives import NormalizedText


def text(i, value, x, y, size=3, rotation=0, page=1):
    return NormalizedText(id=i, text=value, normalized=value, insertion=(x, y),
        bbox=(x, y, x + size, y + size), font_size=size, rotation=rotation, page_number=page)


def reference(items):
    kept = []
    for item in items:
        match = next((i for i, other in enumerate(kept) if pe._fraction_overlay_duplicate(other, item)), None)
        if match is None:
            kept.append(item)
        elif pe._fraction_dedupe_score(item) < pe._fraction_dedupe_score(kept[match]):
            kept[match] = item
    return [item for item in kept if not (pe._SLASH_RE.match((item.text or '').strip())
        and any(other is not item and pe._slash_fraction_overlay_duplicate(item, other) for other in kept))]


def test_fraction_index_matches_historical_order_and_replacement():
    if not hasattr(pe, '_dedupe_fraction_overlays'):
        pytest.skip('This host uses a separate source-character-certified merge.')
    rng = random.Random(1709)
    for _ in range(40):
        items = [text(i, rng.choice(['1/2', '1 / 2', '3/16', '/', 'A1', '316', 'DETAIL']),
            rng.randrange(-12, 12) * .41, rng.randrange(-12, 12) * .43,
            rng.choice([1, 2, 3, 4]), rng.choice([0, 1, 90]), rng.choice([1, 2])) for i in range(250)]
        items[0].bbox = None
        assert pe._dedupe_fraction_overlays(items) == reference(items)


def test_nonfraction_and_distant_fraction_text_avoid_quadratic_comparisons(monkeypatch):
    if not hasattr(pe, '_dedupe_fraction_overlays'):
        pytest.skip('This host uses a separate source-character-certified merge.')
    count = 0
    original = pe._fraction_overlay_duplicate
    def counted(a, b):
        nonlocal count
        count += 1
        return original(a, b)
    monkeypatch.setattr(pe, '_fraction_overlay_duplicate', counted)
    items = [text(i, '1/2' if i % 3 == 0 else 'DETAIL', i % 100 * 30, i // 100 * 30) for i in range(8000)]
    assert pe._dedupe_fraction_overlays(items) == items
    assert count < len(items) * 10


def test_glyph_queue_preserves_every_repeated_character_and_font_in_order():
    page = SimpleNamespace(get_texttrace=lambda: [
        {'font': 'A', 'chars': [(ord('A'), i) for i in range(30000)]},
        {'font': 'B', 'chars': [(ord('A'), 999)]}])
    queues = pe._trace_glyph_queues(page)
    assert [pe._pop_trace_glyph_id(queues, 'A', 'A') for _ in range(30000)] == list(range(30000))
    assert pe._pop_trace_glyph_id(queues, 'A', 'A') is None
    assert pe._pop_trace_glyph_id(queues, 'B', 'A') == 999


def test_fraction_index_preserves_rounded_cell_boundary_matches():
    if not hasattr(pe, '_dedupe_fraction_overlays'):
        pytest.skip('This host uses a separate source-character-certified merge.')
    tol = getattr(pe, '_FRAC_OVERLAY_TOL_MM', None) or pe._FRAC_X_OVERLAP_MM
    a, b = text(1, '1/2', 0, 0), text(2, '1/2', 0, 0)
    # A tiny negative center and exactly one tolerance away can round to
    # an accepted distance while falling two grid cells apart.
    a.bbox = (-1e-100, -2, -1e-100, 2)
    b.bbox = (0, -2, tol * 2, 2)
    assert pe._fraction_overlay_duplicate(a, b)
    assert pe._dedupe_fraction_overlays([a, b]) == reference([a, b])
