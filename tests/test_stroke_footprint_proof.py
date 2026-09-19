"""Round-cap ink is a physical capsule, including a zero-length PDF dot."""
import math

import pytest

from librecad_pdf_importer.core.stroke_footprint import capsule_edges, short_round_stroke, unclipped_capsules, bind_similarity_strokes


def stroke(**changes):
    row = dict(type="s", items=[("l", (10., 20.), (10.01, 20.))], width=12.,
               lineCap=(1, 1, 1), color=(1., .5, .25), fill=None,
               closePath=False, stroke_opacity=1., dashes="[] 0")
    row.update(changes)
    return row


def test_near_zero_line_keeps_full_capsule_not_tiny_centerline():
    cap = short_round_stroke(stroke())
    assert cap["area"] == pytest.approx(math.pi * 36 + .12)
    edges = capsule_edges(cap)
    assert [edge[0] for edge in edges] == ["line", "arc", "line", "arc"]
    points = [point for edge in edges for point in edge[1:]]
    assert (min(p[0] for p in points), max(p[0] for p in points)) == pytest.approx((4, 16.01))
    assert (min(p[1] for p in points), max(p[1] for p in points)) == (14, 26)
    assert all(edges[i][-1] == edges[(i + 1) % len(edges)][1] for i in range(len(edges)))


def test_zero_length_is_circle_with_no_degenerate_edges():
    cap = short_round_stroke(stroke(items=[("l", (10, 20), (10, 20))]))
    assert cap["area"] == pytest.approx(math.pi * 36)
    assert [edge[0] for edge in capsule_edges(cap)] == ["arc", "arc"]


def test_rotated_capsule_keeps_width_and_length_without_mutating_source():
    row = stroke(items=[("l", (0, 0), (3, 4))], width=6)
    cap = short_round_stroke(row)
    assert cap["length"] == 5
    assert cap["area"] == pytest.approx(30 + 9 * math.pi)
    edges = capsule_edges(cap)
    assert edges[0][1] == pytest.approx((-2.4, 1.8))
    assert row["items"] == [("l", (0, 0), (3, 4))]


@pytest.mark.parametrize("changes", [
    {"lineCap": (0, 0, 0)}, {"lineCap": (1, 0, 1)}, {"lineCap": None},
    {"width": 0}, {"width": float("nan")}, {"stroke_opacity": 0}, {"stroke_opacity": .5},
    {"dashes": "[3 2] 0"}, {"type": "fs"}, {"fill": (1, 1, 1)},
    {"closePath": True}, {"color": None},
    {"items": [("l", (0, 0), (13, 0))]},
    {"items": [("l", (0, 0), (0, 0)), ("l", (0, 0), (1, 1))]},
    {"items": [("l", (0, 0), (float("inf"), 0))]},
])
def test_unproven_path_cases_keep_existing_centerline_path(changes):
    assert short_round_stroke(stroke(**changes)) is None


def test_rectangular_clip_must_cover_caps_not_only_centerline():
    row = stroke(seqno=7, level=1)
    full = dict(type="clip", level=0, items=[("re", (0, 0, 30, 40))])
    thin = dict(type="clip", level=0, items=[("re", (9, 19, 11, 21))])
    assert 7 in unclipped_capsules([full, row], (0, 0, 100, 100))
    assert unclipped_capsules([thin, row], (0, 0, 100, 100)) == {}
    assert unclipped_capsules([row], (9, 19, 11, 21)) == {}


def test_unproven_clip_does_not_invent_caps_and_expired_clip_is_removed():
    clip = dict(type="clip", level=0, items=[("c", (0, 0), (0, 1), (1, 1), (1, 0))])
    assert not unclipped_capsules([clip, stroke(seqno=7, level=1)], (0, 0, 100, 100))
    assert 7 in unclipped_capsules([clip, stroke(seqno=7, level=0)], (0, 0, 100, 100))


def test_group_blend_is_recorded_without_being_called_native_compositing_proof():
    group = dict(type="group", level=0, blendmode="Multiply")
    proof = unclipped_capsules([group, stroke(seqno=7, level=1)], (0, 0, 100, 100))[7]
    assert proof["source_blend_modes"] == ["Multiply"]


def test_duplicate_source_identity_has_no_unique_proof():
    row = stroke(seqno=7)
    assert not unclipped_capsules([row, row], (0, 0, 100, 100))


def test_translucent_group_does_not_become_opaque_native_ink():
    group = dict(type="group", level=0, blendmode="Normal", opacity=.5)
    assert not unclipped_capsules([group, stroke(seqno=7, level=1)], (0, 0, 100, 100))


def test_source_ctm_proof_accepts_uniform_caps_and_rejects_elliptical_caps():
    import pymupdf as fitz
    for matrix, expected in [("1 0 0 1 0 0", True), ("2 0 0 2 0 0", True),
                             ("2 0 0 1 0 0", False), ("1 0 .5 1 0 0", False)]:
        with fitz.open() as doc:
            page = doc.new_page(width=300, height=300)
            stream = doc.get_new_xref()
            doc.update_object(stream, "<<>>")
            doc.update_stream(stream, (f"q {matrix} cm 12 w 1 J 1 .5 .25 RG 30 30 m 30.01 30 l S Q").encode())
            page.set_contents(stream)
            rows = page.get_drawings(extended=True)
            proofs = unclipped_capsules(rows, page.rect)
            bound = bind_similarity_strokes(proofs, rows, page.get_svg_image(text_as_path=True))
            assert bool(bound) is expected


def test_duplicate_or_inherited_unproven_svg_strokes_do_not_certify_caps():
    row = stroke(seqno=7)
    proof = unclipped_capsules([row], (0, 0, 100, 100))
    path = '<path transform="matrix(1,0,0,1,0,0)" stroke-width="12" stroke-linecap="round" fill="none" stroke="#ff8040" d="M10 20H10.01"/>'
    assert 7 in bind_similarity_strokes(proof, [row], '<svg>'+path+'</svg>')
    assert not bind_similarity_strokes(proof, [row], '<svg>'+path+path+'</svg>')
    assert not bind_similarity_strokes(proof, [row], '<svg><g transform="scale(2,1)">'+path+'</g></svg>')
    assert not bind_similarity_strokes(proof, [row], '<svg><defs>'+path+'</defs></svg>')


def test_one_uniform_svg_stroke_cannot_certify_a_coincident_elliptical_stroke():
    import pymupdf as fitz
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=300)
        stream = doc.get_new_xref()
        doc.update_object(stream, "<<>>")
        doc.update_stream(stream, b'q 2 0 0 1 0 0 cm 1 .5 .25 RG 12 w 1 J 30 30 m 30.01 30 l S Q '
                                 b'q 1 .5 .25 RG 16.970562 w 1 J 60 30 m 60.02 30 l S Q')
        page.set_contents(stream)
        rows = page.get_drawings(extended=True)
        proofs = unclipped_capsules(rows, page.rect)
        assert len(proofs) == 2
        assert not bind_similarity_strokes(proofs, rows, page.get_svg_image(text_as_path=True))
