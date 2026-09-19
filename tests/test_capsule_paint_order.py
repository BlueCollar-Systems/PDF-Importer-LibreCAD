"""Exact cap events must not cross source text or image paints in saved DXF."""
from copy import deepcopy
from types import SimpleNamespace

import ezdxf
import pymupdf
import pytest

from librecad_pdf_importer.core.document import ExtractionOptions, extract_document
from librecad_pdf_importer.core.image_paint_order import bind_image_paint_order
from librecad_pdf_importer.exporters.dxf_exporter import DxfExportOptions, export_to_dxf


def capsule_page(cap_box=(0, 0, 10, 10)):
    paints = [("fill-text", (1, 1, 4, 4)), ("stroke-path", cap_box),
              ("fill-text", (5, 1, 9, 4))]
    trace = [{"seqno": 0, "chars": [(65, 1, (1, 4), ())]},
             {"seqno": 2, "chars": [(66, 2, (5, 4), ())]}]
    chars = [SimpleNamespace(text="A", source_origin_pdf=(1, 4)),
             SimpleNamespace(text="B", source_origin_pdf=(5, 4))]
    data = SimpleNamespace(primitives=[SimpleNamespace(id=1, source_draw_order=1)],
                           text_items=[SimpleNamespace(id=2, text="A", source_char_layout=[chars[0]]),
                                       SimpleNamespace(id=3, text="B", source_char_layout=[chars[1]])])
    page = SimpleNamespace(get_bboxlog=lambda: paints, get_texttrace=lambda: trace,
                           get_image_info=lambda **kw: [])
    return page, data, paints, trace


def group_text(data):
    data.text_items[0].text = "AB"
    data.text_items[0].source_char_layout += data.text_items.pop().source_char_layout


def test_no_images_capsule_orders_both_text_sides_and_keeps_exact_stroke_key():
    page, data, *_ = capsule_page()
    order = bind_image_paint_order(page, data, [], extra_paint_seqnos=[1])
    assert order.image_seqnos == ()
    assert order.extra_paint_seqnos == order.paint_seqnos == (1,)
    assert order.primitive_keys == {1: 1}
    assert order.text_keys == {2: 0, 3: 2}
    assert bind_image_paint_order(page, data, []) is None


@pytest.mark.parametrize("seqnos", [(1, 1), (-1,), (3,), (True,), (1.0,), (0,)])
def test_invalid_duplicate_and_nonstroke_barriers_reject(seqnos):
    page, data, *_ = capsule_page()
    with pytest.raises(ValueError, match="capsule paint sequence"):
        bind_image_paint_order(page, data, [], extra_paint_seqnos=seqnos)


@pytest.mark.parametrize("duplicate", [False, True])
def test_extra_barrier_requires_one_delivered_source_primitive(duplicate):
    page, data, *_ = capsule_page()
    data.primitives = data.primitives * 2 if duplicate else []
    with pytest.raises(ValueError, match="no unique source primitive"):
        bind_image_paint_order(page, data, [], extra_paint_seqnos=[1])


def test_group_crossing_relevant_cap_has_no_false_whole_item_order():
    page, data, *_ = capsule_page()
    group_text(data)
    with pytest.raises(ValueError, match="item 2 crosses an overlapping capsule"):
        bind_image_paint_order(page, data, [], extra_paint_seqnos=[1])


@pytest.mark.parametrize("cap_box,expected", [((50, 50, 60, 60), 2),
                                              ((0, 0, 4, 4), 0),
                                              ((5, 0, 10, 4), 2)])
def test_group_across_cap_uses_only_intersecting_source_paint_bounds(cap_box, expected):
    page, data, *_ = capsule_page(cap_box)
    group_text(data)
    assert bind_image_paint_order(page, data, [], extra_paint_seqnos=[1]).text_keys == {2: expected}


def test_repeated_character_on_both_sides_of_overlapping_cap_rejects():
    page, data, _paints, trace = capsule_page()
    trace[1]["chars"] = deepcopy(trace[0]["chars"])
    data.text_items = data.text_items[:1]
    with pytest.raises(ValueError, match="overlapping capsule"):
        bind_image_paint_order(page, data, [], extra_paint_seqnos=[1])


def test_image_collision_and_interleaved_keys_preserve_original_image_contract():
    page, data, paints, _trace = capsule_page()
    image_box = (0, 0, 10, 10)
    info = dict(xref=4, number=3, bbox=image_box, width=2, height=2,
                transform=(10, 0, 0, 10, 0, 0))
    image = SimpleNamespace(xref=4, source_kind="xobject_image", alpha_kind="opaque",
                             source_bbox_pdf=image_box, pixel_size=(2, 2), affine_pdf=info["transform"])
    paints.append(("fill-image", image_box))
    page.get_image_info = lambda **kw: [info]
    with pytest.raises(ValueError, match="collides with an image"):
        bind_image_paint_order(page, data, [image], extra_paint_seqnos=[3])
    old = bind_image_paint_order(page, data, [image])
    added = bind_image_paint_order(page, data, [image], extra_paint_seqnos=[1])
    assert old.image_keys == {0: 1} and old.text_keys == {2: 0, 3: 0}
    assert added.paint_seqnos == (1, 3) and added.image_keys == {0: 3}
    assert added.primitive_keys == {1: 1} and added.text_keys == {2: 0, 3: 2}


@pytest.mark.parametrize("rotation", [0, 90])
def test_actual_normal_cap_text_sides_survive_dxf_entity_and_redraw_order(tmp_path, rotation):
    source = tmp_path / "normal-cap-order.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=200, height=120)
        page.insert_text((26, 35), "H", fontsize=10)
        page.draw_line((30, 40), (30.01, 40), width=30, lineCap=1, color=(1, .5, .25))
        page.insert_text((26, 53), "X", fontsize=10)
        page.set_rotation(rotation)
        doc.save(source)
    with extract_document(str(source), ExtractionOptions(import_mode="vector", detect_arcs=False)) as extraction:
        extracted = extraction.pages[0]
        assert len(extracted.source_capsules) == 1
        with pymupdf.open(source) as doc:
            extracted.image_paint_order = bind_image_paint_order(
                doc[0], extracted.page_data, [],
                extra_paint_seqnos=[extracted.source_capsules[0]["source_seqno"]])
        result = export_to_dxf(extraction, str(tmp_path / "ordered.dxf"), DxfExportOptions())
        assert [item["final_representation"] for item in result.text_deliveries] == ["glyphs", "glyphs"]
    saved = ezdxf.readfile(result.output_path)
    entities = list(saved.modelspace())
    assert [entity.dxftype() for entity in entities] == ["INSERT", "HATCH", "LINE", "INSERT"]
    assert entities[1].has_xdata("BCS_SOURCE_STROKE_INK")
    assert list(saved.modelspace().get_redraw_order()) == [
        (entity.dxf.handle, f"{index:X}") for index, entity in enumerate(entities, 1)]
