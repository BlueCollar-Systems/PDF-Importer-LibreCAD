"""Persisted zero-ink controls require original occurrence and program proof."""
from copy import deepcopy

import ezdxf
import pymupdf as fitz
import pytest

from librecad_pdf_importer.importer import run_import
from librecad_pdf_importer.exporters import dxf_exporter as exporter


def make_pdf(path):
    with fitz.open() as pdf:
        page = pdf.new_page(width=160, height=120)
        page.insert_text((30, 30), "A", fontname="cour", fontsize=11)
        page.insert_text((30, 60), "X", fontname="cour", fontsize=11)
        pdf.update_stream(page.get_contents()[-1], b"BT /cour 11 Tf 30 60 Td <0a> Tj ET")
        # Nearby visible paint makes a rectangular page crop invalid proof of
        # this control's own lack of ink.
        page.draw_line((29, 59), (45, 59), width=2)
        pdf.save(path)


@pytest.mark.parametrize("mode", ["text", "glyphs", "geometry", "raster"])
def test_original_control_omission_survives_dxf_reopen_and_rejects_forged_receipt(tmp_path, monkeypatch, mode):
    source, output = tmp_path / "source.pdf", tmp_path / "drawing.dxf"
    make_pdf(source)
    run = run_import(str(source), mode="vector", overrides={"pages": "1", "text_mode": mode})
    saved = {}
    verify = exporter._verify_serialized_text_deliveries
    def capture(doc, deliveries, **kwargs):
        saved.update(doc=doc, deliveries=deepcopy(deliveries), kwargs=kwargs)
        return verify(doc, deliveries, **kwargs)
    monkeypatch.setattr(exporter, "_verify_serialized_text_deliveries", capture)
    result = exporter.export_to_dxf(run.extraction, str(output), exporter.DxfExportOptions(text_mode=mode))
    delivery = next(d for d in result.text_deliveries if d.get("source_text") == "\n")
    assert delivery["verified"] is True
    assert delivery["final_representation"] == "raster"
    assert delivery["entity_handles"] == []
    attempt = delivery["attempts"][-1]
    assert attempt["strategy"] == "verified_source_zero_ink_omission"
    assert attempt["evidence"]["zero_ink_omitted"] is True
    proof = attempt["evidence"]["original_control_zero_ink"]
    assert proof["source_text"] == "\n"
    assert proof["characters"][0]["codepoint"] == 10
    assert proof["characters"][0]["advance_width"] > 0
    reopened = ezdxf.readfile(output)
    verify(reopened, saved["deliveries"], **saved["kwargs"])
    for mutation in ("advance", "program", "remove", "semantic"):
        deliveries = deepcopy(saved["deliveries"])
        target = next(d for d in deliveries if d.get("source_text") == "\n")
        evidence = target["attempts"][-1]["evidence"]
        if mutation == "advance":
            evidence["original_control_zero_ink"]["characters"][0]["advance_width"] += 1
        elif mutation == "program":
            evidence["original_control_zero_ink"]["source_program_sha256"] = "0" * 64
        elif mutation == "remove":
            del evidence["original_control_zero_ink"]
        else:
            target["source_text"] = "changed"
        with pytest.raises(RuntimeError, match="original control zero-ink proof changed"):
            verify(reopened, deliveries, **saved["kwargs"])


def test_control_only_export_rejects_changed_source_pdf(tmp_path, monkeypatch):
    source, output = tmp_path / "source.pdf", tmp_path / "drawing.dxf"
    make_pdf(source)
    run = run_import(str(source), mode="vector", overrides={"pages": "1", "text_mode": "text"})
    page = run.extraction.pages[0].page_data
    page.text_items[:] = [t for t in page.text_items if t.text == "\n"]
    page.primitives[:] = []
    previous = ezdxf.new()
    previous.modelspace().add_line((0, 0), (1, 1))
    previous.saveas(output)
    previous_bytes = output.read_bytes()
    verify = exporter._verify_serialized_text_deliveries
    def mutate(doc, deliveries, **kwargs):
        verify(doc, deliveries, **kwargs)
        source.write_bytes(source.read_bytes() + b"\n% source changed after verification\n")
    monkeypatch.setattr(exporter, "_verify_serialized_text_deliveries", mutate)
    with pytest.raises(RuntimeError, match="Original PDF changed"):
        exporter.export_to_dxf(run.extraction, str(output), exporter.DxfExportOptions(text_mode="text"))
    assert output.read_bytes() == previous_bytes
