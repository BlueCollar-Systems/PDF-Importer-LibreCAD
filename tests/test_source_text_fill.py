"""Only observed filled source glyphs may omit extra contour ink."""
from dataclasses import replace
import hashlib
from types import SimpleNamespace

import ezdxf
from ezdxf.disassemble import recursive_decompose
import pymupdf as fitz
import pytest

import dxf_text_builder as builder
from librecad_pdf_importer.core.text_paint import fill_only_text_receipts, bound_fill_receipt
from librecad_pdf_importer.exporters.dxf_exporter import export_to_dxf, DxfExportOptions
from librecad_pdf_importer.exporters import dxf_exporter
from librecad_pdf_importer.importer import run_import


def source(tmp_path, deterministic_exact_font, mode):
    path = tmp_path / f"paint-{mode}.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=200, height=100)
        page.insert_text((20, 50), "AH", fontsize=20, fontname="BCFixture",
                         fontfile=str(deterministic_exact_font), render_mode=mode)
        doc.save(path)
    run = run_import(str(path), mode="vector", overrides={"text_mode": "glyphs"})
    return path, run


@pytest.mark.parametrize("mode,fill_only", [(0, True), (1, False), (2, False)])
def test_source_filled_glyph_reopens_as_editable_fill_without_outline_ink(
    tmp_path, deterministic_exact_font, mode, fill_only,
):
    path, run = source(tmp_path, deterministic_exact_font, mode)
    output = tmp_path / "result.dxf"
    result = export_to_dxf(run.extraction, str(output), DxfExportOptions(text_mode="glyphs"))
    doc = ezdxf.readfile(output)
    visible = [e for e in doc.modelspace() if not doc.layers.get(e.dxf.layer).is_frozen()]
    leaves = list(recursive_decompose(visible))
    assert leaves and any(e.dxftype() == "SOLID" for e in leaves)
    contours = [e for e in leaves if e.dxftype() in {"LWPOLYLINE", "POLYLINE"}]
    assert bool(contours) is not fill_only
    assert all(d["verified"] and d["final_representation"] == "glyphs" for d in result.text_deliveries)
    if fill_only:
        assert all(e.dxftype() == "SOLID" for e in leaves)
        evidence = result.text_deliveries[0]["attempts"][-1]["evidence"]
        assert evidence["source_fill_contours_omitted"]
        assert evidence["source_text_fill"]["source_pdf_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("change", ["font", "id", "page", "origin", "glyph", "content"])
def test_paint_receipt_cannot_bind_to_a_different_item(tmp_path, deterministic_exact_font, change):
    path, run = source(tmp_path, deterministic_exact_font, 0)
    item = run.extraction.pages[0].page_data.text_items[0]
    with fitz.open(path) as pdf:
        receipts = fill_only_text_receipts(pdf[0], [item], hashlib.sha256(path.read_bytes()).hexdigest())
    assert bound_fill_receipt(item, receipts)
    if change == "font":
        changed = replace(item, font_name="Different Font")
    elif change == "id":
        changed = replace(item, id=99)
    elif change == "page":
        changed = replace(item, page_number=2)
    elif change == "content":
        changed = replace(item, text="HA")
    else:
        char = item.source_char_layout[0]
        char = replace(char, **({"source_origin_pdf": (21., 50.)} if change == "origin" else {"glyph_id": 999}))
        changed = replace(item, source_char_layout=(char, *item.source_char_layout[1:]))
    assert bound_fill_receipt(changed, receipts) is None


@pytest.mark.parametrize("kind", ["unknown", "mixed", "unavailable"])
def test_unknown_or_overprinted_source_keeps_contours(tmp_path, deterministic_exact_font, kind):
    path, run = source(tmp_path, deterministic_exact_font, 0)
    item = run.extraction.pages[0].page_data.text_items[0]
    with fitz.open(path) as pdf:
        traces = pdf[0].get_texttrace()
    if kind == "unknown":
        traces[0]["type"] = None
    elif kind == "mixed":
        traces.append(dict(traces[0], type=1))
    def get_trace():
        if kind == "unavailable":
            raise RuntimeError("synthetic unavailable trace")
        return traces
    page = SimpleNamespace(number=0, get_texttrace=get_trace)
    assert fill_only_text_receipts(page, [item], "a" * 64) == {}


def test_whole_string_alternative_does_not_restore_extra_contours(tmp_path, deterministic_exact_font, monkeypatch):
    _, run = source(tmp_path, deterministic_exact_font, 0)
    def fail_first(*args, **kwargs):
        return builder.TextDeliveryAttempt(source_id=kwargs["source_id"],
            requested_representation=kwargs["requested"], attempted_representation=kwargs["representation"],
            strategy="synthetic unavailable entity strategy", outcome="impossible", cleanup_verified=True)
    monkeypatch.setattr(builder, "_attempt_outline_entity", fail_first)
    output = tmp_path / "alternative.dxf"
    result = export_to_dxf(run.extraction, str(output), DxfExportOptions(text_mode="glyphs"))
    doc = ezdxf.readfile(output)
    visible = [e for e in doc.modelspace() if not doc.layers.get(e.dxf.layer).is_frozen()]
    leaves = list(recursive_decompose(visible))
    assert leaves and all(e.dxftype() == "SOLID" for e in leaves)
    assert result.text_deliveries[0]["verified"]


def test_fill_and_stroke_never_share_a_glyph_definition(tmp_path, deterministic_exact_font):
    path = tmp_path / "mixed-paint.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=200, height=100)
        for mode, y in [(0, 30), (1, 70)]:
            page.insert_text((20, y), "AH", fontsize=20, fontname="BCFixture",
                             fontfile=str(deterministic_exact_font), render_mode=mode)
        pdf.save(path)
    run = run_import(str(path), mode="vector", overrides={"text_mode": "glyphs"})
    output = tmp_path / "mixed.dxf"
    result = export_to_dxf(run.extraction, str(output), DxfExportOptions(text_mode="glyphs"))
    doc = ezdxf.readfile(output)
    groups = [doc.entitydb[d["entity_handles"][0]] for d in result.text_deliveries]
    assert len(groups) == 2
    first, second = [list(recursive_decompose([g])) for g in groups]
    assert all(e.dxftype() == "SOLID" for e in first)
    assert any(e.dxftype() == "LWPOLYLINE" for e in second)


def test_source_changed_after_paint_proof_cannot_be_published(tmp_path, deterministic_exact_font, monkeypatch):
    path, run = source(tmp_path, deterministic_exact_font, 0)
    original = dxf_exporter._build_text_item
    def build(*args, **kwargs):
        delivery = original(*args, **kwargs)
        path.write_bytes(path.read_bytes() + b"\n% changed source\n")
        return delivery
    monkeypatch.setattr(dxf_exporter, "_build_text_item", build)
    output = tmp_path / "changed.dxf"
    with pytest.raises(RuntimeError, match="Original PDF changed"):
        export_to_dxf(run.extraction, str(output), DxfExportOptions(text_mode="glyphs"))
    assert not output.exists()
