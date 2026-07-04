#!/usr/bin/env python3
"""Tests for bcs.source_provenance/1.0 sidecar emission (LibreCAD host)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from librecad_pdf_importer.exporters.dxf_exporter import DxfExportOptions, export_to_dxf  # noqa: E402
from librecad_pdf_importer.importer import ImportRun, run_import, write_import_report  # noqa: E402
from pdfcadcore.import_config import ImportConfig  # noqa: E402
from pdfcadcore.source_provenance import (  # noqa: E402
    ensure_import_session_id,
    record_text_span_provenance,
)

try:
    import pymupdf as fitz  # noqa: E402
except ImportError:  # pragma: no cover
    import fitz  # type: ignore  # noqa: E402

_CORPUS_ENV = os.environ.get("BCS_CORPUS_ROOT") or os.environ.get("PDF_TEST_CORPUS")
CORPUS_ROOT = Path(_CORPUS_ENV) if _CORPUS_ENV else Path(r"C:\1pdf-test-corpus")


def _write_sample_pdf(pdf_path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=120)
    page.insert_text((30, 60), "Provenance sample", fontsize=10)
    doc.save(str(pdf_path))
    doc.close()


class TestLibreCADSourceProvenance(unittest.TestCase):
    def test_write_import_report_emits_sidecar_when_provenance_recorded(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_source_provenance_") as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "sample.pdf"
            _write_sample_pdf(pdf_path)
            report_path = tmp_path / "import_report.json"
            dxf_path = tmp_path / "sample.dxf"

            run = run_import(
                str(pdf_path),
                mode="vector",
                overrides={"import_text": True, "text_mode": "labels"},
            )
            ensure_import_session_id(run.config)
            for page in run.extraction.pages:
                for text in page.page_data.text_items:
                    record_text_span_provenance(
                        run.config,
                        page=int(page.page_data.page_number),
                        span={
                            "bbox": list(text.bbox) if text.bbox else None,
                            "text": text.text,
                            "origin": list(text.insertion),
                            "size": text.font_size,
                        },
                        text=str(text.text or ""),
                        created_entity_type="dxf_text",
                        text_mode="labels",
                    )

            export_to_dxf(
                run.extraction,
                str(dxf_path),
                DxfExportOptions(
                    include_text=True,
                    text_mode="labels",
                    provenance_opts=run.config,
                ),
            )
            write_import_report(run, str(report_path), elapsed_ms=5.0)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertIn("source_provenance", report["extra"])
            sidecar_path = tmp_path / "source_provenance.json"
            self.assertTrue(sidecar_path.is_file())
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            self.assertEqual("bcs.source_provenance/1.0", sidecar["schema"])
            self.assertGreaterEqual(len(sidecar["objects"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
