""""Editable text (LibreCAD font)": words you can click and edit in LibreCAD.

The default ("Exact look") draws every word as exact outlines and keeps an
editable copy on the hidden layer P###_TEXT_SEARCH. The Editable text choice
delivers each visible word as native TEXT in LibreCAD's own font instead: the
letter shapes differ from the PDF, that substitution is disclosed per item and
never certified as the look, and a character LibreCAD's font lacks still steps
down to outlines for that item only.

Uses conftest's CI-only LibreCAD unicode.lff (printable ASCII, no emoji).
Fictional drawing data only (D042 / EX101, MXT-100).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import ezdxf
import pymupdf
import pytest

import dxf_import_engine
from dxf_import_engine import _resume_options_identity
from librecad_pdf_importer.launchers.librecad_launcher import find_librecad_executable
from pdfcadcore.import_config import ImportConfig

LINES = ("D042 EX101 PLATE", "MXT-100 GP 2 REQD")


def _two_line_pdf(path: Path, lines=LINES) -> Path:
    document = pymupdf.open()
    page = document.new_page(width=612, height=396)
    for index, line in enumerate(lines):
        page.insert_text((72, 90 + 40 * index), line, fontname="helv", fontsize=12)
    document.save(str(path))
    document.close()
    return path


def _convert(tmp_path: Path, name: str, *, editable: bool, lines=LINES,
             resumable: bool = False, text_mode: str = "text"):
    folder = tmp_path / name
    folder.mkdir()
    source = _two_line_pdf(folder / "two_lines.pdf", lines)
    output = folder / "two_lines.dxf"
    config = ImportConfig.auto()
    config.import_text = True
    config.text_mode = text_mode
    kwargs = {}
    if resumable:
        # Exactly as the importer window calls the engine (gui.py worker).
        kwargs = dict(
            resumable=True,
            cancel_requested=lambda: False,
            restart_on_resume_mismatch=True,
            librecad_executable=find_librecad_executable() or "",
        )
    stats = dxf_import_engine.convert(
        str(source),
        str(output),
        config=config,
        dxf_version="R2010",
        editable_text=editable,
        **kwargs,
    )
    report_path = Path(stats["import_report_path"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if resumable:
        report = json.loads(
            Path(report["page_reports"][0]).read_text(encoding="utf-8")
        )
    return stats, ezdxf.readfile(output), report, output


def _items(report):
    return report["extra"]["text_representation_delivery"]["items"]


def _on(layer_name: str, base: str) -> bool:
    """The assembled window-path file prefixes each page's layers."""

    return layer_name == base or layer_name.endswith(f"${base}")


def _entity_signature(doc) -> str:
    """Handle-free hash of what is drawn: type, layer, colour and geometry."""

    rows = []
    for entity in doc.modelspace():
        row = [entity.dxftype(), entity.dxf.layer]
        if entity.dxftype() == "TEXT":
            row += [entity.dxf.text, round(entity.dxf.height, 6), entity.dxf.style]
            row += [round(value, 6) for value in entity.dxf.insert]
        elif entity.dxftype() == "INSERT":
            row += [round(value, 6) for value in entity.dxf.insert]
            block = doc.blocks.get(entity.dxf.name)
            row += [len(block), sorted(child.dxftype() for child in block)[:3]]
        rows.append(repr(row))
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


@pytest.mark.parametrize("resumable", [False, True], ids=["one-shot", "window-path"])
def test_editable_text_gives_visible_editable_text_in_librecads_font(tmp_path, resumable):
    stats, doc, report, _ = _convert(
        tmp_path, "editable", editable=True, resumable=resumable
    )
    msp = doc.modelspace()

    visible_text = [
        e for e in msp if e.dxftype() == "TEXT" and _on(e.dxf.layer, "P001_TEXT")
    ]
    assert sorted(e.dxf.text for e in visible_text) == sorted(LINES)
    for entity in visible_text:
        assert doc.styles.get(entity.dxf.style).dxf.font == "unicode"
        layer = doc.layers.get(entity.dxf.layer)
        assert not layer.is_frozen() and layer.is_on()
        assert layer.dxf.plot == 1
    # Nothing drawn twice: no outline blocks, no pictures, no hidden copies.
    assert not [e for e in msp if e.dxftype() == "INSERT"]
    assert not [e for e in msp if e.dxftype() == "IMAGE"]
    assert not [l for l in doc.layers if _on(l.dxf.name, "P001_TEXT_SEARCH")]

    items = _items(report)
    assert len(items) == 2
    for item in items:
        assert item["final_representation"] == "text"
        assert item["verified"] is True
        assert not item.get("degraded")
        final = item["attempts"][-1]
        assert final["outcome"] == "verified"
        assert final["evidence"]["parent_native_font_substitution_accepted"] is True
        # The look is disclosed as LibreCAD's font, never certified as the PDF's.
        assert final["visual_verified"] is False
        assert final["evidence"]["parent_visual_fidelity_verified"] is False
    assert report["extra"]["text_items_degraded_total"] == 0
    assert report["extra"]["editable_text"]["chosen"] is True
    assert report["extra"]["editable_text"]["item_count"] == 2

    delivery = stats["text_delivery"]
    assert delivery["delivered"] == "text"
    assert delivery["degraded_item_count"] == 0
    assert delivery["editable_text_item_count"] == 2


def test_exact_look_default_is_unchanged(tmp_path):
    _, glyph_doc, _, _ = _convert(tmp_path, "glyphs", editable=False, text_mode="glyphs")
    _, default_doc, report, _ = _convert(tmp_path, "default", editable=False)
    msp = default_doc.modelspace()

    # Outlines on the visible layer, the editable copy frozen on the search layer.
    assert len([e for e in msp if e.dxftype() == "INSERT"]) == 2
    assert not [e for e in msp if e.dxftype() == "TEXT" and e.dxf.layer == "P001_TEXT"]
    search = [e for e in msp if e.dxftype() == "TEXT" and e.dxf.layer == "P001_TEXT_SEARCH"]
    assert sorted(e.dxf.text for e in search) == sorted(LINES)
    assert default_doc.layers.get("P001_TEXT_SEARCH").is_frozen()
    assert _entity_signature(default_doc) == _entity_signature(glyph_doc)
    assert all(item["final_representation"] == "glyphs" for item in _items(report))
    assert report["extra"].get("editable_text", {}).get("chosen", False) is False


def test_a_character_librecads_font_lacks_steps_down_for_that_item_only(tmp_path):
    # The CI unicode.lff has printable ASCII only, so the degree sign is missing.
    lines = ("D042 EX101 PLATE", "MXT-100 BEND 45°")
    stats, doc, report, _ = _convert(tmp_path, "missing", editable=True, lines=lines)
    finals = sorted(item["final_representation"] for item in _items(report))
    assert finals == ["glyphs", "text"]
    msp = doc.modelspace()
    visible = [e.dxf.text for e in msp if e.dxftype() == "TEXT" and e.dxf.layer == "P001_TEXT"]
    assert visible == [lines[0]]
    assert len([e for e in msp if e.dxftype() == "INSERT"]) == 1
    stepped = next(i for i in _items(report) if i["final_representation"] == "glyphs")
    assert stepped["fallback_used"] is True
    assert "unicode.lff" in stepped["attempts"][0]["reason"]
    assert report["extra"]["text_items_degraded_total"] == 0
    assert stats["text_delivery"]["editable_text_item_count"] == 1


def test_a_page_made_under_one_choice_is_never_resumed_under_the_other():
    config = ImportConfig.auto()
    exact, _ = _resume_options_identity(config, "R2010", None, True, False)
    editable, payload = _resume_options_identity(config, "R2010", None, True, True)
    assert exact != editable
    assert payload["editable_text"] is True


def test_command_line_offers_the_same_choice_and_says_what_it_delivered(
    tmp_path, capsys
):
    import pdf2dxf

    source = _two_line_pdf(tmp_path / "two_lines.pdf")
    editable_out = tmp_path / "editable.dxf"
    assert pdf2dxf.main([str(source), str(editable_out), "--editable-text"]) == 0
    printed = capsys.readouterr().out
    assert "Text delivery: requested=text; delivered=text; fallback=no" in printed
    assert "Editable text:   2 of 2 text item(s) in LibreCAD's font" in printed
    assert "Editable copies" not in printed
    msp = ezdxf.readfile(editable_out).modelspace()
    assert len([e for e in msp if e.dxftype() == "TEXT" and e.dxf.layer == "P001_TEXT"]) == 2

    exact_out = tmp_path / "exact.dxf"
    assert pdf2dxf.main([str(source), str(exact_out)]) == 0
    printed = capsys.readouterr().out
    assert "Text delivery: requested=text; delivered=glyphs; fallback=yes" in printed
    assert "Editable copies: hidden layer P###_TEXT_SEARCH (thaw it to edit)" in printed
    assert "Editable text:" not in printed
    # Far smaller: no outline blocks for the editable words.
    assert editable_out.stat().st_size < exact_out.stat().st_size / 2

    assert pdf2dxf.main(
        [str(source), str(tmp_path / "x.dxf"), "--editable-text", "--text-mode", "glyphs"]
    ) == 2
    assert "--editable-text works with --text-mode text" in capsys.readouterr().err
