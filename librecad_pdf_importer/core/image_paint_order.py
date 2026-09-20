"""Bind editable content to the source intervals separated by image paints.

This is intentionally not a general PDF compositor. It preserves the existing
vector/text order within each interval, but cannot move an opaque image across
source content. All coordinates used for identity are original PDF coordinates.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
import math


@dataclass
class ImagePaintOrder:
    image_seqnos: tuple[int, ...] = ()
    primitive_keys: dict[int, int] = field(default_factory=dict)
    text_keys: dict[int, int] = field(default_factory=dict)
    image_keys: dict[int, int] = field(default_factory=dict)


def _finite_tuple(value, count):
    result = tuple(float(component) for component in value)
    if len(result) != count or not all(math.isfinite(component) for component in result):
        raise ValueError("image paint identity has invalid source coordinates")
    return result


def bind_image_paint_order(page, page_data, placements):
    """Return a fully bound order for individual images, or no composite order.

    Composite/page rasters have their own explicit display contract. A genuine
    binding failure for individual images raises instead of guessing an order.
    """
    if not placements or any(
        image.source_kind not in {"xobject_image", "inline_image"}
        or image.alpha_kind not in {"opaque", "rectangular_opaque"}
        for image in placements
    ):
        return None
    image_info = list(page.get_image_info(hashes=True, xrefs=True))
    bboxlog = list(page.get_bboxlog())
    events = [
        (seqno, _finite_tuple(row[1], 4))
        for seqno, row in enumerate(bboxlog)
        if row[0] == "fill-image"
    ]
    if len(image_info) != len(events):
        raise ValueError("source image paint and occurrence inventories disagree")
    for info, (_seqno, bbox) in zip(image_info, events, strict=True):
        if _finite_tuple(info["bbox"], 4) != bbox:
            raise ValueError("source image paint bbox disagrees with its occurrence")
    order = ImagePaintOrder(image_seqnos=tuple(event[0] for event in events))
    available = list(range(len(image_info)))
    for placement_index, image in enumerate(placements):
        matches = []
        for ordinal in available:
            info = image_info[ordinal]
            if int(info.get("xref") or 0) != int(image.xref):
                continue
            if _finite_tuple(info["bbox"], 4) != _finite_tuple(image.source_bbox_pdf, 4):
                continue
            if (int(info["width"]), int(info["height"])) != tuple(image.pixel_size):
                continue
            if image.source_kind == "inline_image":
                if int(info["number"]) != image.source_number:
                    continue
            elif _finite_tuple(info["transform"], 6) != _finite_tuple(image.affine_pdf, 6):
                continue
            matches.append(ordinal)
        if not matches:
            raise ValueError("delivered image has no exact source paint occurrence")
        # Repeated identical XObject+transform occurrences are consumed in source
        # order. They have identical pixels/geometry; none is merged or dropped.
        ordinal = matches[0]
        available.remove(ordinal)
        order.image_keys[placement_index] = ordinal * 2 + 1
    if available:
        raise ValueError("source image occurrence has no delivered image placement")

    def content_key(seqno):
        if (not isinstance(seqno, int) or isinstance(seqno, bool)
                or not 0 <= seqno < len(bboxlog)):
            raise ValueError("editable content has no valid source paint sequence")
        if seqno in order.image_seqnos:
            raise ValueError("editable source paint sequence identifies an image")
        return 2 * bisect_right(order.image_seqnos, seqno)

    for primitive in page_data.primitives:
        order.primitive_keys[primitive.id] = content_key(primitive.source_draw_order)

    traced = defaultdict(set)
    for span in page.get_texttrace():
        seqno = span["seqno"]
        key = content_key(seqno)
        for char in span["chars"]:
            traced[(chr(char[0]), _finite_tuple(char[2], 2))].add(key)
    for item in page_data.text_items:
        keys = set()
        if not item.source_char_layout and item.text.strip():
            raise ValueError("text has no original character paint identity")
        for char in item.source_char_layout:
            if not char.text.strip():
                continue  # MuPDF may synthesize spaces; they have no painted ink.
            matches = traced.get((char.text, _finite_tuple(char.source_origin_pdf, 2)))
            if not matches:
                raise ValueError(f"text item {item.id} character {char.text!r} has no source paint occurrence")
            if len(matches) != 1:
                raise ValueError(f"text item {item.id} character paint order is ambiguous across an image")
            keys.update(matches)
        if len(keys) > 1:
            raise ValueError(f"grouped source text item {item.id} crosses an image paint boundary")
        order.text_keys[item.id] = next(iter(keys), 0)
    return order


def apply_image_paint_order(layout, keys):
    """Set both physical DXF entity order and its explicit redraw-order table."""
    if not keys:
        return
    entities = list(layout)
    handles = [str(entity.dxf.handle) for entity in entities]
    if len(set(handles)) != len(handles) or set(handles) != set(keys):
        raise ValueError("image paint ordering does not cover the exact native entity set")
    ordered = sorted(entities, key=lambda entity: keys[str(entity.dxf.handle)])
    # Keep the existing EntitySpace object, all entities, handles and owners.
    # Some CAD readers use ENTITIES order; others honor SORTENTSTABLE.
    layout.entity_space.entities[:] = ordered
    layout.set_redraw_order([
        (str(entity.dxf.handle), f"{index:X}")
        for index, entity in enumerate(ordered, start=1)
    ])


def verify_serialized_image_paint_order(path, expected_handles):
    """Check actual ENTITIES and SORTENTSTABLE bytes with bounded memory.

    Linked child VERTEX/ATTRIB records are not top-level entities; only the
    handles of the exact planned modelspace set participate in this proof.
    Existing candidate verification separately verifies native entity counts.
    """
    expected = tuple(expected_handles)
    expected_set = set(expected)
    physical = []
    sort_records = []
    current_sort = None
    in_entities = False
    section_pending = False
    # Only ASCII group codes and handles are read here. A pre-R2007 DXF is cp1252,
    # so one TEXT value with a degree sign must not cost the sheet a decode error.
    with open(path, encoding="utf-8", errors="surrogateescape") as stream:
        while True:
            code_line = stream.readline()
            if not code_line:
                break
            value_line = stream.readline()
            if not value_line:
                raise ValueError("truncated serialized image paint order")
            code, value = code_line.strip(), value_line.strip()
            if code == "0":
                if current_sort is not None:
                    sort_records.append(current_sort)
                    current_sort = None
                if value == "SECTION":
                    section_pending = True
                elif value == "ENDSEC":
                    in_entities = False
                elif value == "SORTENTSTABLE":
                    current_sort = []
            elif code == "2" and section_pending:
                in_entities = value == "ENTITIES"
                section_pending = False
            elif code == "5" and in_entities and value in expected_set:
                physical.append(value)
            if current_sort is not None and code in {"331", "5"}:
                current_sort.append((code, value))
    if tuple(physical) != expected:
        raise ValueError("serialized physical image paint order changed")
    # A SORTENTSTABLE has its own handle first, then alternating entity handle
    # (331) and redraw handle (5). Other layout tables are not accepted in place
    # of the modelspace table containing our exact entity set.
    wanted = [(tag, value) for i, handle in enumerate(expected, 1)
              for tag, value in (("331", handle), ("5", f"{i:X}"))]
    matches = [record[1:] for record in sort_records if record and
               {value for code, value in record if code == "331"} == expected_set]
    if matches != [wanted]:
        raise ValueError("serialized explicit image redraw order changed")
