"""BCS-ARCH-001 CLI contract: --mode auto produces an auto_mode block (LC)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:
    import fitz


def _write_sample_pdf(pdf_path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=120)
    page.draw_line((20, 20), (120, 20), color=(0, 0, 0), width=1.0)
    page.insert_text((30, 60), "AISC W12x26", fontsize=10)
    doc.save(str(pdf_path))
    doc.close()


class TestModeCli(unittest.TestCase):
    """Smoke-test the ``--mode auto`` CLI contract for BCS-ARCH-001."""

    def test_cli_exposes_text_and_item_raster_as_distinct_text_modes(self) -> None:
        from librecad_pdf_importer.cli import build_parser

        parser = build_parser()
        text_mode = next(
            action for action in parser._actions if action.dest == "text_mode"
        )
        self.assertIn("text", text_mode.choices)
        self.assertIn("raster", text_mode.choices)

    def test_cli_writes_import_report_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_mode_cli_report_") as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "sample.pdf"
            out_path = tmp_path / "summary.json"
            out_dxf = tmp_path / "out.dxf"

            _write_sample_pdf(pdf_path)

            cmd = [
                sys.executable,
                "-m",
                "librecad_pdf_importer.cli",
                str(pdf_path),
                "--mode",
                "vector",
                "--text-mode",
                "3d_text",
                "--out",
                str(out_dxf),
                "--json",
                str(out_path),
            ]
            result = subprocess.run(
                cmd,
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                msg=f"CLI failed: stdout={result.stdout!r} stderr={result.stderr!r}",
            )

            data = json.loads(out_path.read_text(encoding="utf-8"))
            report_path = Path(data["export"]["import_report_path"])
            self.assertTrue(report_path.is_file())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["host"]["app"], "librecad")
            self.assertIn("phases", report["performance"])
            self.assertIn("text_source_spans", report["extra"])
            delivery = data["export"]["text_delivery"]
            self.assertEqual(delivery["requested"], "3d_text")
            self.assertEqual(delivery["delivered"], "text")
            self.assertTrue(delivery["verified"])
            self.assertTrue(delivery["fallback_used"])
            self.assertEqual(delivery["item_count"], 1)
            self.assertEqual(delivery["entity_count"], 1)
            self.assertEqual(delivery["report_path"], str(report_path))

    def test_auto_mode_produces_auto_mode_block(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_mode_cli_") as tmp:
            pdf_path = Path(tmp) / "sample.pdf"
            out_path = Path(tmp) / "summary.json"
            out_dxf = Path(tmp) / "out.dxf"
            _write_sample_pdf(pdf_path)
            cmd = [
                sys.executable,
                "-m",
                "librecad_pdf_importer.cli",
                str(pdf_path),
                "--mode",
                "auto",
                "--out",
                str(out_dxf),
                "--json",
                str(out_path),
            ]
            result = subprocess.run(
                cmd,
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                msg=f"CLI failed: stdout={result.stdout!r} stderr={result.stderr!r}",
            )
            self.assertTrue(out_path.is_file(), f"Expected output file: {out_path}")

            data = json.loads(out_path.read_text(encoding="utf-8"))
            # LC CLI nests extraction summary under 'import'.
            self.assertIn("import", data, "Summary JSON missing 'import' block")
            import_block = data["import"]
            self.assertIn("auto_mode", import_block, "Summary missing auto_mode block")

            block = import_block["auto_mode"]
            self.assertEqual(block.get("requested"), "auto")
            self.assertIsInstance(block.get("per_page"), list)
            self.assertGreaterEqual(len(block["per_page"]), 1)
            first = block["per_page"][0]
            self.assertIn(first.get("resolved"), {"vector", "raster", "hybrid"})
            self.assertIn("reason", first)
            self.assertIsInstance(block.get("summary"), str)

    def test_cli_preserves_native_text_when_exact_source_font_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_mode_cli_3d_fallback_") as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "sample.pdf"
            out_dxf = tmp_path / "out.dxf"
            accepted_report = tmp_path / "out_import_report.json"
            _write_sample_pdf(pdf_path)
            # Make the exact source font unavailable. LibreCAD still has a
            # parent-native LFF representation, so a 3D request must stop at
            # editable flat Text rather than skipping to Glyphs or Raster.
            pdf = fitz.open(str(pdf_path))
            font_xref = pdf[0].get_fonts(full=True)[0][0]
            font_object = pdf.xref_object(font_xref)
            mutated_font_object = (
                font_object.replace(
                    "/BaseFont/Helvetica", "/BaseFont/DefinitelyMissingFont"
                ).replace(
                    "/BaseFont /Helvetica", "/BaseFont /DefinitelyMissingFont"
                )
            )
            self.assertNotEqual(mutated_font_object, font_object)
            pdf.update_object(font_xref, mutated_font_object)
            pdf.saveIncr()
            pdf.close()
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "librecad_pdf_importer.cli",
                    str(pdf_path),
                    "--mode",
                    "vector",
                    "--text-mode",
                    "3d_text",
                    "--out",
                    str(out_dxf),
                ],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout={result.stdout!r} stderr={result.stderr!r}",
            )
            self.assertTrue(out_dxf.is_file())
            self.assertTrue(accepted_report.is_file())
            summary = json.loads(result.stdout)
            self.assertEqual(summary["export"]["text_delivery"]["requested"], "3d_text")
            self.assertEqual(summary["export"]["text_delivery"]["delivered"], "text")
            self.assertTrue(summary["export"]["text_delivery"]["fallback_used"])
            report = json.loads(accepted_report.read_text(encoding="utf-8"))
            delivery = report["extra"]["text_representation_delivery"]
            self.assertTrue(delivery["verified"])
            self.assertEqual(
                delivery["items"][0]["requested_representation"], "3d_text"
            )
            self.assertEqual(delivery["items"][0]["final_representation"], "text")
            self.assertTrue(delivery["items"][0]["fallback_used"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
