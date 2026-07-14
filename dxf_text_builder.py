# -*- coding: utf-8 -*-
# dxf_text_builder.py -- NormalizedText -> DXF text entities
# Copyright (c) 2024-2026 BlueCollar Systems -- BUILT. NOT BOUGHT.
# Licensed under the MIT License. See LICENSE for details.
"""
Convert :class:`NormalizedText` items produced by *pdfcadcore* into DXF
``TEXT`` or ``MTEXT`` entities via :mod:`ezdxf`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Tuple, Union

import ezdxf
from ezdxf import path as ezdxf_path
from ezdxf.addons import text2path

if TYPE_CHECKING:
    from ezdxf.layouts import BaseLayout

from pdfcadcore.primitives import NormalizedText
from pdfcadcore.import_config import ImportConfig

# Threshold (character count) above which MTEXT is used instead of TEXT.
_MTEXT_THRESHOLD = 120

# DXF text styles created on demand.  Maps font_name -> style_name.
_created_styles: dict[str, str] = {}

# Counter for generating unique style names.
_style_counter = 0


def _ensure_text_style(doc: ezdxf.document.Drawing, font_name: str) -> str:
    """Return the DXF text-style name for *font_name*, creating it if needed."""
    global _style_counter  # noqa: PLW0603

    if not font_name:
        return "Standard"

    if font_name in _created_styles:
        return _created_styles[font_name]

    # Build a short style name
    _style_counter += 1
    style_name = f"S{_style_counter}"

    # Map common PDF font stems to reasonable TrueType fallbacks
    base = font_name.split("-")[0].split("+")[-1]  # strip subset prefix
    ttf = "arial.ttf"
    lower = base.lower()
    if "courier" in lower or "mono" in lower:
        ttf = "cour.ttf"
    elif "times" in lower or "serif" in lower:
        ttf = "times.ttf"
    elif "helv" in lower or "arial" in lower or "sans" in lower:
        ttf = "arial.ttf"

    try:
        doc.styles.add(style_name, font=ttf)
    except ezdxf.DXFTableEntryError:
        pass  # already exists (unlikely)

    _created_styles[font_name] = style_name
    return style_name


def build_text(
    text_item: NormalizedText,
    msp: "BaseLayout",
    layer_name: str,
    config: ImportConfig,
    is_r12: bool = False,
    target_app: str = "generic",
    dxf_version: str = "R2010",
    return_delivered_kind: bool = False,
) -> Union[int, Tuple[str, int]]:
    """Add a TEXT or MTEXT entity to *msp* for the given *text_item*.

    Parameters
    ----------
    text_item:
        A :class:`NormalizedText` from the extraction pipeline.
    msp:
        The ezdxf modelspace (or any layout) to add the entity to.
    layer_name:
        DXF layer name for the entity.
    config:
        Import configuration (controls text_mode, etc.).
    is_r12:
        ``True`` when targeting DXF R12 (limited entity support).
    target_app:
        Target CAD application: ``"generic"``, ``"librecad"``, etc.
        When ``"librecad"``, MTEXT is avoided because LibreCAD has
        known issues with MTEXT bounding boxes.
    dxf_version:
        Target DXF version string (e.g. ``"R2010"``).  When the version
        is ``"R2000"`` or earlier, TEXT entities are used exclusively
        because older DXF versions have limited MTEXT support.
    """
    def _result(delivered_kind: str, count: int) -> Union[int, Tuple[str, int]]:
        """Preserve the legacy count return while exposing actual delivery."""
        if return_delivered_kind:
            return (delivered_kind, int(count))
        return int(count)

    content = text_item.text
    if not content or not content.strip():
        return _result("dxf_text", 0)

    # NormalizedText.font_size is already the PDF nominal text height in mm.
    # Bboxes are placement/reference data and must not resize editable TEXT.
    try:
        height = max(0.5, float(text_item.font_size))
    except (TypeError, ValueError):
        height = 0.5

    # Insertion point
    insert = (text_item.insertion[0], text_item.insertion[1])

    # Rotation (degrees)
    rotation = text_item.rotation or 0.0

    # Base attributes
    attribs: dict = {
        "layer": layer_name,
        "rotation": rotation,
    }

    # Apply source text color when available
    text_color = text_item.color
    if text_color is not None and not is_r12:
        ri, gi, bi = (round(text_color[0] * 255),
                      round(text_color[1] * 255),
                      round(text_color[2] * 255))
        from ezdxf.colors import rgb2int
        attribs["true_color"] = rgb2int((ri, gi, bi))

    doc = msp.doc

    # Resolve text style (skip for R12 -- limited style support)
    if not is_r12 and doc is not None:
        style = _ensure_text_style(doc, text_item.font_name)
        attribs["style"] = style

    geometry_text = (config.text_mode or "").strip().lower() in {"geometry", "glyphs"}
    if geometry_text:
        attribs["height"] = height
        attribs["insert"] = insert
        source = msp.add_text(content, dxfattribs=attribs)
        outline_attribs = {
            key: value
            for key, value in attribs.items()
            if key in {"layer", "color", "true_color", "lineweight", "linetype"}
        }
        try:
            paths = text2path.make_paths_from_entity(source)
            if is_r12:
                outlines = list(
                    ezdxf_path.to_polylines2d(paths, dxfattribs=outline_attribs)
                )
            else:
                outlines = list(
                    ezdxf_path.to_lwpolylines(paths, dxfattribs=outline_attribs)
                )
            if outlines:
                try:
                    msp.delete_entity(source)
                except Exception:
                    try:
                        source.destroy()
                    except Exception:
                        pass
                for entity in outlines:
                    msp.add_entity(entity)
                return _result("outlines", len(outlines))
        except Exception:
            pass
        # The source TEXT remains in the DXF when conversion fails or yields
        # no outlines.  Callers that request delivery metadata must report
        # this genuine Glyphs/Geometry -> Labels fallback.
        return _result("dxf_text", 1)

    # Determine whether MTEXT is allowed.  Force TEXT-only when:
    #   - targeting DXF R12 (no MTEXT support at all)
    #   - target_app is "librecad" (MTEXT bounding-box issues)
    #   - dxf_version is R2000 or earlier (limited MTEXT support)
    force_text = is_r12 or target_app.lower() == "librecad" or dxf_version <= "R2000"

    # Choose TEXT vs MTEXT
    if len(content) > _MTEXT_THRESHOLD and not force_text:
        # MTEXT -- multi-line / long text
        attribs["char_height"] = height
        msp.add_mtext(
            content,
            dxfattribs=attribs,
        ).set_location(insert, attachment_point=1)  # TOP_LEFT
        return _result("dxf_text", 1)
    else:
        # Single-line TEXT
        attribs["height"] = height
        attribs["insert"] = insert
        msp.add_text(
            content,
            dxfattribs=attribs,
        )
        return _result("dxf_text", 1)


def reset_text_styles() -> None:
    """Clear the cached text-style registry (call between documents)."""
    global _style_counter  # noqa: PLW0603
    _created_styles.clear()
    _style_counter = 0
