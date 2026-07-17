# -*- coding: utf-8 -*-
"""Shared plain-English pre-import guidance for all PDF Vector Importer hosts."""

from __future__ import annotations

PREFLIGHT_HEADLINE = (
    "Professional import — maximum fidelity. Auto picks vector, raster, or hybrid per page."
)

PREFLIGHT_TEXT_MODES = (
    "The selected text representation is preserved whenever the host can create it. "
    "A different representation is allowed only after an item-specific impossibility check, "
    "and every fallback or failure is recorded."
)

PREFLIGHT_SCALE_NOTE = (
    "Scale is detected from title blocks when possible. "
    "If import_report shows a scale warning, verify one known dimension before takeoff."
)

PREFLIGHT_IMPORT_REPORT = (
    "Every import can write import_report.json with a plain-English human_summary "
    "and scale cross-check notes for support."
)

SCALE_CROSSCHECK_BANNER = (
    "Scale may be wrong — measure one known dimension on the drawing before takeoff or ordering material."
)

PREFLIGHT_OFFLINE_INSTALL = (
    "Release packages (Windows RBZ, installer EXE, portable ZIP, Blender add-on ZIP) "
    "work without internet after download. Source installs may run preflight_check.py --install once "
    "to vendor Python wheels if lib/ is empty."
)


def preflight_paragraph(host: str = "") -> str:
    """Return a short pre-import paragraph suitable for INSTALL docs and UI."""

    parts = [PREFLIGHT_HEADLINE, PREFLIGHT_TEXT_MODES]
    key = str(host or "").strip().lower()
    if key == "librecad":
        parts.append(
            "LibreCAD: Text remains editable DXF TEXT. Labels first records that "
            "DXF has no native Label entity, then tries Text. Parent-native LFF "
            "substitution is reported and is never called source-font exact. "
            "Grouped Glyphs, raw Geometry, and Raster remain distinct; flat DXF "
            "TEXT cannot be reported as delivered 3D Text."
        )
    elif key == "blender":
        parts.append(
            "Blender: Text = flat editable FONT; 3D Text = extruded FONT; "
            "Glyphs = CURVE; Geometry = MESH; Raster = an aligned item patch. "
            "Blender has no persistent model Label entity, so a Labels request records "
            "that host limitation before trying Text."
        )
    elif key in {"sketchup", "freecad"}:
        parts.append(
            "SketchUp / FreeCAD: Labels for editable text; "
            "Text, Glyphs, Geometry, Raster, and 3D Text remain distinct requested results."
        )
    parts.append(PREFLIGHT_SCALE_NOTE)
    return " ".join(parts)


__all__ = [
    "PREFLIGHT_HEADLINE",
    "PREFLIGHT_TEXT_MODES",
    "PREFLIGHT_SCALE_NOTE",
    "PREFLIGHT_IMPORT_REPORT",
    "PREFLIGHT_OFFLINE_INSTALL",
    "SCALE_CROSSCHECK_BANNER",
    "preflight_paragraph",
]
