"""Invalid reference dimensions must not import or write a scaled drawing."""
from unittest.mock import Mock

import pytest

from librecad_pdf_importer import cli


@pytest.mark.parametrize("flags", [
    ["--scale", "0"], ["--scale", "-1"], ["--scale", "nan"], ["--scale", "inf"],
    ["--reference-detected-mm", "10"], ["--reference-real-mm", "10"],
    ["--reference-detected-mm", "0", "--reference-real-mm", "10"],
    ["--reference-detected-mm", "10", "--reference-real-mm", "-1"],
    ["--reference-detected-mm", "nan", "--reference-real-mm", "10"],
    ["--reference-detected-mm", "10", "--reference-real-mm", "inf"],
    ["--reference-detected-mm", "1e-300", "--reference-real-mm", "1e300"],
    ["--reference-detected-mm", "1e300", "--reference-real-mm", "1e-300"],
])
def test_invalid_scale_stops_before_source_or_output_work(monkeypatch, capsys, flags):
    monkeypatch.setattr("sys.argv", ["lcpdf-import", "drawing.pdf", *flags])
    imported = Mock()
    exported = Mock()
    monkeypatch.setattr(cli, "run_import", imported)
    monkeypatch.setattr(cli, "export_to_dxf", exported)
    assert cli.main() == 1
    assert capsys.readouterr().err.strip()
    imported.assert_not_called()
    exported.assert_not_called()


def test_both_cli_entrypoints_default_to_the_documented_legacy_dxf():
    from pdf2dxf import _build_parser

    assert cli.build_parser().parse_args(["drawing.pdf"]).dxf_version == "R2010"
    assert _build_parser().parse_args(["drawing.pdf"]).dxf_version == "R2010"
