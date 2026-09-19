"""Owner decision 2026-09-19: one unverifiable text item never costs the sheet.

"These tools are meant to help, not hinder." The text builder's failure
classification is unchanged (proven impossible / unproven failure / invalid
layout); only its consequence changed. One item degrades down a ladder --
requested rungs, item raster patch, visible TEXT on ``P###_TEXT_DEGRADED``,
reported drop -- and the sheet always exports. The degrade is loud instead:
the item stays ``verified=False`` (so contract-ready / certification still
fail), is listed in the report, counted as a warning, and printed on stderr.

Synthetic, deterministic fixtures only (drawing D042 / EX101, job 1000-01).
"""
from __future__ import annotations

from collections import Counter
from contextlib import ExitStack
import json
from pathlib import Path
import sys
from unittest.mock import patch

import ezdxf
import pytest

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore

from dxf_text_builder import TextDeliveryAttempt, TextDeliveryResult
from librecad_pdf_importer import cli as cli_module
from librecad_pdf_importer.exporters import dxf_exporter as exporter
from librecad_pdf_importer.importer import run_import, write_import_report


_TARGET = "EX101"
# TextDeliveryResult.to_dict() as it was before this change: an item that does
# not degrade must not grow a single key.
_PRE_CHANGE_DELIVERY_KEYS = {
    "source_id",
    "requested_representation",
    "final_representation",
    "verified",
    "fallback_used",
    "entity_handles",
    "support_entity_handles",
    "referenced_entity_handles",
    "terminal_fallback_authorized",
    "failure_reason",
    "attempts",
}


# Two different triangles clip one flood fill: their intersection is not computed.
_UNRESOLVABLE_CLIP_FILL = (
    b"q 10 10 m 90 10 l 50 90 l h W n 10 90 m 90 90 l 50 10 l h W n "
    b"0 0 1 rg 0 0 100 100 re f Q"
)


def _write_pdf(path: Path, *, target: str = _TARGET, with_image: bool = False,
               with_unresolvable_clip_fill: bool = False) -> Path:
    pdf = fitz.open()
    page = pdf.new_page(width=300, height=200)
    page.insert_text((30, 40), "D042 SAMPLE", fontsize=11)
    if with_image:
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 3, 2), False)
        pixmap.clear_with(255)
        pixmap.set_pixel(0, 0, (255, 0, 0))
        xref = page.insert_image(fitz.Rect(20, 20, 200, 140), stream=pixmap.tobytes("png"))
    page.insert_text((30, 70), target, fontsize=11)
    if with_image:
        page.insert_image(fitz.Rect(20, 20, 200, 140), xref=xref)
    page.insert_text((30, 100), "JOB 1000-01", fontsize=11)
    page.draw_line((20, 120), (280, 120))
    if with_unresolvable_clip_fill:
        page.draw_rect(fitz.Rect(0, 0, 1, 1))  # a content stream of its own to replace
        pdf.update_stream(page.get_contents()[-1], _UNRESOLVABLE_CLIP_FILL)
    pdf.save(str(path))
    pdf.close()
    return path


def _fail_one_item(target: str = _TARGET, *, raises: bool = False,
                   message: str = "injected unproven failure"):
    """The builder fails WITHOUT impossibility proof for exactly one item."""

    real_build_text = exporter.build_text

    def build_text(text_item, *args, **kwargs):
        if text_item.text != target:
            return real_build_text(text_item, *args, **kwargs)
        if raises:
            raise ValueError(message)
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
        fitz.DisplayList,
        "get_pixmap",
        side_effect=RuntimeError("terminal renderer unavailable"),
    )


def _export(tmp_path: Path, name: str, pdf_path: Path, *, text_mode="glyphs",
            include_images=False, faults=(), dxf_version="R2018"):
    run = run_import(
        str(pdf_path), mode="vector", overrides={"pages": "1", "text_mode": text_mode}
    )
    ids = {
        item.text: f"text_span:1:{item.id}"
        for item in run.extraction.pages[0].page_data.text_items
    }
    output = tmp_path / f"{name}.dxf"
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
            ),
        )
    report_path = tmp_path / f"{name}_import_report.json"
    write_import_report(run, str(report_path), elapsed_ms=1.0)
    run.close()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return result, report, ezdxf.readfile(output), ids


def _census(drawing) -> Counter:
    return Counter((entity.dxftype(), entity.dxf.layer) for entity in drawing.modelspace())


def _shape(delivery: dict) -> tuple:
    """What one delivery is, independent of handle numbering."""
    return (
        delivery["requested_representation"],
        delivery["final_representation"],
        delivery["verified"],
        delivery["fallback_used"],
        len(delivery["entity_handles"]),
        [
            (attempt["attempted_representation"], attempt["strategy"], attempt["outcome"])
            for attempt in delivery["attempts"]
        ],
        sorted(delivery),
    )


def _by_id(result) -> dict:
    return {delivery["source_id"]: delivery for delivery in result.text_deliveries}


# ---------------------------------------------------------------------------
# (1) unproven failure -> raster patch, everything else identical, loud report
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raises", [False, True], ids=["failed_attempt", "builder_exception"])
def test_one_unproven_failure_becomes_a_raster_patch_and_the_sheet_exports(
    tmp_path, raises
) -> None:
    pdf_path = _write_pdf(tmp_path / "D042.pdf")
    base_result, base_report, base_drawing, ids = _export(tmp_path, "baseline", pdf_path)
    result, report, drawing, _ = _export(
        tmp_path, "degraded", pdf_path, faults=[_fail_one_item(raises=raises)]
    )

    target = _by_id(result)[ids[_TARGET]]
    assert target["final_representation"] == "raster"
    assert target["verified"] is False
    assert target["degraded"] is True and target["dropped"] is False
    assert target["degrade_policy"] == "item_failure_never_costs_sheet"
    assert target["proof_class"] == "unproven_failure"
    assert target["fallback_used"] is True
    assert target["attempts"][0]["outcome"] == "failed"
    assert target["attempts"][0]["strategy"] == (
        "text_builder_exception" if raises else "entity_text2path"
    )
    assert target["attempts"][-1]["attempted_representation"] == "raster"
    assert target["attempts"][-1]["outcome"] == "verified"
    assert target["fallback_reason_code"] == "item_degraded_after_unproven_failure"
    crash_evidence = target["attempts"][0]["evidence"]
    if raises:
        # A rescued builder crash may be OUR bug: where it was raised is kept, bounded.
        assert crash_evidence["exception_type"] == "ValueError"
        tail = crash_evidence["traceback_tail"]
        assert tail[0] == "Traceback (most recent call last):"
        assert tail[-1] == "ValueError: injected unproven failure"
        assert any("test_text_item_degrade.py" in line and "build_text" in line for line in tail)
        assert len("\n".join(tail)) <= 4000
    else:
        assert "traceback_tail" not in crash_evidence
    image = drawing.entitydb[target["entity_handles"][0]]
    assert image.dxftype() == "IMAGE" and image.dxf.layer == "P001_TEXT"
    assert Path(target["attempts"][-1]["evidence"]["asset_path"]).is_file()

    # Everything else is identical to the sheet without the failing item.
    for text in ("D042 SAMPLE", "JOB 1000-01"):
        assert _shape(_by_id(result)[ids[text]]) == _shape(_by_id(base_result)[ids[text]])
    assert _census(drawing) - Counter({("IMAGE", "P001_TEXT"): 1}) == (
        _census(base_drawing) - Counter({("INSERT", "P001_TEXT"): 1})
    )
    assert sorted(
        tuple(round(value, 9) for value in entity.dxf.insert)
        for entity in drawing.modelspace().query("INSERT")
    ) == sorted(
        tuple(round(value, 9) for value in entity.dxf.insert)
        for entity in base_drawing.modelspace().query("INSERT")
        if entity.dxf.handle != _by_id(base_result)[ids[_TARGET]]["entity_handles"][0]
    )

    # Loud: listed, counted as a warning, never certified.
    extra = report["extra"]
    assert extra["text_items_degraded"] == [
        {
            "source_id": ids[_TARGET],
            "page": 1,
            "text": _TARGET,
            "reason": "ValueError: injected unproven failure",
            "reason_code": "item_degraded_after_unproven_failure",
            "proof_class": "unproven_failure",
            "delivered": "raster",
        }
    ]
    assert report["fallback"]["used"] is True
    assert report["fallback"]["text_items_degraded"] == result.text_fallbacks
    assert extra["text_items_degraded_total"] == 1
    assert extra["text_items_degraded_truncated"] is False
    assert report["result"]["warnings"] == 1 and base_report["result"]["warnings"] == 0
    assert "warnings_present" in extra["diagnostics"]["signals"]
    assert extra["result_status"] == "success"
    assert extra["text_representation_delivery"]["verified"] is False
    assert extra["import_contract_ready"]["ready"] is False
    assert extra["import_contract_ready"]["checks"]["text_delivery"] is False
    assert base_report["extra"]["import_contract_ready"]["checks"]["text_delivery"] is True
    assert result.text_fallbacks == [
        {
            "requested": "glyphs",
            "delivered": "raster",
            "reason": "item_degraded_after_unproven_failure",
            "count": 1,
        }
    ]
    summary = exporter.summarize_text_delivery(
        "glyphs", result.text_deliveries, report_path="report.json"
    )
    assert summary["verified"] is False
    assert summary["failed_source_ids"] == [ids[_TARGET]]
    assert summary["degraded_item_count"] == 1


def test_bounded_traceback_keeps_the_raise_site_under_a_very_long_message(tmp_path) -> None:
    # The message is the LAST line of a formatted traceback: cutting the tail alone
    # spent the whole budget on a 7,000-character message and lost every frame.
    from librecad_pdf_importer.importer import terminal_failure_record

    long_message = "SAMPLE " * 1000
    pdf_path = _write_pdf(tmp_path / "D042-long.pdf")
    result, _report, _drawing, ids = _export(
        tmp_path, "long", pdf_path,
        faults=[_fail_one_item(raises=True, message=long_message)],
    )
    crash = _by_id(result)[ids[_TARGET]]["attempts"][0]
    tail = crash["evidence"]["traceback_tail"]
    assert tail[0] == "Traceback (most recent call last):"
    assert any("test_text_item_degrade.py" in line and "build_text" in line for line in tail)
    assert tail[-1].startswith("ValueError: SAMPLE SAMPLE") and tail[-1].endswith("...")
    assert len("\n".join(tail)) <= 4000
    assert crash["reason"] == f"ValueError: {long_message}"  # the full text stays here

    def raise_site() -> None:
        raise KeyError(long_message)

    try:
        raise_site()
    except KeyError as exc:
        failure = terminal_failure_record(exc)
    assert len(failure["message"]) == 2000
    assert failure["traceback"][0] == "Traceback (most recent call last):"
    assert any("in raise_site" in line for line in failure["traceback"])
    assert failure["traceback"][-1].startswith("KeyError: 'SAMPLE SAMPLE")
    assert len("\n".join(failure["traceback"])) <= 4000


def test_item_without_visible_ink_is_never_described_as_a_delivered_raster_patch(
    tmp_path,
) -> None:
    # Render mode 3 paints nothing. The raster rung proves that and makes no patch
    # ("verified_source_zero_ink_omission"): nothing visible is missing, and the
    # warning must not claim that a raster patch was delivered.
    pdf_path = tmp_path / "D042-no-ink.pdf"
    pdf = fitz.open()
    page = pdf.new_page(width=300, height=200)
    page.insert_text((30, 40), "D042 SAMPLE", fontsize=11)
    page.insert_text((30, 70), _TARGET, fontsize=11, render_mode=3)
    page.draw_line((20, 120), (280, 120))
    pdf.save(str(pdf_path))
    pdf.close()

    result, report, drawing, ids = _export(
        tmp_path, "no-ink", pdf_path, faults=[_fail_one_item()]
    )

    target = _by_id(result)[ids[_TARGET]]
    assert target["degraded"] is True and target["verified"] is False
    assert target["attempts"][-1]["strategy"] == "verified_source_zero_ink_omission"
    assert target["entity_handles"] == [] and not drawing.modelspace().query("IMAGE")
    [entry] = report["extra"]["text_items_degraded"]
    assert entry["delivered"] == "raster" and entry["no_visible_ink"] is True
    [line] = exporter.degraded_text_item_lines(report["extra"]["text_items_degraded"], 1)
    assert line.endswith("; the source item has no visible ink, so nothing was drawn.")
    assert "raster patch" not in line
    # Still loud and never certified: the item itself was not verified.
    assert report["result"]["warnings"] == 1
    assert report["extra"]["import_contract_ready"]["ready"] is False


# ---------------------------------------------------------------------------
# (2) raster impossible too -> visible TEXT on P###_TEXT_DEGRADED, with a paint key
# ---------------------------------------------------------------------------
def test_unrenderable_item_becomes_visible_degraded_text_with_its_paint_key(tmp_path) -> None:
    # The page binds a source image paint order, so every modelspace entity
    # must own a paint key or apply_image_paint_order aborts the whole sheet.
    pdf_path = _write_pdf(tmp_path / "D042-image.pdf", with_image=True)
    result, report, drawing, ids = _export(
        tmp_path,
        "degraded-text",
        pdf_path,
        include_images=True,
        faults=[_fail_one_item(), _no_item_raster()],
    )

    target = _by_id(result)[ids[_TARGET]]
    assert target["final_representation"] == "text"
    assert target["verified"] is False and target["degraded"] is True
    assert target["dropped"] is False
    assert [attempt["outcome"] for attempt in target["attempts"]] == [
        "failed",
        "failed",
        "degraded",
    ]
    assert "terminal renderer unavailable" in target["attempts"][1]["reason"]
    text = drawing.entitydb[target["entity_handles"][0]]
    assert text.dxftype() == "TEXT"
    assert text.dxf.text == _TARGET
    assert text.dxf.layer == "P001_TEXT_DEGRADED"
    assert not bool(text.dxf.get("invisible", 0))
    layer = drawing.layers.get("P001_TEXT_DEGRADED")
    assert layer.is_on() and not layer.is_frozen()

    # It was ordered between the two image paints like the source span it replaces.
    order = [entity.dxf.handle for entity in drawing.modelspace()]
    images = [entity.dxf.handle for entity in drawing.modelspace().query("IMAGE")]
    assert len(images) == 2
    assert order.index(images[0]) < order.index(text.dxf.handle) < order.index(images[1])
    assert text.dxf.handle in dict(drawing.modelspace().get_redraw_order())

    assert report["extra"]["text_items_degraded"][0]["delivered"] == "text"
    assert report["extra"]["text_items_degraded"][0]["text"] == _TARGET
    assert report["result"]["warnings"] == 1
    assert report["extra"]["import_contract_ready"]["ready"] is False
    assert result.text_fallbacks[-1]["reason"] == "item_degraded_after_unproven_failure"
    assert result.text_fallbacks[-1]["delivered"] == "text"


def test_raster_patch_without_its_pixel_lattice_proof_costs_that_rung_not_the_sheet(
    tmp_path,
) -> None:
    # This used to raise "Final source crop has no exact opaque pixel-lattice
    # proof" and lose the sheet. The unproven IMAGE is removed and the next rung runs.
    real_raster = exporter._attempt_terminal_text_raster

    def raster_without_proof(delivery, **kwargs):
        rescued, asset = real_raster(delivery, **kwargs)
        rescued.attempts[-1].evidence.pop("source_pixel_lattice_verified")
        return rescued, asset

    pdf_path = _write_pdf(tmp_path / "D042-unproven-raster.pdf")
    result, report, drawing, ids = _export(
        tmp_path,
        "unproven-raster",
        pdf_path,
        faults=[
            _fail_one_item(),
            patch.object(
                exporter, "_attempt_terminal_text_raster", side_effect=raster_without_proof
            ),
        ],
    )

    target = _by_id(result)[ids[_TARGET]]
    assert [attempt["outcome"] for attempt in target["attempts"]] == [
        "failed",
        "failed",
        "degraded",
    ]
    assert "pixel-lattice proof" in target["attempts"][1]["reason"]
    assert target["attempts"][1]["cleanup_verified"] is True
    assert target["attempts"][1]["entity_handles"] == []
    assert target["final_representation"] == "text" and target["verified"] is False
    assert not list(drawing.modelspace().query("IMAGE"))
    assert not list(drawing.objects.query("IMAGEDEF"))
    assert not list(tmp_path.rglob("*.png"))
    assert drawing.entitydb[target["entity_handles"][0]].dxf.text == _TARGET
    assert report["extra"]["text_items_degraded"][0]["delivered"] == "text"


@pytest.mark.parametrize(
    ("dxf_version", "acadver", "faults"),
    [("R12", "AC1009", ()), ("R2004", "AC1018", (_no_item_raster,))],
    ids=["R12_has_no_image_rung", "R2004_raster_unavailable"],
)
def test_degraded_text_with_a_degree_sign_survives_a_pre_r2007_dxf(
    tmp_path, dxf_version, acadver, faults
) -> None:
    # A pre-R2007 DXF is cp1252, not UTF-8: the degree sign is the single byte
    # 0xB0 there. The streaming post-write reader decoded strict UTF-8 and the
    # UnicodeDecodeError cost the whole sheet (no DXF, exit 2); it now falls back
    # to the complete load, which reads the file's own codepage.
    target = "EX101 45°"
    pdf_path = _write_pdf(tmp_path / "D042-degree.pdf", target=target)
    result, report, drawing, ids = _export(
        tmp_path,
        "degree",
        pdf_path,
        dxf_version=dxf_version,
        faults=[_fail_one_item(target), *(fault() for fault in faults)],
    )

    assert drawing.dxfversion == acadver
    delivery = _by_id(result)[ids[target]]
    assert delivery["final_representation"] == "text" and delivery["degraded"] is True
    assert delivery["verified"] is False and delivery["dropped"] is False
    text = drawing.entitydb[delivery["entity_handles"][0]]
    assert (text.dxftype(), text.dxf.text, text.dxf.layer) == (
        "TEXT", target, "P001_TEXT_DEGRADED")
    others = [ids["D042 SAMPLE"], ids["JOB 1000-01"]]
    assert all(_by_id(result)[source_id]["verified"] is True for source_id in others)
    assert report["extra"]["text_items_degraded"][0]["text"] == target
    assert report["result"]["warnings"] == 1


# ---------------------------------------------------------------------------
# (3) everything impossible -> dropped, no live handles, sheet still exports
# ---------------------------------------------------------------------------
def test_item_that_no_rung_can_carry_is_dropped_and_reported(tmp_path) -> None:
    # "%%d" is a DXF TEXT control sequence: native TEXT would silently turn it
    # into a degree sign, so the exact source string cannot be kept either.
    unrepresentable = "EX101 %%d"
    pdf_path = _write_pdf(tmp_path / "D042-dropped.pdf", target=unrepresentable)
    result, report, drawing, ids = _export(
        tmp_path,
        "dropped",
        pdf_path,
        faults=[_fail_one_item(unrepresentable), _no_item_raster()],
    )

    target = _by_id(result)[ids[unrepresentable]]
    assert target["dropped"] is True and target["degraded"] is True
    assert target["verified"] is False and target["final_representation"] is None
    assert target["entity_handles"] == []
    assert target["support_entity_handles"] == []
    assert [attempt["outcome"] for attempt in target["attempts"]] == ["failed"] * 3
    assert all(attempt["cleanup_verified"] for attempt in target["attempts"])
    for attempt in target["attempts"]:
        assert attempt["entity_handles"] == [] and attempt["support_entity_handles"] == []
        for handle in attempt["created_entity_handles"]:
            assert handle not in drawing.entitydb
    assert "P001_TEXT_DEGRADED" not in drawing.layers
    assert _census(drawing) == Counter(
        {("INSERT", "P001_TEXT"): 2, ("LINE", "P001_RGB_000_000_000"): 1}
    )
    others = [ids["D042 SAMPLE"], ids["JOB 1000-01"]]
    assert all(_by_id(result)[source_id]["verified"] is True for source_id in others)

    assert report["extra"]["text_items_degraded"] == [
        {
            "source_id": ids[unrepresentable],
            "page": 1,
            "text": unrepresentable,
            "reason": "ValueError: injected unproven failure",
            "reason_code": "item_degraded_after_unproven_failure",
            "proof_class": "unproven_failure",
            "delivered": "none",
        }
    ]
    # A drop is a fallback although it created nothing, and what is not in the
    # drawing is not counted as a text entity.
    dropped_fallback = [{"requested": "glyphs", "delivered": "none",
                         "reason": "item_degraded_after_unproven_failure", "count": 1}]
    assert result.text_fallbacks == dropped_fallback
    assert report["fallback"]["used"] is True
    assert report["fallback"]["text_items_degraded"] == dropped_fallback
    assert report["result"]["text_entities"] == 2 and report["extra"]["text_source_spans"] == 3
    assert report["extra"]["actual_text_entity_types"]["count"] == 2
    assert "2 text items" in report["extra"]["human_summary"]
    assert "without raster fallback" not in report["extra"]["human_summary"]
    assert report["result"]["warnings"] == 1
    assert report["extra"]["import_contract_ready"]["ready"] is False
    assert exporter.degraded_text_item_lines(
        report["extra"]["text_items_degraded"], 1
    )[0].endswith("DROPPED from the drawing.")


def test_post_write_verification_rejects_a_dropped_record_that_owns_a_live_entity(
    tmp_path,
) -> None:
    pdf_path = _write_pdf(tmp_path / "D042-tamper.pdf", target="EX101 %%d")
    real_verify = exporter._verify_serialized_text_deliveries
    sessions = []

    def capture(doc, deliveries, **kwargs):
        sessions.append(kwargs["trusted_positioned_session"])
        return real_verify(doc, deliveries, **kwargs)

    result, _report, drawing, ids = _export(
        tmp_path,
        "tamper",
        pdf_path,
        faults=[
            _fail_one_item("EX101 %%d"),
            _no_item_raster(),
            patch.object(exporter, "_verify_serialized_text_deliveries", side_effect=capture),
        ],
    )
    deliveries = [dict(item) for item in result.text_deliveries]
    real_verify(drawing, deliveries, trusted_positioned_session=sessions[-1])

    dropped = next(item for item in deliveries if item.get("dropped"))
    live = _by_id(result)[ids["D042 SAMPLE"]]["entity_handles"][0]
    dropped["attempts"] = [dict(dropped["attempts"][0], created_entity_handles=[live])]
    with pytest.raises(RuntimeError, match="dropped item owns live handles"):
        real_verify(drawing, deliveries, trusted_positioned_session=sessions[-1])


# ---------------------------------------------------------------------------
# (4) proof_class repeats the builder's own verdict, never a guess from outcomes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("font_failure_changes", "proof_class"),
    [
        ({}, "proven_impossible"),
        ({"detail": "font helper unavailable"}, "unproven_failure"),
        ({"source_xref": None}, "unproven_failure"),
    ],
    ids=["item_bound_empty_font_program", "runtime_font_helper", "proof_not_bound_to_item"],
)
def test_proof_class_is_proven_only_when_the_builder_itself_proved_the_item(
    tmp_path, font_failure_changes, proof_class
) -> None:
    # Every rung of all three ends "impossible". The builder authorizes only the
    # item-bound empty font program; a font failure that may be OUR runtime's is
    # refused, and the report must not call that refusal proven.
    from dataclasses import replace
    from types import SimpleNamespace

    import dxf_text_builder as builder
    from librecad_pdf_importer.core.document import DocumentExtraction, ExtractedPage
    from pdfcadcore.primitives import PageData
    from test_e2_fraction_font_proof import _empty_program_item

    item = _empty_program_item()
    item.font_failure = replace(item.font_failure, **font_failure_changes)
    extraction = DocumentExtraction(
        pdf_path=str(tmp_path / "unreadable-source.pdf"),
        pages=[ExtractedPage(page_data=PageData(
            page_number=3, width=300.0, height=200.0, text_items=[item],
        ), profile=SimpleNamespace())],
    )
    with patch.object(builder, "_resolve_exact_font", return_value=builder._ExactFontResolution(
        source_name="Arial", family="Arial", exact=False, reason="no exact match",
    )):
        result = exporter.export_to_dxf(
            extraction,
            str(tmp_path / "proof-class.dxf"),
            exporter.DxfExportOptions(include_images=False, text_mode="glyphs"),
        )

    delivery = result.text_deliveries[0]
    builder_attempts = delivery["attempts"][:-2]  # then the raster and TEXT rungs
    assert builder_attempts
    assert all(attempt["outcome"] == "impossible" for attempt in builder_attempts)
    assert {
        attempt["evidence"]["fallback_authorized_for_this_item"]
        for attempt in builder_attempts
    } == {proof_class == "proven_impossible"}
    assert delivery["degraded"] is True and delivery["verified"] is False
    assert delivery["proof_class"] == proof_class
    assert result.text_fallbacks[0]["reason"] == (
        "item_degraded_after_proven_impossibility"
        if proof_class == "proven_impossible"
        else "item_degraded_after_unproven_failure"
    )


# ---------------------------------------------------------------------------
# (5) a sheet with NO failing item is exactly what it was
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text_mode", ["text", "glyphs", "geometry", "raster"])
def test_sheet_without_a_failing_item_is_unchanged(tmp_path, text_mode) -> None:
    pdf_path = _write_pdf(tmp_path / "D042-clean.pdf")
    result, report, drawing, _ids = _export(tmp_path, "clean", pdf_path, text_mode=text_mode)
    again, _report, drawing_again, _ = _export(tmp_path, "again", pdf_path, text_mode=text_mode)

    assert len(result.text_deliveries) == 3
    for delivery in result.text_deliveries:
        assert set(delivery) == _PRE_CHANGE_DELIVERY_KEYS
        assert delivery["verified"] is True
        assert all(attempt["outcome"] != "degraded" for attempt in delivery["attempts"])
    expected_type = {"text": "INSERT", "glyphs": "INSERT", "raster": "IMAGE"}.get(text_mode)
    text_entities = [
        entity for entity in drawing.modelspace() if entity.dxf.layer == "P001_TEXT"
    ]
    if expected_type:
        assert [entity.dxftype() for entity in text_entities] == [expected_type] * 3
    assert not any("DEGRADED" in layer.dxf.name for layer in drawing.layers)
    assert _census(drawing) == _census(drawing_again)
    assert [_shape(item) for item in result.text_deliveries] == [
        _shape(item) for item in again.text_deliveries
    ]
    assert all(
        record["reason"] not in {
            "item_degraded_after_unproven_failure",
            "item_degraded_after_proven_impossibility",
        }
        for record in result.text_fallbacks
    )

    # The only report differences are the new fields, empty / zero.
    extra = report["extra"]
    assert extra["text_items_degraded"] == []
    assert extra["text_items_degraded_total"] == 0
    assert extra["text_items_degraded_truncated"] is False
    assert report["result"]["warnings"] == 0
    assert "warnings_present" not in extra["diagnostics"]["signals"]
    assert extra["text_representation_delivery"]["verified"] is True
    assert extra["import_contract_ready"]["checks"]["text_delivery"] is True
    summary = exporter.summarize_text_delivery(
        text_mode, result.text_deliveries, report_path="report.json"
    )
    assert summary["verified"] is True and summary["failed_source_ids"] == []
    assert summary["degraded_item_count"] == 0 and summary["degraded_items"] == []
    assert exporter.degraded_text_item_lines([], 0) == []


# ---------------------------------------------------------------------------
# (6) post-write verification mismatch on one item -> ONE retry, item degraded
# ---------------------------------------------------------------------------
def _run_with_verification(tmp_path: Path, name: str, verify_factory):
    pdf_path = _write_pdf(tmp_path / f"{name}.pdf")
    run = run_import(
        str(pdf_path), mode="vector", overrides={"pages": "1", "text_mode": "glyphs"}
    )
    ids = {
        item.text: f"text_span:1:{item.id}"
        for item in run.extraction.pages[0].page_data.text_items
    }
    output = tmp_path / f"{name}.dxf"
    output.write_bytes(b"prior accepted output\r\n")
    calls: list = []
    verify = verify_factory(ids, calls, exporter._verify_serialized_text_deliveries)
    try:
        with patch.object(exporter, "_verify_serialized_text_deliveries", side_effect=verify):
            result = exporter.export_to_dxf(
                run.extraction,
                str(output),
                exporter.DxfExportOptions(
                    include_images=False, text_mode="glyphs", provenance_opts=run.config
                ),
            )
    finally:
        run.close()
    return result, output, ids, calls


def test_post_write_mismatch_on_one_item_is_retried_once_and_that_item_degrades(
    tmp_path,
) -> None:
    def factory(ids, calls, real_verify):
        def verify(doc, deliveries, **kwargs):
            calls.append([item["source_id"] for item in deliveries if item.get("degraded")])
            if len(calls) == 1:
                raise RuntimeError(
                    f"serialized text delivery {ids[_TARGET]}: content or transform changed"
                )
            return real_verify(doc, deliveries, **kwargs)

        return verify

    result, output, ids, calls = _run_with_verification(tmp_path, "retry", factory)

    assert calls == [[], [ids[_TARGET]]]  # exactly one re-export, that item forced down
    drawing = ezdxf.readfile(output)
    target = _by_id(result)[ids[_TARGET]]
    assert target["verified"] is False and target["degraded"] is True
    assert target["final_representation"] == "raster"
    assert target["proof_class"] == "unproven_failure"
    assert target["attempts"][0]["strategy"] == "serialized_delivery_verification"
    assert "content or transform changed" in target["degrade_reason"]
    assert drawing.entitydb[target["entity_handles"][0]].dxftype() == "IMAGE"
    for text in ("D042 SAMPLE", "JOB 1000-01"):
        assert _by_id(result)[ids[text]]["verified"] is True
    # The rolled-back first pass left nothing behind.
    sessions = list(output.with_name(f"{output.stem}_assets").iterdir())
    assert len(sessions) == 1
    assert not list(tmp_path.glob(".*.tmp"))


def test_two_post_write_mismatches_are_both_covered_by_the_one_retry(tmp_path) -> None:
    # The real verifier used to stop at the FIRST mismatch, so the one retry
    # rescued that item and the second mismatch still cost the sheet.
    broken_texts = (_TARGET, "JOB 1000-01")
    raised: list = []

    def factory(ids, calls, real_verify):
        def verify(doc, deliveries, **kwargs):
            calls.append([item["source_id"] for item in deliveries if item.get("degraded")])
            if len(calls) == 1:
                dead = {ids[text]: f"DEAD{index}" for index, text in enumerate(broken_texts)}
                deliveries = [
                    dict(item, entity_handles=[dead[item["source_id"]]])
                    if item["source_id"] in dead
                    else item
                    for item in deliveries
                ]
            try:
                return real_verify(doc, deliveries, **kwargs)
            except RuntimeError as exc:
                raised.append(exc)
                raise

        return verify

    result, output, ids, calls = _run_with_verification(tmp_path, "retry-two", factory)

    assert calls == [[], [ids[text] for text in broken_texts]]
    assert isinstance(raised[0], exporter._SerializedTextDeliveryMismatches)
    assert raised[0].messages == [
        f"serialized text delivery {ids[text]}: missing live handle DEAD{index}"
        for index, text in enumerate(broken_texts)
    ]
    assert str(raised[0]).endswith("(and 1 more mismatching text item(s))")
    drawing = ezdxf.readfile(output)
    for text in broken_texts:
        delivery = _by_id(result)[ids[text]]
        assert delivery["verified"] is False and delivery["degraded"] is True
        assert delivery["final_representation"] == "raster"
        assert "missing live handle DEAD" in delivery["degrade_reason"]
        assert drawing.entitydb[delivery["entity_handles"][0]].dxftype() == "IMAGE"
    assert _by_id(result)[ids["D042 SAMPLE"]]["verified"] is True


def test_a_fault_while_checking_one_delivery_is_that_items_mismatch(tmp_path) -> None:
    # Not only RuntimeError: a KeyError/TypeError raised while the verifier
    # inspects one item's evidence is confined to that item as well.
    def factory(ids, calls, real_verify):
        def verify(doc, deliveries, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                deliveries = [
                    dict(item, support_entity_handles=5)
                    if item["source_id"] == ids[_TARGET]
                    else item
                    for item in deliveries
                ]
            return real_verify(doc, deliveries, **kwargs)

        return verify

    result, _output, ids, calls = _run_with_verification(tmp_path, "retry-fault", factory)

    assert len(calls) == 2
    delivery = _by_id(result)[ids[_TARGET]]
    assert delivery["degraded"] is True and delivery["final_representation"] == "raster"
    assert delivery["degrade_reason"] == (
        f"serialized text delivery {ids[_TARGET]}: TypeError: 'int' object is not iterable"
    )


def test_post_write_mismatch_that_survives_the_retry_fails_cleanly(tmp_path) -> None:
    def factory(ids, calls, _real_verify):
        def verify(_doc, _deliveries, **_kwargs):
            calls.append(1)
            raise RuntimeError(
                f"serialized text delivery {ids[_TARGET]}: content or transform changed"
            )

        return verify

    with pytest.raises(
        RuntimeError, match="still failing after one forced-degrade re-export"
    ) as raised:
        _run_with_verification(tmp_path, "retry-fails", factory)

    assert "content or transform changed" in str(raised.value)
    output = tmp_path / "retry-fails.dxf"
    assert output.read_bytes() == b"prior accepted output\r\n"
    assert not output.with_name(f"{output.stem}_assets").exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_only_a_failure_confined_to_one_delivery_is_retried() -> None:
    deliveries = [
        {"source_id": "text_span:1:16", "final_representation": "glyphs"},
        {"source_id": "text_span:1:165", "final_representation": "raster"},
        {"source_id": "text_span:1:7", "final_representation": "text", "degraded": True},
        {"source_id": "text_span:1:8", "final_representation": None, "degraded": True,
         "dropped": True},
    ]
    name = exporter._serialized_mismatch_item
    prefix = "serialized text delivery"
    # Each failed rung forces the NEXT one: outlines -> raster -> TEXT -> drop.
    assert name(f"{prefix} text_span:1:16: glyph bbox changed", deliveries) == (
        "text_span:1:16", exporter._TEXT_DEGRADE_RUNG_RASTER)
    assert name(f"{prefix} text_span:1:165: raster asset missing", deliveries) == (
        "text_span:1:165", exporter._TEXT_DEGRADE_RUNG_TEXT)
    assert name(f"{prefix} text_span:1:7: degraded text changed", deliveries) == (
        "text_span:1:7", exporter._TEXT_DEGRADE_RUNG_DROP)
    # Nothing below a drop, and structural failures name no single delivery.
    assert name(f"{prefix} text_span:1:8: dropped item owns live handles", deliveries) is None
    assert name(f"{prefix} has invalid or duplicate source id: 'text_span:1:16'",
                deliveries) is None
    assert name("positioned verification session is not authentic", deliveries) is None

    # Several mismatches force every named item; one structural message among
    # them keeps the whole failure fatal.
    rungs = exporter._serialized_mismatch_rungs
    messages = [f"{prefix} text_span:1:16: glyph bbox changed",
                f"{prefix} text_span:1:165: raster asset missing"]
    assert rungs(exporter._SerializedTextDeliveryMismatches(messages), deliveries) == {
        "text_span:1:16": (exporter._TEXT_DEGRADE_RUNG_RASTER, messages[0]),
        "text_span:1:165": (exporter._TEXT_DEGRADE_RUNG_TEXT, messages[1]),
    }
    assert rungs(RuntimeError(messages[0]), deliveries) == {
        "text_span:1:16": (exporter._TEXT_DEGRADE_RUNG_RASTER, messages[0])}
    assert rungs(exporter._SerializedTextDeliveryMismatches(
        [messages[0], f"{prefix} text_span:1:8: dropped item owns live handles"]
    ), deliveries) is None


# ---------------------------------------------------------------------------
# CLI level: exit code 0 + stderr lines; structural failures clean, no traceback
# ---------------------------------------------------------------------------
def _run_cli(monkeypatch, capsys, argv, main=None):
    monkeypatch.setattr(sys, "argv", ["lcpdf-import", *argv])
    code = (main or cli_module.main)()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _failure_report_named_on(stderr: str, stem: str) -> dict:
    # "Complete failure report: <path>" (exit 2) or "(complete failure report: <path>)".
    path = Path(stderr.split("omplete failure report: ", 1)[1].strip().rstrip(")"))
    assert path.is_file() and path.name.startswith(stem)
    return json.loads(path.read_text(encoding="utf-8"))


def test_cli_exports_the_sheet_prints_one_line_per_degraded_item_and_exits_zero(
    tmp_path, monkeypatch, capsys
) -> None:
    pdf_path = _write_pdf(tmp_path / "D042-cli.pdf")
    output = tmp_path / "D042-cli.dxf"
    summary_path = tmp_path / "summary.json"
    with _fail_one_item():
        code, _out, err = _run_cli(
            monkeypatch,
            capsys,
            [str(pdf_path), "--out", str(output), "--mode", "vector", "--pages", "1",
             "--text-mode", "glyphs", "--no-images", "--json", str(summary_path)],
        )

    assert code == 0
    assert ezdxf.readfile(output) is not None
    warning_lines = [line for line in err.splitlines() if line.startswith("Warning: text item")]
    assert len(warning_lines) == 1
    assert "'EX101'" in warning_lines[0] and "unproven_failure" in warning_lines[0]
    assert warning_lines[0].endswith("delivered as an unverified raster patch.")
    assert "Traceback" not in err and "Import stopped" not in err
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    text_delivery = summary["export"]["text_delivery"]
    assert text_delivery["verified"] is False and text_delivery["degraded_item_count"] == 1
    report = json.loads(
        Path(summary["export"]["import_report_path"]).read_text(encoding="utf-8")
    )
    assert report["extra"]["text_items_degraded_total"] == 1
    assert report["result"]["warnings"] == 1
    assert report["extra"]["import_contract_ready"]["ready"] is False


def test_degraded_item_lines_and_report_block_are_bounded() -> None:
    records = [
        {"source_id": f"text_span:1:{index}", "degraded": True, "dropped": index % 2 == 0,
         "final_representation": None if index % 2 == 0 else "raster",
         "source_text": f"EX{index:03d}", "source_page_number": 1,
         "degrade_reason": "ValueError: injected", "proof_class": "unproven_failure"}
        for index in range(205)
    ] + [{"source_id": "text_span:1:999", "verified": True, "final_representation": "glyphs"}]
    block = exporter.degraded_text_items(records)
    assert block["total"] == 205 and block["truncated"] is True
    assert len(block["items"]) == exporter.TEXT_ITEMS_DEGRADED_REPORT_LIMIT == 200
    assert block["items"][0]["delivered"] == "none" and block["items"][1]["delivered"] == "raster"
    lines = exporter.degraded_text_item_lines(block["items"], block["total"])
    assert len(lines) == 21
    assert lines[-1].startswith("... and 185 more degraded text item(s)")
    # A console codepage can never turn the warning into a crash.
    exotic = exporter.degraded_text_item_lines(
        [dict(block["items"][0], text="⌀ 25 ±1")], 1
    )
    assert exotic[0].isascii()
    # One physical, bounded line each, whatever the exception or the source text
    # carries; the report keeps the full strings.
    unruly = exporter.degraded_text_item_lines(
        [dict(block["items"][0], text="SAMPLE " * 400,
              reason="RuntimeError: first line\nsecond line\r\nthird " + "x" * 3000)], 1
    )
    assert len(unruly) == 1 and unruly[0].splitlines() == [unruly[0]]
    assert "first line second line third" in unruly[0]
    assert len(unruly[0]) < 450 and unruly[0].endswith("DROPPED from the drawing.")
    # Control characters (NUL, BEL, BS, ESC, DEL) never reach a console either.
    hostile = exporter.degraded_text_item_lines(
        [dict(block["items"][0], text="EX\x00101",
              reason="ValueError: \x1b[31mSAMPLE\x07\x08\x7f alert")], 1
    )
    assert len(hostile) == 1
    assert not any(ord(char) < 32 or ord(char) == 127 for char in hostile[0])
    assert "'EX 101'" in hostile[0] and "ValueError: [31mSAMPLE alert" in hostile[0]


def _duplicate_source_ids(real_run_import):
    def run_with_duplicates(*args, **kwargs):
        run = real_run_import(*args, **kwargs)
        items = run.extraction.pages[0].page_data.text_items
        items[1].id = items[0].id
        return run

    return run_with_duplicates


def test_cli_duplicate_source_ids_stay_fatal_but_end_cleanly(
    tmp_path, monkeypatch, capsys
) -> None:
    pdf_path = _write_pdf(tmp_path / "D042-duplicate.pdf")
    output = tmp_path / "D042-duplicate.dxf"
    output.write_bytes(b"prior accepted output\r\n")
    with patch.object(
        cli_module, "run_import", side_effect=_duplicate_source_ids(cli_module.run_import)
    ):
        code, _out, err = _run_cli(
            monkeypatch,
            capsys,
            [str(pdf_path), "--out", str(output), "--mode", "vector", "--pages", "1",
             "--text-mode", "glyphs", "--no-images"],
        )

    assert code == 2
    assert err.startswith("Import stopped: ")
    assert "duplicate stable text source identity" in err
    assert "Traceback" not in err
    assert output.read_bytes() == b"prior accepted output\r\n"
    assert not output.with_name(f"{output.stem}_assets").exists()
    report = _failure_report_named_on(err, "D042-duplicate_failed_import_report_")
    assert report["extra"]["result_status"] == "failed"
    assert report["extra"]["import_contract_ready"]["ready"] is False
    # The report says WHY, not only "failed": error text, type, bounded traceback.
    failure = report["extra"]["terminal_failure"]
    assert failure["type"] == "ImportStopped" and failure["deliberate_stop"] is True
    assert failure["message"].endswith("duplicate stable text source identity")
    assert failure["traceback"][0] == "Traceback (most recent call last):"
    assert any("dxf_exporter.py" in line for line in failure["traceback"])
    assert len("\n".join(failure["traceback"])) <= 4000
    assert report["extra"]["import_contract_ready"]["checks"]["no_terminal_failure"] is False


def test_cli_unexpected_export_failure_is_one_line_exit_3_and_the_report_keeps_the_cause(
    tmp_path, monkeypatch, capsys
) -> None:
    # Not a deliberate stop: it may be OUR bug. Exit code 3 and one readable line
    # (never "Import stopped"), and the failure report keeps the raise site that
    # the console no longer shows.
    pdf_path = _write_pdf(tmp_path / "D042-bug.pdf")
    output = tmp_path / "D042-bug.dxf"
    output.write_bytes(b"prior accepted output\r\n")
    argv = [str(pdf_path), "--out", str(output), "--mode", "vector", "--pages", "1",
            "--text-mode", "glyphs", "--no-images"]
    with patch.object(
        exporter, "_verify_serialized_image_assets", side_effect=KeyError("handle")
    ):
        code, _out, err = _run_cli(monkeypatch, capsys, argv)
        verbose_code, _out, verbose_err = _run_cli(monkeypatch, capsys, [*argv, "--verbose"])

    assert code == 3 and verbose_code == 3
    assert "KeyError: 'handle'" in err and "Import stopped" not in err
    assert "Traceback" not in err and len(err.strip().splitlines()) == 1
    assert "Traceback" in verbose_err
    assert output.read_bytes() == b"prior accepted output\r\n"
    report = _failure_report_named_on(err, "D042-bug_failed_import_report_")
    assert report["extra"]["result_status"] == "failed"
    failure = report["extra"]["terminal_failure"]
    assert failure["type"] == "KeyError" and failure["deliberate_stop"] is False
    assert failure["message"] == "'handle'"
    assert any("_export_to_dxf_impl" in line for line in failure["traceback"])
    assert failure["traceback"][-1] == "KeyError: 'handle'"


@pytest.mark.parametrize("entry", ["lcpdf-import", "pdf2dxf"])
def test_unwritable_failure_report_never_hides_the_original_failure_or_its_exit_code(
    tmp_path, monkeypatch, capsys, entry
) -> None:
    # Read-only folder, disk full: exactly when an export fails, writing its failure
    # report may fail too. The ORIGINAL cause and its exit code (2 deliberate stop,
    # 3 otherwise) survive, and stderr says that no failure report could be written.
    import librecad_pdf_importer.importer as importer_module
    import pdf2dxf

    pdf_path = _write_pdf(tmp_path / "D042-full.pdf")
    output = tmp_path / "D042-full.dxf"
    real_write = importer_module.write_import_report

    def unwritable(run, path, **kwargs):
        if kwargs.get("terminal_failure"):
            raise OSError(28, "No space left on device", str(path))
        return real_write(run, path, **kwargs)

    def run_entry():
        if entry == "pdf2dxf":
            code = pdf2dxf.main(
                [str(pdf_path), str(output), "--mode", "vector", "--text-mode", "glyphs"]
            )
            return code, capsys.readouterr().err
        code, _out, err = _run_cli(
            monkeypatch,
            capsys,
            [str(pdf_path), "--out", str(output), "--mode", "vector", "--pages", "1",
             "--text-mode", "glyphs", "--no-images"],
        )
        return code, err

    # lcpdf-import binds both names at import; the engine looks them up per call.
    module = cli_module if entry == "lcpdf-import" else importer_module
    with patch.object(module, "write_import_report", side_effect=unwritable):
        with patch.object(
            module, "run_import", side_effect=_duplicate_source_ids(run_import)
        ):
            stop_code, stop_err = run_entry()
        with patch.object(
            exporter, "_verify_serialized_image_assets", side_effect=KeyError("handle")
        ):
            bug_code, bug_err = run_entry()

    assert stop_code == 2
    assert stop_err.startswith("Import stopped: ")
    assert "duplicate stable text source identity" in stop_err
    assert bug_code == 3
    assert "KeyError: 'handle'" in bug_err and len(bug_err.strip().splitlines()) == 1
    for err in (stop_err, bug_err):
        assert "he failure report could not be written: OSError: [Errno 28]" in err
        assert "omplete failure report:" not in err and "Traceback" not in err
    assert not output.exists()
    assert list(tmp_path.glob("*_failed_import_report_*.json")) == []


def test_report_carries_the_rescue_reason_code_beside_the_sheets_verified_fallbacks(
    tmp_path,
) -> None:
    # LibreCAD's default Text mode: every visible item is a VERIFIED text -> glyphs
    # fallback, and fallback.text describes those. The rescued item's reason code
    # must reach the report all the same, or scoring cannot tell the two apart.
    pdf_path = _write_pdf(tmp_path / "D042-mixed.pdf")
    result, report, _drawing, ids = _export(
        tmp_path, "mixed", pdf_path, text_mode="text", faults=[_fail_one_item(raises=True)]
    )

    rescued = {"requested": "text", "delivered": "raster",
               "reason": "item_degraded_after_unproven_failure", "count": 1}
    assert report["fallback"]["used"] is True
    assert report["fallback"]["text"] == {
        "requested": "text", "delivered": "glyphs",
        "reason": "requested_representation_failed_verification", "count": 2}
    assert report["fallback"]["text_items_degraded"] == [rescued]
    assert rescued in result.text_fallbacks
    [entry] = report["extra"]["text_items_degraded"]
    assert entry["reason_code"] == rescued["reason"]
    records = {item["source_id"]: item
               for item in report["extra"]["text_representation_delivery"]["items"]}
    assert records[ids[_TARGET]]["fallback_reason_code"] == rescued["reason"]
    # A verified fallback is not a rescue and carries no rescue code.
    assert "fallback_reason_code" not in records[ids["D042 SAMPLE"]]
    # The one-sentence reason and the human summary name the rescue too: APPENDED
    # to the verified fallbacks' wording, which this default mode always has.
    assert report["fallback"]["reason"] == (
        "text_mode_fallback: text -> glyphs (requested_representation_failed_verification); "
        "text_items_degraded: 1 x text -> raster (item_degraded_after_unproven_failure)"
    )
    summary = report["extra"]["human_summary"]
    assert "text mode fallback: text -> glyphs" in summary
    assert "1 x text -> raster (item degraded after unproven failure)" in summary


def test_default_text_mode_summary_says_that_an_item_was_dropped(tmp_path) -> None:
    unrepresentable = "EX101 %%d"
    pdf_path = _write_pdf(tmp_path / "D042-text-drop.pdf", target=unrepresentable)
    _result, report, _drawing, _ids = _export(
        tmp_path, "text-drop", pdf_path, text_mode="text",
        faults=[_fail_one_item(unrepresentable), _no_item_raster()],
    )

    assert report["fallback"]["text"]["delivered"] == "glyphs"  # the verified fallbacks
    assert report["fallback"]["reason"].startswith("text_mode_fallback: text -> glyphs (")
    assert report["fallback"]["reason"].endswith(
        "; text_items_degraded: 1 x text -> none (item_degraded_after_unproven_failure)"
        "; 1 dropped from the drawing"
    )
    summary = report["extra"]["human_summary"]
    assert "1 x text -> none" in summary and "1 dropped from the drawing" in summary
    assert "2 text items" in summary and report["result"]["text_entities"] == 2


def test_report_names_the_rescue_when_the_legacy_text_fallback_block_is_empty(tmp_path) -> None:
    # fallback.text is empty when no text MODE changed (Text mode whose rescued item
    # ends as degraded TEXT is "text -> text"). The report must still say why a
    # fallback was used, in fallback.reason and in the human summary.
    import librecad_pdf_importer.importer as importer_module

    pdf_path = _write_pdf(tmp_path / "D042-same-mode.pdf")
    with patch.object(importer_module, "_text_mode_fallback_for_report", return_value=None):
        _result, report, _drawing, _ids = _export(
            tmp_path, "same-mode", pdf_path, faults=[_fail_one_item(), _no_item_raster()]
        )

    assert "text" not in report["fallback"]
    assert report["fallback"]["used"] is True
    assert report["fallback"]["reason"] == (
        "text_items_degraded: 1 x glyphs -> text (item_degraded_after_unproven_failure)"
    )
    assert "item degraded after unproven failure" in report["extra"]["human_summary"]


def test_cli_post_write_mismatch_that_survives_the_retry_ends_cleanly(
    tmp_path, monkeypatch, capsys
) -> None:
    pdf_path = _write_pdf(tmp_path / "D042-mismatch.pdf")
    output = tmp_path / "D042-mismatch.dxf"
    output.write_bytes(b"prior accepted output\r\n")

    def verify(_doc, deliveries, **_kwargs):
        raise RuntimeError(
            f"serialized text delivery {deliveries[1]['source_id']}: raster asset missing"
        )

    with patch.object(exporter, "_verify_serialized_text_deliveries", side_effect=verify):
        code, _out, err = _run_cli(
            monkeypatch,
            capsys,
            [str(pdf_path), "--out", str(output), "--mode", "vector", "--pages", "1",
             "--text-mode", "glyphs", "--no-images"],
        )

    assert code == 2
    assert err.startswith("Import stopped: serialized text delivery text_span:1:")
    assert "still failing after one forced-degrade re-export" in err
    assert "Traceback" not in err
    assert output.read_bytes() == b"prior accepted output\r\n"
    report = _failure_report_named_on(err, "D042-mismatch_failed_import_report_")
    assert report["extra"]["result_status"] == "failed"
    # The failure report names the item that was forced down the ladder.
    assert report["extra"]["text_items_degraded_total"] == 1


def test_pdf2dxf_entry_point_warns_on_degrade_and_ends_cleanly_on_structural_failure(
    tmp_path, capsys
) -> None:
    import librecad_pdf_importer.importer as importer_module
    import pdf2dxf

    pdf_path = _write_pdf(tmp_path / "D042-pdf2dxf.pdf")
    output = tmp_path / "D042-pdf2dxf.dxf"
    with _fail_one_item():
        code = pdf2dxf.main(
            [str(pdf_path), str(output), "--mode", "vector", "--text-mode", "glyphs"]
        )
    captured = capsys.readouterr()
    assert code == 0 and output.is_file()
    assert captured.err.count("Warning: text item text_span:1:") == 1
    assert "Traceback" not in captured.err

    prior = output.read_bytes()
    with patch.object(
        importer_module, "run_import", side_effect=_duplicate_source_ids(run_import)
    ):
        code = pdf2dxf.main(
            [str(pdf_path), str(output), "--mode", "vector", "--text-mode", "glyphs"]
        )
    captured = capsys.readouterr()
    assert code == 2
    assert captured.err.startswith("Import stopped: ")
    assert "duplicate stable text source identity" in captured.err
    assert captured.err.count("Complete failure report:") == 1
    assert "Traceback" not in captured.err
    assert output.read_bytes() == prior
    failure = _failure_report_named_on(
        captured.err, "D042-pdf2dxf_failed_import_report_"
    )["extra"]["terminal_failure"]
    assert failure["type"] == "ImportStopped" and failure["deliberate_stop"] is True
    # The report keeps the reason itself, not the console's pointer back to the report.
    assert failure["message"].endswith("duplicate stable text source identity")

    # Anything else is an unexpected failure: exit code 3 and ONE readable line,
    # which still points the operator at the failure report the export left.
    with patch.object(
        exporter,
        "export_to_dxf",
        side_effect=UnicodeDecodeError("utf-8", b"\xb0", 0, 1, "invalid start byte"),
    ):
        code = pdf2dxf.main(
            [str(pdf_path), str(output), "--mode", "vector", "--text-mode", "glyphs"]
        )
    captured = capsys.readouterr()
    assert code == 3
    assert "UnicodeDecodeError: 'utf-8' codec can't decode byte 0xb0" in captured.err
    assert "Import stopped" not in captured.err and "Traceback" not in captured.err
    assert len(captured.err.strip().splitlines()) == 1
    report = _failure_report_named_on(captured.err, "D042-pdf2dxf_failed_import_report_")
    assert report["extra"]["terminal_failure"]["type"] == "UnicodeDecodeError"
    assert report["extra"]["terminal_failure"]["deliberate_stop"] is False
    assert output.read_bytes() == prior


def test_pdf2dxf_and_the_gui_stat_never_count_a_dropped_item_as_a_text_item(
    tmp_path, capsys
) -> None:
    # The report already said 2 text entities of 3 source spans; stdout "Text items"
    # and the GUI's "Text:" log line are fed by the same stat and said 3.
    import pdf2dxf
    from dxf_import_engine import convert
    from pdfcadcore.import_config import ImportConfig

    unrepresentable = "EX101 %%d"
    pdf_path = _write_pdf(tmp_path / "D042-count.pdf", target=unrepresentable)
    with _fail_one_item(unrepresentable), _no_item_raster():
        code = pdf2dxf.main(
            [str(pdf_path), str(tmp_path / "D042-count.dxf"), "--mode", "vector",
             "--text-mode", "glyphs"]
        )
        captured = capsys.readouterr()
        config = ImportConfig.vector()
        config.import_text = True
        config.text_mode = "glyphs"
        stats = convert(  # the GUI's call: resumable, one checkpointed page record
            str(pdf_path), str(tmp_path / "D042-count-gui.dxf"), config=config, resumable=True
        )

    assert code == 0
    assert "DROPPED from the drawing" in captured.err
    [text_items_line] = [line for line in captured.out.splitlines() if "Text items:" in line]
    assert text_items_line.split(":")[1].strip() == "2"
    assert stats["text_items"] == 2 and stats["text_delivery"]["item_count"] == 3
    report = json.loads(
        (tmp_path / "D042-count_import_report.json").read_text(encoding="utf-8")
    )
    assert report["result"]["text_entities"] == 2 and report["extra"]["text_source_spans"] == 3


def test_batch_cli_writes_the_degraded_sheet_but_never_counts_it_as_passed(
    tmp_path, monkeypatch, capsys
) -> None:
    from librecad_pdf_importer import batch_cli

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_pdf(input_dir / "D042-batch.pdf")
    report_path = tmp_path / "batch.json"
    with _fail_one_item():
        code, _out, err = _run_cli(
            monkeypatch,
            capsys,
            [str(input_dir), str(tmp_path / "output"), "--mode", "vector",
             "--text-mode", "glyphs", "--json", str(report_path)],
            main=batch_cli.main,
        )

    # The DXF was written, but a DEGRADED sheet is as uncertified as a FAIL sheet:
    # a script that spots uncertified sheets by the exit code keeps working.
    assert code == 1
    assert (tmp_path / "output" / "D042-batch.dxf").is_file()
    assert err.count("Warning: text item text_span:1:") == 1
    aggregate = json.loads(report_path.read_text(encoding="utf-8"))
    assert (aggregate["passed"], aggregate["degraded"], aggregate["failed"]) == (0, 1, 0)
    assert aggregate["results"][0]["status"] == "DEGRADED"
    assert aggregate["results"][0]["text_items_degraded"] == 1


def test_qa_smoke_gate_still_fails_a_sheet_with_a_degraded_text_item(
    tmp_path, monkeypatch, capsys
) -> None:
    # Operators get their sheet; QA gates stay exactly as strict as the old abort.
    from librecad_pdf_importer import qa_smoke

    pdf_path = _write_pdf(tmp_path / "D042-qa.pdf")
    report_path = tmp_path / "qa.json"
    argv = [str(pdf_path), "--mode", "vector", "--json", str(report_path)]
    code, _out, _err = _run_cli(monkeypatch, capsys, argv, main=qa_smoke.main)
    assert code == 0
    assert json.loads(report_path.read_text(encoding="utf-8"))["results"][0]["status"] == "PASS"

    with _fail_one_item():
        code, _out, _err = _run_cli(monkeypatch, capsys, argv, main=qa_smoke.main)
    assert code == 1
    result = json.loads(report_path.read_text(encoding="utf-8"))["results"][0]
    assert result["status"] == "FAIL" and result["text_items_degraded"] == 1


def test_sheet_with_a_left_out_clipped_fill_and_a_degraded_text_item_says_both(
    tmp_path, monkeypatch, capsys
) -> None:
    # The two "never costs the sheet" changes meet on one sheet. Each keeps its own
    # block and stderr line, and every warnings count is the SUM of the two.
    from dxf_import_engine import convert
    from librecad_pdf_importer import batch_cli, qa_smoke
    from pdfcadcore.import_config import ImportConfig

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    pdf_path = _write_pdf(input_dir / "D042-both.pdf", with_unresolvable_clip_fill=True)
    summary_path = tmp_path / "summary.json"
    with _fail_one_item():
        code, _out, err = _run_cli(
            monkeypatch, capsys,
            [str(pdf_path), "--out", str(tmp_path / "cli-D042-both.dxf"), "--mode", "vector",
             "--text-mode", "glyphs", "--no-images", "--json", str(summary_path)],
        )
        batch_code, _out, batch_err = _run_cli(
            monkeypatch, capsys,
            [str(input_dir), str(tmp_path / "batch"), "--mode", "vector",
             "--text-mode", "glyphs", "--json", str(tmp_path / "batch.json")],
            main=batch_cli.main,
        )
        qa_code, _out, _err = _run_cli(
            monkeypatch, capsys,
            [str(pdf_path), "--mode", "vector", "--json", str(tmp_path / "qa.json")],
            main=qa_smoke.main,
        )
        config = ImportConfig.vector()
        config.import_text, config.text_mode = True, "glyphs"
        stats = convert(str(pdf_path), str(tmp_path / "gui-D042-both.dxf"),
                        config=config, resumable=True)

    # lcpdf-import: the DXF was written, so exit 0; both warnings on stderr.
    assert code == 0 and (tmp_path / "cli-D042-both.dxf").is_file()
    assert err.count("clipped fill(s) could not be resolved") == 1
    assert err.count("Warning: text item text_span:1:") == 1
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    report = json.loads(
        Path(summary["export"]["import_report_path"]).read_text(encoding="utf-8")
    )
    assert report["extra"]["clip_fill_delivery"]["dropped"] == 1
    assert report["extra"]["text_items_degraded_total"] == 1
    assert report["result"]["warnings"] == 2
    assert report["extra"]["import_contract_ready"]["ready"] is False

    # lcpdf-batch: DEGRADED (never passed), DXF written, exit 1, warnings summed.
    assert batch_code == 1 and (tmp_path / "batch" / "D042-both.dxf").is_file()
    assert batch_err.count("D042-both.pdf: WARNING: page(s) 1: 1 clipped fill(s)") == 1
    assert batch_err.count("D042-both.pdf: Warning: text item text_span:1:") == 1
    aggregate = json.loads((tmp_path / "batch.json").read_text(encoding="utf-8"))
    assert (aggregate["passed"], aggregate["degraded"], aggregate["failed"]) == (0, 1, 0)
    assert aggregate["warnings"] == 2
    [sheet] = aggregate["results"]
    assert (sheet["status"], sheet["warnings"], sheet["text_items_degraded"]) == ("DEGRADED", 2, 1)
    assert sheet["clip_fill_delivery"]["dropped"] == 1

    # The QA gate still fails the sheet, for its text; the fill alone would not.
    assert qa_code == 1
    [qa_result] = json.loads((tmp_path / "qa.json").read_text(encoding="utf-8"))["results"]
    assert (qa_result["status"], qa_result["warnings"], qa_result["text_items_degraded"]) == (
        "FAIL", 2, 1)

    # Resumable / GUI: both reach the returned stats and the report they point at.
    assert stats["clip_fill_warning"].startswith("WARNING: page(s) 1: 1 clipped fill(s)")
    assert stats["text_delivery"]["degraded_item_count"] == 1
    resumable = json.loads(Path(stats["import_report_path"]).read_text(encoding="utf-8"))
    assert resumable["warnings"] == 2
    assert resumable["clip_fill_delivery"]["dropped"] == 1
    assert resumable["text_items_degraded_total"] == 1
    assert (resumable["pages_certified"], resumable["pages_degraded"]) == ([], [1])


def test_gui_has_one_completion_message_that_carries_both_warnings() -> None:
    gui_source = (Path(__file__).resolve().parents[1] / "gui.py").read_text(encoding="utf-8")
    assert gui_source.count("show_done(") == 1  # one completion message path
    start = gui_source.index("self.after(0, lambda: show_done(")
    completion = gui_source[start:gui_source.index("except Exception", start)]
    assert "text item(s) could not " in completion  # the degraded-text warning
    assert "{clip_fill_warning}" in completion  # the clipped-fill sentence


def test_gui_error_box_names_the_failure_report_once_whatever_stopped_the_export(
    tmp_path,
) -> None:
    # The console entry points name the failure report of an unexpected failure;
    # the GUI box showed only "'handle'". Driven without a Tk window.
    pytest.importorskip("tkinter")
    import threading
    from types import SimpleNamespace

    import gui
    import librecad_pdf_importer.importer as importer_module

    pdf_path = _write_pdf(tmp_path / "D042-box.pdf")
    glyphs_label = next(label for label, mode in gui.TEXT_MODES.items() if mode == "glyphs")

    def error_box(name: str, fault) -> str:
        values = {"_var_scale": "1.0", "_var_import_text": True, "_var_text_mode": glyphs_label,
                  "_var_pages": "", "_var_dxf_ver": "R2018", "_var_launch_librecad": False}
        app = SimpleNamespace(
            **{key: SimpleNamespace(get=lambda value=value: value)
               for key, value in values.items()},
            _cancel_event=threading.Event(),
            _log=lambda _message: None,
            after=lambda _ms, callback: callback(),
            _finish_conversion=lambda: None,
        )
        with fault, patch.object(gui.messagebox, "showerror") as showerror:
            gui.Pdf2DxfApp._run_conversion(app, str(pdf_path), str(tmp_path / f"{name}.dxf"))
        [call] = showerror.call_args_list
        assert call.args[0] == "Conversion failed"
        return call.args[1]

    unexpected = error_box("D042-box-bug", patch.object(
        exporter, "_verify_serialized_image_assets", side_effect=KeyError("handle")
    ))
    stopped = error_box("D042-box-stop", patch.object(
        importer_module, "run_import", side_effect=_duplicate_source_ids(run_import)
    ))

    assert unexpected.startswith("'handle'")
    assert "duplicate stable text source identity" in stopped
    for message in (unexpected, stopped):
        assert message.count("Complete failure report: ") == 1
        named = Path(message.split("Complete failure report: ", 1)[1].strip())
        assert named.is_file() and "_failed_import_report_" in named.name


def test_forced_re_export_says_the_page_fidelity_surface_reason_once(tmp_path) -> None:
    # The one forced re-export runs the export twice on the same extraction. A
    # compositing-required page appends its fidelity-surface sentence to
    # resolved_reason on the way in, and must not say it twice in the report.
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), 1)
    for y in range(8):
        for x in range(8):
            inside = 1 <= x < 7 and 1 <= y < 7  # a transparent border: real alpha
            pixmap.set_pixel(x, y, (0, 128, 255, 255) if inside else (0, 0, 0, 0))
    pdf = fitz.open()
    page = pdf.new_page(width=300, height=200)
    page.insert_image(fitz.Rect(10, 110, 90, 190), stream=pixmap.tobytes("png"))
    page.insert_text((30, 40), "D042 SAMPLE", fontsize=11)
    page.insert_text((30, 70), _TARGET, fontsize=11)
    pdf.save(str(tmp_path / "D042-surface.pdf"))
    pdf.close()

    run = run_import(
        str(tmp_path / "D042-surface.pdf"), mode="vector",
        overrides={"pages": "1", "text_mode": "glyphs", "raster_dpi": 72},
    )
    target_id = next(
        f"text_span:1:{item.id}"
        for item in run.extraction.pages[0].page_data.text_items
        if item.text == _TARGET
    )
    real_verify = exporter._verify_serialized_text_deliveries
    calls: list = []

    def verify(doc, deliveries, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError(f"serialized text delivery {target_id}: content or transform changed")
        return real_verify(doc, deliveries, **kwargs)

    try:
        with patch.object(exporter, "RECTANGULAR_CROP_MAX_PIXELS", 1), patch.object(
            exporter, "_verify_serialized_text_deliveries", side_effect=verify
        ):
            exporter.export_to_dxf(
                run.extraction,
                str(tmp_path / "D042-surface.dxf"),
                exporter.DxfExportOptions(text_mode="glyphs", provenance_opts=run.config),
            )
        reason = str(run.extraction.pages[0].resolved_reason)
    finally:
        run.close()

    assert len(calls) == 2  # the forced re-export happened
    assert reason.count("compositing-required transparency delivered") == 1


def test_resumable_conversion_carries_degraded_items_to_the_gui(tmp_path) -> None:
    # The GUI converts through the resumable engine and shows a WARNING (never
    # an error box) from exactly these aggregate fields.
    from dxf_import_engine import convert
    from pdfcadcore.import_config import ImportConfig

    pdf_path = _write_pdf(tmp_path / "D042-gui.pdf")
    config = ImportConfig.vector()
    config.import_text = True
    config.text_mode = "glyphs"
    with _fail_one_item():
        stats = convert(
            str(pdf_path), str(tmp_path / "D042-gui.dxf"), config=config, resumable=True
        )

    assert (tmp_path / "D042-gui.dxf").is_file()
    assert stats["text_delivery"]["degraded_item_count"] == 1
    assert [item["text"] for item in stats["text_delivery"]["degraded_items"]] == [_TARGET]
    assert stats["text_delivery"]["verified"] is False
    assert stats["text_delivery"]["degraded_items_truncated"] is False
    gui_source = (Path(__file__).resolve().parents[1] / "gui.py").read_text(encoding="utf-8")
    assert "messagebox.showwarning if degraded_count else messagebox.showinfo" in gui_source
    assert '"Done with warnings" if degraded_count else "Done"' in gui_source


def test_resumable_report_never_calls_a_page_with_a_degraded_item_certified(tmp_path) -> None:
    # Before the degrade an unverifiable item aborted its page, so every
    # checkpointed page was fully verified and "certified" was true. It must stay
    # true: the degraded page is exported and resumable, listed apart, and the
    # report the run points the operator at is as loud as the page report.
    import re

    from dxf_import_engine import convert
    from pdfcadcore.import_config import ImportConfig

    pdf_path = tmp_path / "D042-two-pages.pdf"
    pdf = fitz.open()
    for title, label in (("D042 SAMPLE", _TARGET), ("D100 SAMPLE", "MXT-100")):
        page = pdf.new_page(width=300, height=200)
        page.insert_text((30, 40), title, fontsize=11)
        page.insert_text((30, 70), label, fontsize=11)
        page.draw_line((20, 120), (280, 120))
    pdf.save(str(pdf_path))
    pdf.close()
    config = ImportConfig.vector()
    config.import_text = True
    config.text_mode = "glyphs"
    output = tmp_path / "D042-two-pages.dxf"

    runs = []
    for _attempt in range(2):  # the second run resumes both checkpoints
        messages: list = []
        with _fail_one_item():
            stats = convert(
                str(pdf_path), str(output), config=config, resumable=True,
                progress_callback=messages.append,
            )
        runs.append([message for message in messages if message.startswith("Page ")])
    assert runs == [
        ["Page 1/2 exported with 1 degraded text item(s) - NOT certified",
         "Page 2/2 certified"],
        ["Page 1/2 exported with 1 degraded text item(s) - NOT certified (resumed)",
         "Page 2/2 certified (resumed)"],
    ]
    # The GUI progress bar follows both wordings.
    gui_source = (Path(__file__).resolve().parents[1] / "gui.py").read_text(encoding="utf-8")
    progress = re.search(r're\.search\(r"([^"]+)", msg\)', gui_source).group(1)
    assert [re.search(progress, message).groups() for message in runs[0]] == [
        ("1", "2"), ("2", "2")]

    assert output.is_file() and stats["resumed_pages"] == 2
    summary = json.loads(Path(stats["import_report_path"]).read_text(encoding="utf-8"))
    assert summary["schema"] == "bcs.resumable_import_report/1.0"
    assert summary["result"] == "complete"
    assert summary["pages_requested"] == [1, 2]
    assert summary["pages_certified"] == [2]
    assert summary["pages_degraded"] == [1]
    assert summary["warnings"] == 1
    assert summary["text_items_degraded_total"] == 1
    assert summary["text_items_degraded_truncated"] is False
    assert [
        (item["page"], item["text"], item["proof_class"], item["delivered"])
        for item in summary["text_items_degraded"]
    ] == [(1, _TARGET, "unproven_failure", "raster")]
