from __future__ import annotations

from librecad_pdf_importer.core.document import parse_pages_spec
from pdf2dxf import _parse_pages
from pdf2dxf import _build_parser
import pytest


def test_cli_page_selection_keeps_zero_based_config_contract() -> None:
    assert _parse_pages("1") == [0]
    assert _parse_pages("2") == [1]
    assert _parse_pages("1,3-4") == [0, 2, 3]


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
