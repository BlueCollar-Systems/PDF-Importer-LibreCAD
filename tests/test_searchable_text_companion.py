"""Owner decision 2026-09-19: LibreCAD importer output is SEARCHABLE.

The v1.0.81 guarantee stands: a visibly substituted LibreCAD LFF font is never
certified as delivered Text -- glyph outlines are the visual truth. So every
span whose string is not in the file (outlines, raw geometry, raster patch,
reported drop) gets ONE hidden native TEXT with the exact source string on the
frozen, non-plotting layer ``P###_TEXT_SEARCH``. The companion certifies
nothing: no delivery field, count or TEXTMODE-1 bucket changes, and a companion
that fails costs that companion only (a warning), never the item or the sheet.

Synthetic, deterministic fixtures only (drawing D042 / EX101, D100 / MXT-100,
"SAMPLE", job 1000-01).
"""
from __future__ import annotations

from contextlib import ExitStack
import json
import math
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from unittest.mock import patch

import ezdxf
from ezdxf.lldxf.encoding import decode_dxf_unicode
import pytest

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore

from dxf_text_builder import TextDeliveryAttempt, TextDeliveryResult, _target_advance_width
from librecad_pdf_importer import cli as cli_module
from librecad_pdf_importer.exporters import dxf_exporter as exporter
from librecad_pdf_importer.importer import run_import, write_import_report


_LAYER = "P001_TEXT_SEARCH"
_TARGET = "EX101"
_LINES = ("D042 SAMPLE", _TARGET, "JOB 1000-01")
_NO_COMPANIONS = {
    "enabled": False, "written": 0, "not_representable": 0, "failed": 0,
    "mismatch": 0, "layers": [],
}


def _write_pdf(path: Path, lines=_LINES, *, with_image: bool = False) -> Path:
    pdf = fitz.open()
    page = pdf.new_page(width=300, height=200)
    page.insert_text((30, 40), lines[0], fontsize=11)
    if with_image:
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 3, 2), False)
        pixmap.clear_with(255)
        pixmap.set_pixel(0, 0, (255, 0, 0))
        xref = page.insert_image(fitz.Rect(20, 20, 200, 140), stream=pixmap.tobytes("png"))
    page.insert_text((30, 70), lines[1], fontsize=11)
    if with_image:
        page.insert_image(fitz.Rect(20, 20, 200, 140), xref=xref)
    # The last line is rotated: the companion must follow the item's rotation.
    page.insert_text((250, 180), lines[2], fontsize=9, rotate=90)
    for offset, extra in enumerate(lines[3:]):
        page.insert_text((30, 130 + 20 * offset), extra, fontsize=11)
    page.draw_line((20, 120), (280, 120))
    pdf.save(str(path))
    pdf.close()
    return path


def _export(directory: Path, pdf_path: Path, *, text_mode="glyphs", include_images=False,
            dxf_version="R2018", searchable_text=True, faults=()):
    """One export to ``<directory>/sheet.dxf`` plus its import report."""

    directory.mkdir(parents=True, exist_ok=True)
    run = run_import(
        str(pdf_path), mode="vector", overrides={"pages": "1", "text_mode": text_mode}
    )
    items = {item.text: item for item in run.extraction.pages[0].page_data.text_items}
    output = directory / "sheet.dxf"
    with ExitStack() as stack:
        for fault in faults:
            stack.enter_context(fault)
        result = exporter.export_to_dxf(
            run.extraction,
            str(output),
            exporter.DxfExportOptions(
                include_images=include_images,
                text_mode=text_mode,
                dxf_version=dxf_version,
                provenance_opts=run.config,
                searchable_text=searchable_text,
            ),
        )
    report_path = directory / "sheet_import_report.json"
    write_import_report(run, str(report_path), elapsed_ms=1.0)
    run.close()
    return SimpleNamespace(
        result=result,
        report=json.loads(report_path.read_text(encoding="utf-8")),
        drawing=ezdxf.readfile(output),
        items=items,
        output=output,
        by_text={
            delivery["search_text"]["content"]: delivery
            for delivery in result.text_deliveries
            if "search_text" in delivery
        },
    )


def _companions(drawing) -> list:
    return [entity for entity in drawing.modelspace() if entity.dxf.layer.endswith("TEXT_SEARCH")]


def _visible(drawing) -> list:
    """(type, handle, layer) of everything that is NOT a hidden companion."""
    return [
        (entity.dxftype(), entity.dxf.handle, entity.dxf.layer)
        for entity in drawing.modelspace()
        if not entity.dxf.layer.endswith("TEXT_SEARCH")
    ]


def _stable(value, directory: Path):
    """Drop what legitimately differs between two exports: the companions' own
    keys, the output folder, the per-export asset session and the clock."""

    if isinstance(value, dict):
        return {
            key: _stable(child, directory)
            for key, child in value.items()
            if key not in {"search_text", "searchable_text_companions", "performance",
                           "report_meta", "import_session_id"}
        }
    if isinstance(value, list):
        return [_stable(child, directory) for child in value]
    if isinstance(value, str):
        return re.sub(r"\b[0-9a-f]{32}\b", "<session>", value.replace(str(directory), "<out>"))
    return value


def _fail_one_item(target: str = _TARGET):
    """The builder fails WITHOUT impossibility proof for exactly one item."""

    real_build_text = exporter.build_text

    def build_text(text_item, *args, **kwargs):
        if text_item.text != target:
            return real_build_text(text_item, *args, **kwargs)
        source_id = f"text_span:{text_item.page_number}:{text_item.id}"
        requested = str(args[2].text_mode)
        return TextDeliveryResult(
            source_id=source_id,
            requested_representation=requested,
            final_representation=None,
            verified=False,
            attempts=[
                TextDeliveryAttempt(
                    source_id=source_id,
                    requested_representation=requested,
                    attempted_representation=requested,
                    strategy="entity_text2path",
                    outcome="failed",
                    reason="ValueError: injected unproven failure",
                    cleanup_verified=True,
                )
            ],
            failure_reason="ValueError: injected unproven failure",
        )

    return patch.object(exporter, "build_text", side_effect=build_text)


def _no_item_raster():
    return patch.object(
        fitz.DisplayList, "get_pixmap", side_effect=RuntimeError("terminal renderer unavailable")
    )


def _no_degraded_text():
    def refuse(delivery, *_args, **_kwargs):
        return TextDeliveryResult(
            source_id=delivery.source_id,
            requested_representation=delivery.requested_representation,
            final_representation=None,
            verified=False,
            attempts=list(delivery.attempts),
            failure_reason=delivery.failure_reason,
        )

    return patch.object(exporter, "_attempt_degraded_text", side_effect=refuse)


# ---------------------------------------------------------------------------
# (1) one hidden TEXT per span, and NOTHING certified changes because of it
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text_mode", ["glyphs", "geometry", "raster"])
def test_each_outlined_or_rastered_span_gets_one_hidden_text_and_certifies_nothing(
    tmp_path, text_mode
) -> None:
    pdf_path = _write_pdf(tmp_path / "D042.pdf")
    on = _export(tmp_path / "on", pdf_path, text_mode=text_mode)
    off = _export(tmp_path / "off", pdf_path, text_mode=text_mode, searchable_text=False)

    companions = _companions(on.drawing)
    assert sorted(entity.dxf.text for entity in companions) == sorted(_LINES)
    for entity in companions:
        item = on.items[entity.dxf.text]
        delivery = on.by_text[entity.dxf.text]
        assert delivery["final_representation"] == text_mode and delivery["verified"] is True
        assert delivery["search_text"] == {
            "status": "written", "handle": entity.dxf.handle, "layer": _LAYER,
            "content": item.text,
        }
        assert entity.dxf.handle not in delivery["entity_handles"]
        assert (entity.dxftype(), entity.dxf.layer, entity.dxf.style) == ("TEXT", _LAYER, "unicode")
        assert tuple(entity.dxf.insert)[:2] == pytest.approx(tuple(item.insertion[:2]), abs=1e-9)
        assert float(entity.dxf.rotation) == pytest.approx(float(item.rotation), abs=1e-9)
        # Cap height from the source font when a builder rung resolved it, else 0.72 em.
        ratios = [
            attempt["evidence"].get("source_cap_height_ratio") for attempt in delivery["attempts"]
        ]
        known = next((ratio for ratio in ratios if ratio), None)
        assert (known is None) == (text_mode == "raster")
        assert float(entity.dxf.height) == pytest.approx(item.font_size * (known or 0.72))
        # FIT-aligned to the source advance, along the item's own rotation.
        advance, _source = _target_advance_width(item)
        angle = math.radians(float(item.rotation))
        assert int(entity.dxf.halign) == 5
        assert tuple(entity.dxf.align_point)[:2] == pytest.approx(
            (item.insertion[0] + advance * math.cos(angle),
             item.insertion[1] + advance * math.sin(angle)),
            abs=1e-9,
        )
    assert on.items["JOB 1000-01"].rotation == pytest.approx(90.0)

    # Hidden: frozen and non-plotting, and it stays so through a save / reload.
    resaved = tmp_path / "resaved.dxf"
    on.drawing.saveas(resaved)
    for drawing in (on.drawing, ezdxf.readfile(resaved)):
        layer = drawing.layers.get(_LAYER)
        assert layer.is_frozen() and int(layer.dxf.plot) == 0
        assert len(_companions(drawing)) == 3

    # With vs without the option: only the companions, their layer, the
    # search_text keys and the report block differ -- handles included.
    assert all("search_text" not in delivery for delivery in off.result.text_deliveries)
    assert _LAYER not in off.drawing.layers and not _companions(off.drawing)
    assert _stable(on.result.text_deliveries, tmp_path / "on") == _stable(
        off.result.text_deliveries, tmp_path / "off"
    )
    assert _visible(on.drawing) == _visible(off.drawing)
    assert {layer.dxf.name for layer in on.drawing.layers} - {_LAYER} == {
        layer.dxf.name for layer in off.drawing.layers
    }
    for field in ("entity_count", "image_count", "delivered_text_entity_counts", "text_fallbacks"):
        assert getattr(on.result, field) == getattr(off.result, field), field
    assert on.result.layer_count == off.result.layer_count + 1
    assert on.result.searchable_text_companions == {
        "enabled": True, "written": 3, "not_representable": 0, "failed": 0,
        "mismatch": 0, "layers": [_LAYER],
    }
    assert off.result.searchable_text_companions == _NO_COMPANIONS
    # The whole report: TEXTMODE-1 buckets, counts, warnings, contract readiness.
    assert on.report["extra"]["searchable_text_companions"] == on.result.searchable_text_companions
    assert off.report["extra"]["searchable_text_companions"] == _NO_COMPANIONS
    assert _stable(on.report, tmp_path / "on") == _stable(off.report, tmp_path / "off")
    assert on.report["extra"]["actual_text_entity_types"]["native_text"] == 0
    assert on.report["extra"]["actual_text_entity_types"]["dxf_text"] == 0
    assert on.report["result"]["warnings"] == 0
    assert on.report["extra"]["import_contract_ready"]["ready"] is True


def test_default_text_mode_keeps_outlines_as_the_truth_and_adds_the_search_layer(tmp_path) -> None:
    # Text mode still descends to outlines (v1.0.81); "labels" no longer means
    # "nothing searchable". Whitespace is already a TEXT: no companion.
    pdf_path = _write_pdf(tmp_path / "D042-text.pdf", (*_LINES, "   "))
    for text_mode in ("text", "labels"):
        sheet = _export(tmp_path / text_mode, pdf_path, text_mode=text_mode)
        assert sorted(entity.dxf.text for entity in _companions(sheet.drawing)) == sorted(_LINES)
        for text in _LINES:
            assert sheet.by_text[text]["final_representation"] == "glyphs"
            assert sheet.by_text[text]["verified"] is True
        whitespace = sheet.by_text["   "]
        assert whitespace["final_representation"] == "text"
        assert whitespace["search_text"] == {
            "status": "not_needed", "handle": None, "layer": None, "content": "   ",
        }
        assert sheet.result.searchable_text_companions["written"] == 3


# ---------------------------------------------------------------------------
# (2) exact strings survive, non-ASCII included, in UTF-8 and in cp1252 files
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("dxf_version", "utf8_file"), [("R2010", True), ("R2000", False), ("R12", False)]
)
def test_exact_non_ascii_string_survives_in_every_dxf_version(
    tmp_path, dxf_version, utf8_file
) -> None:
    # NFKC would turn the superscript two into "2": the companion is the EXACT string.
    latin1 = "EX101 45° M²"
    greek = "MXT-100 Ω Δ"
    pdf_path = tmp_path / "D100.pdf"
    pdf = fitz.open()
    page = pdf.new_page(width=300, height=200)
    page.insert_text((30, 40), latin1, fontsize=11)
    writer = fitz.TextWriter(page.rect)
    writer.append((30, 70), greek, font=fitz.Font("cjk"), fontsize=11)
    writer.write_text(page)
    page.draw_line((20, 120), (280, 120))
    pdf.save(str(pdf_path))
    pdf.close()

    sheet = _export(tmp_path / dxf_version, pdf_path, dxf_version=dxf_version)

    assert set(sheet.items) == {latin1, greek}
    decoded = sorted(decode_dxf_unicode(entity.dxf.text) for entity in _companions(sheet.drawing))
    assert decoded == sorted([latin1, greek])
    assert all(sheet.by_text[text]["search_text"]["status"] == "written" for text in (latin1, greek))
    assert sheet.result.searchable_text_companions["mismatch"] == 0
    assert sheet.drawing.layers.get(_LAYER).is_frozen()
    # A pre-R2007 DXF is cp1252: other characters are \U+XXXX escapes there, so
    # a raw grep of the file does not find them (README says so).
    raw = sheet.output.read_bytes()
    assert ("Ω".encode("utf-8") in raw) is utf8_file
    assert (b"\\U+03a9" in raw.lower().replace(b"\\u+", b"\\U+")) is not utf8_file
    if dxf_version == "R12":
        assert not sheet.drawing.layers.get(_LAYER).dxf.hasattr("plot")  # R12 has no plot flag


# ---------------------------------------------------------------------------
# (3) a string native TEXT cannot carry literally is skipped and reported
# ---------------------------------------------------------------------------
def test_caret_and_percent_control_strings_are_skipped_and_reported(tmp_path) -> None:
    unrepresentable = ("MXT-100^", "EX101 %%d", "D100 " + chr(92) + "U+00B0")
    pdf_path = _write_pdf(tmp_path / "D042-controls.pdf", ("D042 SAMPLE", *unrepresentable))
    sheet = _export(tmp_path / "controls", pdf_path)

    assert [entity.dxf.text for entity in _companions(sheet.drawing)] == ["D042 SAMPLE"]
    for text in unrepresentable:
        delivery = sheet.by_text[text]
        assert delivery["verified"] is True and delivery["final_representation"] == "glyphs"
        assert delivery["search_text"] == {
            "status": "not_representable", "handle": None, "layer": _LAYER, "content": text,
            "reason": "DXF TEXT cannot carry this source string unchanged",
        }
    assert sheet.result.searchable_text_companions == {
        "enabled": True, "written": 1, "not_representable": 3, "failed": 0,
        "mismatch": 0, "layers": [_LAYER],
    }
    assert sheet.report["result"]["warnings"] == 0  # skipped and reported, not a warning


def test_page_whose_strings_are_all_unrepresentable_leaves_no_empty_layer(tmp_path) -> None:
    pdf_path = _write_pdf(tmp_path / "D042-all.pdf", ("EX101^", "EX102^", "EX103^"))
    sheet = _export(tmp_path / "all", pdf_path)
    assert sheet.result.searchable_text_companions["not_representable"] == 3
    assert _LAYER not in sheet.drawing.layers and not _companions(sheet.drawing)


# ---------------------------------------------------------------------------
# (4) a companion writer fault costs that companion only: a warning
# ---------------------------------------------------------------------------
def test_companion_writer_fault_costs_that_companion_only_and_is_a_warning(tmp_path) -> None:
    real_writer = exporter._write_search_text_companion

    def writer(text_item, *args, **kwargs):
        if text_item.text == _TARGET:
            raise RuntimeError("injected companion fault")
        return real_writer(text_item, *args, **kwargs)

    pdf_path = _write_pdf(tmp_path / "D042-fault.pdf")
    sheet = _export(
        tmp_path / "fault", pdf_path,
        faults=[patch.object(exporter, "_write_search_text_companion", side_effect=writer)],
    )

    target = sheet.by_text[_TARGET]
    assert target["verified"] is True and target["final_representation"] == "glyphs"
    assert target["search_text"] == {
        "status": "failed", "handle": None, "layer": _LAYER, "content": _TARGET,
        "reason": "RuntimeError: injected companion fault",
    }
    assert sorted(entity.dxf.text for entity in _companions(sheet.drawing)) == [
        "D042 SAMPLE", "JOB 1000-01",
    ]
    block = sheet.report["extra"]["searchable_text_companions"]
    assert (block["written"], block["failed"]) == (2, 1)
    assert sheet.report["result"]["warnings"] == 1
    assert sheet.report["extra"]["text_representation_delivery"]["verified"] is True
    assert sheet.report["extra"]["import_contract_ready"]["checks"]["text_delivery"] is True
    assert sheet.report["extra"]["text_items_degraded_total"] == 0
    assert exporter.searchable_text_warning_line(block).startswith(
        "Warning: 1 hidden search-text companion(s)"
    )
    assert exporter.searchable_text_warning_line(_NO_COMPANIONS) == ""


def test_companion_entity_fault_removes_the_half_written_text(tmp_path) -> None:
    # The fault is INSIDE the writer, after the TEXT exists: it must not stay.
    import dxf_text_builder as builder

    real_fit = builder._fit_text_advance

    def fit(entity, *args, **kwargs):
        if entity.dxf.text == _TARGET:
            raise ValueError("injected FIT fault")
        return real_fit(entity, *args, **kwargs)

    pdf_path = _write_pdf(tmp_path / "D042-fit.pdf")
    sheet = _export(
        tmp_path / "fit", pdf_path, text_mode="raster",
        faults=[patch.object(builder, "_fit_text_advance", side_effect=fit)],
    )
    assert sheet.by_text[_TARGET]["search_text"]["status"] == "failed"
    assert sheet.by_text[_TARGET]["search_text"]["reason"] == "ValueError: injected FIT fault"
    assert _TARGET not in [entity.dxf.text for entity in sheet.drawing.modelspace().query("TEXT")]
    assert sheet.by_text[_TARGET]["verified"] is True


# ---------------------------------------------------------------------------
# (5) a page with images: every companion owns a paint key
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("dxf_version", ["R2018", "R2004"])
def test_every_companion_owns_a_paint_key_when_the_page_binds_an_image_order(
    tmp_path, dxf_version
) -> None:
    # apply_image_paint_order refuses a modelspace entity without a paint key and
    # that would cost the whole sheet. In R2004 the degree sign is the cp1252 byte
    # 0xB0: the streaming paint-order check must not lose the sheet to it either.
    lines = ("D042 SAMPLE", "EX101 45°", "JOB 1000-01")
    pdf_path = _write_pdf(tmp_path / "D042-image.pdf", lines, with_image=True)
    applied = []
    real_apply = exporter.apply_image_paint_order

    def apply(layout, keys):
        applied.append(dict(keys))
        return real_apply(layout, keys)

    sheet = _export(
        tmp_path / "image", pdf_path, include_images=True, dxf_version=dxf_version,
        faults=[patch.object(exporter, "apply_image_paint_order", side_effect=apply)],
    )

    companions = _companions(sheet.drawing)
    assert sorted(entity.dxf.text for entity in companions) == sorted(lines)
    assert len(applied) == 1
    redraw = dict(sheet.drawing.modelspace().get_redraw_order())
    for entity in companions:
        assert entity.dxf.handle in applied[0] and entity.dxf.handle in redraw
    assert set(applied[0]) == {entity.dxf.handle for entity in sheet.drawing.modelspace()}
    assert sheet.result.searchable_text_companions["written"] == 3
    # Ordered like the source span it accompanies: between the two image paints.
    order = [entity.dxf.handle for entity in sheet.drawing.modelspace()]
    images = [entity.dxf.handle for entity in sheet.drawing.modelspace().query("IMAGE")]
    middle = sheet.by_text["EX101 45°"]["search_text"]["handle"]
    assert len(images) == 2
    assert order.index(images[0]) < order.index(middle) < order.index(images[1])


# ---------------------------------------------------------------------------
# (6) the post-write check is soft: mismatch + warning, never the sheet
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tamper", ["content", "layer", "type", "missing", "thawed"])
def test_tampered_companion_is_a_mismatch_warning_and_never_fails_the_sheet(
    tmp_path, tamper
) -> None:
    real_reopen = exporter._reopen_candidate_for_verification
    real_once = exporter._export_to_dxf_once
    exports = []

    def reopen(*args, **kwargs):
        candidate, auditor = real_reopen(*args, **kwargs)
        entity = next(item for item in _companions(candidate) if item.dxf.text == _TARGET)
        if tamper == "content":
            entity.dxf.text = "EX1O1"
        elif tamper == "layer":
            entity.dxf.layer = "P001_TEXT"
        elif tamper == "type":
            candidate.entitydb[entity.dxf.handle] = candidate.modelspace().add_point((0, 0))
        elif tamper == "missing":
            candidate.modelspace().delete_entity(entity)
        else:
            candidate.layers.get(_LAYER).thaw()
        return candidate, auditor

    def once(*args, **kwargs):
        exports.append(1)
        return real_once(*args, **kwargs)

    pdf_path = _write_pdf(tmp_path / "D042-tamper.pdf")
    sheet = _export(
        tmp_path / "tamper", pdf_path,
        faults=[
            patch.object(exporter, "_reopen_candidate_for_verification", side_effect=reopen),
            patch.object(exporter, "_export_to_dxf_once", side_effect=once),
        ],
    )

    assert exports == [1]  # never a retry of the sheet
    mismatched = [_TARGET] if tamper != "thawed" else list(_LINES)  # the layer hides them all
    for text in _LINES:
        delivery = sheet.by_text[text]
        assert delivery["verified"] is True and delivery["final_representation"] == "glyphs"
        assert delivery["search_text"]["status"] == (
            "mismatch" if text in mismatched else "written"
        )
    assert sheet.by_text[_TARGET]["search_text"]["reason"]
    block = sheet.report["extra"]["searchable_text_companions"]
    assert (block["written"], block["mismatch"]) == (3 - len(mismatched), len(mismatched))
    assert sheet.report["result"]["warnings"] == len(mismatched)
    assert sheet.report["extra"]["text_representation_delivery"]["verified"] is True
    assert sheet.report["extra"]["result_status"] == "success"
    assert sheet.output.is_file()


def test_companion_survives_the_reduced_reopen_used_by_post_write_verification(tmp_path) -> None:
    # The reduced verification copy keeps what the delivery records address:
    # search_text.handle is collected like every other "...handle" key.
    pdf_path = _write_pdf(tmp_path / "D042-keep.pdf")
    sheet = _export(tmp_path / "keep", pdf_path)
    handles = {delivery["search_text"]["handle"] for delivery in sheet.result.text_deliveries}
    assert None not in handles and len(handles) == 3
    assert handles <= exporter._verification_keep_handles(sheet.result.text_deliveries, [])


# ---------------------------------------------------------------------------
# (7) CLI: on by default, --no-searchable-text writes none and no layer
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("entry", ["lcpdf-import", "pdf2dxf"])
@pytest.mark.parametrize("switch", [None, "--searchable-text", "--no-searchable-text"])
def test_cli_switch_writes_the_companions_by_default_and_none_when_switched_off(
    tmp_path, monkeypatch, capsys, entry, switch
) -> None:
    import pdf2dxf

    pdf_path = _write_pdf(tmp_path / "D042-cli.pdf")
    output = tmp_path / "D042-cli.dxf"
    extra = [switch] if switch else []
    if entry == "pdf2dxf":
        code = pdf2dxf.main(
            [str(pdf_path), str(output), "--mode", "vector", "--text-mode", "glyphs", *extra]
        )
    else:
        monkeypatch.setattr(sys, "argv", [
            "lcpdf-import", str(pdf_path), "--out", str(output), "--mode", "vector",
            "--pages", "1", "--text-mode", "glyphs", "--no-images", *extra,
        ])
        code = cli_module.main()
    captured = capsys.readouterr()

    assert code == 0 and "search-text companion" not in captured.err
    drawing = ezdxf.readfile(output)
    report = json.loads(
        (tmp_path / "D042-cli_import_report.json").read_text(encoding="utf-8")
    )
    block = report["extra"]["searchable_text_companions"]
    if switch == "--no-searchable-text":
        assert not _companions(drawing) and _LAYER not in drawing.layers
        assert "TEXT" not in {entity.dxftype() for entity in drawing.modelspace()}
        assert block == _NO_COMPANIONS
        assert all(
            "search_text" not in item
            for item in report["extra"]["text_representation_delivery"]["items"]
        )
    else:
        assert sorted(entity.dxf.text for entity in _companions(drawing)) == sorted(_LINES)
        assert drawing.layers.get(_LAYER).is_frozen()
        assert (block["enabled"], block["written"], block["layers"]) == (True, 3, [_LAYER])
    if entry == "lcpdf-import":
        assert json.loads(captured.out)["export"]["searchable_text_companions"] == block


def test_cli_says_one_warning_line_when_a_companion_is_lost(tmp_path, monkeypatch, capsys) -> None:
    import pdf2dxf

    pdf_path = _write_pdf(tmp_path / "D042-lost.pdf")
    with patch.object(
        exporter, "_write_search_text_companion", side_effect=RuntimeError("injected")
    ):
        monkeypatch.setattr(sys, "argv", [
            "lcpdf-import", str(pdf_path), "--out", str(tmp_path / "a.dxf"), "--mode", "vector",
            "--pages", "1", "--text-mode", "glyphs", "--no-images",
        ])
        assert cli_module.main() == 0
        first = capsys.readouterr().err
        assert pdf2dxf.main(
            [str(pdf_path), str(tmp_path / "b.dxf"), "--mode", "vector", "--text-mode", "glyphs"]
        ) == 0
        second = capsys.readouterr().err
    for err in (first, second):
        assert err.count("Warning: 3 hidden search-text companion(s)") == 1
        assert "Traceback" not in err
    assert not _companions(ezdxf.readfile(tmp_path / "a.dxf"))


def test_no_import_text_means_no_companions_either(tmp_path) -> None:
    pdf_path = _write_pdf(tmp_path / "D042-notext.pdf")
    run = run_import(str(pdf_path), mode="vector", overrides={"pages": "1", "import_text": False})
    result = exporter.export_to_dxf(
        run.extraction,
        str(tmp_path / "notext.dxf"),
        exporter.DxfExportOptions(include_text=False, include_images=False),
    )
    run.close()
    assert result.searchable_text_companions == _NO_COMPANIONS
    assert not _companions(ezdxf.readfile(tmp_path / "notext.dxf"))


# ---------------------------------------------------------------------------
# (8) degraded-to-raster and dropped items get one; a visible degraded TEXT does not
# ---------------------------------------------------------------------------
def test_degraded_raster_and_dropped_items_get_a_companion_but_degraded_text_does_not(
    tmp_path,
) -> None:
    pdf_path = _write_pdf(tmp_path / "D042-degrade.pdf")

    raster = _export(tmp_path / "raster", pdf_path, faults=[_fail_one_item()])
    target = raster.by_text[_TARGET]
    assert target["final_representation"] == "raster" and target["degraded"] is True
    assert target["verified"] is False  # the companion never changes the item's own flag
    assert target["search_text"]["status"] == "written"
    assert raster.drawing.entitydb[target["search_text"]["handle"]].dxf.text == _TARGET

    visible = _export(
        tmp_path / "visible", pdf_path, faults=[_fail_one_item(), _no_item_raster()]
    )
    target = visible.by_text[_TARGET]
    assert target["final_representation"] == "text" and target["degraded"] is True
    assert target["search_text"] == {
        "status": "not_needed", "handle": None, "layer": None, "content": _TARGET,
    }
    assert [
        entity.dxf.layer
        for entity in visible.drawing.modelspace().query("TEXT")
        if entity.dxf.text == _TARGET
    ] == ["P001_TEXT_DEGRADED"]  # the string is in the file exactly once
    assert visible.result.searchable_text_companions["written"] == 2

    dropped = _export(
        tmp_path / "dropped", pdf_path,
        faults=[_fail_one_item(), _no_item_raster(), _no_degraded_text()],
    )
    target = dropped.by_text[_TARGET]
    assert target["dropped"] is True and target["final_representation"] is None
    assert target["entity_handles"] == [] and target["verified"] is False
    assert target["search_text"]["status"] == "written"
    companion = dropped.drawing.entitydb[target["search_text"]["handle"]]
    assert (companion.dxftype(), companion.dxf.text, companion.dxf.layer) == (
        "TEXT", _TARGET, _LAYER)
    # A drop stays a drop: reported, a warning, not counted as a text entity.
    assert dropped.report["extra"]["text_items_degraded"][0]["delivered"] == "none"
    assert dropped.report["result"]["text_entities"] == 2
    assert dropped.report["result"]["warnings"] == 1
    assert dropped.result.searchable_text_companions["written"] == 3


# ---------------------------------------------------------------------------
# (9) the layer: R12 still exports; a shared layer is never frozen
# ---------------------------------------------------------------------------
def test_r12_still_exports_with_a_frozen_search_layer(tmp_path) -> None:
    pdf_path = _write_pdf(tmp_path / "D042-r12.pdf")
    sheet = _export(tmp_path / "r12", pdf_path, text_mode="geometry", dxf_version="R12")
    assert sheet.drawing.dxfversion == "AC1009"
    assert sorted(entity.dxf.text for entity in _companions(sheet.drawing)) == sorted(_LINES)
    assert all(entity.dxftype() == "TEXT" for entity in _companions(sheet.drawing))
    assert sheet.drawing.layers.get(_LAYER).is_frozen()
    assert all(sheet.by_text[text]["verified"] is True for text in _LINES)


def test_resumable_assembly_keeps_the_search_layer_frozen(tmp_path) -> None:
    # Every GUI conversion is resumable: page checkpoints are re-assembled into
    # one drawing. A thawed layer there would draw LFF text over the outlines.
    import dxf_import_engine as engine
    from pdfcadcore.import_config import ImportConfig

    pdf_path = _write_pdf(tmp_path / "D042-resume.pdf")
    config = ImportConfig.vector()
    config.text_mode = "glyphs"
    output = tmp_path / "resumed.dxf"
    stats = engine.convert(
        str(pdf_path), str(output), config=config, dxf_version="R2010", resumable=True
    )

    drawing = ezdxf.readfile(output)
    companions = _companions(drawing)
    assert sorted(entity.dxf.text for entity in companions) == sorted(_LINES)
    layers = {entity.dxf.layer for entity in companions}
    assert len(layers) == 1 and next(iter(layers)).endswith(_LAYER)
    layer = drawing.layers.get(next(iter(layers)))
    assert layer.is_frozen() and int(layer.dxf.plot) == 0
    assert stats["searchable_text_warning"] == ""
    summary = json.loads((tmp_path / "resumed_import_report.json").read_text(encoding="utf-8"))
    assert summary["warnings"] == 0
    # The summary the operator is pointed at says what a search-text warning is about.
    assert summary["searchable_text_companions"] == {
        "enabled": True, "written": 3, "not_representable": 0, "failed": 0,
        "mismatch": 0, "layers": [_LAYER],
    }
    # The switch is part of the resume identity: pages are never mixed.
    with pytest.raises(engine.ResumeMismatchError):
        engine.convert(
            str(pdf_path), str(output), config=config, dxf_version="R2010",
            resumable=True, searchable_text=False,
        )


def test_resumable_assembly_is_not_sized_by_the_hidden_companions(tmp_path) -> None:
    # Page N+1 is stacked below page N by the page's measured height. ezdxf
    # measures a frozen TEXT like any entity, so a companion that reached past
    # the ink moved the VISIBLE geometry of every later page.
    import dxf_import_engine as engine

    def checkpoint(name: str, *, frozen: bool) -> Path:
        doc = ezdxf.new("R2010")
        layer = doc.layers.new(_LAYER)
        if frozen:
            layer.freeze()
        doc.modelspace().add_line((0, 0), (100, 50))
        doc.modelspace().add_text(
            "D042 SAMPLE", height=4.0, dxfattribs={"layer": _LAYER, "insert": (0, -200)}
        )
        doc.saveas(tmp_path / name)
        return tmp_path / name

    def second_page_line_y(first_page: Path) -> float:
        output = tmp_path / f"{first_page.stem}_assembled.dxf"
        engine._assemble_checkpoints(
            [first_page, checkpoint("page_0002.dxf", frozen=True)], str(output)
        )
        lines = ezdxf.readfile(output).modelspace().query("LINE")
        return min(float(line.dxf.start.y) for line in lines)

    # Hidden companions: page 1 is as tall as its visible LINE (50 * 1.2).
    assert second_page_line_y(checkpoint("page_0001.dxf", frozen=True)) == pytest.approx(-60.0)
    # A thawed layer of that name belongs to the drawing and is visible: measured.
    assert second_page_line_y(checkpoint("page_0001_visible.dxf", frozen=False)) < -299.0


def test_companions_never_move_the_visible_geometry_of_a_resumable_conversion(tmp_path) -> None:
    # Every GUI conversion and pdf2dxf --resume. Text without descenders is the
    # outermost ink of each page, so the companion's TEXT box reaches past it.
    import dxf_import_engine as engine
    from pdfcadcore.import_config import ImportConfig

    pdf_path = tmp_path / "D100-pages.pdf"
    pdf = fitz.open()
    for number in (1, 2):
        page = pdf.new_page(width=300, height=200)
        page.insert_text((30, 30), "D100 SAMPLE", fontsize=24)
        page.draw_line((20, 150), (280, 150))
        page.insert_text((30, 180), f"MXT-100 P{number}", fontsize=8)
    pdf.save(str(pdf_path))
    pdf.close()

    placed = {}
    for searchable_text in (True, False):
        config = ImportConfig.vector()
        config.text_mode = "glyphs"
        output = tmp_path / ("on" if searchable_text else "off") / "sheet.dxf"
        output.parent.mkdir()
        engine.convert(
            str(pdf_path), str(output), config=config, dxf_version="R2010",
            resumable=True, searchable_text=searchable_text,
        )
        drawing = ezdxf.readfile(output)
        assert len(_companions(drawing)) == (4 if searchable_text else 0)
        placed[searchable_text] = [
            (entity.dxftype(), entity.dxf.layer, tuple(
                round(value, 9)
                for value in (entity.dxf.start if entity.dxftype() == "LINE" else entity.dxf.insert)
            ))
            for entity in drawing.modelspace()
            if entity.dxftype() in {"LINE", "INSERT"}
            and not entity.dxf.layer.endswith("TEXT_SEARCH")
        ]
    assert len({point[1] for kind, _layer, point in placed[False] if kind == "LINE"}) == 2
    assert placed[True] == placed[False]


def _pending(record: dict, text: str, page_number: int = 1):
    item = SimpleNamespace(
        text=text, insertion=(10.0, 20.0), rotation=0.0, font_size=4.0, font_name="Arial",
        color=None, advance_width=12.0, bbox=None, target_quad_model=None,
    )
    return (record, item, None, page_number, (1, 0))


def test_search_layer_is_dedicated_and_a_layer_the_drawing_owns_is_never_frozen() -> None:
    # Without source-layer names every page layer collapses to "P001": the
    # companions still get a layer of their own, because freezing hides a layer.
    doc = ezdxf.new("R2018")
    record = {"final_representation": "glyphs"}
    keys: dict = {}
    exporter._write_search_text_companions(
        doc, doc.modelspace(), [_pending(record, "D100 SAMPLE")],
        opts=exporter.DxfExportOptions(prefer_source_layers=False),
        is_r12=False, source_paint_keys=keys,
    )
    assert record["search_text"]["layer"] == "P001_TEXT_SEARCH"
    assert keys == {record["search_text"]["handle"]: (1, 0)}
    assert not doc.layers.has_entry("P001") or not doc.layers.get("P001").is_frozen()

    # A PDF layer that is literally called TEXT_SEARCH owns that name already.
    doc = ezdxf.new("R2018")
    doc.layers.new("P001_TEXT_SEARCH")
    doc.modelspace().add_line((0, 0), (1, 1), dxfattribs={"layer": "P001_TEXT_SEARCH"})
    record = {"final_representation": "glyphs"}
    keys = {}
    exporter._write_search_text_companions(
        doc, doc.modelspace(), [_pending(record, "D100 SAMPLE")],
        opts=exporter.DxfExportOptions(), is_r12=False, source_paint_keys=keys,
    )
    assert record["search_text"]["status"] == "failed" and keys == {}
    assert "already belongs to the drawing" in record["search_text"]["reason"]
    assert not doc.layers.get("P001_TEXT_SEARCH").is_frozen()
    assert [entity.dxftype() for entity in doc.modelspace()] == ["LINE"]


@pytest.mark.parametrize(
    ("dxf_version", "text"),
    [
        ("R2018", "C:" + chr(92) + "PROJ" + chr(92) + "D042"),  # LibreCAD: a line break
        ("R2018", "EX101" + chr(92) + "~SAMPLE"),  # LibreCAD: a space
        ("R2000", "EX" + chr(0x81) + "101"),  # C1 control: not in cp1252, written as other text
        ("R2018", "EX" + chr(0xD800) + "101"),  # lone surrogate: not UTF-8, written as other text
    ],
)
def test_string_the_host_or_the_writer_would_alter_is_skipped_never_written_altered(
    dxf_version, text
) -> None:
    doc = ezdxf.new(dxf_version)
    record = {"final_representation": "glyphs"}
    keys: dict = {}
    exporter._write_search_text_companions(
        doc, doc.modelspace(), [_pending(record, text)],
        opts=exporter.DxfExportOptions(), is_r12=False, source_paint_keys=keys,
    )
    assert record["search_text"] == {
        "status": "not_representable", "handle": None, "layer": _LAYER, "content": text,
        "reason": "DXF TEXT cannot carry this source string unchanged",
    }
    assert keys == {} and len(doc.modelspace()) == 0 and not doc.layers.has_entry(_LAYER)


def test_advance_below_float_resolution_is_not_written_as_a_degenerate_fit() -> None:
    doc = ezdxf.new("R2018")
    record = {"final_representation": "glyphs"}
    pending = _pending(record, "D100 SAMPLE")
    pending[1].insertion, pending[1].advance_width = (1000.0, 1000.0), 1e-14
    exporter._write_search_text_companions(
        doc, doc.modelspace(), [pending],
        opts=exporter.DxfExportOptions(), is_r12=False, source_paint_keys={},
    )
    assert record["search_text"]["status"] == "written"
    entity = doc.entitydb[record["search_text"]["handle"]]
    assert (int(entity.dxf.halign), int(entity.dxf.valign)) == (0, 0)  # LEFT, not FIT
    assert tuple(entity.dxf.insert)[:2] == (1000.0, 1000.0)


# ---------------------------------------------------------------------------
# (10) a lost companion is a warning in every entry point, and fails none
# ---------------------------------------------------------------------------
def _lose_the_target_companion():
    real_writer = exporter._write_search_text_companion

    def writer(text_item, *args, **kwargs):
        if text_item.text == _TARGET:
            raise RuntimeError("injected companion fault")
        return real_writer(text_item, *args, **kwargs)

    return patch.object(exporter, "_write_search_text_companion", side_effect=writer)


def test_lost_companion_is_a_warning_in_batch_and_qa_smoke_and_fails_neither(
    tmp_path, monkeypatch, capsys
) -> None:
    from librecad_pdf_importer import batch_cli, qa_smoke

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    pdf_path = _write_pdf(input_dir / "D042-lost.pdf")
    with _lose_the_target_companion():
        monkeypatch.setattr(sys, "argv", [
            "lcpdf-batch", str(input_dir), str(tmp_path / "batch"), "--mode", "vector",
            "--text-mode", "glyphs", "--json", str(tmp_path / "batch.json"),
        ])
        batch_code = batch_cli.main()
        batch_err = capsys.readouterr().err
        monkeypatch.setattr(sys, "argv", [
            "qa_smoke", str(pdf_path), "--mode", "vector", "--json", str(tmp_path / "qa.json"),
        ])
        qa_code = qa_smoke.main()
        capsys.readouterr()

    # A batch writes no import report per PDF: the line names the batch report.
    assert batch_code == 0
    assert batch_err.count(
        "D042-lost.pdf: Warning: 1 hidden search-text companion(s) could not be written or "
        "verified; the drawing itself is unaffected. See searchable_text_companions in the "
        "batch report."
    ) == 1
    aggregate = json.loads((tmp_path / "batch.json").read_text(encoding="utf-8"))
    [sheet] = aggregate["results"]
    assert (aggregate["passed"], aggregate["warnings"]) == (1, 1)
    assert (sheet["status"], sheet["warnings"]) == ("PASS", 1)
    assert sheet["searchable_text_companions"]["failed"] == 1
    lost = {"failed": 1, "mismatch": 0}
    assert exporter.searchable_text_warning_line(lost).endswith("in the import report.")
    assert exporter.searchable_text_warning_line(lost, see="Run with --json.").endswith(
        "unaffected. Run with --json."
    )

    assert qa_code == 0
    [qa_result] = json.loads((tmp_path / "qa.json").read_text(encoding="utf-8"))["results"]
    assert (qa_result["status"], qa_result["warnings"]) == ("PASS", 1)


def test_lost_companion_reaches_the_gui_log_and_the_resumable_summary(tmp_path) -> None:
    # Every GUI conversion is resumable. Driven without a Tk window.
    pytest.importorskip("tkinter")
    import threading

    import gui

    pdf_path = _write_pdf(tmp_path / "D042-gui.pdf")
    glyphs_label = next(label for label, mode in gui.TEXT_MODES.items() if mode == "glyphs")
    values = {"_var_scale": "1.0", "_var_import_text": True, "_var_text_mode": glyphs_label,
              "_var_pages": "", "_var_dxf_ver": "R2018", "_var_launch_librecad": False}
    logged: list = []
    app = SimpleNamespace(
        **{key: SimpleNamespace(get=lambda value=value: value) for key, value in values.items()},
        _cancel_event=threading.Event(),
        _log=logged.append,
        after=lambda _ms, callback: callback(),
        _finish_conversion=lambda: None,
    )
    with ExitStack() as stack:
        stack.enter_context(_lose_the_target_companion())
        showinfo = stack.enter_context(patch.object(gui.messagebox, "showinfo"))
        showerror = stack.enter_context(patch.object(gui.messagebox, "showerror"))
        gui.Pdf2DxfApp._run_conversion(
            app, str(pdf_path), str(tmp_path / "gui.dxf"),
            gui.Pdf2DxfApp._capture_options(app),
        )

    line = "Warning: 1 hidden search-text companion(s) could not be written or verified"
    assert not showerror.called
    assert sum(1 for message in logged if str(message).startswith(line)) == 1
    [done] = showinfo.call_args_list
    assert done.args[0] == "Done" and done.args[1].count(line) == 1
    summary = json.loads((tmp_path / "gui_import_report.json").read_text(encoding="utf-8"))
    assert summary["warnings"] == 1
    assert summary["searchable_text_companions"] == {
        "enabled": True, "written": 2, "not_representable": 0, "failed": 1,
        "mismatch": 0, "layers": [_LAYER],
    }
