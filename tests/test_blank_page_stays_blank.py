"""A blank PDF page is an empty sheet, not a full-page picture."""
from __future__ import annotations

import pymupdf

from librecad_pdf_importer.importer import run_import


def test_blank_page_is_not_rasterized(tmp_path):
    pdf_path = tmp_path / "blank.pdf"
    document = pymupdf.open()
    document.new_page(width=200, height=200)
    document.save(pdf_path)
    document.close()

    run = run_import(str(pdf_path), mode="auto", overrides={"pages": "1"})
    page = run.extraction.pages[0]
    assert page.resolved_mode == "vector"
    assert page.images == []
    assert page.page_data.primitives == []
    assert "Blank page" in (page.resolved_reason or "")
