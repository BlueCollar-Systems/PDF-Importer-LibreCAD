"""A plain sheet with a border near the paper edge stays editable lines.

Auto mode used to treat any page with a few items and one border covering
most of the paper as "page frame only": it laid a full-page picture under the
real lines and lettering, or (with no text) delivered ONLY that picture. A
border is perfectly representable as vectors. A page picture is now added
only when the page shows ink the extractor did not deliver (a cheap coarse
render is the evidence), or when the page has no vector content at all.

Every fixture is synthetic and generated here (fictional job D042, mark EX101).
"""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from librecad_pdf_importer.core.document import ExtractionOptions, extract_document

W, H = 612.0, 792.0
NOTES = ("JOB D042 SAMPLE", "MARK EX101 PLATE", "W12X26 A572-50 TYP", "SEE DETAIL 4")


def _sheet(path: Path, *, border=True, line=True, notes=NOTES, picture=False,
           shading=False) -> Path:
    document = pymupdf.open()
    page = document.new_page(width=W, height=H)
    shape = page.new_shape()
    if border:
        shape.draw_rect(pymupdf.Rect(18, 18, W - 18, H - 18))
        shape.finish(color=(0, 0, 0), width=1)
    if line:
        shape.draw_line((72, 200), (540, 200))
        shape.finish(color=(0, 0, 0), width=0.5)
    shape.commit()
    for index, note in enumerate(notes):
        page.insert_text((72, 300 + index * 18), note, fontname="helv", fontsize=11)
    if picture:
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 64, 64), False)
        pixmap.clear_with(90)
        page.insert_image(pymupdf.Rect(40, 40, W - 40, H - 40), stream=pixmap.tobytes("png"))
    if shading:
        # Ink the vector extractor does not deliver: a large dark area drawn
        # as an image-free smooth shading.
        page.draw_rect(pymupdf.Rect(60, 420, 540, 700), color=None, fill=(0.2, 0.2, 0.2))
    document.save(str(path))
    document.close()
    return path


def _extract(path: Path, **options):
    return extract_document(str(path), ExtractionOptions(**options))


def _page_rasters(page):
    return [image for image in page.images if image.source_kind == "page_raster"]


def test_border_line_and_notes_stay_vectors_without_a_page_picture(tmp_path):
    with _extract(_sheet(tmp_path / "a.pdf")) as extraction:
        page = extraction.pages[0]
        assert not _page_rasters(page)
        assert len(page.page_data.primitives) == 2
        assert len(page.page_data.text_items) == 4
        assert page.resolved_mode != "raster"
        assert "raster fallback" not in str(page.resolved_reason or "")


def test_text_off_still_keeps_the_border_and_line_as_vectors(tmp_path):
    with _extract(_sheet(tmp_path / "a.pdf"), import_text=False) as extraction:
        page = extraction.pages[0]
        assert not _page_rasters(page)
        assert len(page.page_data.primitives) == 2
        assert page.resolved_mode != "raster"


@pytest.mark.parametrize("line", [False, True], ids=["border-only", "border-and-line"])
def test_border_only_sheets_stay_vectors(tmp_path, line):
    path = _sheet(tmp_path / "c.pdf", line=line, notes=())
    with _extract(path) as extraction:
        page = extraction.pages[0]
        assert not _page_rasters(page)
        assert len(page.page_data.primitives) == (2 if line else 1)
        assert page.resolved_mode != "raster"


def test_a_picture_inside_the_border_is_still_delivered(tmp_path):
    with _extract(_sheet(tmp_path / "p.pdf", picture=True, notes=())) as extraction:
        page = extraction.pages[0]
        assert page.images, "the embedded picture was lost"
        assert len(page.page_data.primitives) >= 1 or page.resolved_mode == "raster"


def test_a_truly_empty_page_still_gets_its_page_picture(tmp_path):
    path = _sheet(tmp_path / "empty.pdf", border=False, line=False, notes=())
    with _extract(path) as extraction:
        page = extraction.pages[0]
        assert len(_page_rasters(page)) == 1
        assert page.resolved_mode == "raster"


def test_unextracted_ink_on_a_frame_page_still_falls_back_to_raster(tmp_path, monkeypatch):
    """The coarse render is real evidence: ink the extractor did not deliver."""

    from librecad_pdf_importer.core import document as document_module

    path = _sheet(tmp_path / "missed.pdf", shading=True, notes=())
    real = document_module._frame_page_unextracted_ink_ratio

    def drop_the_dark_area(page, page_data, opts):
        # Pretend the extractor never saw the filled area, as with a shading.
        page_data.primitives = [
            prim for prim in page_data.primitives if prim.fill_color is None
        ]
        return real(page, page_data, opts)

    monkeypatch.setattr(document_module, "_frame_page_unextracted_ink_ratio", drop_the_dark_area)
    with _extract(path) as extraction:
        page = extraction.pages[0]
        assert page.resolved_mode == "raster"
        assert len(_page_rasters(page)) == 1
        assert "unextracted ink" in str(page.resolved_reason)
