"""Accuracy-preserving import performance regressions for pdfcadcore."""
from __future__ import annotations

import importlib
import math
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _package_name() -> str:
    if (ROOT / "PDFVectorImporter" / "pdfcadcore").is_dir():
        return "PDFVectorImporter.pdfcadcore"
    if (ROOT / "pdf_vector_importer" / "pdfcadcore").is_dir():
        return "pdf_vector_importer.pdfcadcore"
    return "pdfcadcore"


def _module(name: str):
    return importlib.import_module(f"{_package_name()}.{name}")


def _fingerprint(page_data) -> tuple:
    prims = tuple(
        (
            p.type,
            tuple(p.points or ()),
            p.center,
            p.radius,
            p.start_angle,
            p.end_angle,
            p.closed,
        )
        for p in page_data.primitives
    )
    texts = tuple(
        (t.text, t.normalized, t.insertion, tuple(t.generic_tags))
        for t in page_data.text_items
    )
    return prims, texts, page_data.width, page_data.height


def test_drawings_need_text_counts_skips_stroked_cad_pages() -> None:
    auto_mode = _module("auto_mode")
    stroked = [
        {"fill": None, "color": (0, 0, 0), "items": [("l", i)], "rect": (0, 0, 10, 10)}
        for i in range(2000)
    ]
    fill_flood = [
        {"fill": (0, 0, 0), "color": None, "items": [("re", i)], "rect": (0, 0, 1, 1)}
        for i in range(2000)
    ]
    assert auto_mode.drawings_need_text_counts([]) is True
    assert auto_mode.drawings_need_text_counts(stroked) is False
    assert auto_mode.drawings_need_text_counts(fill_flood) is True

    stroked_class = auto_mode.classify_page_content(
        stroked, text_blocks_count=0, text_words_count=0, page_area=20000.0
    )
    stroked_with_text = auto_mode.classify_page_content(
        stroked, text_blocks_count=2000, text_words_count=4000, page_area=20000.0
    )
    assert stroked_class["type"] == stroked_with_text["type"] == "vectors"


def test_classify_text_is_idempotent_and_keeps_tag_meanings() -> None:
    primitives = _module("primitives")
    classifier = _module("generic_classifier")
    page = primitives.PageData(
        page_number=1,
        width=100.0,
        height=100.0,
        text_items=[
            primitives.NormalizedText(id=1, text="NOTE 1", normalized="NOTE 1"),
            primitives.NormalizedText(id=2, text='1" = 1', normalized='1" = 1'),
            primitives.NormalizedText(id=3, text="W12x26", normalized="W12X26"),
        ],
    )
    classifier.classify_text(page)
    first = [list(t.generic_tags) for t in page.text_items]
    classifier.classify_text(page)
    second = [list(t.generic_tags) for t in page.text_items]
    assert first == second
    assert "note_indicator" in first[0]
    assert "dimension_like" in first[1]
    assert first[2] == []


def test_dimension_association_matches_all_pairs_reference() -> None:
    primitives = _module("primitives")
    recognizer = _module("generic_recognizer")
    lines = []
    for index in range(80):
        x = (index % 10) * 40.0
        y = (index // 10) * 40.0
        lines.append(
            primitives.Primitive(
                id=index + 1,
                type="line",
                points=[(x, y), (x + 10.0, y)],
                bbox=(x, y, x + 10.0, y + 0.5),
            )
        )
    texts = [
        primitives.NormalizedText(
            id=1001,
            text="12 MM",
            normalized="12 MM",
            insertion=(5.0, 0.2),
            generic_tags=["dimension_like"],
        ),
        primitives.NormalizedText(
            id=1002,
            text="25 MM",
            normalized="25 MM",
            insertion=(205.0, 120.2),
            generic_tags=["dimension_like"],
        ),
        primitives.NormalizedText(
            id=1003,
            text="99 MM",
            normalized="99 MM",
            insertion=(900.0, 900.0),
            generic_tags=["dimension_like"],
        ),
    ]
    radius = primitives.RecognitionConfig().dimension_assoc_radius
    expected = []
    for txt in texts:
        nearest = None
        nearest_dist = radius
        for prim in lines:
            cx = (prim.bbox[0] + prim.bbox[2]) / 2.0
            cy = (prim.bbox[1] + prim.bbox[3]) / 2.0
            dist = math.hypot(txt.insertion[0] - cx, txt.insertion[1] - cy)
            if dist < nearest_dist:
                nearest = prim
                nearest_dist = dist
        expected.append(nearest.id if nearest is not None else None)

    actual = recognizer.associate_dimensions(texts, lines, radius)
    assert [row["nearest_prim_id"] for row in actual] == expected
    assert actual[0]["nearest_prim_id"] == 1
    assert actual[2]["nearest_prim_id"] is None


def test_dense_circle_recognition_and_profile_preserve_all_points():
    primitives = _module("primitives")
    profiler = _module("document_profiler")
    recognizer = _module("generic_recognizer")
    points = [(10 + 5 * math.cos(i * math.tau / 200),
               10 + 5 * math.sin(i * math.tau / 200)) for i in range(201)]
    page = primitives.PageData(page_number=1, width=100, height=100,
        primitives=[primitives.Primitive(id=1, type="closed_loop", points=points,
            closed=True, bbox=(5, 5, 15, 15), area=math.pi * 25)])
    assert profiler.profile(page).circle_count == 1
    result = recognizer.analyze(page)
    assert len(result.circles) == 1
    assert result.circles[0]["radius"] == pytest.approx(5)
    assert page.primitives[0].points == points


def test_partial_existing_classifier_tags_do_not_suppress_other_meanings():
    primitives = _module("primitives")
    classifier = _module("generic_classifier")
    text = primitives.NormalizedText(id=1, text="NOTE 12 MM", normalized="NOTE 12 MM",
        generic_tags=["note_indicator"])
    page = primitives.PageData(page_number=1, width=100, height=100, text_items=[text])
    classifier.classify_text(page)
    assert text.generic_tags == ["note_indicator", "dimension_like"]
    text.normalized = "NOTE 12 MM QTY"
    classifier.classify_text(page)
    assert text.generic_tags == ["note_indicator", "dimension_like", "quantity_indicator"]


def test_extract_page_reuses_prefetched_drawings(tmp_path) -> None:
    extractor = _module("primitive_extractor")
    fitz = pytest.importorskip("pymupdf")

    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.draw_line(fitz.Point(10, 10), fitz.Point(290, 10))
    page.draw_rect(fitz.Rect(20, 30, 120, 90))
    page.draw_circle(fitz.Point(200, 120), 40)
    page.insert_text(fitz.Point(30, 180), "NOTE 1")
    path = tmp_path / "reuse_drawings.pdf"
    doc.save(str(path))
    doc.close()

    class CountingPage:
        def __init__(self, inner):
            self._inner = inner
            self.get_drawings_calls = 0

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def get_drawings(self, *args, **kwargs):
            self.get_drawings_calls += 1
            return self._inner.get_drawings(*args, **kwargs)

    src = fitz.open(str(path))
    inner = src[0]
    counted = CountingPage(inner)
    drawings = counted.get_drawings()
    assert counted.get_drawings_calls == 1
    reused = extractor.extract_page(counted, page_num=1, drawings=drawings)
    assert counted.get_drawings_calls == 1
    fetched = extractor.extract_page(CountingPage(src[0]), page_num=1)
    assert _fingerprint(reused) == _fingerprint(fetched)
    assert len(reused.primitives) >= 2
    src.close()
