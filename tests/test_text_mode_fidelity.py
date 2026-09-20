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
    export_to_dxf,
)
from librecad_pdf_importer.importer import run_import, write_import_report


class TestLibreCADTextModeFidelity(unittest.TestCase):
    """Requested types succeed with disclosed substitutions or degrade one item loudly."""

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
            "text": ("glyphs", "INSERT", "outline_curve_or_mesh", True),
            "labels": ("glyphs", "INSERT", "outline_curve_or_mesh", True),
            "3d_text": ("glyphs", "INSERT", "outline_curve_or_mesh", True),
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

    def _assert_unproven_outline_failure_degrades_item(self, mode: str, empty: bool) -> None:
        """Owner decision 2026-09-19: the classification stays, the abort goes.

        An unproven outline failure still never authorizes a certified
        cross-type fallback -- the builder's attempts stay ``failed`` and the
        item stays ``verified=False`` -- but it costs only that item: the sheet
        exports with the item as a reported, unverified raster patch.
        """
        run = run_import(
            str(self.pdf_path),
            mode="vector",
            overrides={"pages": "1", "import_text": True, "text_mode": mode},
        )
        output = self.tmp_path / f"{mode}_{'empty' if empty else 'raises'}.dxf"
        output.write_bytes(b"prior accepted output\r\n")
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
            result = export_to_dxf(
                run.extraction,
                str(output),
                DxfExportOptions(
                    include_images=False,
                    text_mode=mode,
                    provenance_opts=run.config,
                ),
            )

        drawing = ezdxf.readfile(output)
        self.assertEqual(
            [entity.dxftype() for entity in drawing.modelspace()], ["IMAGE"]
        )
        delivery = result.text_deliveries[0]
        self.assertIs(delivery["verified"], False)
        self.assertIs(delivery["degraded"], True)
        self.assertIs(delivery["dropped"], False)
        self.assertEqual(delivery["final_representation"], "raster")
        self.assertEqual(delivery["proof_class"], "unproven_failure")
        self.assertIs(delivery["terminal_fallback_authorized"], False)
        attempts = delivery["attempts"]
        self.assertEqual(
            [attempt["attempted_representation"] for attempt in attempts],
            [mode, mode, "raster"],
        )
        self.assertEqual(
            [attempt["outcome"] for attempt in attempts],
            ["failed", "failed", "verified"],
        )
        self.assertTrue(all(attempt["cleanup_verified"] for attempt in attempts))
        self.assertFalse(any(attempt["entity_handles"] for attempt in attempts[:-1]))
        self.assertEqual(
            result.text_fallbacks[0]["reason"], "item_degraded_after_unproven_failure"
        )
        report_path = self.tmp_path / f"{mode}_degraded_import_report.json"
        write_import_report(run, str(report_path), elapsed_ms=1.0)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["result"]["warnings"], 1)
        self.assertEqual(
            [item["source_id"] for item in report["extra"]["text_items_degraded"]],
            [delivery["source_id"]],
        )
        self.assertIs(report["extra"]["text_representation_delivery"]["verified"], False)
        self.assertIs(report["extra"]["import_contract_ready"]["ready"], False)

    def test_outline_exceptions_degrade_one_item_without_certifying_it(self) -> None:
        for mode in ("glyphs", "geometry"):
            with self.subTest(mode=mode):
                self._assert_unproven_outline_failure_degrades_item(mode, empty=False)

    def test_empty_outline_artifacts_degrade_one_item_without_certifying_it(self) -> None:
        for mode in ("glyphs", "geometry"):
            with self.subTest(mode=mode):
                self._assert_unproven_outline_failure_degrades_item(mode, empty=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
