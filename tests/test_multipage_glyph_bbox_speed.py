# -*- coding: utf-8 -*-
"""Glyph certification bbox stays exact without copying every fill triangle.

Combined multi-page sheets spend most of their time in text export. Each
character is a shared SOLID (or straight LWPOLYLINE) definition placed by an
INSERT. Certifying the span used to copy and transform every triangle twice
(once while committing, once while verifying). The fast bbox applies the same
placement matrix to the definition's own vertices.
"""
from __future__ import annotations

import time

import ezdxf

from dxf_text_builder import _bbox_tuple, glyph_outline_bbox, iter_glyph_outline_entities


def _nested_insert(doc, *, solids=True, bulge=False, outer_scale=1.0, child_rotation=0.0, negative=False):
    glyph = doc.blocks.new("G_A")
    if solids:
        for index in range(12):
            x = index * 0.15
            glyph.add_solid([(x, 0.0), (x + 0.1, 0.0), (x + 0.05, 0.2), (x + 0.05, 0.2)])
    else:
        points = [(0.0, 0.0, 0.0, 0.0, 0.4 if bulge else 0.0), (1.0, 0.0), (1.0, 0.4), (0.0, 0.5)]
        glyph.add_lwpolyline(points, format="xyseb" if bulge else "xy", close=True)
    outer = doc.blocks.new("SPAN")
    scale = -0.5 if negative else 0.57
    outer.add_blockref(
        "G_A",
        (0.2, 0.0),
        dxfattribs={"xscale": scale, "yscale": 0.58, "rotation": child_rotation},
    )
    outer.add_blockref(
        "G_A",
        (1.1, 0.05),
        dxfattribs={"xscale": scale, "yscale": 0.58, "rotation": child_rotation + 12.0},
    )
    return doc.modelspace().add_blockref(
        "SPAN",
        (25.0, 40.0),
        dxfattribs={"xscale": outer_scale, "yscale": outer_scale, "rotation": 8.0},
    )


def _slow_bbox(insert):
    return _bbox_tuple(list(iter_glyph_outline_entities(insert)))


def test_solid_glyph_bbox_matches_the_copy_and_transform_path() -> None:
    doc = ezdxf.new("R2010")
    insert = _nested_insert(doc, solids=True, child_rotation=20.0)
    assert glyph_outline_bbox(insert) == _slow_bbox(insert)


def test_straight_lwpolyline_glyph_bbox_matches() -> None:
    doc = ezdxf.new("R2010")
    insert = _nested_insert(doc, solids=False, bulge=False, child_rotation=15.0)
    assert glyph_outline_bbox(insert) == _slow_bbox(insert)


def test_bulge_and_mirror_still_match_by_falling_back() -> None:
    bulged = _nested_insert(ezdxf.new("R2010"), solids=False, bulge=True)
    mirrored = _nested_insert(ezdxf.new("R2010"), solids=True, negative=True)
    assert glyph_outline_bbox(bulged) == _slow_bbox(bulged)
    assert glyph_outline_bbox(mirrored) == _slow_bbox(mirrored)


def test_repeated_solid_glyphs_are_certified_faster_than_copying_them() -> None:
    doc = ezdxf.new("R2010")
    glyph = doc.blocks.new("G")
    for index in range(40):
        x = (index % 8) * 0.2
        y = (index // 8) * 0.2
        glyph.add_solid([(x, y), (x + 0.15, y), (x + 0.08, y + 0.18)])
    span = doc.blocks.new("SPAN")
    for index in range(24):
        span.add_blockref(
            "G",
            (index * 0.9, (index % 3) * 0.4),
            dxfattribs={"xscale": 0.42, "yscale": 0.421, "rotation": float(index % 7)},
        )
    inserts = []
    for index in range(30):
        inserts.append(
            doc.modelspace().add_blockref(
                "SPAN",
                (index * 18.0, (index % 5) * 12.0),
                dxfattribs={"rotation": float(index % 4)},
            )
        )

    for insert in inserts[:3]:
        assert glyph_outline_bbox(insert) == _slow_bbox(insert)

    def _time(fn, repeats: int) -> float:
        started = time.perf_counter()
        for _ in range(repeats):
            for insert in inserts:
                fn(insert)
        return time.perf_counter() - started

    _time(glyph_outline_bbox, 1)  # warm the definition cache
    fast = _time(glyph_outline_bbox, 2)
    slow = _time(_slow_bbox, 2)
    assert fast < slow * 0.5, f"fast bbox {fast:.3f}s was not twice as quick as {slow:.3f}s"
