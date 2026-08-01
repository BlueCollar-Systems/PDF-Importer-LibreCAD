from __future__ import annotations

import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from unittest.mock import patch
import ezdxf
try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 preferred name
except ImportError:
    import fitz  # Legacy fallback

from pdfcadcore.primitive_extractor import _merge_stacked_fractions, extract_page
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.primitives import NormalizedText
from dxf_text_builder import build_text
from librecad_pdf_importer.core.document import (
    ExtractionOptions,
    _classify_pixmap_alpha,
    _extract_images,
    extract_document,
)
from librecad_pdf_importer.exporters.dxf_exporter import (
    DxfExportOptions,
    _rectangular_opaque_crop,
    export_to_dxf,
)
from librecad_pdf_importer.importer import run_import, write_import_report


def _dxf_linked_asset(drawing, image_def) -> Path:
    path = Path(str(image_def.dxf.filename))
    if not path.is_absolute():
        path = Path(str(drawing.filename)).resolve().parent / path
    return path.resolve()


class TestDxfPipeline(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="lc_pdf_importer_test_")
        self.tmp_path = Path(self._tmp.name)
        self.pdf_path = self.tmp_path / "sample.pdf"
        self.dxf_path = self.tmp_path / "sample.dxf"
        self._build_sample_pdf(self.pdf_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _build_sample_pdf(self, out_path: Path) -> None:
        doc = fitz.open()
        page = doc.new_page(width=600, height=400)
        page.draw_line((50, 50), (300, 50), color=(0, 0, 0), width=1.0)

        center = (210, 200)
        radius = 40
        pts = []
        for i in range(12):
            angle = 2 * math.pi * i / 12
            pts.append((center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle)))
        pts.append(pts[0])
        page.draw_polyline(pts, color=(0, 0, 1), width=1.0)

        page.insert_text((70, 130), "BOLT 3/4\" DIA", fontsize=12)

        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 12, 12), 0)
        pix.clear_with(0x3366CC)
        page.insert_image(fitz.Rect(360, 60, 420, 120), stream=pix.tobytes("png"))

        # Second page to validate default page-selection behavior.
        page2 = doc.new_page(width=300, height=200)
        page2.draw_line((25, 25), (220, 25), color=(1, 0, 0), width=1.0)

        doc.save(str(out_path))

    def _build_transparent_image_pdf(self, out_path: Path) -> None:
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 4, 4), 1)
        pix.clear_with(0)
        for y in range(4):
            for x in range(4):
                alpha = 255 if x == y else 0
                pix.set_pixel(x, y, (255, 0, 0, alpha))

        doc = fitz.open()
        page = doc.new_page(width=100, height=100)
        page.insert_image(
            fitz.Rect(10, 10, 50, 50),
            stream=pix.tobytes("png"),
        )
        invisible = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 4, 4), 1)
        for y in range(4):
            for x in range(4):
                invisible.set_pixel(x, y, (0, 0, 0, 0))
        page.insert_image(
            fitz.Rect(60, 10, 90, 40),
            stream=invisible.tobytes("png"),
        )
        doc.save(str(out_path))
        doc.close()

    def _build_inline_image_pdf(
        self,
        out_path: Path,
        *,
        image_count: int,
        include_vector_content: bool,
        unique_colors: bool = False,
        affine_transform: bool = False,
    ) -> None:
        doc = fitz.open()
        page = doc.new_page(width=220, height=160)
        if include_vector_content:
            page.draw_line((5, 5), (210, 5), color=(0, 0, 0), width=1.0)
            page.insert_text((6, 154), "EDITABLE VECTOR TEXT", fontsize=8)
        retained_content = page.read_contents()
        inline_content = []
        for index in range(image_count):
            if affine_transform:
                matrix = "20 5 7 15 80 40"
            else:
                column = index % 20
                row = index // 20
                x = 10 + column * 10
                y = 10 + row * 9
                matrix = f"6 0 0 5 {x} {y}"
            if unique_colors:
                color = bytes(
                    (index % 256, (index // 256) % 256, (index * 37) % 256)
                )
            else:
                color = b"\xff\x00\x00" if index % 2 == 0 else b"\x00\x00\xff"
            inline_content.append(
                f"q {matrix} cm BI /W 1 /H 1 /BPC 8 /CS /RGB ID ".encode(
                    "ascii"
                )
                + color
                + b" EI Q\n"
            )
        content_xref = doc.get_new_xref()
        doc.update_object(content_xref, "<<>>")
        doc.update_stream(content_xref, retained_content + b"".join(inline_content))
        page.set_contents(content_xref)
        doc.save(str(out_path))
        doc.close()

    def _build_filled_and_stroked_pdf(self, out_path: Path) -> None:
        doc = fitz.open()
        page = doc.new_page(width=100, height=100)
        page.draw_rect(
            fitz.Rect(20, 20, 80, 80),
            color=(0.0, 0.0, 0.0),
            fill=(0.5, 0.5, 0.5),
            width=2.0,
        )
        doc.save(str(out_path))
        doc.close()

    def test_pdf_to_dxf_export(self) -> None:
        run = run_import(str(self.pdf_path), mode="vector", overrides={"pages": "1"})
        export = export_to_dxf(run.extraction, str(self.dxf_path))

        self.assertTrue(Path(export.output_path).is_file())
        self.assertGreater(export.entity_count, 0)
        self.assertGreaterEqual(export.layer_count, 1)

        dxf = ezdxf.readfile(export.output_path)
        entities = list(dxf.modelspace())
        self.assertGreater(len(entities), 0)

        types = {entity.dxftype() for entity in entities}
        self.assertTrue({"LINE", "LWPOLYLINE", "ARC", "CIRCLE"}.intersection(types))

    def test_filled_stroked_path_keeps_distinct_fill_and_stroke_colors(self) -> None:
        source = self.tmp_path / "filled-and-stroked.pdf"
        output = self.tmp_path / "filled-and-stroked.dxf"
        self._build_filled_and_stroked_pdf(source)
        run = run_import(
            str(source),
            mode="vector",
            overrides={"pages": "1", "import_text": False},
        )

        export_to_dxf(
            run.extraction,
            str(output),
            DxfExportOptions(include_text=False, include_images=False),
        )

        drawing = ezdxf.readfile(output)
        entities = list(drawing.modelspace())
        hatches = [entity for entity in entities if entity.dxftype() == "HATCH"]
        strokes = [
            entity
            for entity in entities
            if entity.dxftype() in {"LWPOLYLINE", "POLYLINE"}
        ]
        self.assertEqual(len(hatches), 1)
        self.assertEqual(len(strokes), 1)
        self.assertEqual(hatches[0].dxf.true_color, 0x808080)
        self.assertEqual(hatches[0].dxf.color, 8)
        self.assertEqual(strokes[0].dxf.true_color, 0x000000)
        self.assertTrue(hatches[0].dxf.solid_fill)
        self.assertTrue(all(path.is_closed for path in hatches[0].paths))

    def test_r12_filled_stroked_path_uses_solid_fill_and_distinct_aci(self) -> None:
        source = self.tmp_path / "filled-and-stroked-r12.pdf"
        output = self.tmp_path / "filled-and-stroked-r12.dxf"
        self._build_filled_and_stroked_pdf(source)
        run = run_import(
            str(source),
            mode="vector",
            overrides={"pages": "1", "import_text": False},
        )

        export_to_dxf(
            run.extraction,
            str(output),
            DxfExportOptions(
                include_text=False,
                include_images=False,
                dxf_version="R12",
            ),
        )

        entities = list(ezdxf.readfile(output).modelspace())
        fills = [entity for entity in entities if entity.dxftype() == "SOLID"]
        strokes = [entity for entity in entities if entity.dxftype() == "POLYLINE"]
        self.assertTrue(fills)
        self.assertEqual(len(strokes), 1)
        self.assertEqual({entity.dxf.color for entity in fills}, {8})
        self.assertEqual(strokes[0].dxf.color, 250)

    def test_full_page_white_fill_uses_parent_paper_instead_of_black_hatch(self) -> None:
        source = self.tmp_path / "white-page-background.pdf"
        output = self.tmp_path / "white-page-background.dxf"
        doc = fitz.open()
        page = doc.new_page(width=100, height=100)
        page.draw_rect(
            page.rect,
            color=None,
            fill=(1.0, 1.0, 1.0),
            width=0.0,
        )
        page.draw_line((10, 50), (90, 50), color=(0.0, 0.0, 0.0), width=1.0)
        doc.save(str(source))
        doc.close()
        run = run_import(
            str(source),
            mode="vector",
            overrides={"pages": "1", "import_text": False},
        )

        export_to_dxf(
            run.extraction,
            str(output),
            DxfExportOptions(include_text=False, include_images=False),
        )

        entities = list(ezdxf.readfile(output).modelspace())
        self.assertFalse(any(entity.dxftype() == "HATCH" for entity in entities))
        self.assertEqual(
            [entity.dxftype() for entity in entities if entity.dxftype() == "LINE"],
            ["LINE"],
        )

    def test_smaller_white_fill_avoids_librecad_print_color_inversion(self) -> None:
        source = self.tmp_path / "white-knockout.pdf"
        output = self.tmp_path / "white-knockout.dxf"
        doc = fitz.open()
        page = doc.new_page(width=100, height=100)
        page.draw_rect(
            fitz.Rect(20, 20, 80, 80),
            color=(0.0, 0.0, 0.0),
            fill=(1.0, 1.0, 1.0),
            width=1.0,
        )
        doc.save(str(source))
        doc.close()
        run = run_import(
            str(source),
            mode="vector",
            overrides={"pages": "1", "import_text": False},
        )

        export_to_dxf(
            run.extraction,
            str(output),
            DxfExportOptions(include_text=False, include_images=False),
        )

        hatch = next(
            entity
            for entity in ezdxf.readfile(output).modelspace()
            if entity.dxftype() == "HATCH"
        )
        self.assertEqual(hatch.dxf.true_color, 0xFEFEFE)
        self.assertNotIn(hatch.dxf.color, {7})

    def test_embedded_image_soft_mask_is_preserved(self) -> None:
        source = self.tmp_path / "transparent.pdf"
        image_dir = self.tmp_path / "extracted_images"
        self._build_transparent_image_pdf(source)

        extraction = extract_document(
            str(source),
            ExtractionOptions(
                pages="1",
                import_mode="vector",
                import_text=False,
                import_images=True,
                image_dir=str(image_dir),
            ),
        )

        self.assertEqual(len(extraction.pages[0].images), 1)
        extracted = fitz.Pixmap(extraction.pages[0].images[0].path)
        self.assertTrue(extracted.alpha)
        alpha_samples = bytes(extracted.samples)[extracted.n - 1 :: extracted.n]
        self.assertEqual(min(alpha_samples), 0)
        self.assertEqual(max(alpha_samples), 255)

    def test_vector_mode_extracts_tractable_inline_images_individually(self) -> None:
        source = self.tmp_path / "inline-tractable.pdf"
        self._build_inline_image_pdf(
            source,
            image_count=3,
            include_vector_content=True,
        )
        with fitz.open(source) as document:
            page = document[0]
            self.assertEqual(page.get_images(full=True), [])
            image_info = page.get_image_info(hashes=True, xrefs=True)
            self.assertEqual(len(image_info), 3)
            self.assertTrue(all(int(info["xref"]) == 0 for info in image_info))

        run = run_import(
            str(source),
            mode="vector",
            overrides={"pages": "1", "raster_dpi": 144},
        )
        page = run.extraction.pages[0]
        self.assertGreater(len(page.page_data.primitives), 0)
        self.assertGreater(len(page.page_data.text_items), 0)
        self.assertEqual(len(page.images), 3)
        self.assertTrue(all(image.xref == 0 for image in page.images))
        self.assertTrue(
            all(image.source_kind == "inline_image" for image in page.images)
        )
        self.assertTrue(all(image.source_instance_count == 1 for image in page.images))

    def test_dense_inline_images_use_exact_transparent_images_only_composite(
        self,
    ) -> None:
        source = self.tmp_path / "inline-dense-mixed.pdf"
        expected_images = self.tmp_path / "inline-dense-images-only.pdf"
        self._build_inline_image_pdf(
            source,
            image_count=300,
            include_vector_content=True,
            unique_colors=True,
        )
        self._build_inline_image_pdf(
            expected_images,
            image_count=300,
            include_vector_content=False,
            unique_colors=True,
        )

        run = run_import(
            str(source),
            mode="vector",
            overrides={"pages": "1", "raster_dpi": 144},
        )
        page = run.extraction.pages[0]
        self.assertGreater(len(page.page_data.primitives), 0)
        self.assertGreater(len(page.page_data.text_items), 0)
        self.assertEqual(len(page.images), 1)
        composite = page.images[0]
        self.assertEqual(composite.xref, 0)
        self.assertEqual(composite.source_kind, "inline_image_composite")
        self.assertEqual(composite.source_instance_count, 300)
        self.assertIn("300 inline image instances", page.resolved_reason)

        actual = fitz.Pixmap(composite.path)
        with fitz.open(expected_images) as expected_document:
            expected = expected_document[0].get_pixmap(
                matrix=fitz.Matrix(2.0, 2.0),
                alpha=True,
            )
        self.assertEqual(actual.tobytes("png"), expected.tobytes("png"))
        self.assertTrue(actual.alpha)

        output = self.tmp_path / "inline-dense-mixed.dxf"
        result = export_to_dxf(
            run.extraction,
            str(output),
            DxfExportOptions(provenance_opts=run.config),
        )
        drawing = ezdxf.readfile(output)
        self.assertEqual(result.image_count, 1)
        self.assertEqual(len(list(drawing.modelspace().query("IMAGE"))), 1)
        self.assertTrue(
            any(
                item.source_kind == "page_raster_alpha_fidelity_fallback"
                for item in run.config._source_provenance_objects
            )
        )
        delivered_image = next(iter(drawing.modelspace().query("IMAGE")))
        delivered_def = drawing.entitydb.get(
            str(delivered_image.dxf.image_def_handle)
        )
        delivered_pixmap = fitz.Pixmap(str(_dxf_linked_asset(drawing, delivered_def)))
        with fitz.open(source) as source_document:
            reference_page = source_document[0].get_pixmap(
                matrix=fitz.Matrix(2.0, 2.0),
                alpha=False,
            )
        self.assertFalse(delivered_pixmap.alpha)
        self.assertEqual(
            delivered_pixmap.tobytes("png"),
            reference_page.tobytes("png"),
        )

        report_path = self.tmp_path / "inline-dense-mixed_import_report.json"
        write_import_report(run, str(report_path), elapsed_ms=1.0)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        delivery = report["extra"]["image_delivery"]["per_page"][0]
        self.assertEqual(delivery["source_instances"], 300)
        self.assertEqual(delivery["placements"], 1)
        self.assertEqual(delivery["source_kinds"], {"inline_image_composite": 300})

    def test_affine_inline_image_uses_exact_images_only_composite(self) -> None:
        source = self.tmp_path / "inline-affine-mixed.pdf"
        expected_images = self.tmp_path / "inline-affine-images-only.pdf"
        self._build_inline_image_pdf(
            source,
            image_count=1,
            include_vector_content=True,
            affine_transform=True,
        )
        self._build_inline_image_pdf(
            expected_images,
            image_count=1,
            include_vector_content=False,
            affine_transform=True,
        )

        run = run_import(
            str(source),
            mode="vector",
            overrides={"pages": "1", "raster_dpi": 144},
        )
        page = run.extraction.pages[0]
        self.assertGreater(len(page.page_data.primitives), 0)
        self.assertGreater(len(page.page_data.text_items), 0)
        self.assertEqual(len(page.images), 1)
        composite = page.images[0]
        self.assertEqual(composite.source_kind, "inline_image_composite")
        self.assertEqual(composite.source_instance_count, 1)

        actual = fitz.Pixmap(composite.path)
        with fitz.open(expected_images) as expected_document:
            expected = expected_document[0].get_pixmap(
                matrix=fitz.Matrix(2.0, 2.0),
                alpha=True,
            )
        self.assertEqual(actual.tobytes("png"), expected.tobytes("png"))

    def test_precomposed_alpha_image_is_not_merged_with_soft_mask_twice(self) -> None:
        image_dir = self.tmp_path / "precomposed-alpha"
        image_dir.mkdir()
        document = object()
        constructor_calls = []

        class FakePixmap:
            def __init__(self, *args):
                constructor_calls.append(args)
                if len(args) != 2 or args != (document, 7):
                    raise RuntimeError(
                        "soft mask was redundantly merged into an alpha pixmap"
                    )
                self.alpha = True
                self.n = 4
                self.width = 2
                self.height = 2
                self.colorspace = SimpleNamespace(n=3)
                self.samples = bytes(
                    (255, 0, 0, 255)
                    + (0, 255, 0, 128)
                    + (0, 0, 255, 255)
                    + (255, 255, 255, 64)
                )

            @staticmethod
            def save(path):
                Path(path).write_bytes(b"precomposed-alpha-png")

        class Page:
            rect = SimpleNamespace(width=100.0, height=100.0, x0=0.0, y0=0.0)

            @staticmethod
            def get_images(*, full=False):
                self.assertTrue(full)
                return [(7, 8)]

            @staticmethod
            def get_image_rects(_image_info, *, transform=False):
                self.assertTrue(transform)
                return [
                    (
                        SimpleNamespace(x0=10.0, y0=20.0, x1=30.0, y1=40.0),
                        (20.0, 0.0, 0.0, 20.0, 10.0, 20.0),
                    )
                ]

        with patch(
            "librecad_pdf_importer.core.document.fitz.Pixmap",
            FakePixmap,
        ):
            placements = _extract_images(
                document,
                Page(),
                page_number=1,
                options=ExtractionOptions(),
                image_dir=image_dir,
            )

        self.assertEqual(constructor_calls, [(document, 7)])
        self.assertEqual(len(placements), 1)
        self.assertTrue(Path(placements[0].path).is_file())

    def test_export_stages_image_assets_beside_the_accepted_dxf(self) -> None:
        run = run_import(str(self.pdf_path), mode="vector", overrides={"pages": "1"})
        source_asset = Path(run.extraction.pages[0].images[0].path)
        expected_sha = hashlib.sha256(source_asset.read_bytes()).hexdigest()

        export_to_dxf(
            run.extraction,
            str(self.dxf_path),
            DxfExportOptions(include_text=False, include_images=True),
        )

        drawing = ezdxf.readfile(str(self.dxf_path))
        image = list(drawing.modelspace().query("IMAGE"))[0]
        self.assertTrue(int(image.dxf.flags) & 8)
        raster_variables = list(drawing.objects.query("RASTERVARIABLES"))
        self.assertEqual(len(raster_variables), 1)
        self.assertEqual(int(raster_variables[0].dxf.frame), 0)
        self.assertEqual(int(raster_variables[0].dxf.units), 1)
        image_def = drawing.entitydb.get(str(image.dxf.image_def_handle))
        staged_asset = _dxf_linked_asset(drawing, image_def)
        asset_parent = self.dxf_path.with_name(f"{self.dxf_path.stem}_assets").resolve()
        self.assertIn(asset_parent, staged_asset.parents)
        self.assertNotEqual(staged_asset, source_asset.resolve())
        self.assertTrue(staged_asset.is_file())
        self.assertEqual(
            hashlib.sha256(staged_asset.read_bytes()).hexdigest(),
            expected_sha,
        )

    def test_export_crops_rectangular_opaque_alpha_for_save_stability(self) -> None:
        source = self.tmp_path / "alpha-crop.pdf"
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 6, 6), 1)
        for y in range(6):
            for x in range(6):
                pix.set_pixel(x, y, (0, 0, 0, 0))
        for y in range(1, 3):
            for x in range(2, 4):
                pix.set_pixel(x, y, (255, 0, 0, 255))
        document = fitz.open()
        page = document.new_page(width=100, height=100)
        page.insert_image(fitz.Rect(10, 20, 70, 80), stream=pix.tobytes("png"))
        document.save(source)
        document.close()

        run = run_import(str(source), mode="vector", overrides={"pages": "1"})
        placement = run.extraction.pages[0].images[0]
        exact_alpha_asset = self.tmp_path / "exact-alpha-source.png"
        exact_alpha_asset.write_bytes(pix.tobytes("png"))
        placement.path = str(exact_alpha_asset)
        export_to_dxf(
            run.extraction,
            str(self.dxf_path),
            DxfExportOptions(include_text=False, include_images=True),
        )

        drawing = ezdxf.readfile(self.dxf_path)
        staged_images = []
        for candidate in drawing.modelspace().query("IMAGE"):
            candidate_def = drawing.entitydb.get(str(candidate.dxf.image_def_handle))
            candidate_size = tuple(round(value) for value in candidate_def.dxf.image_size)
            if candidate_size[:2] == (2, 2):
                staged_images.append((candidate, candidate_def))
        self.assertEqual(len(staged_images), 1)
        image, image_def = staged_images[0]
        staged_pixmap = fitz.Pixmap(str(_dxf_linked_asset(drawing, image_def)))
        self.assertFalse(staged_pixmap.alpha)
        self.assertEqual((staged_pixmap.width, staged_pixmap.height), (2, 2))
        self.assertEqual(staged_pixmap.pixel(0, 0), (255, 0, 0))
        self.assertEqual(staged_pixmap.pixel(1, 1), (255, 0, 0))
        expected_insert = (
            float(placement.x_mm) + float(placement.width_mm) * (2.0 / 6.0),
            float(placement.y_mm) + float(placement.height_mm) * (3.0 / 6.0),
        )
        expected_size = (
            float(placement.width_mm) * (2.0 / 6.0),
            float(placement.height_mm) * (2.0 / 6.0),
        )
        self.assertTrue(
            all(
                math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-9)
                for actual, expected in zip(
                    tuple(image.dxf.insert)[:2], expected_insert, strict=True
                )
            )
        )
        actual_size = (
            math.hypot(image.dxf.u_pixel.x, image.dxf.u_pixel.y)
            * float(image.dxf.image_size.x),
            math.hypot(image.dxf.v_pixel.x, image.dxf.v_pixel.y)
            * float(image.dxf.image_size.y),
        )
        self.assertTrue(
            all(
                math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-9)
                for actual, expected in zip(actual_size, expected_size, strict=True)
            )
        )

    def test_oversized_rectangular_alpha_crop_uses_bounded_page_surface(self) -> None:
        source = self.tmp_path / "oversized-alpha-crop.pdf"
        output = self.tmp_path / "oversized-alpha-crop.dxf"
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), 1)
        for y in range(8):
            for x in range(8):
                pixmap.set_pixel(x, y, (0, 0, 0, 0))
        for y in range(1, 7):
            for x in range(1, 7):
                pixmap.set_pixel(x, y, (0, 128, 255, 255))
        document = fitz.open()
        page = document.new_page(width=100, height=100)
        page.insert_image(fitz.Rect(10, 10, 90, 90), stream=pixmap.tobytes("png"))
        document.save(source)
        document.close()

        run = run_import(
            str(source),
            mode="vector",
            overrides={"pages": "1", "raster_dpi": 72, "import_text": False},
        )
        with patch(
            "librecad_pdf_importer.exporters.dxf_exporter.RECTANGULAR_CROP_MAX_PIXELS",
            1,
        ):
            result = export_to_dxf(
                run.extraction,
                str(output),
                DxfExportOptions(include_text=False, provenance_opts=run.config),
            )

        self.assertEqual(result.image_count, 1)
        drawing = ezdxf.readfile(output)
        image = next(iter(drawing.modelspace().query("IMAGE")))
        image_definition = drawing.entitydb.get(str(image.dxf.image_def_handle))
        delivered = fitz.Pixmap(str(_dxf_linked_asset(drawing, image_definition)))
        with fitz.open(source) as source_document:
            expected = source_document[0].get_pixmap(
                matrix=fitz.Matrix(1, 1),
                colorspace=fitz.csRGB,
                alpha=False,
            )
        self.assertFalse(delivered.alpha)
        self.assertEqual(delivered.tobytes("png"), expected.tobytes("png"))
        self.assertIn("host-safe opaque page", run.extraction.pages[0].resolved_reason)

    def test_alpha_classifier_uses_zero_copy_samples_view_when_available(self) -> None:
        class ZeroCopyPixmap:
            width = 1
            height = 1
            n = 4
            stride = 4
            alpha = True
            samples_mv = memoryview(bytes((1, 2, 3, 255)))

            @property
            def samples(self):
                raise AssertionError("full raster copy was accessed")

        self.assertEqual(
            _classify_pixmap_alpha(ZeroCopyPixmap()),
            ("opaque", (0, 0, 1, 1)),
        )

    def test_rectangular_alpha_crop_normalizes_grayscale_to_rgb(self) -> None:
        source = self.tmp_path / "grayscale-alpha.png"
        pixmap = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 4, 4), 1)
        for y in range(4):
            for x in range(4):
                pixmap.set_pixel(x, y, (0, 0))
        for y in range(1, 3):
            for x in range(1, 3):
                pixmap.set_pixel(x, y, (128, 255))
        pixmap.save(source)

        delivered = fitz.Pixmap(
            _rectangular_opaque_crop(source, (1, 1, 3, 3))
        )
        self.assertFalse(delivered.alpha)
        self.assertEqual(int(delivered.colorspace.n), 3)
        self.assertEqual((delivered.width, delivered.height), (2, 2))
        self.assertEqual(delivered.pixel(0, 0), (128, 128, 128))

    def test_text_only_hybrid_omits_zero_ink_backing_image(self) -> None:
        source = self.tmp_path / "text-only-hybrid.pdf"
        output = self.tmp_path / "text-only-hybrid.dxf"
        document = fitz.open()
        page = document.new_page(width=200, height=100)
        page.insert_text((20, 50), "EDITABLE", fontsize=12)
        document.save(source)
        document.close()

        run = run_import(
            str(source),
            mode="hybrid",
            overrides={"pages": "1", "raster_dpi": 72, "text_mode": "text"},
        )
        result = export_to_dxf(
            run.extraction,
            str(output),
            DxfExportOptions(text_mode="text", provenance_opts=run.config),
        )
        drawing = ezdxf.readfile(output)

        self.assertEqual(result.image_count, 0)
        self.assertEqual(len(list(drawing.modelspace().query("IMAGE"))), 0)
        self.assertGreater(len(run.extraction.pages[0].page_data.text_items), 0)
        self.assertGreater(result.entity_count, 0)
        self.assertTrue(result.text_deliveries)

    def test_partial_alpha_over_vector_uses_exact_opaque_page_fallback(self) -> None:
        source = self.tmp_path / "partial-alpha-over-vector.pdf"
        output = self.tmp_path / "partial-alpha-over-vector.dxf"
        alpha = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 4, 4), 1)
        for y in range(4):
            for x in range(4):
                alpha.set_pixel(x, y, (255, 0, 0, 128))
        document = fitz.open()
        page = document.new_page(width=100, height=100)
        page.draw_rect(page.rect, color=(0, 0, 0), fill=(0, 0, 0))
        page.insert_image(fitz.Rect(25, 25, 75, 75), stream=alpha.tobytes("png"))
        document.save(source)
        document.close()

        run = run_import(
            str(source),
            mode="vector",
            overrides={"pages": "1", "raster_dpi": 72, "import_text": False},
        )
        result = export_to_dxf(
            run.extraction,
            str(output),
            DxfExportOptions(include_text=False, provenance_opts=run.config),
        )
        drawing = ezdxf.readfile(output)
        images = list(drawing.modelspace().query("IMAGE"))
        self.assertEqual(result.image_count, 1)
        self.assertEqual(len(images), 1)
        image_def = drawing.entitydb.get(str(images[0].dxf.image_def_handle))
        delivered = fitz.Pixmap(str(_dxf_linked_asset(drawing, image_def)))
        with fitz.open(source) as reference_document:
            reference = reference_document[0].get_pixmap(
                matrix=fitz.Matrix(1, 1), alpha=False
            )
        self.assertFalse(delivered.alpha)
        self.assertEqual(delivered.tobytes("png"), reference.tobytes("png"))
        self.assertEqual(run.extraction.pages[0].resolved_mode, "hybrid")
        self.assertIn("host-safe opaque page", run.extraction.pages[0].resolved_reason)

    def test_compositing_fallback_tiles_bound_large_page_assets(self) -> None:
        source = self.tmp_path / "partial-alpha-tiled.pdf"
        output = self.tmp_path / "partial-alpha-tiled.dxf"
        alpha = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 2, 2), 1)
        for y in range(2):
            for x in range(2):
                alpha.set_pixel(x, y, (0, 0, 255, 128))
        document = fitz.open()
        page = document.new_page(width=130, height=130)
        page.insert_image(fitz.Rect(10, 10, 120, 120), stream=alpha.tobytes("png"))
        document.save(source)
        document.close()

        run = run_import(
            str(source),
            mode="vector",
            overrides={"pages": "1", "raster_dpi": 72, "import_text": False},
        )
        with patch(
            "librecad_pdf_importer.exporters.dxf_exporter.TERMINAL_TILE_PIXELS",
            64,
        ):
            result = export_to_dxf(
                run.extraction,
                str(output),
                DxfExportOptions(include_text=False, provenance_opts=run.config),
            )
        drawing = ezdxf.readfile(output)
        images = list(drawing.modelspace().query("IMAGE"))
        self.assertEqual(result.image_count, 9)
        self.assertEqual(len(images), 9)
        for image in images:
            image_def = drawing.entitydb.get(str(image.dxf.image_def_handle))
            delivered = fitz.Pixmap(str(_dxf_linked_asset(drawing, image_def)))
            self.assertFalse(delivered.alpha)
            self.assertLessEqual(delivered.width, 64)
            self.assertLessEqual(delivered.height, 64)

    def test_large_inline_composite_uses_lightweight_page_fidelity_marker(self) -> None:
        source = self.tmp_path / "inline-marker.pdf"
        output = self.tmp_path / "inline-marker.dxf"
        self._build_inline_image_pdf(
            source,
            image_count=300,
            include_vector_content=True,
            unique_colors=True,
        )
        with patch(
            "librecad_pdf_importer.core.document.INLINE_IMAGE_COMPOSITE_MAX_PIXELS",
            1,
        ):
            run = run_import(
                str(source),
                mode="vector",
                overrides={"pages": "1", "raster_dpi": 72},
            )
        marker = run.extraction.pages[0].images[0]
        self.assertEqual(marker.source_kind, "inline_image_page_fidelity_required")
        self.assertEqual(marker.path, "")
        self.assertEqual(marker.alpha_kind, "compositing_required")

        result = export_to_dxf(
            run.extraction,
            str(output),
            DxfExportOptions(provenance_opts=run.config),
        )
        self.assertEqual(result.image_count, 1)
        drawing = ezdxf.readfile(output)
        delivered = next(iter(drawing.modelspace().query("IMAGE")))
        image_def = drawing.entitydb.get(str(delivered.dxf.image_def_handle))
        actual = fitz.Pixmap(str(_dxf_linked_asset(drawing, image_def)))
        with fitz.open(source) as document:
            expected = document[0].get_pixmap(
                matrix=fitz.Matrix(1, 1),
                colorspace=fitz.csRGB,
                alpha=False,
            )
        self.assertEqual(actual.tobytes("png"), expected.tobytes("png"))

    def test_tiled_page_surface_matches_monolithic_with_bounded_antialias_delta(
        self,
    ) -> None:
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                source = self.tmp_path / f"tile-transform-{rotation}.pdf"
                output = self.tmp_path / f"tile-transform-{rotation}.dxf"
                alpha = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 3, 3), 1)
                for y in range(3):
                    for x in range(3):
                        alpha.set_pixel(x, y, (255, 0, 0, 128))
                document = fitz.open()
                page = document.new_page(width=180, height=140)
                page.draw_line((7, 11), (170, 129), color=(0, 0, 1), width=1)
                page.insert_image(
                    fitz.Rect(30, 30, 91, 92),
                    stream=alpha.tobytes("png"),
                )
                page.set_cropbox(fitz.Rect(7, 11, 170, 129))
                page.set_rotation(rotation)
                document.xref_set_key(page.xref, "UserUnit", "2")
                document.save(source)
                document.close()

                run = run_import(
                    str(source),
                    mode="vector",
                    overrides={"pages": "1", "raster_dpi": 72, "import_text": False},
                )
                with patch(
                    "librecad_pdf_importer.exporters.dxf_exporter.TERMINAL_TILE_PIXELS",
                    64,
                ):
                    export_to_dxf(
                        run.extraction,
                        str(output),
                        DxfExportOptions(include_text=False, provenance_opts=run.config),
                    )

                drawing = ezdxf.readfile(output)
                with fitz.open(source) as source_document:
                    expected = source_document[0].get_pixmap(
                        matrix=fitz.Matrix(1, 1),
                        colorspace=fitz.csRGB,
                        alpha=False,
                    )
                width = int(expected.width)
                height = int(expected.height)
                reconstructed = bytearray(width * height * 3)
                coverage = bytearray(width * height)
                page_width = float(run.extraction.pages[0].page_data.width)
                page_height = float(run.extraction.pages[0].page_data.height)
                images = list(drawing.modelspace().query("IMAGE"))
                self.assertGreater(len(images), 1)
                for image in images:
                    image_def = drawing.entitydb.get(str(image.dxf.image_def_handle))
                    tile = fitz.Pixmap(str(_dxf_linked_asset(drawing, image_def)))
                    tile_width = int(tile.width)
                    tile_height = int(tile.height)
                    width_units = (
                        math.hypot(image.dxf.u_pixel.x, image.dxf.u_pixel.y)
                        * float(image.dxf.image_size.x)
                    )
                    height_units = (
                        math.hypot(image.dxf.v_pixel.x, image.dxf.v_pixel.y)
                        * float(image.dxf.image_size.y)
                    )
                    left = round(float(image.dxf.insert.x) / page_width * width)
                    bottom = round(float(image.dxf.insert.y) / page_height * height)
                    top = height - bottom - round(height_units / page_height * height)
                    self.assertEqual(
                        round(width_units / page_width * width),
                        tile_width,
                    )
                    samples = memoryview(tile.samples)
                    for row in range(tile_height):
                        source_start = row * tile_width * 3
                        target_start = ((top + row) * width + left) * 3
                        reconstructed[
                            target_start : target_start + tile_width * 3
                        ] = samples[source_start : source_start + tile_width * 3]
                        coverage_start = (top + row) * width + left
                        coverage[
                            coverage_start : coverage_start + tile_width
                        ] = b"\x01" * tile_width
                self.assertTrue(coverage and all(coverage))
                expected_samples = bytes(expected.samples)
                channel_deltas = [
                    abs(actual - reference)
                    for actual, reference in zip(
                        reconstructed,
                        expected_samples,
                        strict=True,
                    )
                ]
                max_channel_delta = max(channel_deltas, default=0)
                changed_ratio = sum(delta != 0 for delta in channel_deltas) / len(
                    channel_deltas
                )
                mean_channel_delta = sum(channel_deltas) / len(channel_deltas)
                # MuPDF rerasterizes anti-aliased edges for each bounded clip.
                # These strict aggregate bounds accept sparse edge rounding
                # while rejecting a visible seam, displaced content, or a
                # wrong transparency composite.
                self.assertLessEqual(max_channel_delta, 32)
                self.assertLessEqual(changed_ratio, 0.02)
                self.assertLessEqual(mean_channel_delta, 0.25)

    def test_page_surface_reduces_dpi_to_stay_inside_resource_budget(self) -> None:
        source = self.tmp_path / "resource-bounded-surface.pdf"
        output = self.tmp_path / "resource-bounded-surface.dxf"
        alpha = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 2, 2), 1)
        for y in range(2):
            for x in range(2):
                alpha.set_pixel(x, y, (255, 0, 0, 128))
        document = fitz.open()
        page = document.new_page(width=200, height=100)
        page.insert_image(fitz.Rect(10, 10, 190, 90), stream=alpha.tobytes("png"))
        document.save(source)
        document.close()

        run = run_import(
            str(source),
            mode="vector",
            overrides={"pages": "1", "raster_dpi": 300, "import_text": False},
        )
        with (
            patch(
                "librecad_pdf_importer.exporters.dxf_exporter.TERMINAL_MAX_PAGE_PIXELS",
                20_000,
            ),
            patch(
                "librecad_pdf_importer.exporters.dxf_exporter.TERMINAL_MAX_PAGE_DIMENSION",
                200,
            ),
            patch(
                "librecad_pdf_importer.exporters.dxf_exporter.TERMINAL_TILE_PIXELS",
                64,
            ),
        ):
            result = export_to_dxf(
                run.extraction,
                str(output),
                DxfExportOptions(include_text=False, provenance_opts=run.config),
            )

        drawing = ezdxf.readfile(output)
        delivered_pixels = 0
        for image in drawing.modelspace().query("IMAGE"):
            image_definition = drawing.entitydb.get(str(image.dxf.image_def_handle))
            tile = fitz.Pixmap(str(_dxf_linked_asset(drawing, image_definition)))
            delivered_pixels += int(tile.width) * int(tile.height)
            self.assertLessEqual(tile.width, 64)
            self.assertLessEqual(tile.height, 64)
            self.assertFalse(tile.alpha)
        self.assertEqual(result.image_count, 8)
        self.assertEqual(delivered_pixels, 20_000)
        self.assertIn("resource-bounded 72.0 DPI", run.extraction.pages[0].resolved_reason)

    def test_page_surface_fails_closed_below_minimum_safe_dpi(self) -> None:
        source = self.tmp_path / "over-budget-surface.pdf"
        output = self.tmp_path / "over-budget-surface.dxf"
        alpha = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 2, 2), 1)
        for y in range(2):
            for x in range(2):
                alpha.set_pixel(x, y, (255, 0, 0, 128))
        document = fitz.open()
        page = document.new_page(width=100, height=100)
        page.insert_image(fitz.Rect(10, 10, 90, 90), stream=alpha.tobytes("png"))
        document.save(source)
        document.close()

        run = run_import(
            str(source),
            mode="vector",
            overrides={"pages": "1", "raster_dpi": 300, "import_text": False},
        )
        with (
            patch(
                "librecad_pdf_importer.exporters.dxf_exporter.TERMINAL_MAX_PAGE_PIXELS",
                100,
            ),
            patch(
                "librecad_pdf_importer.exporters.dxf_exporter.TERMINAL_MAX_PAGE_DIMENSION",
                10,
            ),
            self.assertRaisesRegex(RuntimeError, "exceeds the safe fidelity-surface"),
        ):
            export_to_dxf(
                run.extraction,
                str(output),
                DxfExportOptions(include_text=False, provenance_opts=run.config),
            )
        self.assertFalse(output.exists())
        self.assertFalse(output.with_name(f"{output.stem}_assets").exists())

    def test_import_run_close_reclaims_only_importer_owned_image_workspace(self) -> None:
        run = run_import(str(self.pdf_path), mode="vector", overrides={"pages": "1"})
        source_asset = Path(run.extraction.pages[0].images[0].path)
        owned_workspace = source_asset.parent

        self.assertTrue(source_asset.is_file())
        run.close()
        self.assertFalse(owned_workspace.exists())

        # Closing an already-closed run is safe and cannot broaden deletion scope.
        run.close()

    def test_cleanup_never_removes_a_caller_owned_image_directory(self) -> None:
        caller_owned = self.tmp_path / "caller-owned-images"
        extraction = extract_document(
            str(self.pdf_path),
            ExtractionOptions(
                pages="1",
                import_mode="vector",
                import_text=False,
                import_images=True,
                image_dir=str(caller_owned),
            ),
        )
        extracted_asset = Path(extraction.pages[0].images[0].path)

        extraction.cleanup_temporary_assets()

        self.assertTrue(caller_owned.is_dir())
        self.assertTrue(extracted_asset.is_file())

    def test_failed_extraction_reclaims_the_importer_owned_image_workspace(self) -> None:
        real_temporary_directory = tempfile.TemporaryDirectory
        retained_workspaces = []

        def tracked_workspace(*args, **kwargs):
            kwargs["dir"] = str(self.tmp_path)
            workspace = real_temporary_directory(*args, **kwargs)
            retained_workspaces.append(workspace)
            return workspace

        with (
            patch(
                "librecad_pdf_importer.core.document.tempfile.TemporaryDirectory",
                side_effect=tracked_workspace,
            ),
            patch(
                "librecad_pdf_importer.core.document._extract_images",
                side_effect=RuntimeError("simulated extraction failure"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated extraction failure"):
                extract_document(
                    str(self.pdf_path),
                    ExtractionOptions(
                        pages="1",
                        import_mode="vector",
                        import_text=False,
                        import_images=True,
                    ),
                )

        self.assertTrue(retained_workspaces)
        self.assertTrue(all(not Path(item.name).exists() for item in retained_workspaces))

    def test_failed_candidate_removes_staged_image_assets_and_preserves_prior_dxf(self) -> None:
        run = run_import(str(self.pdf_path), mode="vector", overrides={"pages": "1"})
        prior = b"prior accepted DXF\r\n"
        self.dxf_path.write_bytes(prior)

        with patch(
            "librecad_pdf_importer.exporters.dxf_exporter.ezdxf.readfile",
            side_effect=RuntimeError("simulated candidate reopen failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "candidate reopen"):
                export_to_dxf(
                    run.extraction,
                    str(self.dxf_path),
                    DxfExportOptions(include_text=False, include_images=True),
                )

        self.assertEqual(self.dxf_path.read_bytes(), prior)
        self.assertFalse(
            self.dxf_path.with_name(f"{self.dxf_path.stem}_assets").exists()
        )

    def test_unreadable_image_asset_fails_closed_and_preserves_prior_dxf(self) -> None:
        run = run_import(str(self.pdf_path), mode="vector", overrides={"pages": "1"})
        corrupt = self.tmp_path / "corrupt.png"
        corrupt.write_bytes(b"not an image")
        run.extraction.pages[0].images[0].path = str(corrupt)
        prior = b"prior accepted DXF\r\n"
        self.dxf_path.write_bytes(prior)

        with self.assertRaisesRegex(RuntimeError, "image asset"):
            export_to_dxf(
                run.extraction,
                str(self.dxf_path),
                DxfExportOptions(include_text=False, include_images=True),
            )

        self.assertEqual(self.dxf_path.read_bytes(), prior)

    def test_default_page_selection_imports_all_pages(self) -> None:
        run = run_import(str(self.pdf_path), mode="vector")
        self.assertEqual(len(run.extraction.pages), 2)

    def test_run_import_defaults_to_librecad_text(self) -> None:
        run = run_import(str(self.pdf_path), mode="vector", overrides={"pages": "1"})
        self.assertEqual(run.config.text_mode, "text")

    def test_raster_mode_outputs_image_entity(self) -> None:
        run = run_import(
            str(self.pdf_path),
            mode="raster",
            overrides={"pages": "1", "import_text": False},
        )
        export = export_to_dxf(
            run.extraction,
            str(self.dxf_path),
            DxfExportOptions(include_text=False, include_images=True),
        )

        dxf = ezdxf.readfile(export.output_path)
        types = {entity.dxftype() for entity in dxf.modelspace()}
        self.assertIn("IMAGE", types)
        report_path = self.tmp_path / "explicit_raster_import_report.json"
        write_import_report(run, str(report_path), elapsed_ms=1.0)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(run.extraction.requested_mode, "raster")
        self.assertEqual(run.extraction.pages[0].resolved_mode, "raster")
        self.assertFalse(report["fallback"]["used"])
        self.assertIsNone(report["fallback"]["reason"])

    def test_text_cloud_auto_does_not_preempt_requested_labels(self) -> None:
        """Auto classification must preserve the requested text representation."""
        with (
            patch(
                "librecad_pdf_importer.core.document._looks_like_text_cloud_page",
                return_value=True,
            ),
            patch(
                "librecad_pdf_importer.core.document._render_page_raster",
                return_value=None,
            ) as render_raster,
        ):
            run = run_import(
                str(self.pdf_path),
                mode="auto",
                overrides={"pages": "1", "text_mode": "labels"},
            )

        page = run.extraction.pages[0]
        self.assertTrue(page.page_data.text_items)
        self.assertFalse(page.raster_fallback_failed)
        self.assertEqual(page.resolved_mode, "vector")
        self.assertIn("vector", page.resolved_reason.lower())
        render_raster.assert_not_called()

        export = export_to_dxf(
            run.extraction,
            str(self.dxf_path),
            DxfExportOptions(
                include_images=False,
                text_mode="labels",
                provenance_opts=run.config,
            ),
        )
        dxf = ezdxf.readfile(export.output_path)
        self.assertIn("INSERT", {entity.dxftype() for entity in dxf.modelspace()})

        report_path = self.tmp_path / "raster_none_import_report.json"
        write_import_report(run, str(report_path), elapsed_ms=1.0)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(report["fallback"]["used"])
        self.assertEqual(report["fallback"]["text"]["requested"], "labels")
        self.assertEqual(report["fallback"]["text"]["delivered"], "glyphs")
        self.assertEqual(report["extra"]["text_mode"], "labels")
        self.assertGreaterEqual(
            report["extra"]["actual_text_entity_types"]["outline_curve_or_mesh"],
            1,
        )

    def test_text_cloud_auto_never_calls_raster_for_requested_geometry(self) -> None:
        """A requested non-raster text type blocks auto-raster preemption."""
        with (
            patch(
                "librecad_pdf_importer.core.document._looks_like_text_cloud_page",
                return_value=True,
            ),
            patch(
                "librecad_pdf_importer.core.document._render_page_raster",
                side_effect=OSError("simulated raster save failure"),
            ) as render_raster,
        ):
            run = run_import(
                str(self.pdf_path),
                mode="auto",
                overrides={"pages": "1", "text_mode": "geometry"},
            )

        page = run.extraction.pages[0]
        self.assertTrue(page.page_data.text_items)
        self.assertFalse(page.raster_fallback_failed)
        self.assertEqual(page.resolved_mode, "vector")
        self.assertIn("vector", page.resolved_reason.lower())
        render_raster.assert_not_called()

    def test_blank_forced_raster_none_fails_loudly(self) -> None:
        """A terminal raster without any viable prior content cannot be silent."""
        blank_pdf = self.tmp_path / "blank_raster.pdf"
        doc = fitz.open()
        doc.new_page(width=600, height=400)
        doc.save(str(blank_pdf))
        doc.close()

        with patch(
            "librecad_pdf_importer.core.document._render_page_raster",
            return_value=None,
        ):
            with self.assertRaisesRegex(RuntimeError, "no viable vector/text representation"):
                run_import(str(blank_pdf), mode="raster", overrides={"pages": "1"})

    def test_forced_page_raster_reports_the_exact_resource_limit(self) -> None:
        source = self.tmp_path / "bounded-raster-diagnostic.pdf"
        document = fitz.open()
        page = document.new_page(width=100, height=100)
        page.draw_line((5, 5), (95, 95), color=(0, 0, 0), width=1)
        document.save(source)
        document.close()

        with (
            patch(
                "librecad_pdf_importer.core.document.PAGE_RASTER_MAX_PIXELS",
                100,
            ),
            patch(
                "librecad_pdf_importer.core.document.PAGE_RASTER_MAX_DIMENSION",
                10,
            ),
        ):
            run = run_import(
                str(source),
                mode="raster",
                overrides={"pages": "1", "raster_dpi": 300},
            )
        extracted_page = run.extraction.pages[0]
        self.assertTrue(extracted_page.raster_fallback_failed)
        self.assertIn(
            "safe raster resource budget even at 36 DPI",
            extracted_page.resolved_reason,
        )

    def test_page_raster_document_budget_stops_before_unbounded_growth(self) -> None:
        source = self.tmp_path / "bounded-raster-document.pdf"
        document = fitz.open()
        for _ in range(2):
            page = document.new_page(width=10, height=10)
            page.draw_line((1, 1), (9, 9), color=(0, 0, 0), width=1)
        document.save(source)
        document.close()

        with patch(
            "librecad_pdf_importer.core.document.PAGE_RASTER_MAX_JOB_PIXELS",
            150,
        ):
            run = run_import(
                str(source),
                mode="raster",
                overrides={"pages": "All", "raster_dpi": 72},
            )

        first_page, second_page = run.extraction.pages
        self.assertEqual(len(first_page.images), 1)
        self.assertEqual(first_page.images[0].pixel_size, (10, 10))
        self.assertEqual(second_page.images, [])
        self.assertTrue(second_page.raster_fallback_failed)
        self.assertIn("document raster budget exceeded", second_page.resolved_reason)

    def test_geometry_text_mode_outputs_noneditable_outlines(self) -> None:
        run = run_import(str(self.pdf_path), mode="vector", overrides={"pages": "1"})
        export = export_to_dxf(
            run.extraction,
            str(self.dxf_path),
            DxfExportOptions(include_images=False, text_mode="geometry"),
        )

        self.assertGreater(export.entity_count, 0)
        dxf = ezdxf.readfile(export.output_path)
        text_layer_entities = [
            entity for entity in dxf.modelspace()
            if str(entity.dxf.layer or "") == "P001_TEXT"
        ]
        self.assertGreater(len(text_layer_entities), 0)
        text_layer_types = {entity.dxftype() for entity in text_layer_entities}
        self.assertNotIn("TEXT", text_layer_types)
        self.assertNotIn("MTEXT", text_layer_types)
        self.assertTrue({"LWPOLYLINE", "POLYLINE"}.intersection(text_layer_types))

    def test_labels_fall_back_to_exact_visual_glyphs_when_lff_is_not_equivalent(self) -> None:
        run = run_import(str(self.pdf_path), mode="vector", overrides={"pages": "1"})
        export = export_to_dxf(
            run.extraction,
            str(self.dxf_path),
            DxfExportOptions(include_images=False, text_mode="labels"),
        )

        self.assertGreater(export.entity_count, 0)
        dxf = ezdxf.readfile(export.output_path)
        text_layer_types = {
            entity.dxftype()
            for entity in dxf.modelspace()
            if str(entity.dxf.layer or "") == "P001_TEXT"
        }
        self.assertEqual(text_layer_types, {"INSERT"})
        self.assertTrue(all(item["fallback_used"] for item in export.text_deliveries))
        self.assertTrue(
            all(item["final_representation"] == "glyphs" for item in export.text_deliveries)
        )
        self.assertTrue(
            all(
                item["attempts"][0]["evidence"][
                    "parent_native_label_entity_available"
                ]
                is False
                for item in export.text_deliveries
            )
        )
        self.assertTrue(
            all(
                next(
                    attempt
                    for attempt in item["attempts"]
                    if attempt["attempted_representation"] == "text"
                )["outcome"]
                == "impossible"
                for item in export.text_deliveries
            )
        )

    def test_auto_mode_text_only_page_preserves_visible_text_content(self) -> None:
        text_only_pdf = self.tmp_path / "text_only.pdf"
        doc = fitz.open()
        page = doc.new_page(width=600, height=400)
        page.insert_text((72, 100), "W12x26 COLUMN", fontsize=14)
        page.insert_text((72, 130), "15/16 FIELD BOLT", fontsize=12)
        doc.save(str(text_only_pdf))
        doc.close()

        extraction = extract_document(
            str(text_only_pdf),
            ExtractionOptions(
                pages="1",
                import_mode="auto",
                import_text=True,
                import_images=True,
            ),
        )
        summary = extraction.summary()
        self.assertEqual(summary["pages"], 1)
        self.assertEqual(summary["auto_mode"]["per_page"][0]["resolved"], "vector")
        self.assertGreaterEqual(summary["text_items"], 2)
        self.assertEqual(summary["images"], 0)

        export = export_to_dxf(
            extraction,
            str(self.dxf_path),
            DxfExportOptions(include_images=False, text_mode="labels"),
        )
        self.assertGreater(export.entity_count, 0)
        dxf = ezdxf.readfile(export.output_path)
        types = {entity.dxftype() for entity in dxf.modelspace()}
        self.assertIn("INSERT", types)
        self.assertNotIn("TEXT", types)
        self.assertNotIn("IMAGE", types)

    def test_3d_text_uses_exact_visual_glyph_fallback_in_librecad(self) -> None:
        run = run_import(str(self.pdf_path), mode="vector", overrides={"pages": "1"})
        run.config.import_text = True
        run.config.text_mode = "3d_text"
        export = export_to_dxf(
            run.extraction,
            str(self.dxf_path),
            DxfExportOptions(
                include_images=False,
                text_mode="3d_text",
                provenance_opts=run.config,
            ),
        )

        dxf = ezdxf.readfile(export.output_path)
        text_layer_types = {
            entity.dxftype()
            for entity in dxf.modelspace()
            if str(entity.dxf.layer or "") == "P001_TEXT"
        }
        self.assertEqual(text_layer_types, {"INSERT"})
        self.assertTrue(all(item["fallback_used"] for item in export.text_deliveries))

        report_path = self.tmp_path / "3d_text_import_report.json"
        write_import_report(run, str(report_path), elapsed_ms=1.0)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(report["fallback"]["used"])
        self.assertEqual(report["fallback"]["text"]["requested"], "3d_text")
        self.assertEqual(report["fallback"]["text"]["delivered"], "glyphs")
        self.assertEqual(report["extra"]["text_mode"], "3d_text")
        actual = report["extra"]["actual_text_entity_types"]
        self.assertEqual(actual["entity_type"], "glyphs")
        self.assertEqual(actual["native_3d_text"], 0)
        self.assertEqual(actual["dxf_text"], 0)
        self.assertGreaterEqual(actual["outline_curve_or_mesh"], 1)

    def test_generic_native_text_height_preserves_source_em_via_exact_cap_ratio(self) -> None:
        run = run_import(
            str(self.pdf_path),
            mode="vector",
            overrides={"pages": "1", "text_mode": "text"},
        )
        item = run.extraction.pages[0].page_data.text_items[0]
        asset = item.font_asset
        self.assertIsNotNone(asset)
        font_path = self.tmp_path / f"{asset.usable_sha256}.{asset.usable_format}"
        font_path.write_bytes(asset.usable_bytes)
        config = ImportConfig(text_mode="text")
        config._embedded_font_asset_paths = {asset.asset_id: str(font_path)}
        doc = ezdxf.new("R2010")
        msp = doc.modelspace()

        result = build_text(
            item,
            msp,
            "TEXT",
            config,
            target_app="generic",
            return_delivery_result=True,
        )

        self.assertTrue(result.verified)
        text_entities = [entity for entity in msp if entity.dxftype() == "TEXT"]
        self.assertEqual(len(text_entities), 1)
        evidence = result.attempts[0].evidence
        expected = (
            evidence["source_font_em_height"]
            * evidence["source_cap_height_ratio"]
        )
        self.assertAlmostEqual(float(text_entities[0].dxf.height), expected)
        self.assertAlmostEqual(evidence["actual_height"], expected)

    def test_glyphs_text_mode_outputs_noneditable_outlines(self) -> None:
        run = run_import(str(self.pdf_path), mode="vector", overrides={"pages": "1"})
        export = export_to_dxf(
            run.extraction,
            str(self.dxf_path),
            DxfExportOptions(include_images=False, text_mode="glyphs"),
        )

        self.assertGreater(export.entity_count, 0)
        dxf = ezdxf.readfile(export.output_path)
        text_layer_types = {
            entity.dxftype()
            for entity in dxf.modelspace()
            if str(entity.dxf.layer or "") == "P001_TEXT"
        }
        self.assertNotIn("TEXT", text_layer_types)
        self.assertNotIn("MTEXT", text_layer_types)
        self.assertEqual(text_layer_types, {"INSERT"})
        glyph_refs = [
            entity for entity in dxf.modelspace()
            if str(entity.dxf.layer or "") == "P001_TEXT"
        ]
        self.assertGreater(len(glyph_refs), 0)
        for glyph_ref in glyph_refs:
            block = dxf.blocks.get(glyph_ref.dxf.name)
            self.assertTrue(
                all(
                    entity.dxftype() in {"LWPOLYLINE", "POLYLINE", "SOLID"}
                    for entity in block
                )
            )
            self.assertIn("SOLID", {entity.dxftype() for entity in block})

    def test_dxf_version_override(self) -> None:
        run = run_import(str(self.pdf_path), mode="vector", overrides={"pages": "1"})
        export = export_to_dxf(
            run.extraction,
            str(self.dxf_path),
            DxfExportOptions(dxf_version="R12", include_images=False),
        )
        self.assertTrue(Path(export.output_path).is_file())
        dxf = ezdxf.readfile(export.output_path)
        self.assertEqual(dxf.dxfversion, "AC1009")

    def test_default_spread_stacks_pages_with_20_percent_gap(self) -> None:
        run = run_import(str(self.pdf_path), mode="vector")
        page1 = run.extraction.pages[0].page_data
        page2 = run.extraction.pages[1].page_data
        page1_line = next(p for p in page1.primitives if p.type == "line" and len(p.points) == 2)
        page2_line = next(p for p in page2.primitives if p.type == "line" and len(p.points) == 2)

        export = export_to_dxf(
            run.extraction,
            str(self.dxf_path),
            DxfExportOptions(include_images=False),
        )

        dxf = ezdxf.readfile(export.output_path)
        page1_y = None
        page2_y = None
        for entity in dxf.modelspace():
            if entity.dxftype() != "LINE":
                continue
            layer = str(entity.dxf.layer or "")
            if page1_y is None and layer.startswith("P001"):
                page1_y = float(entity.dxf.start.y)
            elif page2_y is None and layer.startswith("P002"):
                page2_y = float(entity.dxf.start.y)
            if page1_y is not None and page2_y is not None:
                break

        self.assertIsNotNone(page1_y)
        self.assertIsNotNone(page2_y)
        expected_page1_y = float(page1_line.points[0][1])
        expected_page2_y = float(page2_line.points[0][1] - (page1.height * 1.2))
        self.assertAlmostEqual(page1_y, expected_page1_y, delta=0.1)
        self.assertAlmostEqual(page2_y, expected_page2_y, delta=0.1)

    def test_multipage_no_geometry_overlap(self) -> None:
        """Verify geometry from page 1 and page 2 occupy non-overlapping Y bands."""
        run = run_import(str(self.pdf_path), mode="vector")
        export = export_to_dxf(
            run.extraction,
            str(self.dxf_path),
            DxfExportOptions(include_images=False),
        )
        dxf = ezdxf.readfile(export.output_path)

        # Collect Y extents per page layer
        page_y_bands: dict[str, list[float]] = {}
        for entity in dxf.modelspace():
            layer = str(entity.dxf.layer or "")
            # Extract page number from layer name (P001_*, P002_*, etc.)
            page_key = layer[:4] if layer.startswith("P0") else None
            if page_key is None:
                continue
            ys = []
            if entity.dxftype() == "LINE":
                ys = [entity.dxf.start.y, entity.dxf.end.y]
            elif entity.dxftype() == "LWPOLYLINE":
                ys = [pt[1] for pt in entity.get_points()]
            elif entity.dxftype() in ("CIRCLE", "ARC"):
                c = entity.dxf.center
                r = entity.dxf.radius
                ys = [c.y - r, c.y + r]
            if ys:
                page_y_bands.setdefault(page_key, []).extend(ys)

        # Must have at least 2 pages
        self.assertGreaterEqual(len(page_y_bands), 2, "Expected 2+ page layers")

        # Verify no overlap between consecutive pages
        sorted_pages = sorted(page_y_bands.keys())
        for i in range(len(sorted_pages) - 1):
            p1 = sorted_pages[i]
            p2 = sorted_pages[i + 1]
            p1_min = min(page_y_bands[p1])
            p1_max = max(page_y_bands[p1])
            p2_min = min(page_y_bands[p2])
            p2_max = max(page_y_bands[p2])
            # Page 2 should be entirely below page 1 (negative Y direction)
            self.assertLess(
                p2_max, p1_min,
                f"Page overlap detected: {p1} Y=[{p1_min:.1f},{p1_max:.1f}] "
                f"vs {p2} Y=[{p2_min:.1f},{p2_max:.1f}]"
            )

    def test_export_sets_extents_and_modelspace_vport(self) -> None:
        run = run_import(str(self.pdf_path), mode="vector")
        export = export_to_dxf(
            run.extraction,
            str(self.dxf_path),
            DxfExportOptions(include_images=False),
        )

        dxf = ezdxf.readfile(export.output_path)
        msp = dxf.modelspace()
        extmin = tuple(float(v) for v in msp.dxf.extmin)
        extmax = tuple(float(v) for v in msp.dxf.extmax)
        self.assertLess(extmin[0], extmax[0])
        self.assertLess(extmin[1], extmax[1])

        active = dxf.viewports.get("*Active")
        self.assertTrue(active)
        vp = active[0]
        self.assertGreater(float(vp.dxf.height), 0.0)
        center = vp.dxf.center
        self.assertAlmostEqual(float(center[0]), (extmin[0] + extmax[0]) * 0.5, places=1)
        self.assertAlmostEqual(float(center[1]), (extmin[1] + extmax[1]) * 0.5, places=1)

    def test_extract_page_handles_quad_path_items(self) -> None:
        class _QuadPage:
            rect = fitz.Rect(0, 0, 200, 200)

            def get_drawings(self):
                quad = fitz.Quad(
                    fitz.Point(20, 20),
                    fitz.Point(80, 20),
                    fitz.Point(20, 60),
                    fitz.Point(80, 60),
                )
                return [{
                    "items": [("qu", quad)],
                    "color": (0, 0, 0),
                    "fill": None,
                    "width": 1.0,
                }]

            def get_text(self, _kind):
                return {"blocks": []}

        page_data = extract_page(_QuadPage(), page_num=1, scale=1.0, flip_y=True)
        self.assertEqual(len(page_data.primitives), 1)
        self.assertTrue(page_data.primitives[0].closed)
        self.assertGreaterEqual(len(page_data.primitives[0].points), 5)

    def test_stacked_fraction_text_is_merged(self) -> None:
        def text_item(idx: int, text: str, y: float) -> NormalizedText:
            return NormalizedText(
                id=idx,
                text=text,
                normalized=text,
                insertion=(12.0, y),
                bbox=(10.0, y - 0.5, 14.0, y + 0.5),
                font_size=2.0,
                page_number=1,
            )

        merged = _merge_stacked_fractions([
            text_item(1, "15", 12.0),
            text_item(2, "/", 10.0),
            text_item(3, "16", 8.5),
        ])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].text, "15/16")

    def test_stacked_fraction_merge_ignores_full_size_whole_number(self) -> None:
        items = [
            NormalizedText(
                id=1, text="2", normalized="2",
                insertion=(425.62, 276.96), bbox=(425.62, 274.93, 427.86, 278.98),
                font_size=4.05, page_number=1,
            ),
            NormalizedText(
                id=2, text="1", normalized="1",
                insertion=(427.91, 277.88), bbox=(427.91, 276.10, 429.89, 279.65),
                font_size=3.55, page_number=1,
            ),
            NormalizedText(
                id=3, text="4", normalized="4",
                insertion=(430.12, 276.35), bbox=(430.12, 274.58, 432.09, 278.13),
                font_size=3.55, page_number=1,
            ),
            NormalizedText(
                id=4, text="/", normalized="/",
                insertion=(429.44, 277.26), bbox=(429.44, 275.15, 430.61, 279.37),
                font_size=4.23, page_number=1,
            ),
        ]

        merged = _merge_stacked_fractions(items)
        texts = [item.text for item in merged]

        self.assertIn("2", texts)
        self.assertIn("1/4", texts)
        self.assertNotIn("2/4", texts)

    def test_auto_mode_fill_art_prefers_raster(self) -> None:
        fill_pdf = self.tmp_path / "fill_art.pdf"
        doc = fitz.open()
        page = doc.new_page(width=800, height=600)
        for idx in range(430):
            x = (idx % 43) * 18.0
            y = (idx // 43) * 18.0
            rect = fitz.Rect(x, y, x + 14.0, y + 14.0)
            page.draw_rect(rect, color=None, fill=(0.2, 0.6, 0.2), width=0)
        doc.save(str(fill_pdf))
        doc.close()

        extraction = extract_document(
            str(fill_pdf),
            ExtractionOptions(
                pages="1",
                import_mode="auto",
                import_text=True,
                import_images=True,
            ),
        )
        summary = extraction.summary()
        self.assertEqual(summary["pages"], 1)
        self.assertEqual(summary["primitives"], 0)
        self.assertGreaterEqual(summary["images"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
