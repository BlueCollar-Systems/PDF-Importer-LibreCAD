from __future__ import annotations

import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

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
from librecad_pdf_importer.core.document import ExtractionOptions, extract_document
from librecad_pdf_importer.exporters.dxf_exporter import DxfExportOptions, export_to_dxf
from librecad_pdf_importer.importer import run_import, write_import_report


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
        staged_asset = Path(str(image_def.dxf.filename)).resolve()
        asset_parent = self.dxf_path.with_name(f"{self.dxf_path.stem}_assets").resolve()
        self.assertIn(asset_parent, staged_asset.parents)
        self.assertNotEqual(staged_asset, source_asset.resolve())
        self.assertTrue(staged_asset.is_file())
        self.assertEqual(
            hashlib.sha256(staged_asset.read_bytes()).hexdigest(),
            expected_sha,
        )

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
        self.assertIn("TEXT", {entity.dxftype() for entity in dxf.modelspace()})

        report_path = self.tmp_path / "raster_none_import_report.json"
        write_import_report(run, str(report_path), elapsed_ms=1.0)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(report["fallback"]["used"])
        self.assertEqual(report["fallback"]["text"]["requested"], "labels")
        self.assertEqual(report["fallback"]["text"]["delivered"], "text")
        self.assertEqual(report["extra"]["text_mode"], "labels")
        self.assertGreaterEqual(
            report["extra"]["actual_text_entity_types"]["dxf_text"],
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

    def test_labels_loudly_fall_back_to_native_text_with_parent_lff_font(self) -> None:
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
        self.assertEqual(text_layer_types, {"TEXT"})
        self.assertTrue(all(item["fallback_used"] for item in export.text_deliveries))
        self.assertTrue(
            all(item["final_representation"] == "text" for item in export.text_deliveries)
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
        self.assertIn("TEXT", types)
        self.assertNotIn("IMAGE", types)

    def test_3d_text_uses_loud_native_text_fallback_in_librecad(self) -> None:
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
        self.assertEqual(text_layer_types, {"TEXT"})
        self.assertTrue(all(item["fallback_used"] for item in export.text_deliveries))

        report_path = self.tmp_path / "3d_text_import_report.json"
        write_import_report(run, str(report_path), elapsed_ms=1.0)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(report["fallback"]["used"])
        self.assertEqual(report["fallback"]["text"]["requested"], "3d_text")
        self.assertEqual(report["fallback"]["text"]["delivered"], "text")
        self.assertEqual(report["extra"]["text_mode"], "3d_text")
        actual = report["extra"]["actual_text_entity_types"]
        self.assertEqual(actual["entity_type"], "text")
        self.assertEqual(actual["native_3d_text"], 0)
        self.assertGreaterEqual(actual["dxf_text"], 1)

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
