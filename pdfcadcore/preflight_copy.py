# -*- coding: utf-8 -*-
"""Shared plain-English pre-import guidance for all PDF Vector Importer hosts."""

from __future__ import annotations

PREFLIGHT_HEADLINE = (
    "Professional import — maximum fidelity. Auto picks vector, raster, or hybrid per page."
)

PREFLIGHT_TEXT_MODES = (
    "Text modes: Labels = editable text you can change later; "
    "Outlines / Glyphs / Geometry = vector fidelity (exact strokes, not editable). "
    "LibreCAD is 2D only — use Labels or Outlines; it has no true 3D text."
)

PREFLIGHT_SCALE_NOTE = (
    "Scale is detected from title blocks when possible. "
    "If import_report shows a scale warning, verify one known dimension before takeoff."
)

PREFLIGHT_IMPORT_REPORT = (
    "Every import can write import_report.json with a plain-English human_summary "
    "and scale cross-check notes for support."
)


def preflight_paragraph(host: str = "") -> str:
    """Return a short pre-import paragraph suitable for INSTALL docs and UI."""

    parts = [PREFLIGHT_HEADLINE, PREFLIGHT_TEXT_MODES]
    key = str(host or "").strip().lower()
    if key == "librecad":
        parts.append("LibreCAD: Labels (editable DXF TEXT) or Outlines only — no 3D text.")
    elif key in {"sketchup", "freecad", "blender"}:
        parts.append(
            "SketchUp / FreeCAD / Blender: Labels for editable text; "
            "Outlines or Glyphs for exact visual fidelity; 3D text where the host supports it."
        )
    parts.append(PREFLIGHT_SCALE_NOTE)
    return " ".join(parts)


__all__ = [
    "PREFLIGHT_HEADLINE",
    "PREFLIGHT_TEXT_MODES",
    "PREFLIGHT_SCALE_NOTE",
    "PREFLIGHT_IMPORT_REPORT",
    "preflight_paragraph",
]
