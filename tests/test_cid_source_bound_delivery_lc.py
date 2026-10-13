"""Real source-CFF text survives the CLI and serialized editable DXF output."""
from hashlib import sha256
from io import BytesIO
import json

import ezdxf
from fontTools.cffLib import CFFFontSet
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont
import pymupdf as fitz
import pytest

from pdf2dxf import main
from pdfcadcore.primitive_extractor import extract_page


@pytest.mark.parametrize("requested", [None, "glyphs", "geometry"])
def test_public_cid_label_delivers_editable_source_glyphs_after_serialized_readback(tmp_path, requested):
    source = tmp_path / "public-cid-label.pdf"
    with fitz.open() as document:
        page = document.new_page(width=240, height=160)
        page.insert_font(fontname="SyntheticControlFont", fontbuffer=fitz.Font("helv").buffer)
        page.insert_text((15, 130), "BLENDER CONTROL", fontname="SyntheticControlFont", fontsize=10)
        page.draw_rect(fitz.Rect(20, 20, 100, 60), color=(0, 0, 0), fill=(0.8, 0.9, 1))
        record = page.get_fonts(full=True)[0]
        original = document.extract_font(record[0])[3]
        digest = sha256(original).hexdigest()
        item = extract_page(page, 1).text_items[0]
        asset = item.font_asset
        assert item.font_failure is None
        assert asset.source_bytes == original and asset.source_sha256 == digest
        assert asset.source_format == "cff" and asset.source_inventory_format == "cid"
        assert asset.source_inventory_type == "Type0"
        cff = CFFFontSet()
        cff.decompile(BytesIO(original), None, isCFF2=False)
        top = cff.topDictIndex[0]
        with TTFont(BytesIO(asset.usable_bytes), lazy=False) as font:
            assert font.getGlyphOrder() == list(top.charset)
            for char in item.source_char_layout:
                assert char.source_font_binding_verified and char.source_font_program_sha256 == digest
                glyph = font.getBestCmap()[ord(char.text)]
                assert font.getGlyphID(glyph) == char.glyph_id
                original_pen = RecordingPen()
                top.CharStrings[glyph].draw(original_pen)
                usable_pen = RecordingPen()
                font.getGlyphSet()[glyph].draw(usable_pen)
                assert usable_pen.value == original_pen.value
        document.save(source)
    output = tmp_path / ((requested or "default") + ".dxf")
    args = [str(source), str(output), "--mode", "vector"]
    if requested is not None:
        args += ["--text-mode", requested]
    assert main(args) == 0
    report = json.loads(output.with_name(output.stem + "_import_report.json").read_text())
    delivery = report["extra"]["text_representation_delivery"]
    assert delivery["verified"] is True
    assert len(delivery["items"]) == 1
    delivered = delivery["items"][0]
    assert delivered["verified"] is True
    assert delivered["final_representation"] == ("geometry" if requested == "geometry" else "glyphs")
    assert delivered["entity_handles"]
    drawing = ezdxf.readfile(output)
    for handle in delivered["entity_handles"]:
        owner = drawing.entitydb[handle]
        assert owner.dxftype() != "IMAGE"
        if owner.dxftype() == "INSERT":
            assert list(owner.virtual_entities())
    assert not list(drawing.modelspace().query("IMAGE"))
    assert report["extra"]["text_items_degraded_total"] == 0
