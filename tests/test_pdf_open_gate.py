# -*- coding: utf-8 -*-
"""Open-time PDF gate: malformed inputs must reject cleanly, not traceback."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdfcadcore.fitz_loader import PdfOpenError, safe_open


class TestPdfOpenGate(unittest.TestCase):
    def test_empty_file_rejects_cleanly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_open_gate_") as tmp:
            path = Path(tmp) / "empty.pdf"
            path.write_bytes(b"")
            with self.assertRaises(PdfOpenError) as ctx:
                safe_open(str(path))
            self.assertEqual(ctx.exception.reason, "empty_file")

    def test_non_pdf_rejects_cleanly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_open_gate_") as tmp:
            path = Path(tmp) / "not.pdf"
            path.write_text("not a pdf", encoding="utf-8")
            with self.assertRaises(PdfOpenError) as ctx:
                safe_open(str(path))
            self.assertIn(ctx.exception.reason, {"not_a_pdf", "corrupt", "empty_file"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
