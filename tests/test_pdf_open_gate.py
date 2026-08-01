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

    def test_em_dash_filename_opens_via_stream(self) -> None:
        minimal_pdf = (
            b"%PDF-1.1\n"
            b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
            b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n"
            b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 3 3] >>endobj\n"
            b"xref\n0 4\n0000000000 65535 f \n"
            b"0000000009 00000 n \n0000000068 00000 n \n0000000125 00000 n \n"
            b"trailer<< /Size 4 /Root 1 0 R >>\nstartxref\n196\n%%EOF\n"
        )
        with tempfile.TemporaryDirectory(prefix="lc_open_gate_") as tmp:
            path = Path(tmp) / "Shop\u2014Drawing.pdf"
            path.write_bytes(minimal_pdf)
            doc = safe_open(str(path))
            try:
                self.assertGreaterEqual(int(doc.page_count), 1)
            finally:
                doc.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
