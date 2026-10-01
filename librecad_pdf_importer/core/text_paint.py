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
