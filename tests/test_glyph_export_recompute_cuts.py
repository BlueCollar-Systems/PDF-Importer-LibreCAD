"""Cost cuts in the glyph export path must not change what is verified.

Profiling `1011 (1 OF 2) - Rev 0.pdf` (979 items, 931 delivered as nested glyph
blocks) at v1.0.87 showed ~64% of `export_dxf_ms` was recomputation of already-known
values: (a) `_verify_serialized_text_deliveries` re-hashed each of 130 immutable glyph
definitions every time an item referenced one (3,599 hashes), and (b) both
`_commit_outlines` and verification exploded every nested INSERT into ~171k transformed
SOLID fill copies to compute an outline bbox that only reads LWPOLYLINE/POLYLINE.

These tests pin the two cuts to *bit-identical* results against the ezdxf path they
replace, and prove the memo cannot hide a changed definition.
"""

from __future__ import annotations

import dataclasses
from unittest.mock import patch

import ezdxf
import pytest
from ezdxf.disassemble import recursive_decompose

import dxf_text_builder as dxf_text_builder_module
from dxf_text_builder import (
    TextDeliveryResult,
    _bbox_tuple,
    _glyph_definition_geometry_fingerprint,
    build_text,
    iter_glyph_outline_entities,
)
from librecad_pdf_importer.exporters import dxf_exporter as dxf_exporter_module
from librecad_pdf_importer.exporters.dxf_exporter import (
    _verify_serialized_text_deliveries,
)
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.primitives import NormalizedText

OUTLINE_TYPES = {"LWPOLYLINE", "POLYLINE"}


def _item(item_id: int, insertion, rotation: float, text: str = "W12X30") -> NormalizedText:
    return NormalizedText(
        id=item_id,
        text=text,
        normalized=text,
        insertion=insertion,
        bbox=(insertion[0] - 2.0, insertion[1] - 4.0, insertion[0] + 10.0, insertion[1] + 4.0),
        font_size=0.08,
        rotation=rotation,
        font_name="BCS Deterministic Test",
        page_number=3,
        advance_width=7.5,
    )


def _glyph_doc(dxf_version: str = "R2010"):
    """Two real nested-glyph deliveries that share glyph definitions."""
    doc = ezdxf.new(dxf_version)
    msp = doc.modelspace()
    deliveries = []
    for item_id, insertion, rotation in ((17, (12.25, 24.5), 33.0), (18, (40.0, 9.5), 0.0)):
        result = build_text(
            _item(item_id, insertion, rotation),
            msp,
            "TEXT",
            ImportConfig(text_mode="glyphs"),
            target_app="generic",
            dxf_version=dxf_version,
            return_delivery_result=True,
        )
        assert isinstance(result, TextDeliveryResult)
        assert result.final_representation == "glyphs"
        deliveries.append(result.to_dict())
    return doc, msp, deliveries


def _old_outlines(block_ref):
    return [e for e in recursive_decompose([block_ref]) if e.dxftype() in OUTLINE_TYPES]


def _outline_points(entity):
    if entity.dxftype() == "LWPOLYLINE":
        return ("LWPOLYLINE", tuple(tuple(p) for p in entity.get_points(format="xyseb")))
    return (
        "POLYLINE",
        tuple(
            (tuple(v.dxf.location), v.dxf.get("bulge", 0.0), v.dxf.get("start_width", 0.0))
            for v in entity.vertices
        ),
    )


@pytest.mark.parametrize("dxf_version", ["R2010", "R12"])
def test_outline_decompose_is_bit_identical_to_recursive_decompose(dxf_version: str) -> None:
    doc, msp, _ = _glyph_doc(dxf_version)
    inserts = [e for e in msp if e.dxftype() == "INSERT"]
    assert len(inserts) == 2

    # Negative control: the fills really are there and the old path really transforms
    # them -- otherwise skipping them proves nothing.
    everything = list(recursive_decompose(inserts))
    solids = [e for e in everything if e.dxftype() == "SOLID"]
    assert solids, "glyph definitions are expected to carry SOLID fills"

    for insert in inserts:
        old = _old_outlines(insert)
        new = list(iter_glyph_outline_entities(insert))
        assert old, "delivery must resolve to at least one outline"
        assert [e.dxftype() for e in new] == [e.dxftype() for e in old]
        assert all(e.dxftype() in OUTLINE_TYPES for e in new)
        # Same copies, same transform path: exact float equality, not approx.
        assert [_outline_points(e) for e in new] == [_outline_points(e) for e in old]
        assert _bbox_tuple(new) == _bbox_tuple(old)


def test_outline_decompose_matches_ezdxf_on_rotated_scaled_and_bulged_definitions() -> None:
    """Synthetic structure exercising rotation, non-unit scale, bulges and a POLYLINE
    definition, independent of any font: exact equality against ezdxf."""
    doc = ezdxf.new("R2010")
    g_a = doc.blocks.new("G_A")
    g_a.add_lwpolyline(
        [(0, 0, 0, 0, 0.0), (1, 0, 0, 0, 0.5), (1, 1, 0, 0, 0.0), (0, 1, 0, 0, -0.3)],
        format="xyseb",
        close=True,
    )
    for k in range(25):
        g_a.add_solid([(0, 0), (0.1 * k, 0), (0.1 * k, 0.1), (0, 0.1)])
    g_b = doc.blocks.new("G_B")
    poly = g_b.add_polyline2d([(0, 0), (2, 0), (2, 0.5), (0.2, 0.7)], close=True)
    poly.vertices[1].dxf.bulge = 0.25
    g_b.add_solid([(0, 0), (1, 0), (1, 1), (0, 1)])
    outer = doc.blocks.new("T_1")
    outer.add_blockref("G_A", (0.0, 0.0), dxfattribs={"xscale": 0.5, "yscale": 0.5, "rotation": 30.0})
    outer.add_blockref("G_B", (0.7, 0.1), dxfattribs={"xscale": 0.5, "yscale": 0.5, "rotation": 30.0})
    outer.add_blockref("G_A", (1.6, -0.2), dxfattribs={"xscale": 0.5, "yscale": 0.5, "rotation": 120.0})
    msp = doc.modelspace()
    ref = msp.add_blockref("T_1", (10.0, 20.0), dxfattribs={"rotation": 15.0, "xscale": 3.0, "yscale": 3.0})

    old = _old_outlines(ref)
    new = list(iter_glyph_outline_entities(ref))
    assert len(old) == 3
    assert [_outline_points(e) for e in new] == [_outline_points(e) for e in old]
    assert _bbox_tuple(new) == _bbox_tuple(old)
    # And the old path did pay for the fills we skip.
    assert sum(1 for e in recursive_decompose([ref]) if e.dxftype() == "SOLID") == 51


def test_outline_decompose_defers_to_ezdxf_outside_the_glyph_structure() -> None:
    """Anything that is not the nested-glyph shape (e.g. a multi-insert array or a
    non-INSERT entity) must fall back to ezdxf's own decomposition unchanged."""
    doc = ezdxf.new("R2010")
    g = doc.blocks.new("G")
    g.add_lwpolyline([(0, 0), (1, 0), (1, 1)], close=True)
    outer = doc.blocks.new("T")
    outer.add_blockref("G", (0, 0), dxfattribs={"row_count": 2, "column_count": 3,
                                                 "row_spacing": 2.0, "column_spacing": 2.0})
    msp = doc.modelspace()
    ref = msp.add_blockref("T", (5, 5))
    old = _old_outlines(ref)
    new = list(iter_glyph_outline_entities(ref))
    assert len(old) == 6
    assert [_outline_points(e) for e in new] == [_outline_points(e) for e in old]

    line = msp.add_line((0, 0), (1, 1))
    assert list(iter_glyph_outline_entities(line)) == []
    lw = msp.add_lwpolyline([(0, 0), (1, 0)])
    assert [e is lw for e in iter_glyph_outline_entities(lw)] == [True]


def test_serialized_verification_hashes_each_glyph_definition_once() -> None:
    doc, _, deliveries = _glyph_doc()
    referenced = []
    distinct = set()
    for delivery in deliveries:
        attempt = [a for a in delivery["attempts"] if a.get("outcome") == "verified"][0]
        names = list(attempt["evidence"]["glyph_definition_names"])
        assert names
        referenced.extend(names)
        distinct.update(names)
    # Two "W12X30" items share their six glyph definitions: references > distinct.
    assert len(referenced) > len(distinct)

    calls = []
    original = dxf_exporter_module._glyph_definition_geometry_fingerprint

    def counting(block):
        calls.append(str(block.name))
        return original(block)

    with patch.object(
        dxf_exporter_module, "_glyph_definition_geometry_fingerprint", side_effect=counting
    ):
        _verify_serialized_text_deliveries(doc, deliveries)

    assert sorted(calls) == sorted(distinct), (
        "verification must hash each immutable definition exactly once per pass, "
        f"got {len(calls)} hashes for {len(distinct)} definitions"
    )


def test_memoized_verification_still_detects_a_changed_definition() -> None:
    """The memo lives for one verification pass only; a definition mutated before the
    pass must still be caught -- and the recorded digest must not match the fresh one."""
    doc, _, deliveries = _glyph_doc()
    attempt = [a for a in deliveries[0]["attempts"] if a.get("outcome") == "verified"][0]
    name = sorted(attempt["evidence"]["glyph_definition_names"])[0]
    recorded = attempt["evidence"]["glyph_definition_geometry_sha256"][name]
    definition = doc.blocks.get(name)
    assert _glyph_definition_geometry_fingerprint(definition) == recorded

    outline = next(e for e in definition if e.dxftype() == "LWPOLYLINE")
    points = outline.get_points(format="xyseb")
    x, y, s, e, b = points[0]
    points[0] = (x + 1e-6, y, s, e, b)
    outline.set_points(points, format="xyseb")
    assert _glyph_definition_geometry_fingerprint(definition) != recorded

    with pytest.raises(RuntimeError, match="glyph definition geometry changed"):
        _verify_serialized_text_deliveries(doc, deliveries)


def test_commit_outlines_no_longer_transforms_solid_fills() -> None:
    """Build side: `_commit_outlines` computes the resolved bbox through the outline-only
    path. Pin it by asserting SOLID.transform is never invoked during a glyph delivery."""
    from ezdxf.entities import Solid

    with patch.object(Solid, "transform", autospec=True) as solid_transform:
        doc, msp, deliveries = _glyph_doc()
    assert solid_transform.call_count == 0, (
        f"glyph delivery transformed {solid_transform.call_count} SOLID fills; the bbox "
        "only needs the outlines"
    )
    # Deliveries are still fully verified and the outline bbox evidence still present.
    for delivery in deliveries:
        attempt = [a for a in delivery["attempts"] if a.get("outcome") == "verified"][0]
        assert attempt["evidence"]["outline_bbox_verified"] is True
    _verify_serialized_text_deliveries(doc, deliveries)


# ---------------------------------------------------------------------------
# Third cut: exact vertex bbox for plain LWPOLYLINE outlines (ezdxf's extents builds
# a Path per polyline through the generic primitive machinery and then takes the
# min/max of the same LINE_TO vertices).
# ---------------------------------------------------------------------------

from ezdxf import bbox as ezdxf_bbox  # noqa: E402

from dxf_text_builder import _plain_lwpolyline_bbox  # noqa: E402


def _ezdxf_bbox_tuple(entities):
    box = ezdxf_bbox.extents(entities)
    if not box.has_data:
        return None
    return (float(box.extmin.x), float(box.extmin.y), float(box.extmax.x), float(box.extmax.y))


def test_plain_lwpolyline_bbox_is_exact_on_real_glyph_outlines() -> None:
    doc, msp, _ = _glyph_doc()
    inserts = [e for e in msp if e.dxftype() == "INSERT"]
    for insert in inserts:
        outlines = list(iter_glyph_outline_entities(insert))
        assert outlines
        fast = _plain_lwpolyline_bbox(outlines)
        assert fast is not None, "real glyph outlines are plain LWPOLYLINEs; fast path must apply"
        assert fast == _ezdxf_bbox_tuple(outlines)
        assert _bbox_tuple(outlines) == fast
    # And per definition block, on the untransformed outlines.
    for name in {e.dxf.name for i in inserts for e in i.block() if e.dxftype() == "INSERT"}:
        outlines = [e for e in doc.blocks.get(name) if e.dxftype() == "LWPOLYLINE"]
        assert _plain_lwpolyline_bbox(outlines) == _ezdxf_bbox_tuple(outlines)


@pytest.mark.parametrize(
    "shape",
    ["bulge", "const_width", "vertex_width", "elevation", "extrusion", "single_vertex",
     "empty", "polyline", "mixed_types", "nan"],
)
def test_plain_lwpolyline_bbox_falls_back_to_ezdxf_outside_its_shape(shape: str) -> None:
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    if shape == "bulge":
        ents = [msp.add_lwpolyline([(0, 0, 0, 0, 0.7), (2, 0), (2, 1)], format="xyseb")]
    elif shape == "const_width":
        ents = [msp.add_lwpolyline([(0, 0), (2, 0), (2, 1)], dxfattribs={"const_width": 0.2})]
    elif shape == "vertex_width":
        ents = [msp.add_lwpolyline([(0, 0, 0.1, 0.1), (2, 0), (2, 1)], format="xyse")]
    elif shape == "elevation":
        ents = [msp.add_lwpolyline([(0, 0), (2, 0), (2, 1)], dxfattribs={"elevation": 3.0})]
    elif shape == "extrusion":
        ents = [msp.add_lwpolyline([(0, 0), (2, 0), (2, 1)], dxfattribs={"extrusion": (0, 1, 0)})]
    elif shape == "single_vertex":
        ents = [msp.add_lwpolyline([(1.5, 2.5)])]
    elif shape == "empty":
        ents = []
    elif shape == "polyline":
        ents = [msp.add_polyline2d([(0, 0), (2, 0), (2, 1)])]
    elif shape == "mixed_types":
        ents = [msp.add_lwpolyline([(0, 0), (2, 0)]), msp.add_line((5, 5), (6, 6))]
    else:  # nan
        ents = [msp.add_lwpolyline([(0, 0), (float("nan"), 1)])]
    assert _plain_lwpolyline_bbox(ents) is None
    # The public helper still answers exactly what ezdxf answers.
    assert _bbox_tuple(ents) == _ezdxf_bbox_tuple(ents)


def test_plain_lwpolyline_bbox_matches_ezdxf_on_random_plain_polylines() -> None:
    import random

    rng = random.Random(81011)
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    for _ in range(40):
        pts = [(rng.uniform(-1e3, 1e3), rng.uniform(-1e3, 1e3)) for _ in range(rng.randint(2, 40))]
        ents = [msp.add_lwpolyline(pts, close=bool(rng.getrandbits(1)))]
        if rng.getrandbits(1):
            ents.append(msp.add_lwpolyline([(rng.uniform(-9, 9), rng.uniform(-9, 9)) for _ in range(3)]))
        assert _plain_lwpolyline_bbox(ents) == _ezdxf_bbox_tuple(ents)
