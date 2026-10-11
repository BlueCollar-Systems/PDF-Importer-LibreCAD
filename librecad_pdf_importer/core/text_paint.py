"""Bind fill-only glyph delivery to observed source character paint."""
from collections import defaultdict
import hashlib
import json
import math
import re


def _font(name):
    return re.sub(r"^[A-Z]{6}\+", "", str(name or ""))


def _point(value):
    point = tuple(float(v) for v in value)
    if len(point) != 2 or not all(math.isfinite(v) for v in point):
        raise ValueError("source text paint origin is not finite")
    return point


def _identity(item):
    layout = tuple(item.source_char_layout)
    if not layout or "".join(c.text for c in layout) != item.text:
        raise ValueError("source text paint inventory is incomplete")
    chars = [(c.text, c.glyph_id, _point(c.source_origin_pdf)) for c in layout]
    if any(type(glyph_id) is not int or glyph_id < 0
           for text, glyph_id, _ in chars if text.strip()):
        raise ValueError("source text paint glyph identity is unknown")
    value = [item.page_number, item.id, _font(item.font_name), item.text, chars]
    return hashlib.sha256(json.dumps(value, ensure_ascii=True).encode("ascii")).hexdigest()


def fill_only_text_receipts(page, items, source_sha256):
    """Unknown, mixed, stroked or ambiguous paint never authorizes omission."""
    try:
        traced = defaultdict(set)
        for span in page.get_texttrace():
            paint_type = span["type"]
            if type(paint_type) is not int or not _font(span["font"]):
                return {}
            for char in span["chars"]:
                if type(char[0]) is not int or type(char[1]) is not int or char[1] < 0:
                    return {}
                key = (_font(span["font"]), chr(char[0]), _point(char[2]), char[1])
                traced[key].add(paint_type)
    except (AttributeError, KeyError, TypeError, ValueError, RuntimeError, OverflowError):
        return {}
    receipts = {}
    for item in items:
        try:
            if item.page_number != page.number + 1:
                continue
            signature = _identity(item)
            keys = [(_font(item.font_name), c.text, _point(c.source_origin_pdf), c.glyph_id)
                    for c in item.source_char_layout if c.text.strip()]
            if not keys or any(traced.get(key) != {0} for key in keys):
                continue
            source_id = f"text_span:{item.page_number}:{item.id}"
            receipts[source_id] = {
                "schema": "bcs.source_text_fill/1", "source_id": source_id,
                "source_pdf_sha256": source_sha256, "source_page_number": item.page_number,
                "source_character_sha256": signature, "paint_type": 0,
                "painted_character_count": len(keys),
            }
        except (AttributeError, TypeError, ValueError, OverflowError):
            continue
    return receipts


def bound_fill_receipt(item, receipts):
    """Revalidate after export page placement; source coordinates never move."""
    try:
        source_id = f"text_span:{item.page_number}:{item.id}"
        receipt = receipts.get(source_id)
        if (not isinstance(receipt, dict)
                or receipt.get("schema") != "bcs.source_text_fill/1"
                or receipt.get("source_id") != source_id
                or receipt.get("source_page_number") != item.page_number
                or type(receipt.get("paint_type")) is not int or receipt["paint_type"] != 0
                or not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("source_pdf_sha256", "")))
                or receipt.get("source_character_sha256") != _identity(item)
                or receipt.get("painted_character_count") != sum(bool(c.text.strip()) for c in item.source_char_layout)):
            return None
        return dict(receipt)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def fill_backed_text_receipts(page, items, source_sha256, *, check_cancel=lambda: None):
    """Positive original-source proof for fixed ink on a painted rectangle.

    Unknown traces, clip scopes, partial coverage and ambiguous intermediate
    paint never infer a background from a model-space bounding box.
    """
    from ..ink_color import is_near_black_neutral, rgb8, source_paint_rgb8
    from conversion_control import ActivePageCancelled

    try:
        draws = list(page.get_drawings(extended=True))
        log = list(page.get_bboxlog())
        paper_rect = tuple(page.rect * page.derotation_matrix)
        traced = defaultdict(set)
        for span in page.get_texttrace():
            if span["type"] != 0 or type(span["seqno"]) is not int:
                continue
            seqno = span["seqno"]
            if not 0 <= seqno < len(log) or log[seqno][0] != "fill-text":
                return {}
            for char in span["chars"]:
                traced[(_font(span["font"]), chr(char[0]), char[1], _point(char[2]))].add(seqno)
        rectangles = []
        for index, drawing in enumerate(draws):
            if index % 64 == 0:
                check_cancel()
            parts = drawing.get("items") or []
            seqno = drawing.get("seqno")
            if (drawing.get("type") not in ("f", "fs") or drawing.get("level") != 0
                    or drawing.get("layer") or drawing.get("fill_opacity") != 1.0
                    or type(seqno) is not int or not 0 <= seqno < len(log)
                    or log[seqno][0] != "fill-path" or len(parts) != 1 or parts[0][0] != "re"):
                continue
            rect = tuple(float(v) for v in parts[0][1])
            fill = tuple(float(v) for v in drawing["fill"])
            if (len(rect) != 4 or len(fill) != 3 or not all(math.isfinite(v) for v in (*rect, *fill))
                    or rect[0] >= rect[2] or rect[1] >= rect[3]
                    or any(v < 0 or v > 1 for v in fill)):
                continue
            if (seqno == 0 and drawing["type"] == "f" and fill == (1.0, 1.0, 1.0)
                    and all(abs(a-b) <= 1e-6 for a, b in zip(rect, paper_rect, strict=True))):
                continue  # An omitted paper backdrop is not a visible white panel.
            inset = float(drawing.get("width", 0.0)) / 2 if drawing["type"] == "fs" else 0.0
            if not math.isfinite(inset) or inset < 0:
                continue
            rectangles.append((seqno, rect, rgb8(fill), inset))
    except ActivePageCancelled:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, RuntimeError, OverflowError):
        return {}

    def intersects(a, b):
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

    receipts = {}
    for index, item in enumerate(items):
        if index % 32 == 0:
            check_cancel()
        try:
            observed = rgb8(item.color)
            if item.page_number != page.number + 1 or not is_near_black_neutral(*observed):
                continue
            identity = _identity(item)
            chars = [c for c in item.source_char_layout if c.text.strip()]
            keys = [(_font(item.font_name), c.text, c.glyph_id, _point(c.source_origin_pdf)) for c in chars]
            seqnos = set()
            if not keys or any(len(traced.get(key, ())) != 1 for key in keys):
                continue
            for key in keys:
                seqnos.update(traced[key])
            if len(seqnos) != 1:
                continue
            text_seqno = next(iter(seqnos))
            points = [_point(point) for char in chars for point in char.source_quad_pdf]
            if len(points) != len(chars) * 4:
                continue
            text_rect = (min(p[0] for p in points), min(p[1] for p in points),
                         max(p[0] for p in points), max(p[1] for p in points))
            candidates = [(seq, rect, fill) for seq, rect, fill, inset in rectangles
                          if seq < text_seqno and all(rect[0]+inset+1e-6 < x < rect[2]-inset-1e-6
                                                     and rect[1]+inset+1e-6 < y < rect[3]-inset-1e-6
                                                     for x, y in points)]
            if not candidates:
                continue
            seq, rect, fill = max(candidates, key=lambda row: row[0])
            # A rectangle's own outline is harmless: it is outside all enclosed
            # glyph quads. Other intervening paints with intersecting ink bounds
            # make the context unknown, including an image or partial mask.
            unknown = [(n, row) for n, row in enumerate(log[seq+1:text_seqno], seq+1)
                       if intersects(tuple(row[1]), text_rect)
                       and not (n == seq+1 and row[0] == "stroke-path"
                                and any(d.get("seqno") == seq and d.get("type") == "fs" for d in draws))]
            if unknown:
                continue
            source_id = f"text_span:{item.page_number}:{item.id}"
            receipts[source_id] = {
                "schema": "bcs.source_rectangle_backed_ink/1", "source_id": source_id,
                "source_pdf_sha256": source_sha256, "source_page_number": item.page_number,
                "source_character_sha256": identity, "source_text_seqno": text_seqno,
                "source_rectangle_seqno": seq, "source_rectangle_pdf": list(rect),
                "source_rectangle_rgb": list(fill), "source_rgb": list(observed),
                "delivered_rgb": list(source_paint_rgb8(*observed)),
            }
        except (AttributeError, KeyError, TypeError, ValueError, RuntimeError, OverflowError):
            continue
    return receipts


def bound_fill_backed_receipt(item):
    """Bind an export-only color choice to the unchanged original characters."""
    from ..ink_color import is_near_black_neutral, rgb8, source_paint_rgb8
    receipt = getattr(item, "_source_fill_backed_ink_receipt", None)
    try:
        observed = rgb8(item.color)
        if (not isinstance(receipt, dict) or receipt.get("schema") != "bcs.source_rectangle_backed_ink/1"
                or receipt.get("source_id") != f"text_span:{item.page_number}:{item.id}"
                or receipt.get("source_page_number") != item.page_number
                or not re.fullmatch(r"[0-9a-f]{64}", receipt.get("source_pdf_sha256", ""))
                or receipt.get("source_character_sha256") != _identity(item)
                or not is_near_black_neutral(*observed)
                or receipt.get("source_rgb") != list(observed)
                or receipt.get("delivered_rgb") != list(source_paint_rgb8(*observed))):
            return None
        return dict(receipt)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
