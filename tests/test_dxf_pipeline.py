from __future__ import annotations

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

    def test_default_page_selection_imports_all_pages(self) -> None:
        run = run_import(str(self.pdf_path), mode="vector")
        self.assertEqual(len(run.extraction.pages), 2)

    def test_run_import_defaults_to_librecad_labels(self) -> None:
        run = run_import(str(self.pdf_path), mode="vector", overrides={"pages": "1"})
        self.assertEqual(run.config.text_mode, "labels")

    def test_raster_mode_outputs_image_entity(self) -> None:
        run = run_import(str(self.pdf_path), mode="raster", overrides={"pages": "1"})
        export = export_to_dxf(
            run.extraction,
            str(self.dxf_path),
            DxfExportOptions(include_text=False, include_images=True),
        )

        dxf = ezdxf.readfile(export.output_path)
        types = {entity.dxftype() for entity in dxf.modelspace()}
        self.assertIn("IMAGE", types)

    def test_text_cloud_raster_none_retains_text_and_reports_failure(self) -> None:
        """A failed terminal raster must retain a usable text representation."""
        with (
            patch(
                "librecad_pdf_importer.core.document._looks_like_text_cloud_page",
                return_value=True,
            ),
            patch(
                "librecad_pdf_importer.core.document._render_page_raster",
                return_value=None,
            ),
        ):
            run = run_import(str(self.pdf_path), mode="auto", overrides={"pages": "1"})

        page = run.extraction.pages[0]
        self.assertTrue(page.page_data.text_items)
        self.assertTrue(page.raster_fallback_failed)
        self.assertEqual(page.resolved_mode, "vector")
        self.assertIn("raster render failed", page.resolved_reason)

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
        self.assertIn("raster render failed", report["fallback"]["reason"])
        self.assertNotIn("text", report["fallback"])
        self.assertEqual(report["extra"]["text_mode"], "labels")
        self.assertGreaterEqual(report["extra"]["actual_text_entity_types"]["dxf_text"], 1)

    def test_text_cloud_raster_error_retains_text_and_reports_failure(self) -> None:
        """An unexpected page-raster exception must not erase the text fallback."""
        with (
            patch(
                "librecad_pdf_importer.core.document._looks_like_text_cloud_page",
                return_value=True,
            ),
            patch(
                "librecad_pdf_importer.core.document._render_page_raster",
                side_effect=OSError("simulated raster save failure"),
            ),
        ):
            run = run_import(str(self.pdf_path), mode="auto", overrides={"pages": "1"})

        page = run.extraction.pages[0]
        self.assertTrue(page.page_data.text_items)
        self.assertTrue(page.raster_fallback_failed)
        self.assertEqual(page.resolved_mode, "vector")
        self.assertIn("raster render failed", page.resolved_reason)

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

    def test_labels_text_mode_outputs_editable_text(self) -> None:
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
        self.assertIn("TEXT", text_layer_types)
        self.assertNotIn("LWPOLYLINE", text_layer_types)
        self.assertNotIn("POLYLINE", text_layer_types)

    def test_auto_mode_text_only_page_preserves_editable_text(self) -> None:
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

    def test_3d_text_alias_outputs_editable_text_in_2d_librecad(self) -> None:
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
        self.assertIn("TEXT", text_layer_types)

        # TEXTMODE-1 item 10: delivered behavior is unchanged, but the report
        # must present the 2D alias as a documented host-limit fallback.
        report_path = self.tmp_path / "alias_import_report.json"
        write_import_report(run, str(report_path), elapsed_ms=1.0)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(report["fallback"]["used"])
        text_block = report["fallback"]["text"]
        self.assertEqual(text_block["requested"], "3d_text")
        self.assertEqual(text_block["delivered"], "labels")
        self.assertEqual(text_block["reason"], "host_2d_no_3d_text")
        self.assertEqual(report["extra"]["text_mode"], "3d_text")
        self.assertGreaterEqual(
            report["extra"]["actual_text_entity_types"]["dxf_text"], 1
        )

    def test_editable_text_height_preserves_nominal_font_size(self) -> None:
        doc = ezdxf.new("R2010")
        msp = doc.modelspace()
        item = NormalizedText(
            id=1,
            text="LONG CALLOUT TEXT",
            normalized="LONG CALLOUT TEXT",
            insertion=(0.0, 0.0),
            bbox=(0.0, 0.0, 10.0, 3.0),
            font_size=12.0,
            rotation=0.0,
        )

        count = build_text(item, msp, "TEXT", ImportConfig(text_mode="labels"), target_app="librecad")

        self.assertEqual(count, 1)
        text_entities = [entity for entity in msp if entity.dxftype() == "TEXT"]
        self.assertEqual(len(text_entities), 1)
        self.assertEqual(text_entities[0].dxf.height, item.font_size)

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
        self.assertTrue({"LWPOLYLINE", "POLYLINE"}.intersection(text_layer_types))

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
