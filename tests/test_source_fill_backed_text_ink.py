"""Only original-source rectangular paint permits fixed dark text ink."""
from dataclasses import replace
import copy
import hashlib

import ezdxf
from ezdxf.colors import int2rgb
from ezdxf.disassemble import recursive_decompose
import pymupdf
import pytest

from librecad_pdf_importer.core.text_paint import fill_backed_text_receipts, bound_fill_backed_receipt
from librecad_pdf_importer.exporters.dxf_exporter import DxfExportOptions, export_to_dxf
from librecad_pdf_importer.importer import run_import
from librecad_pdf_importer.ink_color import PAINT_RULE_FILL_BACKED_TEXT
from conversion_control import ActivePageCancelled


def _make_pdf(path, font, *, case="panel", pages=1, text_rgb=(0, 0, 0), rotation=0):
    with pymupdf.open() as pdf:
        for _ in range(pages):
            page = pdf.new_page(width=300, height=200)
            def words(target_page=page):
                target_page.insert_text((40, 75), "BLACK ON WHITE PANEL", fontsize=13,
                                 fontname="BCFixture", fontfile=str(font), color=text_rgb)
                target_page.insert_text((40, 145), "BLACK ON PAPER", fontsize=13,
                                 fontname="BCFixture", fontfile=str(font), color=text_rgb)
            if case == "late":
                words()
            if case in ("paper", "rotated-paper"):
                page.draw_rect(page.rect, color=None, fill=(1, 1, 1))
            elif case == "triangle":
                page.draw_polyline([(20, 30), (280, 30), (280, 115)], color=None,
                                   fill=(1, 1, 1), closePath=True)
            else:
                rect = (20, 40, 100, 100) if case == "partial" else (20, 40, 280, 100)
                page.draw_rect(rect, color=(0, 0, 1), fill=(1, 1, 1),
                               width=80 if case == "thick-outline" else 1,
                               fill_opacity=0.5 if case == "transparent" else 1)
                if case == "clipped":
                    stream = page.get_contents()[0]
                    pdf.update_stream(stream, b"q 20 40 25 60 re W n\n" + pdf.xref_stream(stream) + b"\nQ")
            if case == "intermediate-mask":
                page.draw_rect((45, 50, 80, 90), color=None, fill=(0.5, 0.5, 0.5))
            if case == "intermediate-image":
                pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10), False)
                pix.clear_with(120)
                page.insert_image((45, 50, 80, 90), stream=pix.tobytes("png"))
            if case != "late":
                words()
            page.set_rotation(90 if case == "rotated-paper" else rotation)
        pdf.save(path)
    return path


@pytest.mark.parametrize("mode,pages", [("glyphs", 1), ("geometry", 1), ("glyphs", 2)])
@pytest.mark.parametrize("rgb", [(0, 0, 0), (35 / 255, 31 / 255, 32 / 255)])
@pytest.mark.parametrize("rotation", [0, 90])
def test_original_rectangle_backed_dark_ink_stays_separate_from_plain_foreground(
    tmp_path, deterministic_exact_font, mode, pages, rgb, rotation,
):
    source = _make_pdf(tmp_path / "panels.pdf", deterministic_exact_font, pages=pages, text_rgb=rgb, rotation=rotation)
    run = run_import(str(source), mode="vector", overrides={"text_mode": mode})
    items = [item for page in run.extraction.pages for item in page.page_data.text_items]
    original_colors = [item.color for item in items]
    output = tmp_path / "panels.dxf"
    result = export_to_dxf(run.extraction, str(output), DxfExportOptions(text_mode=mode, provenance_opts=run.config))
    doc = ezdxf.readfile(output)
    assert not doc.audit().errors
    expected = (1, 1, 1) if rgb == (0, 0, 0) else (35, 31, 32)
    for index, row in enumerate(result.text_deliveries):
        assert row["verified"] and row["final_representation"] == mode
        entities = [doc.entitydb[handle] for handle in row["entity_handles"]]
        leaves = list(recursive_decompose(entities))
        colors = {tuple(int2rgb(e.dxf.true_color)) for e in leaves}
        assert colors == {expected if index % 2 == 0 else (0, 0, 0)}
    records = [row for row in result.ink_color_deliveries if row["rule"] == PAINT_RULE_FILL_BACKED_TEXT]
    assert len(records) == pages
    assert all(row["source_context"]["source_pdf_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
               and row["source_context"]["source_rectangle_pdf"] == [20, 40, 280, 100]
               and row["source_context"]["source_rectangle_seqno"] < row["source_context"]["source_text_seqno"]
               and row["delivered_rgb"] == list(expected) for row in records)
    assert [item.color for item in items] == original_colors
    assert all(not hasattr(item, "_source_fill_backed_ink_receipt") for item in items)


@pytest.mark.parametrize("case", ["late", "partial", "paper", "rotated-paper", "triangle", "transparent",
                                   "clipped", "intermediate-mask", "intermediate-image", "thick-outline"])
def test_unknown_or_unpainted_context_never_changes_plain_dark_ink(tmp_path, deterministic_exact_font, case):
    source = _make_pdf(tmp_path / (case + ".pdf"), deterministic_exact_font, case=case)
    run = run_import(str(source), mode="vector", overrides={"text_mode": "glyphs"})
    with pymupdf.open(source) as pdf:
        assert fill_backed_text_receipts(pdf[0], run.extraction.pages[0].page_data.text_items,
                                         hashlib.sha256(source.read_bytes()).hexdigest()) == {}


def test_receipt_refuses_changed_source_characters_or_ink(tmp_path, deterministic_exact_font):
    source = _make_pdf(tmp_path / "panel.pdf", deterministic_exact_font)
    run = run_import(str(source), mode="vector", overrides={"text_mode": "glyphs"})
    item = run.extraction.pages[0].page_data.text_items[0]
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    with pymupdf.open(source) as pdf:
        receipts = fill_backed_text_receipts(pdf[0], [item], sha)
        receipt = receipts[f"text_span:1:{item.id}"]
        wrong = copy.copy(item)
        wrong.source_char_layout = (replace(item.source_char_layout[0], source_origin_pdf=(999, 999)),
                                    *item.source_char_layout[1:])
        assert fill_backed_text_receipts(pdf[0], [wrong], sha) == {}
    placed = copy.copy(item)
    placed._source_fill_backed_ink_receipt = receipt
    assert bound_fill_backed_receipt(placed) == receipt
    placed.color = (1, 0, 0)
    assert bound_fill_backed_receipt(placed) is None
    wrong._source_fill_backed_ink_receipt = receipt
    assert bound_fill_backed_receipt(wrong) is None


def test_original_source_proof_never_swallows_cancellation(tmp_path, deterministic_exact_font):
    source = _make_pdf(tmp_path / "panel.pdf", deterministic_exact_font)
    run = run_import(str(source), mode="vector", overrides={"text_mode": "glyphs"})
    def cancel():
        raise ActivePageCancelled("cancel inside source background proof")
    with pymupdf.open(source) as pdf, pytest.raises(ActivePageCancelled, match="inside source background"):
        fill_backed_text_receipts(pdf[0], run.extraction.pages[0].page_data.text_items,
                                 hashlib.sha256(source.read_bytes()).hexdigest(), check_cancel=cancel)


def test_export_proof_cancel_preserves_existing_drawing_and_assets(tmp_path, deterministic_exact_font, monkeypatch):
    from librecad_pdf_importer.core import text_paint
    source = _make_pdf(tmp_path / "panel.pdf", deterministic_exact_font)
    original_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    run = run_import(str(source), mode="vector", overrides={"text_mode": "glyphs"})
    output = tmp_path / "existing.dxf"
    old = ezdxf.new("R2010")
    old.modelspace().add_line((5, 6), (12, 13))
    old.saveas(output)
    assets = tmp_path / "existing_assets"
    assets.mkdir()
    foreign = assets / "keep-existing.txt"
    foreign.write_bytes(b"existing image data")
    before = {p: p.read_bytes() for p in (output, foreign)}
    real = text_paint.fill_backed_text_receipts
    def cancel_proof(*args, **kwargs):
        def cancel():
            raise ActivePageCancelled("source background cancellation")
        kwargs["check_cancel"] = cancel
        return real(*args, **kwargs)
    monkeypatch.setattr(text_paint, "fill_backed_text_receipts", cancel_proof)
    with pytest.raises(ActivePageCancelled, match="source background cancellation"):
        export_to_dxf(run.extraction, str(output), DxfExportOptions(text_mode="glyphs", provenance_opts=run.config))
    assert {p: p.read_bytes() for p in before} == before
    assert list(assets.rglob("*")) == [foreign]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_sha
