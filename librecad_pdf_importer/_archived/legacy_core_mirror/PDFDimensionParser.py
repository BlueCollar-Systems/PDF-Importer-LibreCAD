# -*- coding: utf-8 -*-
# PDFDimensionParser.py — Structured dimension parsing
# BlueCollar Systems — BUILT. NOT BOUGHT.
from __future__ import annotations
import re
from .PDFPrimitives import ParsedDimension

MM_PER_INCH = 25.4


def parse(text: str) -> ParsedDimension:
    raw = text
    s = _normalize(raw)
    result = ParsedDimension(raw_text=raw, normalized_text=s)

    qty = _extract_qty(s)
    if qty:
        result.quantity = qty

    # Slot
    m = re.search(r'(\d+(?:\.\d+)?(?:\s*/\s*\d+)?)\s*"?\s*[xX×]\s*(\d+(?:\.\d+)?(?:\s+\d+\s*/\s*\d+)?(?:\s*/\s*\d+)?)\s*"?\s*(?:SLOT|SSL|LSL)', s, re.I)
    if m:
        w, l = _parse_token(m.group(1)), _parse_token(m.group(2))
        if w and l:
            result.kind, result.value = "slot", {"width": w*MM_PER_INCH, "length": l*MM_PER_INCH}
            result.units, result.confidence = "mm", 0.95
            return result

    # Diameter
    if re.search(r'Ø|DIA\b|HOLE', s, re.I):
        clean = re.sub(r'Ø|DIA\b|HOLE\b|\(\d+\)|\d+\s*[-xX]\s*', ' ', s, flags=re.I).strip()
        v = _parse_token(clean)
        if v is not None:
            result.kind, result.value = "diameter", v * MM_PER_INCH
            result.units, result.confidence = "mm", 0.95
            return result

    # Feet-inches
    m = re.match(r"(\d+(?:\.\d+)?)\s*['′]\s*[-–]?\s*(\d+(?:\.\d+)?)?\s*(?:(\d+)\s*/\s*(\d+))?\s*[\"″]?\s*$", s)
    if m:
        ft = float(m.group(1))
        inc = float(m.group(2)) if m.group(2) else 0
        if m.group(3) and m.group(4) and int(m.group(4)) != 0:
            inc += float(m.group(3)) / float(m.group(4))
        result.kind, result.value = "linear", (ft * 12 + inc) * MM_PER_INCH
        result.units, result.confidence = "mm", 0.95
        return result

    # Metric explicit
    m = re.search(r'(\d+(?:\.\d+)?)\s*(MM|CM|M)\b', s, re.I)
    if m:
        v = float(m.group(1))
        u = m.group(2).upper()
        if u == "CM": v *= 10
        elif u == "M": v *= 1000
        result.kind, result.value = "linear", v
        result.units, result.confidence = "mm", 0.90
        return result

    # Imperial fraction/decimal with inch mark
    v = _parse_imperial(s)
    if v is not None:
        result.kind, result.value = "linear", v * MM_PER_INCH
        result.units, result.confidence = "mm", 0.85
        return result

    # Scale
    m = re.search(r'(\d+)\s*:\s*(\d+)', s)
    if m:
        result.kind, result.value = "scale", {"ratio": [float(m.group(1)), float(m.group(2))]}
        result.confidence = 0.80
        return result

    result.confidence = 0.1
    result.warnings.append("Could not parse")
    return result


def _normalize(t):
    t = t.replace('\u2018',"'").replace('\u2019',"'").replace('\u201C','"').replace('\u201D','"')
    t = t.replace('\u2013','-').replace('\u2014','-').replace('\u2044','/')
    t = re.sub(r'DIA\.?', 'DIA', t, flags=re.I)
    return re.sub(r'\s+', ' ', t).strip()


def _extract_qty(s):
    m = re.match(r'\s*\((\d+)\)', s) or re.match(r'\s*(\d+)\s*[-xX]\s*(?:Ø|\d)', s)
    return int(m.group(1)) if m else None


def _parse_token(s):
    if not s: return None
    s = s.strip().rstrip('"\'')
    m = re.match(r'(\d+)\s+(\d+)\s*/\s*(\d+)$', s)
    if m and int(m.group(3)) != 0: return float(m.group(1)) + float(m.group(2))/float(m.group(3))
    m = re.match(r'(\d+)\s*/\s*(\d+)$', s)
    if m and int(m.group(2)) != 0: return float(m.group(1))/float(m.group(2))
    m = re.match(r'(\d+(?:\.\d+)?)$', s)
    if m: return float(m.group(1))
    return None


def _parse_imperial(s):
    m = re.match(r'\s*(\d+)\s+(\d+)\s*/\s*(\d+)\s*["\u2033]?', s)
    if m and int(m.group(3)) != 0: return float(m.group(1)) + float(m.group(2))/float(m.group(3))
    m = re.match(r'\s*(\d+)\s*/\s*(\d+)\s*["\u2033]?\s*$', s)
    if m and int(m.group(2)) != 0: return float(m.group(1))/float(m.group(2))
    m = re.match(r'\s*(\d+(?:\.\d+)?)\s*["\u2033]', s)
    if m: return float(m.group(1))
    return None

