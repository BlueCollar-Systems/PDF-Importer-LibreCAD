"""The drawing scale read from the title block is shown, and the report has it.

A 1/4" = 1'-0" sheet comes in at paper size in millimetres (a 4'-0" member
measures 25.4). The importer reads "scale 48" from the title block; the user
is told so, with the number to put in Scale, and the report the window points
to carries it for every route. No geometry changes.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import ezdxf
import pytest

import dxf_import_engine
from librecad_pdf_importer.importer import (
    best_resolved_scale,
    drawing_scale_line,
    most_confident_scale,
)
from pdfcadcore.import_config import ImportConfig

NOTATION = "1/4\" = 1'-0\""


def _write_scaled_sheet(path: Path) -> None:
    """Fictional 17x11 sheet: mark EX101, job D042, title block at 1/4" = 1'-0"."""
    import pymupdf

    with pymupdf.open() as document:
        page = document.new_page(width=17 * 72, height=11 * 72)
        # A 1 inch member labelled 4'-0".
        page.draw_line((100, 300), (172, 300), color=(0, 0, 0), width=1)
        page.insert_text((115, 290), "4'-0\"", fontsize=10, fontname="helv")
        page.draw_rect(
            pymupdf.Rect(17 * 72 - 300, 11 * 72 - 120, 17 * 72 - 20, 11 * 72 - 20),
            color=(0, 0, 0),
            width=1,
        )
        page.insert_text(
            (17 * 72 - 290, 11 * 72 - 90), "DRAWING: EX101 BEAM D042",
            fontsize=10, fontname="helv",
        )
        page.insert_text(
            (17 * 72 - 290, 11 * 72 - 60), f"SCALE: {NOTATION}",
            fontsize=10, fontname="helv",
        )
        document.save(path)


@pytest.fixture()
def scaled_sheet(tmp_path: Path) -> Path:
    pdf = tmp_path / "D042" / "EX101.pdf"
    pdf.parent.mkdir(parents=True)
    _write_scaled_sheet(pdf)
    return pdf


def _member_lengths(dxf_path: Path) -> list[float]:
    document = ezdxf.readfile(dxf_path)
    lengths = []
    for entity in document.modelspace().query("LINE"):
        start, end = entity.dxf.start, entity.dxf.end
        lengths.append(math.dist((start.x, start.y), (end.x, end.y)))
    for entity in document.modelspace().query("INSERT"):
        for virtual in entity.virtual_entities():
            if virtual.dxftype() == "LINE":
                start, end = virtual.dxf.start, virtual.dxf.end
                lengths.append(math.dist((start.x, start.y), (end.x, end.y)))
    return lengths


@pytest.mark.parametrize("resumable", [True, False])
def test_both_routes_return_and_report_the_scale(scaled_sheet: Path, resumable: bool):
    output = scaled_sheet.with_name("EX101.dxf")
    stats = dxf_import_engine.convert(
        str(scaled_sheet), str(output), ImportConfig.auto(), resumable=resumable,
    )
    scale = stats["resolved_scale"]
    assert scale["factor"] == 48.0
    assert scale["confidence"] >= 0.70
    assert NOTATION in scale["notation"]

    report = json.loads(Path(stats["import_report_path"]).read_text(encoding="utf-8"))
    assert report == json.loads(
        output.with_name("EX101_import_report.json").read_text(encoding="utf-8")
    )
    reported = report["resolved_scale"] if resumable else report["extra"]["resolved_scale"]
    assert reported["factor"] == 48.0

    # No geometry change: the 1 inch member is still 25.4 at the default scale.
    assert any(math.isclose(length, 25.4, abs_tol=0.05) for length in _member_lengths(output))


def test_resumed_pages_from_an_older_session_read_as_no_scale(scaled_sheet: Path):
    output = scaled_sheet.with_name("EX101.dxf")
    dxf_import_engine.convert(str(scaled_sheet), str(output), ImportConfig.auto(), resumable=True)
    manifest_path = output.with_name("EX101_resume") / "session.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for record in manifest["completed"].values():
        record.pop("resolved_scale", None)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    stats = dxf_import_engine.convert(
        str(scaled_sheet), str(output), ImportConfig.auto(), resumable=True,
    )
    assert stats["resumed_pages"] == 1
    assert stats["resolved_scale"] is None
    report = json.loads(Path(stats["import_report_path"]).read_text(encoding="utf-8"))
    assert report["resolved_scale"] is None


def test_gui_log_and_done_box_name_the_scale_and_the_number(scaled_sheet: Path):
    import gui

    output = scaled_sheet.with_name("EX101.dxf")
    logs: list[str] = []
    app = SimpleNamespace(
        _converting=False, _cancel_event=gui.threading.Event(),
        _btn_convert=Mock(), _btn_cancel=Mock(), _progress=Mock(), _log_text=Mock(),
        _log=lambda message: logs.append(str(message)), after=lambda _ms, callback: callback(),
        _finish_conversion=Mock(),
    )
    options = gui.ConversionOptions(
        scale=1.0, import_text=True, text_mode="text", pages=None,
        dxf_version="R2010", launch_librecad=False,
    )
    with patch.object(gui.messagebox, "showinfo") as info, patch.object(
        gui.messagebox, "showwarning",
    ) as warning, patch.object(gui.messagebox, "showerror") as error:
        gui.Pdf2DxfApp._run_conversion(app, str(scaled_sheet), str(output), options)
    error.assert_not_called()
    done = (info.call_args or warning.call_args).args[1]
    scale_lines = [line for line in logs if line.startswith("Drawing scale found:")]
    assert len(scale_lines) == 1
    line = scale_lines[0]
    assert NOTATION in line and "put 48 in Scale" in line and "paper size" in line
    assert line in done
    report = json.loads(output.with_name("EX101_import_report.json").read_text(encoding="utf-8"))
    assert report["resolved_scale"]["factor"] == 48.0


def test_pdf2dxf_summary_prints_the_scale_line(scaled_sheet: Path, capsys):
    import pdf2dxf

    output = scaled_sheet.with_name("cli.dxf")
    assert pdf2dxf.main([str(scaled_sheet), str(output)]) == 0
    printed = capsys.readouterr().out
    assert "Drawing scale found: " + NOTATION in printed
    assert "add --scale 48 and convert again" in printed


# --- the line itself ------------------------------------------------------

_SCALE = {
    "factor": 48.0, "notation": "SCALE: " + NOTATION, "source": "titleblock",
    "confidence": 0.98, "fallback_reason": "",
}


def test_line_at_paper_size_names_the_multiplier():
    assert drawing_scale_line(_SCALE, 1.0) == (
        "Drawing scale found: 1/4\" = 1'-0\" (98% sure). This DXF is at paper size "
        "(millimetres); to draw at real size put 48 in Scale and convert again."
    )


def test_line_when_scale_already_matches_says_real_size():
    line = drawing_scale_line(_SCALE, 48.0)
    assert "Scale is 48, so this DXF is at real size (millimetres)." in line
    assert "convert again" not in line


def test_line_for_another_user_scale():
    line = drawing_scale_line(_SCALE, 12.0)
    assert "at 12 times paper size" in line and "put 48 in Scale" in line


@pytest.mark.parametrize(
    "scale",
    [
        None,
        {},
        dict(_SCALE, confidence=0.69),
        dict(_SCALE, factor=1.0),
        dict(_SCALE, fallback_reason="no_scale_detected"),
        dict(_SCALE, factor="oops"),
        dict(_SCALE, factor=float("nan")),
    ],
)
def test_line_is_silent_without_a_trusted_scale(scale):
    assert drawing_scale_line(scale, 1.0) == ""


def test_ratio_notation_without_label():
    line = drawing_scale_line(dict(_SCALE, factor=50.0, notation=""), 1.0)
    assert line.startswith("Drawing scale found: 1:50 (98% sure).")


def test_most_confident_scale_keeps_the_first_best_and_skips_bad_records():
    low = dict(_SCALE, factor=96.0, confidence=0.5)
    high = dict(_SCALE, confidence=0.98)
    tie = dict(_SCALE, factor=24.0, confidence=0.98)
    assert most_confident_scale([None, "bad", low, high, tie]) == high
    assert most_confident_scale([None, {"confidence": 0}]) is None


def test_best_resolved_scale_matches_the_report_rule():
    from pdfcadcore.primitives import ResolvedScale

    def page(rs):
        return SimpleNamespace(page_data=SimpleNamespace(resolved_scale=rs))

    pages = [
        page(None),
        page(ResolvedScale(factor=96.0, notation="1/8", source="page_text", confidence=0.6)),
        page(ResolvedScale(factor=48.0, notation="1/4", source="titleblock", confidence=0.98)),
        page(ResolvedScale(factor=1.0, notation="1:1", source="default", confidence=0.0)),
    ]
    assert best_resolved_scale(pages) == {
        "factor": 48.0, "notation": "1/4", "source": "titleblock",
        "confidence": 0.98, "fallback_reason": "",
    }
