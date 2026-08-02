from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import ezdxf
import pytest

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover - compatibility with older PyMuPDF
    import fitz

from pdfcadcore.primitives import PageData, Primitive
from librecad_pdf_importer.core.document import (
    DocumentExtraction,
    ExtractedPage,
    ImagePlacement,
)
from librecad_pdf_importer.exporters import dxf_exporter as exporter
from librecad_pdf_importer.importer import run_import


def _write_rgba_png(path: Path, pixels: list[tuple[int, int, int, int]]) -> None:
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 2, 2), 1)
    for index, pixel in enumerate(pixels):
        pixmap.set_pixel(index % 2, index // 2, pixel)
    pixmap.save(str(path))


def _page(
    page_number: int,
    *,
    images: list[ImagePlacement],
    primitives: list[Primitive] | None = None,
) -> ExtractedPage:
    return ExtractedPage(
        page_data=PageData(
            page_number=page_number,
            width=20.0,
            height=20.0,
            primitives=list(primitives or []),
        ),
        profile=SimpleNamespace(primary_type="mixed", scores={}),
        images=images,
        resolved_mode="hybrid",
    )


def _placement(
    path: Path | str,
    *,
    page_number: int = 1,
    source_kind: str = "page_raster",
    alpha_kind: str = "opaque",
    alpha_present: bool = False,
) -> ImagePlacement:
    return ImagePlacement(
        page_number=page_number,
        x_mm=0.0,
        y_mm=0.0,
        width_mm=20.0,
        height_mm=20.0,
        path=str(path),
        xref=-1,
        source_kind=source_kind,
        pixel_size=(2, 2),
        alpha_kind=alpha_kind,
        alpha_bbox_px=(0, 0, 2, 2),
        alpha_present=alpha_present,
    )


def _image_asset_path(drawing, output: Path) -> Path:
    image = next(iter(drawing.modelspace().query("IMAGE")))
    image_definition = drawing.entitydb.get(str(image.dxf.image_def_handle))
    serialized = Path(str(image_definition.dxf.filename))
    return serialized if serialized.is_absolute() else (output.parent / serialized).resolve()


def test_masked_page_raster_uses_matted_asset_below_editable_entities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    masked = tmp_path / "masked-page-raster.png"
    _write_rgba_png(
        masked,
        [
            (17, 34, 51, 255),
            (90, 80, 70, 128),
            (1, 2, 3, 0),
            (200, 100, 50, 255),
        ],
    )
    placement = _placement(
        masked,
        source_kind="page_raster",
        alpha_kind="compositing_required",
        alpha_present=True,
    )
    placement.masked_text_bboxes_pdf = ((2.0, 3.0, 4.0, 5.0),)
    editable_line = Primitive(
        id=1,
        type="line",
        points=[(1.0, 1.0), (19.0, 19.0)],
        stroke_color=(0.0, 0.0, 0.0),
        page_number=1,
    )
    extraction = DocumentExtraction(
        pdf_path=str(tmp_path / "must-not-be-rerendered.pdf"),
        pages=[_page(1, images=[placement], primitives=[editable_line])],
    )
    output = tmp_path / "masked-page-raster.dxf"

    def reject_full_page_rerender(*_args, **_kwargs):
        raise AssertionError("masked page-raster asset was replaced by a full-page rerender")

    monkeypatch.setattr(exporter, "_render_terminal_page_tiles", reject_full_page_rerender)
    result = exporter.export_to_dxf(
        extraction,
        str(output),
        exporter.DxfExportOptions(
            include_text=False,
            include_images=True,
            attach_metadata=False,
        ),
    )

    assert result.image_count == 1
    drawing = ezdxf.readfile(output)
    delivered = fitz.Pixmap(str(_image_asset_path(drawing, output)))
    assert not delivered.alpha
    assert int(delivered.colorspace.n) == 3
    assert delivered.pixel(0, 0) == (17, 34, 51)
    source = fitz.Pixmap(str(masked))
    source_pixel = source.pixel(1, 0)
    expected_matted = tuple(
        min(int(channel) + 255 - int(source_pixel[3]), 255)
        for channel in source_pixel[:3]
    )
    assert delivered.pixel(1, 0) == expected_matted
    assert delivered.pixel(0, 1) == (255, 255, 255)

    modelspace = drawing.modelspace()
    background_images = list(modelspace.query("IMAGE"))
    editable_entities = [entity for entity in modelspace if entity.dxftype() == "LINE"]
    assert background_images and editable_entities
    modelspace.get_sortents_table(create=False)
    persisted_order = dict(modelspace.get_redraw_order())
    ordered_handles = [
        str(entity.dxf.handle) for entity in modelspace.entities_in_redraw_order()
    ]
    redraw_rank = {handle: index for index, handle in enumerate(ordered_handles)}
    background_handles = {str(entity.dxf.handle) for entity in background_images}
    editable_handles = {str(entity.dxf.handle) for entity in editable_entities}
    assert background_handles | editable_handles <= persisted_order.keys()
    assert all(
        redraw_rank[background] < redraw_rank[editable]
        for background in background_handles
        for editable in editable_handles
    )


def test_terminal_full_page_surface_draws_above_retained_editable_entities(
    tmp_path: Path,
) -> None:
    source = tmp_path / "terminal-page-source.pdf"
    document = fitz.open()
    page = document.new_page(width=100, height=100)
    page.draw_line((10, 10), (90, 90), color=(0.0, 0.0, 0.0), width=2.0)
    document.save(source)
    document.close()

    marker = _placement(
        "",
        source_kind="inline_image_page_fidelity_required",
        alpha_kind="compositing_required",
        alpha_present=True,
    )
    editable_line = Primitive(
        id=1,
        type="line",
        points=[(2.0, 2.0), (18.0, 18.0)],
        stroke_color=(0.0, 0.0, 0.0),
        page_number=1,
    )
    extraction = DocumentExtraction(
        pdf_path=str(source),
        pages=[_page(1, images=[marker], primitives=[editable_line])],
    )
    output = tmp_path / "terminal-page.dxf"

    exporter.export_to_dxf(
        extraction,
        str(output),
        exporter.DxfExportOptions(
            include_text=False,
            include_images=True,
            attach_metadata=False,
            provenance_opts=SimpleNamespace(raster_dpi=72),
        ),
    )

    drawing = ezdxf.readfile(output)
    modelspace = drawing.modelspace()
    images = list(modelspace.query("IMAGE"))
    editables = list(modelspace.query("LINE"))
    assert images and editables
    ordered_handles = [
        str(entity.dxf.handle) for entity in modelspace.entities_in_redraw_order()
    ]
    redraw_rank = {handle: index for index, handle in enumerate(ordered_handles)}
    assert all(
        redraw_rank[str(editable.dxf.handle)] < redraw_rank[str(image.dxf.handle)]
        for editable in editables
        for image in images
    )


def test_hybrid_editable_text_preserves_colored_backing_in_exported_raster(
    tmp_path: Path,
) -> None:
    source = tmp_path / "colored-backing-behind-text.pdf"
    document = fitz.open()
    page = document.new_page(width=120, height=80)
    page.draw_rect(page.rect, color=None, fill=(1.0, 0.0, 0.0), overlay=True)
    page.insert_text(
        (20, 48),
        "MASK",
        fontsize=24,
        color=(0.0, 0.0, 0.0),
        overlay=True,
    )
    document.save(source)
    document.close()

    output = tmp_path / "colored-backing-behind-text.dxf"
    run = run_import(
        str(source),
        mode="hybrid",
        overrides={
            "pages": "1",
            "raster_dpi": 72,
            "import_text": True,
            "text_mode": "text",
        },
    )
    try:
        extracted_page = run.extraction.pages[0]
        assert extracted_page.resolved_mode == "hybrid"
        masked_rasters = [
            placement
            for placement in extracted_page.images
            if placement.source_kind == "page_raster"
            and placement.masked_text_bboxes_pdf
        ]
        assert len(masked_rasters) == 1
        source_bbox = next(
            item.source_bbox_pdf
            for item in extracted_page.page_data.text_items
            if item.text == "MASK"
        )
        assert source_bbox is not None

        exporter.export_to_dxf(
            run.extraction,
            str(output),
            exporter.DxfExportOptions(
                include_text=True,
                text_mode="text",
                include_images=True,
                attach_metadata=False,
                dxf_version="R2010",
                provenance_opts=run.config,
            ),
        )
    finally:
        run.close()

    drawing = ezdxf.readfile(output)
    images = list(drawing.modelspace().query("IMAGE"))
    assert len(images) == 1
    delivered = fitz.Pixmap(str(_image_asset_path(drawing, output)))
    assert not delivered.alpha
    assert (delivered.width, delivered.height) == (120, 80)
    x0, y0, x1, y1 = (float(value) for value in source_bbox)
    sample_x = int((x0 + x1) / 2.0)
    sample_y = int((y0 + y1) / 2.0)
    assert delivered.pixel(sample_x, sample_y) == (255, 0, 0)


def test_all_255_alpha_is_staged_as_opaque_rgb(tmp_path: Path) -> None:
    source = tmp_path / "opaque-with-alpha.png"
    expected_pixels = [
        (10, 20, 30, 255),
        (40, 50, 60, 255),
        (70, 80, 90, 255),
        (100, 110, 120, 255),
    ]
    _write_rgba_png(source, expected_pixels)
    source_pixmap = fitz.Pixmap(str(source))
    assert source_pixmap.alpha

    placement = _placement(source, alpha_kind="opaque", alpha_present=True)
    extraction = DocumentExtraction(
        pdf_path=str(tmp_path / "unused.pdf"),
        pages=[_page(1, images=[placement])],
    )
    transaction = exporter._AssetTransaction()
    try:
        staged, omitted, compositing_pages = exporter._stage_image_assets(
            extraction,
            tmp_path / "owned-assets" / "session",
            transaction,
        )
        assert not omitted
        assert not compositing_pages
        delivered = fitz.Pixmap(str(next(iter(staged.values())).path))
        assert not delivered.alpha
        assert int(delivered.colorspace.n) == 3
        assert [
            delivered.pixel(index % 2, index // 2) for index in range(4)
        ] == [pixel[:3] for pixel in expected_pixels]
    finally:
        transaction.rollback()


def test_cumulative_terminal_resource_cap_rolls_back_output_and_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "resource-cap-source.pdf"
    document = fitz.open()
    document.new_page(width=100, height=100)
    document.new_page(width=100, height=100)
    document.save(source)
    document.close()
    marker_kind = "inline_image_page_fidelity_required"
    pages = [
        _page(
            page_number,
            images=[
                _placement(
                    "",
                    page_number=page_number,
                    source_kind=marker_kind,
                    alpha_kind="compositing_required",
                    alpha_present=True,
                )
            ],
        )
        for page_number in (1, 2)
    ]
    extraction = DocumentExtraction(
        pdf_path=str(source),
        pages=pages,
    )
    output = tmp_path / "resource-capped.dxf"
    prior_output = b"prior accepted DXF\r\n"
    output.write_bytes(prior_output)
    asset_parent = output.with_name(f"{output.stem}_assets")
    rendered_pages: list[int] = []

    def render_terminal_tile(
        _extraction,
        page_number: int,
        _dpi: int,
        asset_root: Path,
        transaction: exporter._AssetTransaction,
    ):
        rendered_pages.append(page_number)
        image_root = asset_root / "images"
        image_root.mkdir(parents=True, exist_ok=True)
        transaction.register_directory(asset_root.parent)
        transaction.register_directory(asset_root)
        transaction.register_directory(image_root)
        asset_path = image_root / f"page-{page_number}.png"
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 2, 2), 0)
        pixmap.clear_with(20 * page_number)
        pixmap.save(str(asset_path))
        transaction.register_file(asset_path)
        content = asset_path.read_bytes()
        placement = _placement(
            asset_path,
            page_number=page_number,
            source_kind="page_raster_alpha_fidelity_fallback",
        )
        staged = exporter._StagedImageAsset(
            source_path=asset_path,
            path=asset_path,
            sha256=hashlib.sha256(content).hexdigest(),
            size_px=(2, 2),
            source_size_px=(2, 2),
            crop_box_px=(0, 0, 2, 2),
            draw_below_editable=True,
        )
        return [placement], {str(asset_path.resolve()): staged}, 72.0

    monkeypatch.setattr(exporter, "_render_terminal_page_tiles", render_terminal_tile)
    monkeypatch.setattr(exporter, "TERMINAL_MAX_JOB_PIXELS", 7)

    with pytest.raises(RuntimeError, match="document fidelity-surface resource budget"):
        exporter.export_to_dxf(
            extraction,
            str(output),
            exporter.DxfExportOptions(
                include_text=False,
                include_images=True,
                attach_metadata=False,
            ),
        )

    assert rendered_pages == []
    assert output.read_bytes() == prior_output
    assert not asset_parent.exists()


def test_cumulative_terminal_pixel_budget_reduces_shared_dpi_before_rendering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "multi-page-fidelity-source.pdf"
    document = fitz.open()
    for page_number in (1, 2):
        page = document.new_page(width=100, height=100)
        page.draw_rect(
            fitz.Rect(10, 10, 90, 90),
            color=(0.0, 0.0, 0.0),
            fill=(page_number / 3.0, 0.25, 0.5),
        )
    document.save(source)
    document.close()

    marker_kind = "inline_image_page_fidelity_required"
    pages = [
        _page(
            page_number,
            images=[
                _placement(
                    "",
                    page_number=page_number,
                    source_kind=marker_kind,
                    alpha_kind="compositing_required",
                    alpha_present=True,
                )
            ],
        )
        for page_number in (1, 2)
    ]
    extraction = DocumentExtraction(pdf_path=str(source), pages=pages)
    output = tmp_path / "multi-page-fidelity.dxf"
    config = SimpleNamespace(raster_dpi=144)
    monkeypatch.setattr(exporter, "TERMINAL_MAX_JOB_PIXELS", 50_000)

    result = exporter.export_to_dxf(
        extraction,
        str(output),
        exporter.DxfExportOptions(
            include_text=False,
            include_images=True,
            attach_metadata=False,
            provenance_opts=config,
        ),
    )

    drawing = ezdxf.readfile(output)
    delivered_pixels = sum(
        round(float(image.dxf.image_size.x)) * round(float(image.dxf.image_size.y))
        for image in drawing.modelspace().query("IMAGE")
    )
    assert result.image_count == 2
    assert delivered_pixels <= 50_000
    assert delivered_pixels > 40_000
    assert all(
        "resource-bounded" in page.resolved_reason for page in extraction.pages
    )


def test_cumulative_terminal_tile_budget_reduces_shared_dpi_before_rendering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "multi-page-tile-source.pdf"
    document = fitz.open()
    document.new_page(width=100, height=100)
    document.new_page(width=100, height=100)
    document.save(source)
    document.close()

    pages = [
        _page(
            page_number,
            images=[
                _placement(
                    "",
                    page_number=page_number,
                    source_kind="inline_image_page_fidelity_required",
                    alpha_kind="compositing_required",
                    alpha_present=True,
                )
            ],
        )
        for page_number in (1, 2)
    ]
    extraction = DocumentExtraction(pdf_path=str(source), pages=pages)
    output = tmp_path / "multi-page-tile-fidelity.dxf"
    monkeypatch.setattr(exporter, "TERMINAL_TILE_PIXELS", 64)
    monkeypatch.setattr(exporter, "TERMINAL_MAX_JOB_TILES", 18)

    result = exporter.export_to_dxf(
        extraction,
        str(output),
        exporter.DxfExportOptions(
            include_text=False,
            include_images=True,
            attach_metadata=False,
            provenance_opts=SimpleNamespace(raster_dpi=144),
        ),
    )

    assert result.image_count <= 18
    assert result.image_count > 8
    assert all(
        "resource-bounded" in page.resolved_reason for page in extraction.pages
    )
