"""A mistyped DXF destination must never replace the drawing being imported."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import dxf_import_engine
from conversion_control import ImportStopped
from librecad_pdf_importer.exporters import dxf_exporter


@pytest.fixture
def source_pdf(tmp_path: Path) -> Path:
    # Fictional input: extraction is mocked, so even a failing regression cannot
    # run a conversion or overwrite the source.
    source = tmp_path / "drawing.pdf"
    source.write_bytes(b"%PDF-1.4\n% fictional source for output-path checks\n%%EOF\n")
    return source


@pytest.fixture(params=["same", "normalized", "relative", "case", "symlink", "hardlink"])
def source_alias(request, source_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    if request.param == "same":
        return source_pdf
    if request.param == "normalized":
        child = source_pdf.parent / "subdirectory"
        child.mkdir()
        return child / ".." / source_pdf.name
    if request.param == "relative":
        monkeypatch.chdir(source_pdf.parent)
        return Path(source_pdf.name)
    if request.param == "case":
        if os.name != "nt":
            pytest.skip("Windows case-insensitive path handling")
        return source_pdf.with_name("DRAWING.PDF")
    alias = source_pdf.with_name("alias.dxf")
    try:
        if request.param == "symlink":
            alias.symlink_to(source_pdf)
        else:
            alias.hardlink_to(source_pdf)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"{request.param} unavailable: {exc}")
    return alias


@pytest.mark.parametrize("resumable", [False, True])
def test_engine_rejects_source_alias_before_pipeline_or_resume_writes(
    source_pdf: Path, source_alias: Path, monkeypatch: pytest.MonkeyPatch, resumable: bool,
) -> None:
    before = source_pdf.read_bytes()
    package = Mock(return_value={})
    resume = Mock(return_value={})
    monkeypatch.setattr(dxf_import_engine, "_convert_via_package", package)
    monkeypatch.setattr(dxf_import_engine, "_convert_resumable", resume)

    with pytest.raises(ImportStopped, match="source PDF.*different output"):
        dxf_import_engine.convert(str(source_pdf), str(source_alias), resumable=resumable)

    package.assert_not_called()
    resume.assert_not_called()
    assert source_pdf.read_bytes() == before


def test_direct_export_rejects_source_alias_before_assets_or_dxf_writes(
    source_pdf: Path, source_alias: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = source_pdf.read_bytes()
    export = Mock(return_value=object())
    monkeypatch.setattr(dxf_exporter, "_export_to_dxf_once", export)

    with pytest.raises(ImportStopped, match="source PDF.*different output"):
        dxf_exporter.export_to_dxf(SimpleNamespace(pdf_path=str(source_pdf)), str(source_alias))

    export.assert_not_called()
    assert source_pdf.read_bytes() == before


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("resumable", [False, True])
def test_engine_preserves_dispatch_for_a_separate_output(
    source_pdf: Path, monkeypatch: pytest.MonkeyPatch, resumable: bool, existing: bool,
) -> None:
    output = source_pdf.with_suffix(".dxf")
    if existing:
        output.write_bytes(b"previous DXF")
    result = {"pages": 1}
    dispatch = Mock(return_value=result)
    target = "_convert_resumable" if resumable else "_convert_via_package"
    monkeypatch.setattr(dxf_import_engine, target, dispatch)

    assert dxf_import_engine.convert(
        str(source_pdf), str(output), resumable=resumable,
    ) is result
    dispatch.assert_called_once()


@pytest.mark.parametrize("existing", [False, True])
def test_direct_export_preserves_a_separate_output(
    source_pdf: Path, monkeypatch: pytest.MonkeyPatch, existing: bool,
) -> None:
    output = source_pdf.with_suffix(".dxf")
    if existing:
        output.write_bytes(b"previous DXF")
    result = object()
    export = Mock(return_value=result)
    monkeypatch.setattr(dxf_exporter, "_export_to_dxf_once", export)
    extraction = SimpleNamespace(pdf_path=str(source_pdf))

    assert dxf_exporter.export_to_dxf(extraction, str(output)) is result
    export.assert_called_once_with(extraction, str(output), None)
