from __future__ import annotations

import hashlib
from pathlib import Path, PureWindowsPath
import re

import ezdxf
try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 preferred name
except ImportError:
    import fitz  # Legacy fallback

from librecad_pdf_importer.exporters.dxf_exporter import (
    DxfExportOptions,
    export_to_dxf,
)
from librecad_pdf_importer.importer import run_import


_SESSION_NAME = re.compile(r"[0-9a-f]{32}")


def _build_opaque_image_pdf(path: Path) -> None:
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 4, 2), False)
    for y in range(2):
        for x in range(4):
            pixmap.set_pixel(x, y, (255, 0, 0) if x < 2 else (0, 0, 255))

    document = fitz.open()
    page = document.new_page(width=120, height=80)
    page.insert_image(fitz.Rect(20, 20, 100, 60), stream=pixmap.tobytes("png"))
    document.save(path)
    document.close()


def _single_image_filename(dxf_path: Path) -> str:
    drawing = ezdxf.readfile(dxf_path)
    image = next(iter(drawing.modelspace().query("IMAGE")))
    image_definition = drawing.entitydb.get(str(image.dxf.image_def_handle))
    assert image_definition is not None
    return str(image_definition.dxf.filename)


def _resolve_image_asset(dxf_path: Path, raw_filename: str) -> Path:
    serialized = Path(raw_filename)
    if serialized.is_absolute():
        return serialized.resolve()
    return (dxf_path.parent / serialized).resolve()


def _referenced_session(dxf_path: Path) -> Path:
    asset = _resolve_image_asset(dxf_path, _single_image_filename(dxf_path))
    asset_parent = dxf_path.with_name(f"{dxf_path.stem}_assets").resolve()
    relative = asset.relative_to(asset_parent)
    assert relative.parts
    assert _SESSION_NAME.fullmatch(relative.parts[0])
    return asset_parent / relative.parts[0]


def test_image_def_path_is_relative_and_survives_adjacent_tree_move(tmp_path: Path) -> None:
    source = tmp_path / "portable-image.pdf"
    output_root = tmp_path / "original"
    output_root.mkdir()
    output = output_root / "portable-image.dxf"
    _build_opaque_image_pdf(source)

    run = run_import(
        str(source),
        mode="vector",
        overrides={"pages": "1", "import_text": False},
    )
    try:
        export_to_dxf(
            run.extraction,
            str(output),
            DxfExportOptions(include_text=False, provenance_opts=run.config),
        )
    finally:
        run.close()

    raw_filename = _single_image_filename(output)
    serialized = Path(raw_filename)
    assert not serialized.is_absolute()
    assert not PureWindowsPath(raw_filename).is_absolute()
    assert ".." not in serialized.parts
    assert serialized.parts[0] == f"{output.stem}_assets"
    assert _SESSION_NAME.fullmatch(serialized.parts[1])

    original_asset = (output.parent / serialized).resolve()
    assert original_asset.is_file()
    original_sha256 = hashlib.sha256(original_asset.read_bytes()).hexdigest()

    moved_root = tmp_path / "moved"
    moved_root.mkdir()
    moved_output = moved_root / output.name
    moved_assets = moved_root / f"{output.stem}_assets"
    output.replace(moved_output)
    output.with_name(f"{output.stem}_assets").replace(moved_assets)

    moved_filename = _single_image_filename(moved_output)
    assert moved_filename == raw_filename
    moved_asset = (moved_output.parent / Path(moved_filename)).resolve()
    assert moved_asset.is_file()
    assert hashlib.sha256(moved_asset.read_bytes()).hexdigest() == original_sha256
    decoded = fitz.Pixmap(str(moved_asset))
    assert (int(decoded.width), int(decoded.height)) == (4, 2)


def test_reexport_removes_only_prior_referenced_uuid_session(tmp_path: Path) -> None:
    source = tmp_path / "reexport-image.pdf"
    output = tmp_path / "reexport-image.dxf"
    _build_opaque_image_pdf(source)

    run = run_import(
        str(source),
        mode="vector",
        overrides={"pages": "1", "import_text": False},
    )
    try:
        options = DxfExportOptions(include_text=False, provenance_opts=run.config)
        export_to_dxf(run.extraction, str(output), options)
        prior_session = _referenced_session(output)
        assert prior_session.is_dir()

        asset_parent = output.with_name(f"{output.stem}_assets")
        unrelated_session_name = "f" * 32
        if unrelated_session_name == prior_session.name:
            unrelated_session_name = "e" * 32
        unrelated_session_marker = (
            asset_parent / unrelated_session_name / "keep-unreferenced.txt"
        )
        unrelated_session_marker.parent.mkdir()
        unrelated_session_marker.write_text("unreferenced UUID session", encoding="utf-8")

        non_uuid_marker = asset_parent / "manual-assets" / "keep-manual.txt"
        non_uuid_marker.parent.mkdir()
        non_uuid_marker.write_text("not importer-owned", encoding="utf-8")
        root_marker = asset_parent / "keep-at-root.txt"
        root_marker.write_text("not a session directory", encoding="utf-8")

        export_to_dxf(run.extraction, str(output), options)
        current_session = _referenced_session(output)
    finally:
        run.close()

    assert current_session != prior_session
    assert current_session.is_dir()
    assert not prior_session.exists()
    assert unrelated_session_marker.read_text(encoding="utf-8") == (
        "unreferenced UUID session"
    )
    assert non_uuid_marker.read_text(encoding="utf-8") == "not importer-owned"
    assert root_marker.read_text(encoding="utf-8") == "not a session directory"
