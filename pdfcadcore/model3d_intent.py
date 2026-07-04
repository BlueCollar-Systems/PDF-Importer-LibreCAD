"""Detect whether a drawing supports honest 3D model generation (Round 8).

Owner directive 2026-07-04: "in the software that's capable of it, I want
the option to generate a 3D model of the PDF if it makes sense to do so."

"Makes sense" is decided from evidence in the drawing itself, never
guessed: a 2D drawing only supports 3D generation when its text carries
explicit third-dimension data. Two evidence classes ship in slice 1:

  plates   -- plate callouts encode thickness: ``PL3/8"X6 7/8"`` means a
              3/8 in thick plate. The profile outline is on the sheet; the
              callout supplies the missing (extrusion) dimension.
  members  -- rolled-shape designations (``W12X30``, ``L3X3X3/8``,
              ``HSS6X6X1/4``, ``C8X11.5``…) name a full cross-section in
              the AISC database; a nearby length (BOM row or dimension)
              completes the solid.

The module is analysis-only and host-neutral: hosts that can build solids
(FreeCAD, Blender, SketchUp) act on the candidates; LibreCAD stays
honestly 2D and just reports what a 3D-capable host could do. Emit the
result under ``import_report.extra["model_3d_intent"]``.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional

__all__ = [
    "PlateCandidate",
    "MemberCandidate",
    "Model3DIntent",
    "analyze_model3d_intent",
    "parse_fraction_inches",
]

# ---------------------------------------------------------------------------
# fraction / dimension text helpers

_FRACTION = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"


def parse_fraction_inches(token: str) -> Optional[float]:
    """'3/8' -> 0.375, '6 7/8' -> 6.875, '1.25' -> 1.25 (inches)."""
    s = (token or "").strip().strip('"').strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d+)\s+(\d+)/(\d+)", s)
    if m:
        whole, num, den = (int(g) for g in m.groups())
        return whole + num / den if den else None
    m = re.fullmatch(r"(\d+)/(\d+)", s)
    if m:
        num, den = (int(g) for g in m.groups())
        return num / den if den else None
    m = re.fullmatch(r"\d+(?:\.\d+)?", s)
    if m:
        return float(s)
    return None


# ---------------------------------------------------------------------------
# candidates

@dataclass
class PlateCandidate:
    """A plate callout whose thickness enables an honest extrusion."""

    callout: str
    thickness_in: float
    width_in: Optional[float] = None
    length_in: Optional[float] = None
    count: int = 1
    mark: Optional[str] = None  # piece mark from a BOM row (p1016 ...)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MemberCandidate:
    """A rolled-shape designation resolvable against the AISC database."""

    designation: str
    family: str  # W, L, C, HSS, PIPE, WT, MC, S, HP
    length_in: Optional[float] = None
    count: int = 1
    mark: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Model3DIntent:
    feasible: bool
    plates: List[PlateCandidate] = field(default_factory=list)
    members: List[MemberCandidate] = field(default_factory=list)
    skipped_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feasible": self.feasible,
            "plates": [p.to_dict() for p in self.plates],
            "members": [m.to_dict() for m in self.members],
            "skipped_reason": self.skipped_reason,
        }


# ---------------------------------------------------------------------------
# detection

# PL3/8"X6 7/8"  |  PL 3/8 X 7  |  PL3/4"X7"X1'-2"
_PLATE_RE = re.compile(
    r"\bPL\s*(" + _FRACTION + r")\s*\"?\s*[xX]\s*(" + _FRACTION + r")\s*\"?"
    r"(?:\s*[xX]\s*([0-9'\-\s/\.\"]+))?",
)

# W12X30, W8X15, L3X3X3/8, C8X11.5, HSS6X6X1/4, PIPE3STD, WT5X22.5, HP12X53
_MEMBER_RE = re.compile(
    r"\b(W|S|M|HP|WT|MT|ST|C|MC)\s?(\d{1,3})\s?[xX]\s?(\d{1,3}(?:\.\d+)?)\b"
    r"|\b(L)\s?(\d{1,2})\s?[xX]\s?(\d{1,2})\s?[xX]\s?(" + _FRACTION + r")\b"
    r"|\b(HSS)\s?(\d{1,2}(?:\.\d+)?)\s?[xX]\s?(\d{1,2}(?:\.\d+)?)\s?[xX]\s?(" + _FRACTION + r")\b"
    r"|\b(PIPE)\s?(\d{1,2})\s?(STD|XS|XXS)\b",
)

# 13'-11 1/4" style lengths (BOM LENGTH column)
_FEET_INCH_RE = re.compile(
    r"(\d+)'\s*-?\s*(\d+(?:\s+\d+/\d+|/\d+)?(?:\.\d+)?)?\s*\"?")

_MARK_RE = re.compile(r"\b([a-z]{1,2}\d{3,5}(?:[A-Z]{1,3}\d{0,3})?)\b")


def _feet_inches_to_inches(text: str) -> Optional[float]:
    m = _FEET_INCH_RE.search(text or "")
    if not m:
        return None
    feet = int(m.group(1))
    inches = parse_fraction_inches(m.group(2) or "0") or 0.0
    return feet * 12.0 + inches


def _member_from_match(m: "re.Match[str]") -> Optional[MemberCandidate]:
    g = m.groups()
    if g[0]:  # W/S/M/HP/WT/MT/ST/C/MC family
        return MemberCandidate(
            designation=f"{g[0]}{g[1]}X{g[2]}", family=g[0])
    if g[3]:  # L angle
        return MemberCandidate(
            designation=f"L{g[4]}X{g[5]}X{g[6]}", family="L")
    if g[7]:  # HSS
        return MemberCandidate(
            designation=f"HSS{g[8]}X{g[9]}X{g[10]}", family="HSS")
    if g[11]:  # PIPE
        return MemberCandidate(
            designation=f"PIPE{g[12]}{g[13]}", family="PIPE")
    return None


def analyze_model3d_intent(
    text_items: Iterable[Any],
    host_supports_3d: bool = True,
) -> Model3DIntent:
    """Scan extracted text for third-dimension evidence.

    ``text_items`` are pdfcadcore ``NormalizedText`` objects (only ``.text``
    is used, so plain strings work in tests). Deduplicates by callout /
    designation, counting repeats; attaches a nearby-in-sequence piece mark
    and a feet-inch length when one appears in the same item's text.
    """
    plates: Dict[str, PlateCandidate] = {}
    members: Dict[str, MemberCandidate] = {}

    for item in text_items:
        text = getattr(item, "text", item)
        if not isinstance(text, str) or not text.strip():
            continue

        mark_m = _MARK_RE.search(text)
        mark = mark_m.group(1) if mark_m else None
        length_in = _feet_inches_to_inches(text)

        for pm in _PLATE_RE.finditer(text):
            thickness = parse_fraction_inches(pm.group(1))
            if thickness is None or not 0.01 <= thickness <= 12.0:
                continue
            width = parse_fraction_inches(pm.group(2))
            callout = re.sub(r"\s+", "", pm.group(0)).upper()
            if callout in plates:
                plates[callout].count += 1
            else:
                plates[callout] = PlateCandidate(
                    callout=callout,
                    thickness_in=round(thickness, 6),
                    width_in=round(width, 6) if width is not None else None,
                    length_in=(pm.group(3) and
                               _feet_inches_to_inches(pm.group(3))) or length_in,
                    mark=mark,
                )

        for mm in _MEMBER_RE.finditer(text):
            cand = _member_from_match(mm)
            if cand is None:
                continue
            key = cand.designation
            if key in members:
                members[key].count += 1
            else:
                cand.length_in = length_in
                cand.mark = mark
                members[key] = cand

    found = bool(plates or members)
    if not host_supports_3d:
        return Model3DIntent(
            feasible=False,
            plates=list(plates.values()),
            members=list(members.values()),
            skipped_reason=(
                "This host is 2D; a 3D-capable host (SketchUp, FreeCAD, "
                "Blender) could generate solids from the detected callouts."
                if found else
                "This host is 2D and no 3D evidence was found."),
        )
    if not found:
        return Model3DIntent(
            feasible=False,
            skipped_reason=(
                "No plate thickness callouts or rolled-shape designations "
                "found - the drawing does not carry enough third-dimension "
                "data for an honest 3D model."),
        )
    return Model3DIntent(feasible=True,
                         plates=list(plates.values()),
                         members=list(members.values()))
