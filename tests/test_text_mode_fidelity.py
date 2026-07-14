"""Production-path TEXTMODE-1 locks for LibreCAD DXF text delivery."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import ezdxf
try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 preferred name
except ImportError:  # pragma: no cover - legacy package name
    import fitz  # type: ignore

from librecad_pdf_importer.core.document import DocumentExtraction, ExtractedPage
from librecad_pdf_importer.exporters.dxf_exporter import DxfExportOptions, export_to_dxf
from librecad_pdf_importer.importer import ImportRun, write_import_report
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.primitives import NormalizedText, PageData


class TestLibreCADTextModeFidelity(unittest.TestCase):
    """Requested modes either produce their family or a loud fallback record."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="lc_text_mode_fidelity_")
        self.tmp_path = Path(self._tmp.name)
        self.pdf_path = self.tmp_path / "source.pdf"
        document = fitz.open()
        document.new_page(width=120, height=80)
        document.save(str(self.pdf_path))
        document.close()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _export_and_report(self, text_mode: str, outline_result: str = "normal"):
        item = NormalizedText(
            id=1,
            text="M12 BOLT",
            normalized="M12 BOLT",
            insertion=(12.0, 24.0),
            bbox=(12.0, 20.0, 42.0, 26.0),
            font_size=4.0,
            rotation=0.0,
            page_number=1,
        )
        page = ExtractedPage(
            page_data=PageData(page_number=1, width=120.0, height=80.0, text_items=[item]),
            profile=SimpleNamespace(titleblock_likely=False),
            resolved_mode="vector",
        )
        config = ImportConfig.vector()
        config.import_text = True
        config.text_mode = text_mode
        run = ImportRun(
            extraction=DocumentExtraction(str(self.pdf_path), pages=[page], requested_mode="vector"),
            config=config,
        )
        suffix = f"{text_mode}_{outline_result}"
        dxf_path = self.tmp_path / f"{suffix}.dxf"
        report_path = self.tmp_path / f"{suffix}_import_report.json"
        options = DxfExportOptions(
            include_images=False,
            text_mode=text_mode,
            provenance_opts=config,
        )

        if outline_result == "raises":
            with patch(
                "dxf_text_builder.text2path.make_paths_from_entity",
                side_effect=RuntimeError("missing outline font"),
            ):
                export_to_dxf(run.extraction, str(dxf_path), options)
        elif outline_result == "empty":
            with patch("dxf_text_builder.text2path.make_paths_from_entity", return_value=[]):
                export_to_dxf(run.extraction, str(dxf_path), options)
        else:
            export_to_dxf(run.extraction, str(dxf_path), options)

        write_import_report(run, str(report_path), elapsed_ms=1.0)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        return config, report, ezdxf.readfile(dxf_path)

    def _assert_requested_or_reported_fallback(
        self,
        report: dict,
        *,
        requested: str,
        delivered: str,
        reason: str | None = None,
    ) -> None:
        text_fallback = report["fallback"].get("text")
        if requested == delivered:
            self.assertIsNone(text_fallback)
            return
        self.assertTrue(report["fallback"]["used"])
        self.assertIsNotNone(text_fallback)
        self.assertEqual(text_fallback["requested"], requested)
        self.assertEqual(text_fallback["delivered"], delivered)
        self.assertTrue(text_fallback["reason"])
        if reason is not None:
            self.assertEqual(text_fallback["reason"], reason)

    def test_outline_exception_delivers_text_with_honest_provenance_and_report(self) -> None:
        config, report, drawing = self._export_and_report("geometry", "raises")

        self.assertIn("TEXT", {entity.dxftype() for entity in drawing.modelspace()})
        objects = list(getattr(config, "_source_provenance_objects", []))
        self.assertEqual([entry.created_entity_type for entry in objects], ["dxf_text"])
        actual = report["extra"]["actual_text_entity_types"]
        self.assertEqual(actual["dxf_text"], 1)
        self.assertTrue(actual["font_rendered"])
        self._assert_requested_or_reported_fallback(
            report,
            requested="geometry",
            delivered="labels",
            reason="text2path_failed",
        )

    def test_empty_outline_delivers_text_with_reported_fallback(self) -> None:
        _, report, drawing = self._export_and_report("glyphs", "empty")

        self.assertIn("TEXT", {entity.dxftype() for entity in drawing.modelspace()})
        self._assert_requested_or_reported_fallback(
            report,
            requested="glyphs",
            delivered="labels",
            reason="text2path_failed",
        )

    def test_3d_text_alias_is_a_reported_host_limit_fallback(self) -> None:
        _, report, drawing = self._export_and_report("3d_text")

        self.assertIn("TEXT", {entity.dxftype() for entity in drawing.modelspace()})
        self.assertEqual(report["extra"]["actual_text_entity_types"]["dxf_text"], 1)
        self._assert_requested_or_reported_fallback(
            report,
            requested="3d_text",
            delivered="labels",
            reason="host_2d_no_3d_text",
        )

    def test_textmode_invariant_uses_production_report_data(self) -> None:
        scenarios = (
            ("labels", "normal", "labels", None),
            ("geometry", "raises", "labels", "text2path_failed"),
            ("3d_text", "normal", "labels", "host_2d_no_3d_text"),
        )

        for requested, outline_result, delivered, reason in scenarios:
            with self.subTest(requested=requested, outline_result=outline_result):
                _, report, _ = self._export_and_report(requested, outline_result)
                self._assert_requested_or_reported_fallback(
                    report,
                    requested=requested,
                    delivered=delivered,
                    reason=reason,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
