from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from librecad_pdf_importer.core.document import DocumentExtraction, ExtractedPage
from librecad_pdf_importer.importer import (
    ImportRun,
    _canonical_text_delivery_attempts,
    run_import,
    write_import_report,
)
from pdf2dxf import __version__
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.import_report import ImportReport
from pdfcadcore.primitives import NormalizedText, PageData
from pdfcadcore.text_delivery_report import resolve_text_representation_delivery
from pdfcadcore.text_delivery_report import build_text_representation_delivery

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 preferred name
except ImportError:
    import fitz  # Legacy fallback


class TestImportReportWriter(unittest.TestCase):
    def _write_blank_pdf(self, path: Path) -> None:
        doc = fitz.open()
        doc.new_page(width=200, height=120)
        doc.save(str(path))
        doc.close()

    def test_write_import_report_uses_package_version(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_import_report_") as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "sample.pdf"
            report_path = tmp_path / "import_report.json"

            doc = fitz.open()
            page = doc.new_page(width=200, height=120)
            page.draw_line((20, 20), (120, 20), color=(0, 0, 0), width=1.0)
            doc.save(str(pdf_path))

            run = run_import(str(pdf_path), mode="vector", overrides={"pages": "1"})
            result = write_import_report(
                run,
                str(report_path),
                elapsed_ms=15.0,
                performance_phases={
                    "run_import_ms": 11.0,
                    "export_dxf_ms": 4.0,
                },
            )

            self.assertEqual(result, str(report_path))
            data = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(data["schema"], "bcs.import_report/1.1")
            self.assertEqual(data["host"]["app"], "librecad")
            self.assertEqual(data["importer"]["version"], __version__)
            self.assertGreaterEqual(data["result"]["primitives"], 1)
            self.assertEqual(data["performance"]["phases"]["run_import_ms"], 11.0)
            self.assertEqual(data["performance"]["phases"]["export_dxf_ms"], 4.0)
            self.assertEqual(data["performance"]["phases"]["total_ms"], 15.0)
            self.assertIn("text_source_spans", data["extra"])
            self.assertIn("text_glyph_estimate", data["extra"])
            self.assertIn("actual_text_entity_types", data["extra"])
            self.assertIn("dxf_text", data["extra"]["actual_text_entity_types"])

    def test_import_report_rejects_nonfinite_json_numbers(self) -> None:
        report = ImportReport(extra={"proof": float("nan")})

        with self.assertRaisesRegex(ValueError, "non-finite.*extra.proof"):
            report.to_json()

    def test_text_delivery_readiness_requires_one_unique_verified_item_per_span(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_delivery_bijection_") as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "source.pdf"
            self._write_blank_pdf(pdf_path)
            text_items = [
                NormalizedText(1, "A", "A", page_number=1),
                NormalizedText(2, "B", "B", page_number=1),
            ]
            page = ExtractedPage(
                page_data=PageData(
                    page_number=1,
                    width=200,
                    height=120,
                    text_items=text_items,
                ),
                profile=SimpleNamespace(titleblock_likely=False),
                resolved_mode="vector",
            )
            config = ImportConfig.vector()
            config.import_text = True
            config.text_mode = "text"
            config._text_representation_deliveries = [  # noqa: SLF001
                {
                    "source_id": "text_span:1:1",
                    "requested_representation": "text",
                    "final_representation": "text",
                    "verified": True,
                    "entity_handles": ["10"],
                },
                "not an item record",
            ]
            run = ImportRun(
                extraction=DocumentExtraction(
                    str(pdf_path), pages=[page], requested_mode="vector"
                ),
                config=config,
            )
            report_path = tmp_path / "report.json"

            write_import_report(run, str(report_path), elapsed_ms=1.0)

            payload = json.loads(report_path.read_text(encoding="utf-8"))
            delivery = payload["extra"]["text_representation_delivery"]
            self.assertFalse(delivery["verified"])

    def test_disabled_or_none_text_emits_verified_explicit_zero_contract(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_delivery_zero_contract_") as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "source.pdf"
            self._write_blank_pdf(pdf_path)
            source_item = NormalizedText(1, "SOURCE", "SOURCE", page_number=1)
            page = ExtractedPage(
                page_data=PageData(
                    page_number=1,
                    width=200,
                    height=120,
                    text_items=[source_item],
                ),
                profile=SimpleNamespace(titleblock_likely=False),
                resolved_mode="vector",
            )

            for import_text, text_mode in ((False, "glyphs"), (True, "none")):
                with self.subTest(import_text=import_text, text_mode=text_mode):
                    config = ImportConfig.vector()
                    config.import_text = import_text
                    config.text_mode = text_mode
                    config._delivered_text_entity_counts = {  # noqa: SLF001
                        "outline_curve_or_mesh": 99
                    }
                    config._text_representation_deliveries = [  # noqa: SLF001
                        {
                            "source_id": "text_span:1:1",
                            "requested_representation": text_mode,
                            "final_representation": text_mode,
                            "verified": True,
                            "entity_handles": ["STALE"],
                        }
                    ]
                    run = ImportRun(
                        extraction=DocumentExtraction(
                            str(pdf_path), pages=[page], requested_mode="vector"
                        ),
                        config=config,
                    )
                    report_path = tmp_path / f"report-{import_text}-{text_mode}.json"

                    write_import_report(run, str(report_path), elapsed_ms=1.0)

                    payload = json.loads(report_path.read_text(encoding="utf-8"))
                    extra = payload["extra"]
                    self.assertEqual(extra["text_mode"], text_mode)
                    self.assertEqual(
                        extra["text_delivery_obligations"],
                        {
                            "schema": "bcs.text_delivery_obligations/1.0",
                            "required": False,
                            "requested_type": text_mode,
                            "source_item_ids": [],
                        },
                    )
                    self.assertEqual(extra["text_delivery_attempts"], [])
                    expected_delivery = build_text_representation_delivery(
                        [],
                        requested_type=text_mode,
                        required=False,
                        expected_source_item_ids=[],
                    )
                    self.assertTrue(expected_delivery["verified"])
                    self.assertEqual(
                        extra["text_representation_delivery"], expected_delivery
                    )
                    resolution = resolve_text_representation_delivery(
                        extra["text_delivery_attempts"],
                        extra["text_representation_delivery"],
                        expected_source_item_ids=[],
                    )
                    self.assertTrue(resolution["verified"])
                    actual_types = extra["actual_text_entity_types"]
                    self.assertEqual(actual_types["entity_type"], "none")
                    self.assertEqual(actual_types["count"], 0)
                    self.assertFalse(actual_types["font_rendered"])
                    self.assertEqual(actual_types["examples"], [])
                    self.assertTrue(
                        all(
                            value == 0
                            for key, value in actual_types.items()
                            if key
                            not in {
                                "entity_type",
                                "count",
                                "font_rendered",
                                "examples",
                            }
                        )
                    )

    def test_report_serializes_deep_attempt_evidence_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_delivery_single_ledger_") as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "source.pdf"
            self._write_blank_pdf(pdf_path)
            text_item = NormalizedText(1, "A", "A", page_number=1)
            page = ExtractedPage(
                page_data=PageData(
                    page_number=1,
                    width=200,
                    height=120,
                    text_items=[text_item],
                ),
                profile=SimpleNamespace(titleblock_likely=False),
                resolved_mode="vector",
            )
            sentinel = "LIBRECAD-UNIQUE-DEEP-EVIDENCE-SENTINEL"
            config = ImportConfig.vector()
            config.import_text = True
            config.text_mode = "text"
            config._delivered_text_entity_counts = {"dxf_text": 1}  # noqa: SLF001
            config._text_representation_deliveries = [  # noqa: SLF001
                {
                    "source_id": "text_span:1:1",
                    "requested_representation": "text",
                    "final_representation": "text",
                    "verified": True,
                    "entity_handles": ["10"],
                    "support_entity_handles": [],
                    "referenced_entity_handles": [],
                    "attempts": [
                        {
                            "source_id": "text_span:1:1",
                            "requested_representation": "text",
                            "attempted_representation": "text",
                            "strategy": "test-native-label",
                            "outcome": "verified",
                            "type_verified": True,
                            "visual_verified": True,
                            "cleanup_verified": True,
                            "created_entity_handles": ["10"],
                            "removed_entity_handles": [],
                            "entity_handles": ["10"],
                            "support_entity_handles": [],
                            "referenced_entity_handles": [],
                            "evidence": {
                                "deep_payload": sentinel,
                                "serialized_record_verified": True,
                            },
                        }
                    ],
                }
            ]
            run = ImportRun(
                extraction=DocumentExtraction(
                    str(pdf_path), pages=[page], requested_mode="vector"
                ),
                config=config,
            )
            report_path = tmp_path / "report.json"

            write_import_report(run, str(report_path), elapsed_ms=1.0)

            raw = report_path.read_text(encoding="utf-8")
            self.assertEqual(raw.count(sentinel), 1)
            payload = json.loads(raw)
            extra = payload["extra"]
            resolution = resolve_text_representation_delivery(
                extra["text_delivery_attempts"],
                extra["text_representation_delivery"],
                expected_source_item_ids={"text_span:1:1"},
            )
            self.assertTrue(resolution["verified"])

    def test_adapter_does_not_invent_reuse_for_unowned_terminal_entity(self) -> None:
        deliveries = [
            {
                "source_id": "text_span:1:1",
                "requested_representation": "text",
                "final_representation": "text",
                "verified": True,
                "entity_handles": ["10"],
                "support_entity_handles": [],
                "referenced_entity_handles": [],
                "attempts": [
                    {
                        "source_id": "text_span:1:1",
                        "requested_representation": "text",
                        "attempted_representation": "text",
                        "strategy": "native_dxf_text",
                        "outcome": "verified",
                        "type_verified": True,
                        "visual_verified": True,
                        "cleanup_verified": True,
                        "created_entity_handles": [],
                        "removed_entity_handles": [],
                        "entity_handles": ["10"],
                        "support_entity_handles": [],
                        "referenced_entity_handles": [],
                        "evidence": {"serialized_record_verified": True},
                    }
                ],
            }
        ]

        ledger = _canonical_text_delivery_attempts(deliveries)
        delivery = build_text_representation_delivery(
            ledger,
            requested_type="text",
            expected_source_item_ids=["text_span:1:1"],
        )

        self.assertEqual(ledger[0]["reused_entity_ids"], [])
        self.assertFalse(ledger[0]["ownership_verified"])
        self.assertFalse(delivery["verified"])

    def test_adapter_rejects_inner_identity_drift_and_skipped_ladder_rung(self) -> None:
        base_attempt = {
            "source_id": "wrong-source",
            "requested_representation": "labels",
            "attempted_representation": "glyphs",
            "strategy": "outline_block",
            "outcome": "verified",
            "type_verified": True,
            "visual_verified": True,
            "cleanup_verified": True,
            "created_entity_handles": ["10"],
            "removed_entity_handles": [],
            "entity_handles": ["10"],
            "support_entity_handles": [],
            "referenced_entity_handles": [None, "20"],
            "evidence": {"serialized_record_verified": True},
        }
        ledger = _canonical_text_delivery_attempts(
            [
                {
                    "source_id": "text_span:1:1",
                    "requested_representation": "labels",
                    "final_representation": "glyphs",
                    "verified": True,
                    "entity_handles": ["10"],
                    "support_entity_handles": [],
                    "referenced_entity_handles": [None, "20"],
                    "attempts": [base_attempt],
                }
            ]
        )

        self.assertEqual(ledger[0]["referenced_entity_ids"], [None, "20"])
        self.assertFalse(ledger[0]["record_verified"])
        self.assertFalse(ledger[0]["ownership_verified"])
        delivery = build_text_representation_delivery(
            ledger,
            requested_type="labels",
            expected_source_item_ids=["text_span:1:1"],
        )
        self.assertFalse(delivery["verified"])

    def test_write_import_report_emits_parts_bootstrap_sidecar(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_parts_bootstrap_") as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "sample.pdf"
            self._write_blank_pdf(pdf_path)
            report_path = tmp_path / "import_report.json"
            texts = [
                NormalizedText(1, "1017FR1", "1017FR1", insertion=(10, 100), page_number=1),
                NormalizedText(2, "1", "1", insertion=(20, 100), page_number=1),
                NormalizedText(3, "W12X30", "W12X30", insertion=(30, 100), page_number=1),
                NormalizedText(4, "13'-11 1/4\"", "13'-11 1/4\"", insertion=(40, 100), page_number=1),
                NormalizedText(5, "417", "417", insertion=(50, 100), page_number=1),
                NormalizedText(6, "GALV.", "GALV.", insertion=(60, 100), page_number=1),
                NormalizedText(7, "A992", "A992", insertion=(70, 100), page_number=1),
            ]
            page = ExtractedPage(
                page_data=PageData(page_number=1, width=200, height=120, text_items=texts),
                profile=SimpleNamespace(titleblock_likely=False),
                resolved_mode="vector",
            )
            run = ImportRun(
                extraction=DocumentExtraction(str(pdf_path), pages=[page], requested_mode="vector"),
                config=ImportConfig.vector(),
            )

            write_import_report(run, str(report_path), elapsed_ms=15.0)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["extra"]["parts_bootstrap"]["row_count"], 1)
            self.assertEqual(
                report["extra"]["parts_bootstrap"]["sidecar_path"],
                "import_report_parts_bootstrap.json",
            )
            sidecar = json.loads(
                (tmp_path / "import_report_parts_bootstrap.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(sidecar["schema"], "bcs.parts_bootstrap/1.0")
            self.assertEqual(sidecar["part_count"], 1)
            self.assertEqual(sidecar["rows"][0]["piece_mark"], "1017FR1")
            self.assertEqual(sidecar["rows"][0]["profile_hint"], "W12X30")
            self.assertIn("report_sha256", sidecar["import_build_stamp"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
