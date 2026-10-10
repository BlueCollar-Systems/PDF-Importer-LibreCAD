"""DXF R12 never loses the whole drawing because of a picture.

R12 has no IMAGE entity. A PDF with a picture used to stop the export with
"IMAGE requires DXF R2000" and no DXF at all. Now the picture steps down: a
closed outline of where it sat goes on layer P###_PICTURES_OMITTED_R12, the
lines and text are delivered as usual, and the step-down is said once (log,
stderr, report).

Every fixture is synthetic and generated here (fictional job D042, mark EX101).
"""
from __future__ import annotations

import json
from pathlib import Path

import ezdxf
import pymupdf
import pytest

import dxf_import_engine
from pdfcadcore.import_config import ImportConfig

MM = 25.4 / 72.0
PICTURE_RECT = (100.0, 100.0, 300.0, 250.0)  # PDF points, y down


def _picture_pdf(path: Path) -> Path:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 32, 32), False)
    pixmap.clear_with(200)
    for x in range(32):
        pixmap.set_pixel(x, x, (200, 30, 30))
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_image(pymupdf.Rect(*PICTURE_RECT), stream=pixmap.tobytes("png"))
    page.draw_line((72, 400), (540, 400), color=(0, 0, 0), width=1)
    page.insert_text((72, 450), "D042 EX101", fontname="helv", fontsize=12)
    document.save(str(path))
    document.close()
    return path


def _convert(tmp_path: Path, name: str, *, dxf_version: str, resumable: bool = False,
             text_mode: str = "text"):
    folder = tmp_path / name
    folder.mkdir()
    source = _picture_pdf(folder / "picture.pdf")
    output = folder / "picture.dxf"
    config = ImportConfig.auto()
    config.text_mode = text_mode
    kwargs = {}
    if resumable:
        kwargs = dict(
            resumable=True,
            cancel_requested=lambda: False,
            restart_on_resume_mismatch=True,
            librecad_executable="",
        )
    stats = dxf_import_engine.convert(
        str(source), str(output), config=config, dxf_version=dxf_version, **kwargs
    )
    assert output.is_file()
    report = json.loads(Path(stats["import_report_path"]).read_text(encoding="utf-8"))
    page_report = report
    if resumable:
        page_report = json.loads(
            Path(report["page_reports"][0]).read_text(encoding="utf-8")
        )
    return stats, ezdxf.readfile(output), report, page_report


def _omitted_layer(name: str) -> bool:
    return name.endswith("P001_PICTURES_OMITTED_R12")


@pytest.mark.parametrize("resumable", [False, True], ids=["one-shot", "window-path"])
def test_r12_steps_a_picture_down_to_its_outline_and_says_so(tmp_path, resumable):
    stats, doc, report, page_report = _convert(
        tmp_path, "r12", dxf_version="R12", resumable=resumable
    )
    assert doc.dxfversion == "AC1009"
    msp = doc.modelspace()
    assert not [e for e in msp if e.dxftype() == "IMAGE"]
    outlines = [e for e in msp if _omitted_layer(e.dxf.layer)]
    assert len(outlines) == 1
    outline = outlines[0]
    assert outline.dxftype() == "POLYLINE" and outline.is_closed
    xs = [v.dxf.location.x for v in outline.vertices]
    ys = [v.dxf.location.y for v in outline.vertices]
    assert min(xs) == pytest.approx(PICTURE_RECT[0] * MM, abs=0.05)
    assert max(xs) == pytest.approx(PICTURE_RECT[2] * MM, abs=0.05)
    # PDF y runs down; the sheet's y runs up from the bottom edge.
    assert min(ys) == pytest.approx((792 - PICTURE_RECT[3]) * MM, abs=0.05)
    assert max(ys) == pytest.approx((792 - PICTURE_RECT[1]) * MM, abs=0.05)
    # The rest of the sheet still came in.
    assert [e for e in msp if e.dxftype() in {"LINE", "POLYLINE"} and not _omitted_layer(e.dxf.layer)]

    warning = stats["r12_picture_warning"]
    assert warning.startswith("DXF R12 cannot hold pictures: 1 picture(s) left out")
    assert "P###_PICTURES_OMITTED_R12" in warning
    assert "or newer to keep them" in warning
    # No picture file was written for a drawing that cannot reference one.
    assert not list((tmp_path / "r12").rglob("*.png"))

    rows = page_report["extra"]["pictures_omitted_r12"]
    assert rows == [
        {"source_page_number": 1, "pictures": 1, "layer": "P001_PICTURES_OMITTED_R12"}
    ]
    assert page_report["fallback"]["used"] is True
    assert "pictures_omitted_r12" in page_report["fallback"]["reason"]
    assert "pictures omitted r12" in page_report["extra"]["human_summary"]
    if resumable:
        assert report["pictures_omitted_r12"]["pictures"] == 1
        assert report["warnings"] >= 1


def test_r12_requested_raster_text_steps_down_and_is_reported(tmp_path):
    stats, doc, _report, page_report = _convert(
        tmp_path, "r12_raster", dxf_version="R12", text_mode="raster"
    )
    msp = doc.modelspace()
    assert not [e for e in msp if e.dxftype() == "IMAGE"]
    degraded = stats["text_delivery"]["degraded_items"]
    assert stats["text_delivery"]["degraded_item_count"] == 1
    assert degraded[0]["text"] == "D042 EX101"
    assert "DXF R12 cannot hold pictures" in degraded[0]["reason"]
    # Still on the sheet as visible text, never silently lost.
    assert degraded[0]["delivered"] == "text"
    assert [e for e in msp if e.dxftype() == "TEXT" and e.dxf.text == "D042 EX101"]
    assert page_report["extra"]["text_items_degraded_total"] == 1


def test_r2010_still_keeps_the_picture(tmp_path):
    stats, doc, _report, page_report = _convert(tmp_path, "r2010", dxf_version="R2010")
    msp = doc.modelspace()
    assert len([e for e in msp if e.dxftype() == "IMAGE"]) == 1
    assert not [e for e in msp if _omitted_layer(e.dxf.layer)]
    assert stats["r12_picture_warning"] == ""
    assert "pictures_omitted_r12" not in page_report["extra"]


def test_command_line_writes_the_r12_file_and_says_what_was_left_out(tmp_path, capsys):
    import pdf2dxf

    source = _picture_pdf(tmp_path / "picture.pdf")
    output = tmp_path / "picture_r12.dxf"
    assert pdf2dxf.main([str(source), str(output), "--dxf-version", "R12"]) == 0
    assert output.is_file()
    err = capsys.readouterr().err
    assert "DXF R12 cannot hold pictures: 1 picture(s) left out" in err


def test_window_log_and_done_dialog_name_the_left_out_pictures(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock, patch

    pytest.importorskip("tkinter")
    import gui

    warning = (
        "DXF R12 cannot hold pictures: 2 picture(s) left out; their outlines are on "
        "layer P###_PICTURES_OMITTED_R12. Choose R2010 (the default) or newer to keep them."
    )
    log = []
    app = SimpleNamespace(
        _log=log.append, after=lambda _ms, callback: callback(),
        _cancel_event=gui.threading.Event(), _finish_conversion=Mock(), _handoff_path=None,
    )
    options = gui.ConversionOptions(
        scale=1.0, import_text=True, text_mode="text", pages=None,
        dxf_version="R12", launch_librecad=False,
    )
    with patch(
        "dxf_import_engine.convert", return_value={"r12_picture_warning": warning}
    ), patch("pdf_open_guard.precheck_pdf"), patch(
        "librecad_pdf_importer.launchers.librecad_launcher.find_librecad_executable",
        return_value=None,
    ), patch.object(gui.messagebox, "showinfo") as done, patch.object(
        gui.messagebox, "showerror",
    ) as error:
        gui.Pdf2DxfApp._run_conversion(
            app, str(tmp_path / "a.pdf"), str(tmp_path / "a.dxf"), options
        )
    error.assert_not_called()
    assert warning in log
    assert warning in done.call_args.args[1]
