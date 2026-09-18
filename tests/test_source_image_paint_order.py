from copy import deepcopy
from types import SimpleNamespace

import ezdxf
import pymupdf as fitz
import pytest

from librecad_pdf_importer.core.document import ExtractionOptions, extract_document
from librecad_pdf_importer.core.image_paint_order import (
    apply_image_paint_order, bind_image_paint_order, verify_serialized_image_paint_order,
)
from librecad_pdf_importer.exporters.dxf_exporter import DxfExportOptions, export_to_dxf


def make_source(tmp_path, rotation=0):
    source = tmp_path / f"interleaved-{rotation}.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=150)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 3, 2), False)
    pix.clear_with(255)
    pix.set_pixel(0, 0, (255, 0, 0))
    page.insert_text((30, 40), "BEFORE")
    page.draw_line((20, 35), (130, 35))
    xref = page.insert_image(fitz.Rect(20, 20, 140, 100), stream=pix.tobytes("png"))
    page.insert_text((30, 60), "MIDDLE")
    page.draw_line((20, 55), (130, 55))
    page.insert_image(fitz.Rect(20, 20, 140, 100), xref=xref)
    page.insert_text((30, 80), "AFTER")
    page.draw_line((20, 75), (130, 75))
    page.set_rotation(rotation)
    doc.save(source)
    doc.close()
    return source


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_real_repeated_images_bind_interleaved_text_and_lines(tmp_path, rotation):
    with extract_document(str(make_source(tmp_path, rotation)), ExtractionOptions(
        pages="1", import_mode="vector", detect_arcs=False,
    )) as extraction:
        page = extraction.pages[0]
        order = page.image_paint_order
        assert len(order.image_keys) == 2
        assert list(order.image_keys.values()) == [1, 3]
        assert {item.text: order.text_keys[item.id] for item in page.page_data.text_items} == {
            "BEFORE": 0, "MIDDLE": 2, "AFTER": 4,
        }
        assert sorted(order.primitive_keys.values()) == [0, 2, 4]


def test_real_export_preserves_entity_order_redraw_order_and_geometry(tmp_path):
    # No native host launch: reopen the actual serialized DXF independently.
    with extract_document(str(make_source(tmp_path)), ExtractionOptions(
        pages="1", import_mode="vector", import_text=False, detect_arcs=False,
    )) as extraction:
        output = tmp_path / "ordered.dxf"
        export_to_dxf(extraction, str(output), DxfExportOptions(include_text=False))
    doc = ezdxf.readfile(output)
    entities = list(doc.modelspace())
    assert [entity.dxftype() for entity in entities] == ["LINE", "IMAGE", "LINE", "IMAGE", "LINE"]
    assert [entity.dxf.start.y for entity in entities if entity.dxftype() == "LINE"] == pytest.approx(
        [(150-y)*25.4/72 for y in [35, 55, 75]]
    )
    assert list(doc.modelspace().get_redraw_order()) == [
        (entity.dxf.handle, f"{i:X}") for i, entity in enumerate(entities, 1)
    ]


def fake_source():
    info = {"xref": 4, "number": 7, "bbox": (0, 0, 2, 2), "width": 2,
            "height": 2, "transform": (2, 0, 0, 2, 0, 0)}
    image = SimpleNamespace(xref=4, source_kind="xobject_image", alpha_kind="opaque",
        source_bbox_pdf=info["bbox"], pixel_size=(2, 2), affine_pdf=info["transform"])
    trace = [{"seqno": 0, "chars": [(65, 1, (1, 1), ())]},
             {"seqno": 2, "chars": [(66, 2, (3, 1), ())]}]
    char_a = SimpleNamespace(text="A", source_origin_pdf=(1, 1))
    char_b = SimpleNamespace(text="B", source_origin_pdf=(3, 1))
    data = SimpleNamespace(primitives=[SimpleNamespace(id=1, source_draw_order=3)],
        text_items=[SimpleNamespace(id=2, text="A", source_char_layout=[char_a]),
                    SimpleNamespace(id=3, text="B", source_char_layout=[char_b])])
    page = SimpleNamespace(get_image_info=lambda **kw: [info],
        get_bboxlog=lambda: [("fill-text", (0, 0, 2, 2)), ("fill-image", info["bbox"]),
                            ("fill-text", (2, 0, 4, 2)), ("stroke-path", (0, 0, 4, 4))],
        get_texttrace=lambda: trace)
    return page, data, [image], info, trace


@pytest.mark.parametrize("mutation", ["bbox", "affine", "pixels", "xref", "missing_image", "missing_char", "missing_seq"])
def test_binding_mismatch_cannot_silently_reorder(mutation):
    page, data, images, info, trace = fake_source()
    if mutation == "bbox": images[0].source_bbox_pdf = (1, 0, 2, 2)
    elif mutation == "affine": images[0].affine_pdf = (2, 0, 0, 2, 1, 0)
    elif mutation == "pixels": images[0].pixel_size = (3, 2)
    elif mutation == "xref": images[0].xref = 6
    elif mutation == "missing_image": page.get_image_info = lambda **kw: []
    elif mutation == "missing_char": trace.pop()
    elif mutation == "missing_seq": data.primitives[0].source_draw_order = None
    with pytest.raises(ValueError): bind_image_paint_order(page, data, images)


def test_grouped_text_across_image_fails_with_item_identity():
    page, data, images, *_ = fake_source()
    data.text_items[0].text = "AB"
    data.text_items[0].source_char_layout += data.text_items.pop().source_char_layout
    with pytest.raises(ValueError, match="item 2 crosses an image"):
        bind_image_paint_order(page, data, images)


def test_multiple_trace_spans_within_one_image_interval_are_valid():
    page, data, images, _info, trace = fake_source()
    trace[1]["seqno"] = 0
    data.text_items[0].text = "AB"
    data.text_items[0].source_char_layout += data.text_items.pop().source_char_layout
    assert bind_image_paint_order(page, data, images).text_keys == {2: 0}


def test_repeated_character_ambiguous_across_image_rejects():
    page, data, images, _info, trace = fake_source()
    trace[1]["chars"] = deepcopy(trace[0]["chars"])
    with pytest.raises(ValueError, match="ambiguous across an image"):
        bind_image_paint_order(page, data, images)


@pytest.mark.parametrize("kind,alpha", [("page_raster", "opaque"), ("inline_image_composite", "opaque"),
                                      ("xobject_image", "binary_mask"), ("xobject_image", "compositing_required")])
def test_composites_and_masks_retain_separate_display_contract(kind, alpha):
    page, data, images, *_ = fake_source()
    images[0].source_kind = kind
    images[0].alpha_kind = alpha
    assert bind_image_paint_order(page, data, images) is None


def test_ordering_requires_exact_entity_coverage():
    layout = ezdxf.new().modelspace()
    entity = layout.add_line((0, 0), (1, 1))
    with pytest.raises(ValueError, match="exact native entity set"):
        apply_image_paint_order(layout, {entity.dxf.handle: (0, 0), "DEAD": (0, 1)})


@pytest.mark.parametrize("mutation", ["physical", "redraw"])
def test_written_native_order_corruption_rejects(tmp_path, mutation):
    doc = ezdxf.new()
    layout = doc.modelspace()
    a = layout.add_line((0, 0), (1, 1))
    b = layout.add_line((2, 0), (3, 1))
    expected = [a.dxf.handle, b.dxf.handle]
    apply_image_paint_order(layout, {expected[0]: (0, 0), expected[1]: (0, 1)})
    if mutation == "physical": layout.entity_space.entities.reverse()
    else: layout.set_redraw_order([(expected[0], "2"), (expected[1], "1")])
    output = tmp_path / "corrupted-order.dxf"
    doc.saveas(output)
    with pytest.raises(ValueError, match="order changed"):
        verify_serialized_image_paint_order(output, expected)
