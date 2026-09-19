"""Exact local display recipes for source-bound non-text Multiply capsules.

The full source pixel footprint, including outward rounding, must contain only
vector paint. No text, image, shading, or unknown paint may be borrowed into a
display patch. Canonical editable geometry is a separate consumer obligation.
"""
from __future__ import annotations

import hashlib
import json
import math

from .stroke_footprint import unclipped_capsules, bind_similarity_strokes

SCHEMA = "bcs.pdf.nontext-composite/1"
MAX_PATCH_PIXELS = 4_000_000
MAX_PAGE_PIXELS = 32_000_000


def multiply_modes(modes):
    return isinstance(modes, (list, tuple)) and [m for m in modes if m != "Normal"] == ["Multiply"]


def _source_group_declarations(page):
    """Conservatively inspect original PDF dictionaries, not flattened flags.

    MuPDF can report knockout=False for a page with explicit /Group /K true.
    Unrelated declared groups are also checked rather than guessed unreachable.
    """
    doc, records = page.parent, []
    for xref in range(1, doc.xref_length()):
        prefixes = []
        if doc.xref_get_key(xref, "Group")[0] != "null":
            prefixes.append("Group/")
        if doc.xref_get_key(xref, "S") == ("name", "/Transparency"):
            prefixes.append("")
        for prefix in prefixes:
            knockout = doc.xref_get_key(xref, prefix + "K")
            if knockout not in (("null", "null"), ("bool", "false")):
                raise ValueError("Original PDF declares unsupported knockout transparency")
            records.append([xref, prefix, knockout,
                            doc.xref_get_key(xref, prefix + "S"),
                            doc.xref_get_key(xref, prefix + "I")])
    return records


def pixel_count(recipe):
    box = recipe["device_bounds"]
    if (len(box) != 4 or any(type(v) is not int for v in box)
            or box[2] <= box[0] or box[3] <= box[1]):
        raise ValueError("Invalid source composite pixel lattice")
    return (box[2]-box[0]) * (box[3]-box[1])


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _box(value):
    result = tuple(float(v) for v in value)
    if (len(result) != 4 or not all(math.isfinite(v) for v in result)
            or result[0] >= result[2] or result[1] >= result[3]):
        raise ValueError("Invalid composite source bounds")
    return result


def _overlaps(a, b):
    return min(a[2], b[2]) >= max(a[0], b[0]) and min(a[3], b[3]) >= max(a[1], b[1])


def _contains(outer, inner):
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def _page_state(page):
    if int(page.rotation) != 0:
        raise ValueError("Local composite currently requires an unrotated source page")
    box = _box(page.rect)
    if box[:2] != (0., 0.):
        raise ValueError("Local composite currently requires zero-origin page coordinates")
    log = [[str(kind), list(map(float, bounds))] for kind, bounds in page.get_bboxlog()]
    if any(len(row[1]) != 4 or not all(math.isfinite(v) for v in row[1]) for row in log):
        raise ValueError("Invalid source paint inventory")
    return box, log


def qualify_recipes(page, capsule_proofs, *, source_sha256, page_number, dpi=600):
    """Return recipes only for fully certified Multiply capsule footprints.

    ``capsule_proofs`` comes from the independent full-width clip and original
    SVG similarity/unique occurrence proof, not from CAD bounding boxes.
    """
    if (len(source_sha256) != 64 or any(c not in "0123456789abcdef" for c in source_sha256)
            or type(page_number) is not int or page_number < 1
            or type(dpi) is not int or not 72 <= dpi <= 1200):
        raise ValueError("Invalid composite source identity or resolution")
    try:
        page_box, log = _page_state(page)
    except ValueError:
        return []
    if not any(multiply_modes(p.get("source_blend_modes")) for p in capsule_proofs.values()):
        return []
    try:
        group_declarations = _source_group_declarations(page)
    except ValueError:
        return []
    original_rows = page.get_drawings(extended=True)
    groups, source_groups = [], {}
    for row in original_rows:
        level = row.get("level", 0)
        groups = [g for g in groups if g.get("level", 0) < level]
        if row.get("type") == "group":
            groups.append(row)
        elif type(row.get("seqno")) is int and groups and all(
                g.get("opacity", 1) == 1 and g.get("knockout", False) is False
                and g.get("blendmode", "Normal") in ("Normal", "Multiply") for g in groups):
            source_groups[row["seqno"]] = [dict(
                level=g.get("level", 0), blendmode=g.get("blendmode", "Normal"),
                opacity=g.get("opacity", 1), knockout=g.get("knockout", False),
                isolated=g.get("isolated", False), bounds=list(g["rect"])) for g in groups]
    original_svg = page.get_svg_image(text_as_path=True)
    original_proofs = bind_similarity_strokes(
        unclipped_capsules(original_rows, page_box), original_rows,
        original_svg)
    source_svg_sha256 = hashlib.sha256(original_svg.encode()).hexdigest()
    zoom = dpi / 72.
    drawings = {row["seqno"]: row for row in page.get_drawings()
                if type(row.get("seqno")) is int}
    recipes = []
    for seq, proof in sorted(capsule_proofs.items()):
        if (type(seq) is not int or not multiply_modes(proof.get("source_blend_modes"))
                or not proof.get("source_svg_stroke") or seq not in drawings
                or seq not in source_groups
                or seq not in original_proofs or _digest(proof) != _digest(original_proofs[seq])):
            continue
        capsule = proof["capsule"]
        start, end = capsule["start"], capsule["end"]
        width = float(capsule["width"])
        row = drawings[seq]
        if (row.get("type") != "s" or row.get("stroke_opacity") != 1
                or row.get("lineCap") not in ((1, 1, 1), [1, 1, 1])
                or row.get("dashes") not in (None, "[] 0")
                or float(row.get("width", 0)) != width
                or len(row.get("items", ())) != 1 or row["items"][0][0] != "l"
                or list(row["items"][0][1]) != list(start) or list(row["items"][0][2]) != list(end)
                or width <= 0 or not all(math.isfinite(float(v)) for v in (*start, *end, width))):
            continue
        r = width / 2
        ink = (min(start[0], end[0])-r, min(start[1], end[1])-r,
               max(start[0], end[0])+r, max(start[1], end[1])+r)
        clips = proof.get("clip_bounds", ())
        if not clips or not _contains(page_box, ink) or not all(_contains(_box(c), ink) for c in clips):
            continue
        # Render an integral global pixel rectangle. The qualification uses
        # this actual coverage, never the smaller semantic ink rectangle.
        device = (math.floor(ink[0]*zoom), math.floor(ink[1]*zoom),
                  math.ceil(ink[2]*zoom), math.ceil(ink[3]*zoom))
        if pixel_count({"device_bounds": device}) > MAX_PATCH_PIXELS:
            continue  # Retain editable geometry; never silently reduce source DPI.
        coverage = tuple(v/zoom for v in device)
        if not _contains(page_box, coverage):
            continue
        intersects = [(i, kind, bounds) for i, (kind, bounds) in enumerate(log)
                      if _overlaps(coverage, bounds)]
        if (not intersects or seq >= len(log) or log[seq][0] != "stroke-path"
                or not any(i == seq for i, _, _ in intersects)
                or any(kind not in ("fill-path", "stroke-path") for _, kind, _ in intersects)):
            continue
        recipes.append({"schema": SCHEMA, "source_sha256": source_sha256, "page": page_number,
                        "source_paint_order": seq, "source_capsule_proof": proof,
                        "source_ink_bounds_pdf": list(ink), "coverage_bounds_pdf": list(coverage),
                        "device_bounds": list(device), "dpi": dpi, "opacity": 1.,
                        "source_paint_inventory_sha256": _digest(log),
                        "source_svg_sha256": source_svg_sha256,
                        "source_groups": source_groups[seq],
                        "source_group_declarations_sha256": _digest(group_declarations),
                        "source_page_bounds_pdf": list(page_box),
                        "overlapping_source_paints": intersects,
                        "later_source_paints": [i for i, _, _ in intersects if i > seq],
                        "text_and_image_free": True,
                        "display_policy": "Original final-page non-text pixels above unchanged editable geometry; hide display patch to edit underlying paint"})
    return recipes if sum(pixel_count(r) for r in recipes) <= MAX_PAGE_PIXELS else []


def render_recipes(page, recipes, fitz):
    """Validate the complete batch once, then render and verify immutable paint.

    The consumer must also bind its original immutable PDF bytes to source_sha256.
    Whole-page SVG/paint analysis is independent of the number of local patches.
    """
    recipes = list(recipes)
    if not recipes:
        return []
    counts = [pixel_count(r) for r in recipes]
    if max(counts) > MAX_PATCH_PIXELS or sum(counts) > MAX_PAGE_PIXELS:
        raise ValueError("Exact source composite pixel budget exceeded")
    first = recipes[0]
    ids = [r["source_paint_order"] for r in recipes]
    if len(ids) != len(set(ids)) or ids != sorted(ids):
        raise ValueError("Duplicate or unordered composite paint recipes")
    for recipe in recipes:
        if (recipe.get("schema") != SCHEMA or recipe.get("opacity") != 1
                or recipe.get("text_and_image_free") is not True
                or any(recipe[k] != first[k] for k in ("source_sha256", "page", "dpi"))):
            raise ValueError("Unqualified or mixed-source non-text composite recipe")
    fresh = qualify_recipes(page, {r["source_paint_order"]: r["source_capsule_proof"] for r in recipes},
                            source_sha256=first["source_sha256"], page_number=first["page"], dpi=first["dpi"])
    if _digest(fresh) != _digest(recipes):
        raise ValueError("Source composite recipe no longer matches original page")
    result = []
    zoom = first["dpi"] / 72.
    display = page.get_displaylist(annots=True)
    for recipe in recipes:
        pix = display.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                                 clip=fitz.Rect(recipe["coverage_bounds_pdf"]), alpha=False)
        device = [pix.x, pix.y, pix.x+pix.width, pix.y+pix.height]
        if (device != recipe["device_bounds"] or pix.n != 3 or pix.alpha
                or pix.width <= 0 or pix.height <= 0):
            raise ValueError("Source composite render does not match exact pixel lattice")
        encoded = pix.tobytes("png")
        result.append((encoded, {"png_sha256": hashlib.sha256(encoded).hexdigest(),
                                "rgb_sha256": hashlib.sha256(pix.samples).hexdigest(),
                                "width": pix.width, "height": pix.height, "channels": 3,
                                "device_bounds": device, "coverage_bounds_pdf": recipe["coverage_bounds_pdf"]}))
    _box_now, log_now = _page_state(page)
    if (_digest(log_now) != first["source_paint_inventory_sha256"]
            or _digest(_source_group_declarations(page)) != first["source_group_declarations_sha256"]
            or hashlib.sha256(page.get_svg_image(text_as_path=True).encode()).hexdigest() != first["source_svg_sha256"]):
        raise ValueError("Source page changed while rendering composite")
    return result


def render_recipe(page, recipe, fitz):
    """Single-recipe compatibility wrapper; consumers should use batch rendering."""
    return render_recipes(page, [recipe], fitz)[0]
