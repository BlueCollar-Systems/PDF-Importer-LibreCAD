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


def _sheet(path: Path, *, border=True, line=True, notes=NOTES, picture=False) -> Path:
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


def _frame_sheet_with_pattern_fill(path: Path, *, notes=NOTES) -> Path:
    """Border + one line + notes + a tiling-pattern fill the extractor does not
    turn into lines (``/Pattern cs /P1 scn ... re f``)."""

    path = _sheet(path, notes=notes)
    document = pymupdf.open(str(path))
    page = document[0]
    page.clean_contents()
    pattern = document.get_new_xref()
    document.update_object(
        pattern,
        "<< /Type /Pattern /PatternType 1 /PaintType 1 /TilingType 1"
        " /BBox [0 0 8 8] /XStep 8 /YStep 8 /Resources << >> /Length 0 >>",
    )
    document.update_stream(pattern, b"0 0 0 rg 0 0 4 4 re f 4 4 4 4 re f")
    document.xref_set_key(page.xref, "Resources/Pattern", f"<< /P1 {pattern} 0 R >>")
    [contents] = page.get_contents()
    document.update_stream(
        contents,
        document.xref_stream(contents) + b"\nq /Pattern cs /P1 scn 60 92 480 280 re f Q\n",
    )
    patterned = path.with_name(path.stem + "_pattern.pdf")
    document.save(str(patterned))
    document.close()
    return patterned


@pytest.mark.parametrize("notes", [NOTES, ()], ids=["with-notes", "no-notes"])
@pytest.mark.parametrize("import_text", [True, False], ids=["text-on", "text-off"])
def test_ink_the_extractor_missed_keeps_a_page_picture_under_the_lines(
    tmp_path, notes, import_text
):
    """The coarse render is real evidence: a pattern fill the extractor does
    not turn into lines is still seen, as a page picture laid under the lines
    and text, which stay editable. Notes on the sheet never switch this off."""

    path = _frame_sheet_with_pattern_fill(tmp_path / "missed.pdf", notes=notes)
    with _extract(path, import_text=import_text) as extraction:
        page = extraction.pages[0]
        assert len(_page_rasters(page)) == 1, "the patterned area would be lost"
        assert len(page.page_data.primitives) == 2
        assert len(page.page_data.text_items) == (len(notes) if import_text else 0)
        assert page.resolved_mode == "hybrid"
        reason = str(page.resolved_reason)
        assert "unextracted ink" in reason and "fallback" in reason


def test_missed_ink_step_down_is_written_and_reported(tmp_path):
    """The DXF holds the lines, the notes and the page picture, and the
    import report says a fallback was used and why."""

    import json

    import ezdxf

    import pdf2dxf

    path = _frame_sheet_with_pattern_fill(tmp_path / "report.pdf")
    output = tmp_path / "report.dxf"
    assert pdf2dxf.main([str(path), str(output)]) == 0
    types = [entity.dxftype() for entity in ezdxf.readfile(str(output)).modelspace()]
    assert types.count("IMAGE") == 1
    assert types.count("LWPOLYLINE") == 2
    assert types.count("INSERT") == 4
    [report_path] = list(tmp_path.glob("report_import_report.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["fallback"]["used"] is True
    assert "unextracted ink" in report["fallback"]["reason"]
    assert "unextracted ink" in report["extra"]["human_summary"]


def test_at_r12_a_missed_ink_frame_page_keeps_its_lines(tmp_path):
    """R12 cannot hold the page picture: it is left out (outlined and
    reported), and the border and line still come in as lines."""

    import ezdxf

    import pdf2dxf

    path = _frame_sheet_with_pattern_fill(tmp_path / "r12.pdf", notes=())
    output = tmp_path / "r12.dxf"
    assert pdf2dxf.main([str(path), str(output), "--dxf-version", "R12"]) == 0
    layers = [
        (entity.dxftype(), entity.dxf.layer)
        for entity in ezdxf.readfile(str(output)).modelspace()
    ]
    omitted = [row for row in layers if row[1].endswith("_PICTURES_OMITTED_R12")]
    lines = [row for row in layers if row[0] == "POLYLINE" and row not in omitted]
    assert len(omitted) == 1
    assert len(lines) == 2


def _text_cloud_sheet(path: Path) -> Path:
    """A border, one line and 200 short notes: Auto's text-cloud page."""

    document = pymupdf.open()
    page = document.new_page(width=W, height=H)
    shape = page.new_shape()
    shape.draw_rect(pymupdf.Rect(40, 40, W - 40, H - 40))
    shape.finish(color=(0, 0, 0), width=1)
    shape.draw_line((60, 100), (550, 100))
    shape.finish(color=(0, 0, 0), width=0.5)
    shape.commit()
    for index in range(200):
        row, column = divmod(index, 5)
        page.insert_text(
            (60 + column * 100, 130 + row * 15), f"EX{index:03d}", fontname="helv", fontsize=9
        )
    document.save(str(path))
    document.close()
    return path


@pytest.mark.parametrize("pictures_supported", [True, False], ids=["r2010", "r12"])
def test_a_text_cloud_page_keeps_its_lines_when_pictures_cannot_be_written(
    tmp_path, pictures_supported
):
    path = _text_cloud_sheet(tmp_path / "cloud.pdf")
    with _extract(
        path, requested_text_representation="none", pictures_supported=pictures_supported
    ) as extraction:
        page = extraction.pages[0]
        assert len(_page_rasters(page)) == 1
        if pictures_supported:
            assert page.resolved_mode == "raster"
            assert not page.page_data.primitives
        else:
            assert page.resolved_mode == "hybrid"
            assert len(page.page_data.primitives) == 2
            assert "fallback" in str(page.resolved_reason)


def _frame_sheet_with_smooth_shading(path: Path) -> Path:
    """Border + one line + a real smooth shading (PDF ``sh``), no text."""

    document = pymupdf.open()
    page = document.new_page(width=W, height=H)
    shape = page.new_shape()
    shape.draw_rect(pymupdf.Rect(18, 18, W - 18, H - 18))
    shape.finish(color=(0, 0, 0), width=1)
    shape.draw_line((72, 200), (540, 200))
    shape.finish(color=(0, 0, 0), width=0.5)
    shape.commit()
    page.clean_contents()
    shading = document.get_new_xref()
    document.update_object(
        shading,
        "<< /ShadingType 2 /ColorSpace /DeviceGray /Coords [60 0 540 0]"
        " /Function << /FunctionType 2 /Domain [0 1] /C0 [0.2] /C1 [0.7] /N 1 >>"
        " /Extend [false false] >>",
    )
    document.xref_set_key(page.xref, "Resources/Shading", f"<< /Sh1 {shading} 0 R >>")
    [contents] = page.get_contents()
    document.update_stream(
        contents, document.xref_stream(contents) + b"\nq 60 92 480 280 re W n /Sh1 sh Q\n"
    )
    document.save(str(path))
    document.close()
    return path


def test_a_frame_page_with_a_smooth_shading_keeps_its_picture_and_is_written(tmp_path):
    """A smooth shading is not delivered as lines yet; a vector page holding
    one cannot be written, so such a frame page keeps the picture it always
    got instead of failing the whole file."""

    import pdf2dxf
    from librecad_pdf_importer.core.document import _page_paints_smooth_shading

    path = _frame_sheet_with_smooth_shading(tmp_path / "shade.pdf")
    with pymupdf.open(str(path)) as document:
        assert _page_paints_smooth_shading(document[0])
    with pymupdf.open(str(_sheet(tmp_path / "plain.pdf"))) as document:
        assert not _page_paints_smooth_shading(document[0])

    with _extract(path) as extraction:
        page = extraction.pages[0]
        assert page.resolved_mode == "raster"
        assert "smooth shading" in str(page.resolved_reason)

    output = tmp_path / "shade.dxf"
    assert pdf2dxf.main([str(path), str(output)]) == 0
    assert output.is_file()
