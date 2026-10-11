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
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
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
from librecad_pdf_importer.core.document import DocumentExtraction, ExtractedPage
from librecad_pdf_importer.exporters.dxf_exporter import (
    DxfExportOptions,
    _verify_serialized_text_deliveries as _verify_serialized_text_deliveries_impl,
    export_to_dxf,
)
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.primitives import NormalizedText, PageData

OUTLINE_TYPES = {"LWPOLYLINE", "POLYLINE"}
_EMPTY_POSITIONED_SESSION: object | None = None


def _production_empty_positioned_session() -> object:
    global _EMPTY_POSITIONED_SESSION
    if _EMPTY_POSITIONED_SESSION is not None:
        return _EMPTY_POSITIONED_SESSION
    captured: list[object] = []

    def capture(
        doc: object,
        deliveries: list[dict[str, object]],
        **kwargs: object,
    ) -> None:
        session = kwargs["trusted_positioned_session"]
        captured.append(session)
        _verify_serialized_text_deliveries_impl(
            doc,
            deliveries,
            trusted_positioned_session=session,
        )

    with TemporaryDirectory(prefix="lc-empty-positioned-session-") as directory:
        root = Path(directory)
        with patch.object(
            dxf_exporter_module,
            "_verify_serialized_text_deliveries",
            side_effect=capture,
        ):
            export_to_dxf(
                DocumentExtraction(
                    pdf_path=str(root / "must-not-be-read.pdf"),
                    pages=[
                        ExtractedPage(
                            page_data=PageData(
                                page_number=1,
                                width=20.0,
                                height=10.0,
                            ),
                            profile=SimpleNamespace(),
                        )
                    ],
                ),
                str(root / "empty-session.dxf"),
                DxfExportOptions(
                    include_images=False,
                    include_text=False,
                    attach_metadata=False,
                ),
            )
    assert len(captured) == 1
    _EMPTY_POSITIONED_SESSION = captured[0]
    return _EMPTY_POSITIONED_SESSION


def _verify_serialized_text_deliveries(
    doc: object,
    deliveries: list[dict[str, object]],
    *,
    trusted_positioned_anchors: object,
) -> None:
    assert trusted_positioned_anchors == {}
    _verify_serialized_text_deliveries_impl(
        doc,
        deliveries,
        trusted_positioned_session=_production_empty_positioned_session(),
    )


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
        _verify_serialized_text_deliveries(
            doc,
            deliveries,
            trusted_positioned_anchors={},
        )

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
        _verify_serialized_text_deliveries(
            doc,
            deliveries,
            trusted_positioned_anchors={},
        )


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
    _verify_serialized_text_deliveries(
        doc,
        deliveries,
        trusted_positioned_anchors={},
    )


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


# ---- SOLID-only glyph definitions: the fast exact bbox -----------------------

def _fill_only_glyph_doc(tmp_path, deterministic_exact_font):
    """A real glyph delivery whose definitions are SOLID fills only.

    The PDF paints its glyphs filled (not stroked), so the exporter's source
    fill receipt lets the builder omit contour wires, as for any such PDF.
    """
    import pymupdf

    from librecad_pdf_importer.importer import run_import

    source = tmp_path / "fill_only.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=200, height=100)
        page.insert_text((20, 50), "EX101", fontsize=20, fontname="BCFixture",
                         fontfile=str(deterministic_exact_font))
        pdf.save(source)
    run = run_import(str(source), mode="vector", overrides={"text_mode": "glyphs"})
    output = tmp_path / "fill_only.dxf"
    try:
        result = export_to_dxf(
            run.extraction, str(output), DxfExportOptions(text_mode="glyphs")
        )
    finally:
        run.close()
    assert [d["final_representation"] for d in result.text_deliveries] == ["glyphs"]
    evidence = result.text_deliveries[0]["attempts"][-1]["evidence"]
    assert evidence["source_fill_contours_omitted"], "expected a source fill receipt"
    doc = ezdxf.readfile(output)
    msp = doc.modelspace()
    insert = next(
        e for e in msp
        if e.dxftype() == "INSERT" and not doc.layers.get(e.dxf.layer).is_frozen()
    )
    leaves = list(recursive_decompose([insert]))
    assert leaves and all(e.dxftype() == "SOLID" for e in leaves)
    return doc, msp, insert


def _ezdxf_bbox_tuple(entities):
    from ezdxf import bbox as ezdxf_bbox

    box = ezdxf_bbox.extents(entities)
    if not box.has_data:
        return None
    return (float(box.extmin.x), float(box.extmin.y), float(box.extmax.x), float(box.extmax.y))


def test_solid_only_glyph_bbox_is_bit_identical_to_ezdxf(tmp_path, deterministic_exact_font):
    from dxf_text_builder import _plain_solid_bbox

    doc, msp, delivered = _fill_only_glyph_doc(tmp_path, deterministic_exact_font)
    outer = delivered.dxf.name
    inserts = [delivered] + [
        msp.add_blockref(outer, (31.5, -7.25), dxfattribs={"rotation": angle, "xscale": 1.7,
                                                           "yscale": 1.7})
        for angle in (0.0, 33.0, 90.0)
    ]
    for insert in inserts:
        entities = list(iter_glyph_outline_entities(insert))
        assert entities and all(e.dxftype() == "SOLID" for e in entities)
        expected = _ezdxf_bbox_tuple(entities)
        assert expected is not None
        assert _plain_solid_bbox(entities) == expected   # exact, not approx
        assert _bbox_tuple(entities) == expected

    mirrored = msp.add_blockref(outer, (5.0, 5.0), dxfattribs={"xscale": -1.0, "yscale": 1.0})
    entities = list(iter_glyph_outline_entities(mirrored))
    assert entities and any(
        tuple(e.dxf.extrusion) != (0.0, 0.0, 1.0) for e in entities
    ), "a mirrored glyph is expected to flip the SOLID extrusion"
    assert _plain_solid_bbox(entities) is None
    assert _bbox_tuple(entities) == _ezdxf_bbox_tuple(entities)


def _solid(msp, *, extrusion=(0.0, 0.0, 1.0), thickness=0.0, nan=False):
    first = (float("nan"), 0.0) if nan else (0.0, 0.0)
    solid = msp.add_solid([first, (2.0, 0.0), (0.0, 1.0), (2.0, 1.0)])
    solid.dxf.extrusion = extrusion
    if thickness:
        solid.dxf.thickness = thickness
    return solid


@pytest.mark.parametrize(
    "case", ["non_z_extrusion", "mixed_solid_and_line", "empty", "nan_vertex", "thickness"]
)
def test_solid_fast_path_falls_back_to_ezdxf_outside_its_shape(case):
    from dxf_text_builder import _plain_solid_bbox

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    if case == "non_z_extrusion":
        entities = [_solid(msp), _solid(msp, extrusion=(0.0, 0.0, -1.0))]
    elif case == "mixed_solid_and_line":
        entities = [_solid(msp), msp.add_line((0, 0), (5, 5))]
    elif case == "empty":
        entities = []
    elif case == "nan_vertex":
        entities = [_solid(msp, nan=True)]
    else:
        entities = [_solid(msp, thickness=2.5)]
    assert _plain_solid_bbox(entities) is None
    if case != "nan_vertex":
        assert _bbox_tuple(entities) == _ezdxf_bbox_tuple(entities)


def test_solid_fast_path_matches_ezdxf_on_triangles_and_degenerate_fills():
    from dxf_text_builder import _plain_solid_bbox

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    entities = [
        msp.add_solid([(0.1, 0.2), (3.3, 0.2), (1.7, 2.9)]),             # triangle
        msp.add_solid([(5.0, 5.0), (5.0, 5.0), (5.0, 5.0), (5.0, 5.0)]),  # one point
        msp.add_solid([(-1.0, 4.0), (0.5, 4.0), (-1.0, 6.25), (0.5, 6.25)]),
        # A vertex within ezdxf's closeness tolerance of the previous one is
        # skipped by ezdxf; it must be skipped here too, not widen the box.
        # (SOLID order is 0, 1, 3, 2, so vtx2 comes last and is the one skipped.)
        msp.add_solid([(7.0, 1.0), (7.5, 1.0), (7.5 + 5e-13, 2.0), (7.5, 2.0)]),
    ]
    assert _plain_solid_bbox(entities) == _ezdxf_bbox_tuple(entities)
    assert _plain_solid_bbox(entities)[2] == 7.5
    # ezdxf still counts a fill whose vertices all coincide as that one point.
    lone_point = [msp.add_solid([(9.0, 9.0), (9.0, 9.0), (9.0, 9.0)])]
    assert _plain_solid_bbox(lone_point) == _ezdxf_bbox_tuple(lone_point) == (9.0, 9.0, 9.0, 9.0)
