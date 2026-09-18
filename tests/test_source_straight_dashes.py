from copy import deepcopy

import ezdxf
import pymupdf as fitz
import pytest

from pdfcadcore.primitive_extractor import extract_page
from librecad_pdf_importer.core.document import ExtractionOptions, extract_document
from librecad_pdf_importer.core.source_line_dashes import bind_source_line_dashes, dash_intervals
from librecad_pdf_importer.exporters.dxf_exporter import (
    DxfExportOptions, export_to_dxf, _add_source_dash_block,
    _verify_serialized_source_dash_blocks,
)


def page_with_line(*, rotation=0, reverse=False, phase=3, morph=None, pattern="6 4"):
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    a, b = ((100, 20), (10, 20)) if reverse else ((10, 20), (100, 20))
    page.draw_line(a, b, dashes=f"[{pattern}] {phase}", morph=morph)
    page.set_rotation(rotation)
    return doc, page


def test_phase_and_odd_array_repetition_are_not_linetype_guesses():
    assert dash_intervals(30, (6, 4), 3) == ((0, 3), (7, 13), (17, 23), (27, 30))
    assert dash_intervals(16, (3, 2, 1), 0) == ((0, 3), (5, 6), (9, 11), (12, 15))
    assert dash_intervals(30, (6, 4), -2) == ((2, 8), (12, 18), (22, 28))


@pytest.mark.parametrize("position", [0, .5, 1])
def test_empty_visible_interval_cannot_manufacture_zero_length_ink(position):
    assert dash_intervals(30, (6, 4), 0, (position, position)) == ()


@pytest.mark.parametrize("pattern", [(0, 4), (2, 0), (-1, 4), (float("nan"), 1)])
def test_zero_dot_and_invalid_patterns_are_not_fabricated_as_lines(pattern):
    with pytest.raises(ValueError): dash_intervals(20, pattern, 0)


def test_dense_geometry_is_bounded_without_coarsening():
    with pytest.raises(ValueError, match="budget"):
        dash_intervals(100, (.001, .001), 0, limit=12)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("reverse", [False, True])
def test_source_start_phase_rotation_and_explicit_scale(rotation, reverse):
    doc, page = page_with_line(rotation=rotation, reverse=reverse)
    data = extract_page(page, 1, scale=2.5)
    bound = bind_source_line_dashes(page, data, 2.5, True)
    assert len(bound) == 1
    proof = next(iter(bound.values()))
    assert proof.pattern_pdf == pytest.approx((6, 4))
    assert proof.phase_pdf == pytest.approx(3)
    assert proof.source_start_pdf == ((100, 20) if reverse else (10, 20))
    assert len(proof.segments_model) == 10
    import math
    assert math.dist(*proof.segments_model[0]) == pytest.approx(3*25.4/72*2.5)
    doc.close()


def test_anisotropic_source_ctm_uses_along_line_not_geometric_mean_scale():
    doc, page = page_with_line(morph=(fitz.Point(0, 0), fitz.Matrix(2, 0, .5, 3, 0, 0)))
    data = extract_page(page, 1)
    proof = next(iter(bind_source_line_dashes(page, data, 1, True).values()))
    assert proof.pattern_pdf == pytest.approx((12, 8))
    assert proof.phase_pdf == pytest.approx(6)
    assert proof.pattern_pdf[0] != pytest.approx(6*(6**.5))
    doc.close()


def test_clipped_and_reversed_visible_segment_retains_original_dash_phase():
    doc, page = page_with_line()
    data = extract_page(page, 1)
    primitive = data.primitives[0]
    a, b = primitive.points
    primitive.points = [(a[0]+(b[0]-a[0])*.7, a[1]), (a[0]+(b[0]-a[0])*.1, a[1])]
    proof = next(iter(bind_source_line_dashes(page, data, 1, True).values()))
    assert proof.visible_source_interval == pytest.approx((.1, .7))
    # First original painted interval7..13pt is clipped to9..13, not restarted.
    assert proof.segments_model[0][0][0] == pytest.approx(19*25.4/72)
    assert proof.segments_model[0][1][0] == pytest.approx(23*25.4/72)
    doc.close()


def test_unrelated_visible_line_cannot_borrow_source_dash_proof():
    doc, page = page_with_line()
    data = extract_page(page, 1)
    data.primitives[0].points[0] = (999, 999)
    assert not bind_source_line_dashes(page, data, 1, True)
    doc.close()


def test_zero_dot_and_multisegment_pdf_strokes_remain_explicitly_unqualified():
    doc, page = page_with_line(pattern="0 4")
    assert not bind_source_line_dashes(page, extract_page(page, 1), 1, True)
    doc.close()
    doc = fitz.open()
    page = doc.new_page()
    shape = page.new_shape()
    shape.draw_polyline([(10, 20), (100, 20), (100, 100)])
    shape.finish(dashes="[6 4] 0", closePath=False)
    shape.commit()
    assert not bind_source_line_dashes(page, extract_page(page, 1), 1, True)
    doc.close()


def test_rotated_scaled_pdf_userunit_keeps_true_source_dash_units():
    doc, page = page_with_line(rotation=90)
    doc.xref_set_key(page.xref, "UserUnit", "2")
    page = doc.reload_page(page)
    data = extract_page(page, 1, scale=3)
    proof = next(iter(bind_source_line_dashes(page, data, 3, True).values()))
    assert proof.pattern_pdf == pytest.approx((12, 8))
    assert proof.phase_pdf == pytest.approx(6)
    import math
    assert math.dist(*proof.segments_model[0]) == pytest.approx(6*25.4/72*3)
    doc.close()


def test_actual_serialized_native_dash_block_has_exact_segments(tmp_path):
    doc, page = page_with_line()
    source = tmp_path / "dashes.pdf"
    doc.save(source)
    doc.close()
    output = tmp_path / "dashes.dxf"
    with extract_document(str(source), ExtractionOptions(pages="1", import_mode="vector")) as extraction:
        export_to_dxf(extraction, str(output), DxfExportOptions(include_text=False))
        assert len(extraction.pages[0].source_line_dashes) == 1
        assert not extraction.summary()["source_dash_delivery"]["per_page"][0]["native_linetype_source_ids"]
    drawing = ezdxf.readfile(output)
    parent = list(drawing.modelspace())[0]
    assert parent.dxftype() == "INSERT"
    lines = list(drawing.blocks[parent.dxf.name])
    assert len(lines) == 10
    assert all(line.dxf.linetype == "Continuous" for line in lines)
    assert lines[0].dxf.start.x == pytest.approx(10*25.4/72)
    assert lines[0].dxf.end.x == pytest.approx(13*25.4/72)


@pytest.mark.parametrize("mutation", ["translation", "segment", "count", "metadata", "parent_layer", "parent_invisible", "child_invisible"])
def test_saved_dash_verifier_rejects_physical_or_identity_loss(tmp_path, mutation):
    source_doc, page = page_with_line()
    data = extract_page(page, 1)
    proof = next(iter(bind_source_line_dashes(page, data, 1, True).values()))
    doc = ezdxf.new()
    expected = _add_source_dash_block(doc, doc.modelspace(), data.primitives[0], proof, {"layer": "0"}, 0)
    parent = doc.entitydb[expected["handle"]]
    if mutation == "translation": parent.dxf.insert = (1, 0, 0)
    elif mutation == "segment": list(doc.blocks[expected["name"]])[0].dxf.end = (1, 1, 0)
    elif mutation == "count": doc.blocks[expected["name"]].add_line((0, 0), (1, 1))
    elif mutation == "parent_layer":
        doc.layers.new("hidden").freeze()
        parent.dxf.layer = "hidden"
    elif mutation == "parent_invisible": parent.dxf.invisible = 1
    elif mutation == "child_invisible": list(doc.blocks[expected["name"]])[0].dxf.invisible = 1
    else: parent.set_xdata("BCS_SOURCE_DASH", [(1000, "wrong")])
    output = tmp_path / "changed.dxf"
    doc.saveas(output)
    with pytest.raises(RuntimeError):
        _verify_serialized_source_dash_blocks(ezdxf.readfile(output), [deepcopy(expected)])
    source_doc.close()
