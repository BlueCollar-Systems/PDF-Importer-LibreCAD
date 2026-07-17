"""Production-path owner-directive locks for LibreCAD text delivery."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ezdxf
try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore

from librecad_pdf_importer.exporters.dxf_exporter import (
    DxfExportOptions,
    TextRepresentationDeliveryError,
    export_to_dxf,
)
from librecad_pdf_importer.importer import run_import, write_import_report


class TestLibreCADTextModeFidelity(unittest.TestCase):
    """Requested types succeed exactly or fail closed without substitution."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="lc_text_mode_fidelity_")
        self.tmp_path = Path(self._tmp.name)
        self.pdf_path = self.tmp_path / "source.pdf"
        document = fitz.open()
        page = document.new_page(width=120, height=80)
        page.insert_text((12, 24), "M12 BOLT", fontsize=11)
        document.save(str(self.pdf_path))
        document.close()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, text_mode: str):
        run = run_import(
            str(self.pdf_path),
            mode="vector",
            overrides={"pages": "1", "import_text": True, "text_mode": text_mode},
        )
        dxf_path = self.tmp_path / f"{text_mode}.dxf"
        result = export_to_dxf(
            run.extraction,
            str(dxf_path),
            DxfExportOptions(
                include_images=False,
                text_mode=text_mode,
                provenance_opts=run.config,
            ),
        )
        report_path = self.tmp_path / f"{text_mode}_import_report.json"
        write_import_report(run, str(report_path), elapsed_ms=1.0)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        return result, report, ezdxf.readfile(dxf_path)

    def test_every_requested_representation_is_exact_or_loudly_falls_back(self) -> None:
        expected = {
            "text": ("text", "TEXT", "dxf_text", False),
            "labels": ("text", "TEXT", "dxf_text", True),
            "3d_text": ("text", "TEXT", "dxf_text", True),
            "glyphs": ("glyphs", "INSERT", "outline_curve_or_mesh", False),
            "geometry": ("geometry", "LWPOLYLINE", "raw_geometry_edges", False),
        }
        for mode, (delivered, entity_type, bucket, fallback_used) in expected.items():
            with self.subTest(mode=mode):
                result, report, drawing = self._run(mode)
                delivery = result.text_deliveries[0]
                self.assertEqual(delivery["requested_representation"], mode)
                self.assertEqual(delivery["final_representation"], delivered)
                self.assertTrue(delivery["verified"])
                self.assertEqual(delivery["fallback_used"], fallback_used)
                entities = list(drawing.modelspace())
                self.assertIn(entity_type, {entity.dxftype() for entity in entities})
                actual = report["extra"]["actual_text_entity_types"]
                self.assertEqual(actual["entity_type"], delivered)
                self.assertGreaterEqual(actual[bucket], 1)
                if fallback_used:
                    self.assertEqual(report["fallback"]["text"]["requested"], mode)
                    self.assertEqual(
                        report["fallback"]["text"]["delivered"], delivered
                    )
                else:
                    self.assertIsNone(report["fallback"].get("text"))

    def _assert_unproven_outline_failure_stops(self, mode: str, empty: bool) -> None:
        run = run_import(
            str(self.pdf_path),
            mode="vector",
            overrides={"pages": "1", "import_text": True, "text_mode": mode},
        )
        output = self.tmp_path / f"{mode}_{'empty' if empty else 'raises'}.dxf"
        prior = b"prior accepted output\r\n"
        output.write_bytes(prior)
        side_effect = None if empty else RuntimeError("outline helper failed")
        return_value = [] if empty else None
        kwargs = (
            {"return_value": return_value}
            if empty
            else {"side_effect": side_effect}
        )
        with (
            patch("dxf_text_builder.text2path.make_paths_from_entity", **kwargs),
            patch("dxf_text_builder.text2path.make_paths_from_str", **kwargs),
        ):
            with self.assertRaises(TextRepresentationDeliveryError) as raised:
                export_to_dxf(
                    run.extraction,
                    str(output),
                    DxfExportOptions(
                        include_images=False,
                        text_mode=mode,
                        provenance_opts=run.config,
                    ),
                )

        self.assertEqual(output.read_bytes(), prior)
        delivery = raised.exception.delivery
        self.assertFalse(delivery.verified)
        self.assertIsNone(delivery.final_representation)
        self.assertFalse(delivery.terminal_fallback_authorized)
        self.assertEqual(
            [attempt.attempted_representation for attempt in delivery.attempts],
            [mode, mode],
        )
        self.assertTrue(all(attempt.outcome == "failed" for attempt in delivery.attempts))
        self.assertTrue(all(attempt.cleanup_verified for attempt in delivery.attempts))
        self.assertFalse(any(attempt.entity_handles for attempt in delivery.attempts))

    def test_outline_exceptions_do_not_authorize_cross_type_fallback(self) -> None:
        for mode in ("glyphs", "geometry"):
            with self.subTest(mode=mode):
                self._assert_unproven_outline_failure_stops(mode, empty=False)

    def test_empty_outline_artifacts_do_not_authorize_cross_type_fallback(self) -> None:
        for mode in ("glyphs", "geometry"):
            with self.subTest(mode=mode):
                self._assert_unproven_outline_failure_stops(mode, empty=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
