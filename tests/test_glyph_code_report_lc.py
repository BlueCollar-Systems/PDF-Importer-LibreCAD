"""Text delivered as raw glyph codes reaches the LibreCAD operator and report.

LibreCAD imports through pdfcadcore.extract_page, so the shared recovery runs
inside extraction; this host's job is to carry the records onto the page, into
extra.text_glyph_codes, into result.warnings and into one operator line.

Every record here is synthetic (SAMPLE font, fictional job 1000-01).
"""
import json
import sys
from pathlib import Path

import pymupdf
import pytest

from librecad_pdf_importer.core.document import DocumentExtraction, ExtractedPage
from librecad_pdf_importer.importer import run_import, write_import_report
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.primitives import PageData

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

STROKE = b' 0 G 5 5 m 95 5 l S'


def make_pdf(path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=100, height=100)
    page.draw_rect(page.rect)
    pdf.update_stream(page.get_contents()[0], STROKE)
    pdf.save(path)
    pdf.close()
    return str(path)


def recovered(page=1, codes=(2, 4, 5, 1), route="outline_identity"):
    return {
        "page_number": page, "font_name": "SampleGothic", "source_xref": 7,
        "status": "recovered", "route": route, "routes": {route: len(codes)},
        "reason": "", "glyphs": len(codes), "glyphs_recovered": len(codes),
        "raw_codes": list(codes), "raw_codes_truncated": False,
        "reference_faces": ["sample.ttf"], "bbox_pdf": [10.0, 90.0, 60.0, 104.0],
    }


def unproven(page=1, codes=(9, 9), bbox=(200.0, 90.0, 240.0, 104.0)):
    return {
        "page_number": page, "font_name": "SampleGothic", "source_xref": 7,
        "status": "unproven", "route": "", "routes": {},
        "reason": "no_reference_face_available",
        "detail": "no installed face matches 'samplegothic' (0 faces indexed)",
        "glyphs": len(codes), "glyphs_unproven": len(codes),
        "raw_codes": list(codes), "raw_codes_truncated": False,
        "looked_for_face": "samplegothic", "reference_faces": [],
        "bbox_pdf": list(bbox),
    }


def extraction_with(*issues_per_page):
    return DocumentExtraction(pdf_path="SAMPLE.pdf", pages=[
        ExtractedPage(
            page_data=PageData(page_number=number + 1, width=100.0, height=100.0),
            profile=None, resolved_mode="vector", glyph_code_issues=list(issues),
        )
        for number, issues in enumerate(issues_per_page)
    ])


def test_the_document_block_counts_every_page_and_names_the_routes():
    extraction = extraction_with([recovered(), unproven()],
                                 [recovered(page=2, route="embedded_cmap")])

    block = extraction.glyph_code_delivery()

    assert block["schema"] == "bcs.text_glyph_codes/1.0"
    assert (block["spans_examined"], block["recovered"], block["unproven"]) == (3, 2, 1)
    assert block["spans_by_route"] == {"embedded_cmap": 1, "outline_identity": 1}
    assert block["by_reason"] == {"no_reference_face_available": 1}
    assert block["pages"] == [1, 2]
    json.dumps(block, allow_nan=False)


def test_a_document_where_everything_was_proven_never_warns():
    extraction = extraction_with([recovered(), recovered()])

    block = extraction.glyph_code_delivery()

    assert (block["recovered"], block["unproven"]) == (2, 0)
    line = extraction.glyph_code_warning()
    assert "outline_identity" in line and "not read from the PDF" in line
    assert "could not be proven" not in line


def test_the_operator_line_names_the_font_and_the_page_of_an_unproven_span():
    extraction = extraction_with([unproven()], [unproven(page=2)])

    line = extraction.glyph_code_warning()

    assert "2 text span(s)" in line and "SampleGothic" in line
    assert "page 1, 2" in line
    assert "See text_glyph_codes in the import report." in line
    assert "\n" not in line


def test_a_document_with_no_glyph_code_spans_says_nothing():
    extraction = extraction_with([])

    assert extraction.glyph_code_delivery()["spans_examined"] == 0
    assert extraction.glyph_code_warning() == ""


def test_the_import_report_publishes_the_block_and_adds_to_the_warning_sum(tmp_path):
    source = make_pdf(tmp_path / "D042.pdf")
    report_path = tmp_path / "D042_import_report.json"
    with run_import(source, mode="vector", overrides={"import_text": False}) as run:
        write_import_report(run, str(report_path))
        baseline = json.loads(report_path.read_text(encoding="utf-8"))
        assert "text_glyph_codes" not in baseline["extra"]

        run.extraction.pages[0].glyph_code_issues = [recovered(), unproven(), unproven()]
        write_import_report(run, str(report_path))
        report = json.loads(report_path.read_text(encoding="utf-8"))

    block = report["extra"]["text_glyph_codes"]
    assert (block["recovered"], block["unproven"]) == (1, 2)
    assert [item["status"] for item in block["items"]][:2] == ["unproven", "unproven"]
    assert block["items"][0]["raw_codes"] == [9, 9]
    # The two unproven spans ADD to whatever this document warned about already.
    assert report["result"]["warnings"] == baseline["result"]["warnings"] + 2


def test_a_recovered_span_alone_adds_no_warning(tmp_path):
    source = make_pdf(tmp_path / "D100.pdf")
    report_path = tmp_path / "D100_import_report.json"
    with run_import(source, mode="vector", overrides={"import_text": False}) as run:
        write_import_report(run, str(report_path))
        baseline = json.loads(report_path.read_text(encoding="utf-8"))
        run.extraction.pages[0].glyph_code_issues = [recovered(), recovered()]
        write_import_report(run, str(report_path))
        report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["extra"]["text_glyph_codes"]["recovered"] == 2
    assert report["result"]["warnings"] == baseline["result"]["warnings"]


def test_extraction_carries_the_core_records_onto_every_page(tmp_path, monkeypatch):
    # The page loop reads the core's records for that page, beside the
    # clipped-fill records, from the page it has just extracted.
    from librecad_pdf_importer.core import document as document_module

    seen = []

    def fake_issues(page):
        seen.append(page)
        return [unproven(page=page.number + 1)]

    monkeypatch.setattr(document_module, "core_glyph_code_issues", fake_issues)
    source = make_pdf(tmp_path / "D042.pdf")
    with run_import(source, mode="vector", overrides={"import_text": False}) as run:
        assert len(seen) == 1
        assert [len(page.glyph_code_issues) for page in run.extraction.pages] == [1]
        assert run.extraction.glyph_code_delivery()["unproven"] == 1


@pytest.mark.parametrize("status", ["recovered", "unproven"])
def test_the_engine_hands_the_caller_one_line_and_the_block(tmp_path, monkeypatch, status):
    import dxf_import_engine
    from librecad_pdf_importer.core import document as document_module

    record = recovered() if status == "recovered" else unproven()
    monkeypatch.setattr(document_module, "core_glyph_code_issues", lambda _page: [record])
    stats = dxf_import_engine.convert(
        make_pdf(tmp_path / "D042.pdf"), str(tmp_path / "D042.dxf"),
        ImportConfig(import_text=False),
    )

    assert stats["text_glyph_codes"]["spans_examined"] == 1
    assert ("could not be proven" in stats["text_glyph_code_warning"]) == (status == "unproven")


# ── every entry point says the same thing ──


def test_the_cli_summary_publishes_the_block_beside_clip_fill_delivery():
    # A caller driving LibreCAD through the CLI must not have to read a
    # free-text stderr line to learn that text was recovered rather than read.
    extraction = extraction_with([recovered(), unproven()])

    summary = extraction.summary()

    assert "clip_fill_delivery" in summary
    assert summary["text_glyph_codes"] == extraction.glyph_code_delivery()


def test_a_batch_run_prints_one_line_and_counts_only_the_unproven_span(tmp_path, monkeypatch):
    import librecad_pdf_importer.batch_cli as batch_cli
    from librecad_pdf_importer.core import document as document_module

    monkeypatch.setattr(document_module, "core_glyph_code_issues",
                        lambda _page: [recovered(), unproven()])
    source_dir = tmp_path / "in"
    source_dir.mkdir()
    make_pdf(source_dir / "D042.pdf")
    report = tmp_path / "batch.json"
    errors = []
    monkeypatch.setattr(batch_cli, "_print_stderr", lambda line: errors.append(line))
    monkeypatch.setattr(sys, "argv", [
        "batch_cli", str(source_dir), str(tmp_path / "out"),
        "--json", str(report), "--mode", "vector", "--text-mode", "geometry",
    ])

    batch_cli.main()

    aggregate = json.loads(report.read_text(encoding="utf-8"))
    record = aggregate["results"][0]
    assert record["text_glyph_codes"]["spans_examined"] == 2
    # The recovered span is a clean delivery; only the unproven one warns.
    assert record["warnings"] == 1
    assert aggregate["warnings"] == 1
    assert any("could not be proven" in line for line in errors)
    assert any("text_glyph_codes" in line for line in errors)


def test_a_resumed_conversion_publishes_the_block_and_the_warning_term(tmp_path):
    # A cancelled-and-resumed run writes bcs.resumable_import_report/1.0, and
    # that is the report the operator is pointed at. It must say what a
    # single-shot run says, about the same document.
    import dxf_import_engine
    from pdfcadcore.glyph_code_recovery import glyph_code_delivery_block

    output = tmp_path / "D042.dxf"
    output.write_text("", encoding="utf-8")
    manifest = {
        "source_sha256": "0" * 64,
        "options_sha256": "1" * 64,
        "completed": {
            "0": {"page_number": 1, "text_delivery": {},
                  "clip_fill_delivery": {}, "searchable_text_companions": {},
                  "text_glyph_codes": glyph_code_delivery_block([recovered()])},
            "1": {"page_number": 2, "text_delivery": {},
                  "clip_fill_delivery": {}, "searchable_text_companions": {},
                  "text_glyph_codes": glyph_code_delivery_block([unproven(page=2)])},
        },
    }

    summary_path = dxf_import_engine._write_resumable_summary(str(output), manifest, [0, 1])
    payload = json.loads(Path(summary_path).read_text(encoding="utf-8"))

    block = payload["text_glyph_codes"]
    assert (block["spans_examined"], block["recovered"], block["unproven"]) == (2, 1, 1)
    assert block["pages"] == [1, 2]
    assert block["spans_by_route"] == {"outline_identity": 1}
    # Only the unproven span warns; the recovered one is a clean delivery.
    assert payload["warnings"] == 1


def test_the_resumable_stats_carry_the_operator_line_like_a_single_shot_run():
    from librecad_pdf_importer.core.document import glyph_code_warning_line
    from pdfcadcore.glyph_code_recovery import glyph_code_delivery_block

    line = glyph_code_warning_line([glyph_code_delivery_block([recovered(), unproven()])])

    assert "1 text span(s) use an embedded font" in line
    assert "were recovered (outline_identity x1)" in line
    assert "\n" not in line


def test_the_gui_shows_the_operator_the_line_the_engine_produced():
    # The window is checked the way this repo checks it: it logs the line the
    # engine produced and repeats it in the completion box, beside every
    # sibling warning it already surfaces.
    source = (REPO_ROOT / "gui.py").read_text(encoding="utf-8")

    assert 'stats.get("text_glyph_code_warning")' in source
    assert 'f"\\n\\n{glyph_code_warning}" if glyph_code_warning else ""' in source
