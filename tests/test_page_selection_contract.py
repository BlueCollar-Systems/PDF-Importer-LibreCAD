from __future__ import annotations

from librecad_pdf_importer.core.document import parse_pages_spec
from pdf2dxf import _parse_pages
from pdf2dxf import _build_parser
import pytest


def test_cli_page_selection_keeps_zero_based_config_contract() -> None:
    assert _parse_pages("1") == [0]
    assert _parse_pages("2") == [1]
    assert _parse_pages("1,3-4") == [0, 2, 3]
    assert _parse_pages(" All ") is None


@pytest.mark.parametrize("raw", ["0", "-1", "4-2", "1,,2", "one"])
def test_cli_rejects_invalid_page_selection_instead_of_importing_page_one(raw: str) -> None:
    with pytest.raises(ValueError, match="page"):
        _parse_pages(raw)


def test_extractor_translates_zero_based_config_pages_to_pdf_page_numbers() -> None:
    assert parse_pages_spec([0], 4) == [1]
    assert parse_pages_spec([1], 4) == [2]
    assert parse_pages_spec([0, 2, 3], 4) == [1, 3, 4]


def test_extractor_rejects_an_out_of_range_selection_instead_of_substituting_page_one() -> None:
    with pytest.raises(ValueError, match="outside"):
        parse_pages_spec([8], 4)


def test_cli_exposes_real_page_resume_without_changing_the_simple_default() -> None:
    parser = _build_parser()

    assert parser.parse_args(["input.pdf", "output.dxf"]).resume is False
    assert parser.parse_args(["input.pdf", "output.dxf", "--resume"]).resume is True


@pytest.mark.parametrize("selection", [[0, 8], [-1, 0], [0.5], [True], []])
def test_extractor_validates_every_requested_page(selection) -> None:
    with pytest.raises(ValueError, match="page|Page"):
        parse_pages_spec(selection, 4)


@pytest.mark.parametrize("selection", ["1,5", "1-1000000000", "1,,2", "4-2", "one"])
def test_string_selection_is_bounded_and_never_silently_truncated(selection) -> None:
    with pytest.raises(ValueError, match="page"):
        parse_pages_spec(selection, 4)


def test_cli_parser_bounds_ranges_before_expansion() -> None:
    assert _parse_pages("1,3-4", 4) == [0, 2, 3]
    with pytest.raises(ValueError, match="outside this 4-page PDF"):
        _parse_pages("1-1000000000", 4)


def test_resumable_selection_is_rejected_before_resetting_a_session(tmp_path) -> None:
    import pymupdf
    from pdfcadcore.import_config import ImportConfig
    from dxf_import_engine import convert

    pdf = tmp_path / "source.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.save(pdf)
    session = tmp_path / "drawing_resume"
    session.mkdir()
    original = b'{"source_sha256":"old", "options_sha256":"old", "completed":{}}'
    manifest = session / "session.json"
    manifest.write_bytes(original)
    config = ImportConfig.auto()
    config.pages = [0, 1]
    with pytest.raises(ValueError, match="outside this 1-page PDF"):
        convert(str(pdf), str(tmp_path / "drawing.dxf"), config,
                resumable=True, restart_on_resume_mismatch=True)
    assert manifest.read_bytes() == original
    assert not (tmp_path / "drawing.dxf").exists()


@pytest.mark.parametrize("selection", ["1,2", "1-1000000000"])
def test_real_cli_rejects_out_of_range_pages_without_writing_any_output(tmp_path, selection):
    import subprocess
    import sys
    from pathlib import Path
    import pymupdf
    from pdf_open_guard import precheck_pdf

    source = tmp_path / "one-page.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.save(source)
    source_bytes = source.read_bytes()
    assert precheck_pdf(str(source)) == 1
    output = tmp_path / "output.dxf"
    result = subprocess.run(
        [sys.executable, "pdf2dxf.py", str(source), str(output), "--pages", selection, "--resume"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2
    assert "outside this 1-page PDF" in result.stderr
    assert source.read_bytes() == source_bytes
    assert not output.exists()
    assert not (tmp_path / "output_resume").exists()
