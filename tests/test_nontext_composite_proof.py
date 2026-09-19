from __future__ import annotations

import copy
import hashlib
import re

import fitz
import pytest

from librecad_pdf_importer.core import nontext_composite as proof
from librecad_pdf_importer.core.stroke_footprint import bind_similarity_strokes, unclipped_capsules


SHA = "a" * 64


def sample(*, text=False, image=False, stroke_only=False):
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    page.draw_line((20, 0), (90, 70), color=(.2, .2, .2), width=1)
    if text:
        page.insert_text((56, 44), "X", fontsize=8)
    if image:
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 2, 2), False)
        pix.clear_with(128)
        page.insert_image(fitz.Rect(59, 39, 61, 41), pixmap=pix)
    resources = int(doc.xref_get_key(page.xref, "Resources")[1].split()[0])
    doc.xref_set_key(resources, "ExtGState", "<< /Mul << /Type /ExtGState /BM /Multiply /CA 1 /ca 1 >> >>")
    raw = page.read_contents() + (b"\nq " if stroke_only else b"\nq /Mul gs ") + b"1 .5 .25 RG 12 w 1 J 60 60 m 60.01 60 l S Q\n"
    xref = doc.get_new_xref(); doc.update_object(xref, "<<>>"); doc.update_stream(xref, raw); page.set_contents(xref)
    return doc, page


def originals(page):
    rows = page.get_drawings(extended=True)
    return bind_similarity_strokes(unclipped_capsules(rows, tuple(page.rect)), rows,
                                   page.get_svg_image(text_as_path=True))


def recipes(page):
    return proof.qualify_recipes(page, originals(page), source_sha256=SHA, page_number=1)


def many_capsules(width, count):
    doc = fitz.open()
    page = doc.new_page(width=10000, height=10000)
    page.draw_line((0, 0), (1, 1))
    resources = int(doc.xref_get_key(page.xref, "Resources")[1].split()[0])
    doc.xref_set_key(resources, "ExtGState", "<< /Mul << /BM /Multiply /CA 1 /ca 1 >> >>")
    raw = b"\n".join((f"q /Mul gs 1 .5 .25 RG {width} w 1 J {5000+i} 5000 m {5000.01+i} 5000 l S Q").encode() for i in range(count))
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, raw)
    page.set_contents(xref)
    return doc, page


def test_giant_exact_dpi_patch_is_unqualified_before_any_pixel_allocation():
    doc, page = many_capsules(5000, 1)
    assert len(originals(page)) == 1
    assert recipes(page) == []
    doc.close()


def test_many_overlapping_patches_exceeding_page_budget_are_not_partially_rendered():
    doc, page = many_capsules(200, 12)
    assert len(originals(page)) == 12
    assert recipes(page) == []
    doc.close()


def test_render_rechecks_exact_pixel_budget_before_source_or_displaylist_access():
    doc, page = sample()
    recipe = recipes(page)[0]
    recipe["device_bounds"] = [0, 0, 50000, 50000]
    with pytest.raises(ValueError, match="pixel budget"):
        proof.render_recipes(None, [recipe], fitz)
    doc.close()


def test_saved_reopened_normal_group_retains_explicit_opacity_knockout_and_final_pixels():
    doc, _ = sample()
    reopened = fitz.open(stream=doc.tobytes(), filetype="pdf")
    page = reopened[0]
    rows = recipes(page)
    assert len(rows) == 1
    assert [g["blendmode"] for g in rows[0]["source_groups"]] == ["Normal", "Multiply"]
    assert all(g["opacity"] == 1 and not g["knockout"] for g in rows[0]["source_groups"])
    png, _ = proof.render_recipes(page, rows, fitz)[0]
    direct = page.get_pixmap(matrix=fitz.Matrix(600/72, 600/72),
                            clip=fitz.Rect(rows[0]["coverage_bounds_pdf"]), alpha=False)
    assert fitz.Pixmap(png).samples == direct.samples
    reopened.close()
    doc.close()


def test_saved_reopened_knockout_normal_group_is_unqualified():
    doc, page = sample()
    doc.xref_set_key(page.xref, "Group", "<< /S /Transparency /CS /DeviceRGB /I true /K true >>")
    reopened = fitz.open(stream=doc.tobytes(), filetype="pdf")
    page = reopened[0]
    assert reopened.xref_get_key(page.xref, "Group/K") == ("bool", "true")
    assert recipes(page) == []
    reopened.close()
    doc.close()


def test_original_gray_underpaint_uses_final_source_rgb_pixels_and_global_lattice():
    doc, page = sample()
    rows = recipes(page)
    assert len(rows) == 1
    recipe = rows[0]
    encoded, evidence = proof.render_recipe(page, recipe, fitz)
    actual = fitz.Pixmap(encoded)
    original = page.get_pixmap(matrix=fitz.Matrix(recipe["dpi"]/72, recipe["dpi"]/72),
                               clip=fitz.Rect(recipe["coverage_bounds_pdf"]), alpha=False)
    assert actual.samples == original.samples
    assert evidence["rgb_sha256"] == hashlib.sha256(original.samples).hexdigest()
    assert evidence["device_bounds"] == [original.x, original.y, original.x+original.width, original.y+original.height]
    assert recipe["coverage_bounds_pdf"][0] <= recipe["source_ink_bounds_pdf"][0]
    assert recipe["coverage_bounds_pdf"][2] >= recipe["source_ink_bounds_pdf"][2]
    assert any(r[0] < recipe["source_paint_order"] for r in recipe["overlapping_source_paints"])
    doc.close()


@pytest.mark.parametrize("option", ["text", "image"])
def test_no_borrowed_source_text_or_images(option):
    doc, page = sample(**{option: True})
    assert recipes(page) == []
    doc.close()


def test_normal_stroke_keeps_direct_geometry_not_composite():
    doc, page = sample(stroke_only=True)
    assert recipes(page) == []
    doc.close()


def test_no_source_proof_borrowing_or_changed_clip_proof():
    doc, page = sample()
    source = originals(page)
    seq = next(iter(source)); changed = copy.deepcopy(source)
    changed[seq]["source_svg_stroke"]["width"] += 1
    assert proof.qualify_recipes(page, changed, source_sha256=SHA, page_number=1) == []
    doc.close()


@pytest.mark.parametrize("field,value", [("opacity", .5), ("text_and_image_free", False),
                                        ("device_bounds", [0, 0, 10, 10]), ("dpi", 300),
                                        ("later_source_paints", [100]), ("coverage_bounds_pdf", [0, 0, 10, 10])])
def test_render_rejects_tampered_recipe(field, value):
    doc, page = sample(); row = recipes(page)[0]; row[field] = value
    with pytest.raises(ValueError):
        proof.render_recipe(page, row, fitz)
    doc.close()


def test_later_text_added_after_planning_invalidates_recipe():
    doc, page = sample(); row = recipes(page)[0]
    page.insert_text((56, 44), "X", fontsize=8)
    with pytest.raises(ValueError):
        proof.render_recipe(page, row, fitz)
    doc.close()


def test_later_vector_paint_is_explicitly_captured_as_original_final_page():
    doc, page = sample()
    page.draw_line((56, 36), (64, 44), color=(.5, .5, .5), width=.5)
    row = recipes(page)[0]
    assert row["later_source_paints"]
    encoded, _ = proof.render_recipe(page, row, fitz)
    assert encoded.startswith(b"\x89PNG")
    doc.close()


def test_rotation_is_explicitly_outside_bounded_recipe():
    doc, page = sample(); page.set_rotation(90)
    assert recipes(page) == []
    doc.close()


def test_pixel_rounding_margin_cannot_borrow_text_outside_capsule_box():
    doc, page = sample(); row = recipes(page)[0]
    x = (row["coverage_bounds_pdf"][0] + row["source_ink_bounds_pdf"][0]) / 2
    y = row["source_ink_bounds_pdf"][1]+1

    class Page:
        def __getattr__(self, key):
            return getattr(page, key)

        def get_bboxlog(self):
            return page.get_bboxlog()+[("fill-text", (x, y, x, y))]

    assert proof.qualify_recipes(Page(), originals(page), source_sha256=SHA, page_number=1) == []
    doc.close()


def test_batch_rejects_duplicates_and_mixed_identity():
    doc, page = sample(); row = recipes(page)[0]
    with pytest.raises(ValueError, match="Duplicate"):
        proof.render_recipes(page, [row, row], fitz)
    doc.close()


def test_same_bbox_source_recolor_during_render_is_detected():
    doc, page = sample(); row = recipes(page)[0]

    class Page:
        def __getattr__(self, key):
            return getattr(page, key)

        def get_displaylist(self, **options):
            display = page.get_displaylist(**options)

            class Display:
                def get_pixmap(self, **kwargs):
                    pix = display.get_pixmap(**kwargs)
                    raw = page.read_contents()
                    changed = re.sub(rb"(?<!\d)0?\.2 0?\.2 0?\.2 RG", b"0.8 0.8 0.8 RG", raw)
                    assert changed != raw
                    doc.update_stream(page.get_contents()[0], changed)
                    return pix

            return Display()

    with pytest.raises(ValueError, match="changed while rendering"):
        proof.render_recipes(Page(), [row], fitz)
    doc.close()


def test_two_patch_batch_reuses_one_displaylist_and_matches_direct_source(monkeypatch):
    doc, page = sample()
    raw = page.read_contents()+b"\nq /Mul gs 1 .5 .25 RG 12 w 1 J 30 20 m 30.01 20 l S Q\n"
    doc.update_stream(page.get_contents()[0], raw)
    rows = recipes(page)
    assert len(rows) == 2
    calls = []

    class Page:
        def __getattr__(self, key):
            return getattr(page, key)

        def get_displaylist(self, **kwargs):
            calls.append(kwargs)
            return page.get_displaylist(**kwargs)

    results = proof.render_recipes(Page(), rows, fitz)
    assert calls == [{"annots": True}]
    for row, (encoded, evidence) in zip(rows, results, strict=True):
        direct = page.get_pixmap(matrix=fitz.Matrix(row["dpi"]/72, row["dpi"]/72),
                                 clip=fitz.Rect(row["coverage_bounds_pdf"]), alpha=False)
        assert fitz.Pixmap(encoded).samples == direct.samples
        assert evidence["device_bounds"] == [direct.x, direct.y, direct.x+direct.width, direct.y+direct.height]
    doc.close()
