"""Physical header frames and bounded conservative fallback, independently checked."""
from hashlib import sha256
import math
from pathlib import Path

import ezdxf
from ezdxf.math import Vec3
import pytest

from librecad_pdf_importer import drawing_bounds as bounds
from librecad_pdf_importer import drawing_insert as merge
from librecad_pdf_importer.drawing_copy import DrawingCopyCancelled, DrawingCopyError

FIXTURE = Path(__file__).parent / "fixtures/librecad-2.2.1.5/public-glyphs-native-saved.dxf"
FIXTURE_SHA = "02a19de450536731d0409ea04a05a1fc648a5812641cbfabd4da4ffa83abaf69"


def fresh():
    doc = ezdxf.new("R2007")
    doc.units = 4
    return doc


def save_frame(doc, path, low, high):
    doc.header["$EXTMIN"], doc.header["$EXTMAX"] = low, high
    with path.open("x", encoding=doc.output_encoding) as stream:
        merge._write_merged_drawing(doc, stream)


def snapshot(doc):
    # No tag export that could mutate embedded/linked resource payloads.
    return (merge._header_state(doc), {e.dxf.handle: dict(e.dxf.all_existing_dxf_attribs())
                                     for e in doc.entitydb.values() if e.is_alive})


def test_native_valid_header_overrides_inverted_layout_cache_without_mutation():
    assert sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_SHA
    doc = ezdxf.readfile(FIXTURE)
    assert any(a > b for a, b in zip(doc.modelspace().dxf.extmin, doc.modelspace().dxf.extmax, strict=True))
    before = snapshot(doc)
    result = bounds.document_bounds(doc)
    assert result.minimum == (3.527777777777778, 10.51012988069227, 0.0)
    assert result.maximum == (45.86111111111111, 52.91666666666666, 0.0)
    assert result.provenance == "declared_HEADER_frame"
    assert snapshot(doc) == before


def test_physical_negative_sheet_offsets_nonunit_union_and_strict_originals(tmp_path):
    base, incoming, output = [tmp_path / name for name in ("base.dxf", "incoming.dxf", "copy.dxf")]
    doc = fresh()
    doc.units = 1  # inches
    doc.modelspace().add_line((-2, -1), (1, 3), dxfattribs={"true_color": 0x123456})
    doc.header["$DIMTXT"] = 7.25
    save_frame(doc, base, (-3, -2, 0), (2, 4, 0))
    source = fresh()  # millimetres; declared margins intentionally exceed ink.
    source.modelspace().add_line((-254, -127), (1016, 762), dxfattribs={"true_color": 0x654321})
    save_frame(source, incoming, (-508, -254, 0), (1270, 1016, 0))
    original = (base.read_bytes(), incoming.read_bytes())
    old = ezdxf.readfile(base)
    state, headers = merge._base_state(old), merge._header_state(old)
    result = merge.insert_into_saved_drawing_copy(base, incoming, output)
    reopened = ezdxf.readfile(output)
    assert Vec3(reopened.header["$EXTMIN"]) == Vec3(-20, -10, 0)
    assert Vec3(reopened.header["$EXTMAX"]) == Vec3(50, 40, 0)
    assert result.insertion_scale == 1 / 25.4
    assert result.drawing_bounds_provenance["base"]["provenance"] == "declared_HEADER_frame"
    assert result.drawing_bounds_provenance["incoming"]["minimum"] == [-508, -254, 0]
    assert result.drawing_bounds_provenance["base_input_sha256"] == sha256(original[0]).hexdigest()
    merge._check_base_state(reopened, state)  # includes original LAYOUT/VPORT/resources/paint
    headers["$EXTMIN"], headers["$EXTMAX"] = [-20, -10, 0], [50, 40, 0]
    merge._check_headers(reopened, headers)
    assert (base.read_bytes(), incoming.read_bytes()) == original
    reopened.header["$EXTMAX"] = old.modelspace().dxf.extmax
    with pytest.raises(DrawingCopyError, match="header setting"):
        merge._check_headers(reopened, headers)
    reopened.modelspace().query("LINE").first.dxf.true_color = 0
    with pytest.raises(DrawingCopyError):
        merge._check_base_state(reopened, state)


def test_missing_frame_uses_conservative_curves_bulges_and_finite_transforms():
    doc = fresh()
    block = doc.blocks.new("PUBLIC_SHARED", base_point=(2, 3, 0))
    block.add_lwpolyline([(2, 3, 0, 0, 1), (12, 3, 0, 0, 0)], format="xyseb")
    nested = doc.blocks.new("PUBLIC_NESTED")
    nested.add_blockref(block.name, (-20, 10), dxfattribs={"xscale": -2, "yscale": 3, "rotation": 90})
    doc.modelspace().add_blockref(nested.name, (100, -100))
    doc.modelspace().add_blockref(block.name, (-50, -50))
    before = snapshot(doc)
    result = bounds.document_bounds(doc)
    assert result.provenance == "conservative_visible_planar_control_geometry"
    assert all(math.isfinite(v) for v in (*result.minimum, *result.maximum))
    assert result.minimum == pytest.approx((-60, -110, 0))
    assert result.maximum == pytest.approx((110, -40, 0))
    # Authored vertices and broad arc envelopes must all be contained.
    for reference in doc.modelspace():
        for entity in reference.virtual_entities():
            if entity.dxftype() == "INSERT":
                continue
            for point in bounds._geometry(entity):
                assert result.minimum[0] <= point[0] <= result.maximum[0]
                assert result.minimum[1] <= point[1] <= result.maximum[1]
    assert snapshot(doc) == before


@pytest.mark.parametrize("kind", ["LWPOLYLINE", "POLYLINE"])
@pytest.mark.parametrize("role", ["base", "incoming"])
def test_physical_wide_polyline_acute_miters_require_declared_frame(tmp_path, kind, role):
    from ezdxf.render.trace import TraceBuilder
    wide, other, output = [tmp_path / name for name in ("wide.dxf", "other.dxf", "copy.dxf")]
    doc = fresh()
    vertices = [(0, 0), (10, 0), (0, .5)]
    if kind == "LWPOLYLINE":
        doc.modelspace().add_lwpolyline(vertices, dxfattribs={"const_width": 2, "true_color": 0x123456})
    else:
        doc.modelspace().add_polyline2d(vertices, dxfattribs={"default_start_width": 2,
            "default_end_width": 2, "true_color": 0x123456})
    doc.saveas(wide)  # Physical invalid HEADER, just like the original blocker.
    actual = ezdxf.readfile(wide)
    entity = actual.modelspace().query(kind).first
    points = [point for polygon in TraceBuilder.from_polyline(entity).polygons() for point in polygon]
    assert min(p.x for p in points) == pytest.approx(-30.0249843945)
    assert max(p.x for p in points) == pytest.approx(50.0249843945)
    original, fields = wide.read_bytes(), snapshot(actual)
    with pytest.raises(DrawingCopyError, match="bounds"):
        bounds.document_bounds(actual)
    assert snapshot(actual) == fields
    neutral = fresh()
    neutral.modelspace().add_line((0, 0), (1, 1))
    neutral.saveas(other)
    base, incoming = (wide, other) if role == "base" else (other, wide)
    with pytest.raises(DrawingCopyError, match="bounds"):
        merge.insert_into_saved_drawing_copy(base, incoming, output)
    assert not output.exists() and wide.read_bytes() == original
    # A complete physical declared frame supports the same wide geometry; its
    # entity/resource/paint bytes still have no permitted normalization.
    framed = tmp_path / "wide-framed.dxf"
    save_frame(actual, framed, (-100, -100, 0), (100, 100, 0))
    physical = ezdxf.readfile(framed)
    before = snapshot(physical)
    frame = bounds.document_bounds(physical)
    assert frame.minimum == (-100, -100, 0) and frame.maximum == (100, 100, 0)
    assert frame.provenance == "declared_HEADER_frame" and snapshot(physical) == before


@pytest.mark.parametrize("kind,width_field", [("LWPOLYLINE", "start_width"), ("LWPOLYLINE", "end_width"),
                                             ("POLYLINE", "start_width"), ("POLYLINE", "end_width")])
def test_per_vertex_widths_also_require_declared_frame(kind, width_field):
    doc = fresh()
    if kind == "LWPOLYLINE":
        row = [0, 0, 0, 0, 0]
        row[2 if width_field == "start_width" else 3] = 2
        doc.modelspace().add_lwpolyline([row, (1, 1, 0, 0, 0)], format="xyseb")
    else:
        entity = doc.modelspace().add_polyline2d([(0, 0), (1, 1)])
        setattr(entity.vertices[0].dxf, width_field, 2)
    before = snapshot(doc)
    with pytest.raises(DrawingCopyError, match="bounds"):
        bounds.document_bounds(doc)
    assert snapshot(doc) == before


@pytest.mark.parametrize("hidden", ["off", "frozen", "invisible"])
@pytest.mark.parametrize("leaf", ["LINE", "TEXT"])
def test_shared_block_hidden_first_never_poison_visible_layer_zero_context(hidden, leaf):
    doc = fresh()
    doc.layers.new("PUBLIC_HIDDEN")
    if hidden == "off":
        doc.layers.get("PUBLIC_HIDDEN").off()
    elif hidden == "frozen":
        doc.layers.get("PUBLIC_HIDDEN").freeze()
    block = doc.blocks.new("PUBLIC_CONTEXT")
    if leaf == "TEXT":
        block.add_text("PUBLIC unsupported active font", dxfattribs={"layer": "0", "color": 0})
    else:
        block.add_line((0, 0), (8, 6), dxfattribs={"layer": "0", "color": 0})
    doc.modelspace().add_blockref(block.name, (1000, 1000),
        dxfattribs={"layer": "PUBLIC_HIDDEN", "invisible": int(hidden == "invisible")})
    doc.modelspace().add_blockref(block.name, (-10, -20))
    before = snapshot(doc)
    if leaf == "TEXT":
        with pytest.raises(DrawingCopyError, match="bounds"):
            bounds.document_bounds(doc)
    else:
        result = bounds.document_bounds(doc)
        assert result.minimum == (-10, -20, 0) and result.maximum == (-2, -14, 0)
    assert snapshot(doc) == before


@pytest.mark.parametrize("axis,value", [("z", float("nan")), ("x", float("inf"))])
def test_nonfinite_declared_header_is_not_xy_only_accepted(axis, value):
    doc = fresh()
    low = [0, 0, 0]
    low["xyz".index(axis)] = value
    doc.header["$EXTMIN"], doc.header["$EXTMAX"] = low, (5, 5, 0)
    doc.modelspace().add_line((0, 0), (5, 5))
    with pytest.raises(DrawingCopyError, match="bounds"):
        bounds.document_bounds(doc)


@pytest.mark.parametrize("change", ["text", "attrib", "nonzero_z", "thickness", "tilt", "cycle",
                                   "missing", "array", "proxy", "nonfinite", "depth", "payload", "count"])
def test_invalid_header_fallback_rejects_incomplete_or_unbounded_geometry(change):
    doc = fresh()
    line = doc.modelspace().add_line((0, 0), (3, 4))
    limit = None
    if change == "text":
        doc.modelspace().add_mtext("PUBLIC unsupported font")
    elif change == "attrib":
        block = doc.blocks.new("PUBLIC_ATTRIB")
        block.add_line((0, 0), (1, 1))
        doc.modelspace().add_blockref(block.name, (0, 0)).add_attrib("PUBLIC", "visible", (0, 0))
    elif change == "nonzero_z":
        line.dxf.end = (3, 4, 1)
    elif change == "thickness":
        line.dxf.thickness = 1
    elif change == "tilt":
        line.dxf.extrusion = (0, 1, 0)
    elif change in {"cycle", "missing", "array", "depth"}:
        block = doc.blocks.new("PUBLIC_BLOCK")
        block.add_line((0, 0), (1, 1))
        reference = doc.modelspace().add_blockref(block.name, (0, 0))
        if change == "cycle":
            block.add_blockref(block.name, (0, 0))
        elif change == "missing":
            reference.dxf.name = "PUBLIC_MISSING"
        elif change == "array":
            reference.dxf.row_count = 2
        else:
            for index in range(33):
                child = doc.blocks.new(f"PUBLIC_DEPTH_{index}")
                block.add_blockref(child.name, (0, 0))
                block = child
    elif change == "proxy":
        line.proxy_graphic = b"PUBLIC unknown geometry"
    elif change == "nonfinite":
        line.dxf.start = (float("inf"), 0, 0)
    elif change == "payload":
        doc.modelspace().add_lwpolyline([(i, i) for i in range(10)])
        limit = 5
    else:
        doc.modelspace().add_point((1, 1))
        limit = 1
    before = snapshot(doc)
    with pytest.raises(DrawingCopyError, match="bounds"):
        bounds.document_bounds(doc, max_records=limit)
    assert snapshot(doc) == before


def test_cancel_empty_and_inverted_z_paths_leave_inputs_and_destination_intact(tmp_path):
    doc = fresh()
    assert bounds.document_bounds(doc) is None
    doc.header["$EXTMIN"], doc.header["$EXTMAX"] = (0, 0, 1), (5, 5, 0)
    doc.modelspace().add_line((2, 3), (4, 5))
    result = bounds.document_bounds(doc)
    assert result.minimum == (2, 3, 0) and result.maximum == (4, 5, 0)
    def cancelled():
        raise DrawingCopyCancelled("PUBLIC cancellation")
    before = snapshot(doc)
    with pytest.raises(DrawingCopyCancelled, match="PUBLIC cancellation"):
        bounds.document_bounds(doc, cancel_check=cancelled)
    assert snapshot(doc) == before
    base, incoming, target = [tmp_path / name for name in ("base.dxf", "incoming.dxf", "copy.dxf")]
    fresh().saveas(base)
    fresh().saveas(incoming)
    original = (base.read_bytes(), incoming.read_bytes())
    with pytest.raises(DrawingCopyError, match="bounds"):
        merge.insert_into_saved_drawing_copy(base, incoming, target)
    assert not target.exists()
    assert (base.read_bytes(), incoming.read_bytes()) == original
    assert not list(tmp_path.glob(".pdf-drawing-copy-*"))


def test_cancellation_inside_cached_closure_is_preserved_as_cancellation():
    doc = fresh()
    block = doc.blocks.new("PUBLIC_CANCEL")
    for index in range(10):
        block.add_line((index, 0), (index, 3))
    doc.modelspace().add_blockref(block.name, (0, 0))
    before, calls = snapshot(doc), []
    def cancelled():
        calls.append(True)
        if len(calls) == 5:
            raise DrawingCopyCancelled("PUBLIC closure cancellation")
    with pytest.raises(DrawingCopyCancelled, match="closure cancellation"):
        bounds.document_bounds(doc, cancel_check=cancelled)
    assert len(calls) == 5 and snapshot(doc) == before


@pytest.mark.parametrize("kind", ["SPLINE", "HATCH", "CIRCLE", "ELLIPSE", "IMAGE"])
def test_complete_typed_curve_and_image_control_envelopes_are_not_silently_skipped(tmp_path, kind):
    doc = fresh()
    if kind == "SPLINE":
        entity = doc.modelspace().add_spline()
        entity.set_open_uniform([(0, 0, 0), (-30, 80, 0), (90, -40, 0), (10, 10, 0)], degree=3)
        low, high = (-30, -40, 0), (90, 80, 0)
    elif kind == "HATCH":
        entity = doc.modelspace().add_hatch()
        path = entity.paths.add_edge_path()
        path.add_arc((20, 30), 10, 10, 320)
        low, high = (0, 0, 0), (30, 40, 0)  # origin/elevation is also a bound control.
    elif kind == "CIRCLE":
        doc.modelspace().add_circle((20, -30), 8)
        low, high = (12, -38, 0), (28, -22, 0)
    elif kind == "ELLIPSE":
        doc.modelspace().add_ellipse((20, -30), major_axis=(6, 8), ratio=.5)
        low, high = (10, -40, 0), (30, -20, 0)
    else:
        definition = doc.add_image_def(str(tmp_path / "PUBLIC-not-read.png"), (20, 10))
        doc.modelspace().add_image(definition, insert=(-10, 30), size_in_units=(40, 30))
        low, high = (-12, 27, 0), (32, 63, 0)
    before = snapshot(doc)
    result = bounds.document_bounds(doc)
    assert result.minimum == pytest.approx(low) and result.maximum == pytest.approx(high)
    assert result.provenance == "conservative_visible_planar_control_geometry"
    assert snapshot(doc) == before
