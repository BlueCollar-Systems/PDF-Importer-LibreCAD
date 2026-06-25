# -*- coding: utf-8 -*-
"""Detect drawing scale from title-block and page text."""

from __future__ import annotations

import re
from typing import Optional

from .dimension_parser import parse as parse_dimension
from .primitives import PageData, ResolvedScale

MM_PER_INCH = 25.4

_SCALE_LABEL = re.compile(r"\b(SCALE|SC\.?|SCL\.?)\b", re.I)
_ARCH_SCALE = re.compile(
    r'(\d+(?:\.\d+)?(?:\s*/\s*\d+)?)\s*["\u2033]?\s*=\s*(.+)',
    re.I,
)
_RATIO_SCALE = re.compile(r"\b(\d+)\s*:\s*(\d+)\b")


def _parse_arch_inches(token: str) -> Optional[float]:
    if not token:
        return None
    s = token.strip().rstrip('"\'')
    m = re.match(r"(\d+)\s+(\d+)\s*/\s*(\d+)$", s)
    if m and int(m.group(3)) != 0:
        return float(m.group(1)) + float(m.group(2)) / float(m.group(3))
    m = re.match(r"(\d+)\s*/\s*(\d+)$", s)
    if m and int(m.group(2)) != 0:
        return float(m.group(1)) / float(m.group(2))
    m = re.match(r"(\d+(?:\.\d+)?)$", s)
    if m:
        return float(m.group(1))
    return None


def _parse_feet_inches_token(token: str) -> Optional[float]:
    if not token:
        return None
    s = token.strip().upper().rstrip('"\'')
    m = re.match(
        r"(\d+(?:\.\d+)?)\s*(?:'|\u2032|FT|FEET)?\s*[-\u2013]?\s*"
        r"(\d+(?:\.\d+)?)?\s*(?:(\d+)\s*/\s*(\d+))?\s*(?:\"|\u2033|IN|INCH|INCHES)?\s*$",
        s,
    )
    if m:
        feet = float(m.group(1))
        inches = float(m.group(2)) if m.group(2) else 0.0
        if m.group(3) and m.group(4) and int(m.group(4)) != 0:
            inches += float(m.group(3)) / float(m.group(4))
        return feet * 12.0 + inches
    return _parse_arch_inches(s)


def _factor_from_arch_match(raw: str) -> Optional[tuple[float, float]]:
    m = _ARCH_SCALE.search(raw)
    if not m:
        return None
    paper_in = _parse_arch_inches(m.group(1))
    real_in = _parse_feet_inches_token(m.group(2))
    if paper_in and real_in and paper_in > 0:
        return real_in / paper_in, 0.88
    return None


def _factor_from_parsed(parsed) -> Optional[tuple[float, float]]:
    if parsed.kind != "scale" or parsed.value is None:
        return None
    value = parsed.value
    if isinstance(value, dict) and "ratio" in value:
        num, den = value["ratio"]
        if num <= 0 or den <= 0:
            return None
        # 1:50 on paper => multiply drawing by den/num to reach real size.
        return den / num, 0.75
    if isinstance(value, dict) and "from" in value and "to" in value:
        paper_in = _parse_arch_inches(str(value["from"]))
        real_in = _parse_arch_inches(str(value["to"]))
        if paper_in and real_in and paper_in > 0:
            return real_in / paper_in, 0.85
    return None


def _titleblock_score(page: PageData, insertion: tuple[float, float]) -> float:
    x, y = insertion
    score = 0.0
    if y <= page.height * 0.35:
        score += 0.35
    if x >= page.width * 0.45:
        score += 0.35
    return score


def resolve_page_scale(page_data: PageData) -> ResolvedScale:
    """Best-effort scale detection for one page."""
    best: Optional[ResolvedScale] = None

    for txt in page_data.text_items:
        raw = (txt.text or "").strip()
        if not raw:
            continue
        normalized = txt.normalized or raw.upper()
        parsed = parse_dimension(raw)
        factor_conf = _factor_from_parsed(parsed)
        if not factor_conf:
            factor_conf = _factor_from_arch_match(raw)
        if not factor_conf:
            m = _RATIO_SCALE.search(normalized)
            if m:
                parsed = parse_dimension(f"{m.group(1)}:{m.group(2)}")
                factor_conf = _factor_from_parsed(parsed)
        if not factor_conf:
            continue

        factor, base_conf = factor_conf
        conf = base_conf + _titleblock_score(page_data, txt.insertion)
        if _SCALE_LABEL.search(normalized):
            conf += 0.15
        if "titleblock_like" in txt.generic_tags:
            conf += 0.10
        if "scale_like" in txt.generic_tags:
            conf += 0.10
        conf = min(conf, 0.98)

        candidate = ResolvedScale(
            factor=float(factor),
            notation=raw,
            source="titleblock" if conf >= 0.70 else "page_text",
            confidence=round(conf, 3),
        )
        if best is None or candidate.confidence > best.confidence:
            best = candidate

    if best:
        return best

    return ResolvedScale(
        factor=1.0,
        notation="1:1",
        source="default",
        confidence=0.0,
        fallback_reason="no_scale_detected",
    )


def probe_page_scale(page, page_num: int = 1) -> ResolvedScale:
    """Detect scale from page text only (no vector primitive extraction)."""
    from .generic_classifier import classify_text
    from .primitive_extractor import _extract_text
    from .primitives import PageData

    page_h = float(page.rect.height)
    page_w = float(page.rect.width)
    text_items = _extract_text(page, page_h, page_num, flip_y=True, scale=1.0)
    page_data = PageData(
        page_number=page_num,
        width=page_w,
        height=page_h,
        text_items=text_items,
    )
    classify_text(page_data)
    return resolve_page_scale(page_data)


__all__ = ["resolve_page_scale", "probe_page_scale"]
