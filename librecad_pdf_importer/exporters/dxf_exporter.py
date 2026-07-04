"""DXF export adapter for LibreCAD workflows."""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import ezdxf
from ezdxf.colors import rgb2int
from ezdxf.units import MM
try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 preferred name
except ImportError:
    import fitz  # Legacy fallback

from ..core.document import DocumentExtraction

from pdfcadcore.import_config import ImportConfig

from dxf_text_builder import build_text, reset_text_styles


@dataclass
class DxfExportOptions:
    include_text: bool = True
    text_mode: str = "labels"
    include_images: bool = True
    group_by_page: bool = True
    prefer_source_layers: bool = True
    attach_metadata: bool = True
    dxf_version: str = "R2018"
    map_dashes: bool = True
    # Page arrangement for multi-page exports:
    # - "spread": stack pages with a 20% gap (default)
    # - "compact": stack pages with small configurable gap
    # - "touch": stack pages edge-to-edge (no gap)
    # - "overlay": place all pages on same origin
    page_arrangement: str = "spread"
    page_gap_ratio: float = 0.02
    provenance_opts: Optional[Any] = None


def _text_span_dict(text_item) -> Dict[str, Any]:
    bbox = getattr(text_item, "bbox", None)
    insertion = getattr(text_item, "insertion", (0.0, 0.0)) or (0.0, 0.0)
    return {
        "text": str(getattr(text_item, "text", "") or ""),
        "bbox": list(bbox) if bbox else None,
        "origin": [float(insertion[0]), float(insertion[1])],
        "size": float(getattr(text_item, "font_size", 0.0) or 0.0),
    }


def _provenance_entity_type(text_mode: str) -> str:
    mode = str(text_mode or "labels").strip().lower()
    if mode in {"glyphs", "geometry", "outlines"}:
        return "raw_geometry_edges"
    return "dxf_text"


@dataclass
class DxfExportResult:
    output_path: str
    entity_count: int
    layer_count: int
    image_count: int


def export_to_dxf(extraction: DocumentExtraction, output_path: str,
                  options: Optional[DxfExportOptions] = None) -> DxfExportResult:
    opts = options or DxfExportOptions()
    dxf_ver = _normalize_dxf_version(opts.dxf_version)
    is_r12 = dxf_ver == "R12"
    reset_text_styles()
    doc = ezdxf.new(dxf_ver)
    doc.units = MM
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()

    entity_count = 0
    image_count = 0
    dash_cache: Dict[str, str] = {}
    image_def_cache: Dict[str, object] = {}

    # Multi-page placement offset.
    _stack_offset_y = 0.0
    arrangement = (opts.page_arrangement or "spread").strip().lower()
    if arrangement not in {"spread", "compact", "touch", "overlay"}:
        arrangement = "spread"
    gap_ratio = max(0.0, float(opts.page_gap_ratio or 0.0))

    # Export extents for host auto-framing (LibreCAD/QCAD/AutoCAD).
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")

    def _track_xy(x: float, y: float) -> None:
        nonlocal min_x, min_y, max_x, max_y
        if x < min_x:
            min_x = x
        if y < min_y:
            min_y = y
        if x > max_x:
            max_x = x
        if y > max_y:
            max_y = y

    for page in extraction.pages:
        # Apply page stacking offset to all coordinates
        dy = _stack_offset_y
        page_w = float(page.page_data.width or 0.0)
        page_h = float(page.page_data.height or 0.0)
        # Seed extents from the page frame so host auto-fit still works even
        # when selected export mode yields no drawable entities on that page.
        _track_xy(0.0, 0.0 + dy)
        _track_xy(page_w, page_h + dy)

        for primitive in page.page_data.primitives:
            display_rgb = primitive.fill_color or primitive.stroke_color
            layer = _layer_name(page.page_data.page_number, primitive.layer_name, display_rgb, opts)
            _ensure_layer(doc, layer, display_rgb)
            attribs = {"layer": layer}
            if not is_r12:
                _apply_color(attribs, display_rgb)
                _apply_lineweight(attribs, primitive.line_width)

            if opts.map_dashes:
                ltype = _linetype_from_dash(doc, primitive.dash_pattern, dash_cache)
                if ltype:
                    attribs["linetype"] = ltype

            # Helper to offset a point by the page stacking offset
            def _ofs(pt, _dy=dy):
                return (pt[0], pt[1] + _dy)

            if primitive.type == "line" and primitive.points and len(primitive.points) == 2:
                start = _ofs(primitive.points[0])
                end = _ofs(primitive.points[1])
                msp.add_line(start, end, dxfattribs=attribs)
                _track_xy(float(start[0]), float(start[1]))
                _track_xy(float(end[0]), float(end[1]))
                entity_count += 1
            elif primitive.type == "circle" and primitive.center and primitive.radius:
                center = _ofs(primitive.center)
                radius = float(primitive.radius)
                msp.add_circle(center, radius, dxfattribs=attribs)
                _track_xy(float(center[0]) - radius, float(center[1]) - radius)
                _track_xy(float(center[0]) + radius, float(center[1]) + radius)
                entity_count += 1
            elif primitive.type == "arc" and primitive.center and primitive.radius:
                start = float(primitive.start_angle or 0.0)
                end = float(primitive.end_angle or 0.0)
                if math.isclose(start, end, abs_tol=1e-6):
                    end = (end + 359.999) % 360.0
                center = _ofs(primitive.center)
                radius = float(primitive.radius)
                msp.add_arc(center, radius, start, end, dxfattribs=attribs)
                _track_xy(float(center[0]) - radius, float(center[1]) - radius)
                _track_xy(float(center[0]) + radius, float(center[1]) + radius)
                entity_count += 1
            elif primitive.points and len(primitive.points) >= 2:
                offset_pts = [_ofs(p) for p in primitive.points]
                msp.add_lwpolyline(offset_pts, format="xy", close=bool(primitive.closed), dxfattribs=attribs)
                for px, py in offset_pts:
                    _track_xy(float(px), float(py))
                entity_count += 1

        if opts.include_text and opts.text_mode != "none":
            text_cfg = ImportConfig.auto()
            text_cfg.text_mode = opts.text_mode
            for text in page.page_data.text_items:
                layer = _layer_name(page.page_data.page_number, "TEXT", None, opts)
                _ensure_layer(doc, layer, None)
                ti = text
                if dy != 0.0:
                    from dataclasses import replace as _dc_replace
                    ti = _dc_replace(
                        text,
                        insertion=(
                            float(text.insertion[0]),
                            float(text.insertion[1]) + dy,
                        ),
                        bbox=(
                            (
                                float(text.bbox[0]),
                                float(text.bbox[1]) + dy,
                                float(text.bbox[2]),
                                float(text.bbox[3]) + dy,
                            )
                            if text.bbox
                            else None
                        ),
                    )
                created = build_text(
                    ti,
                    msp,
                    layer,
                    text_cfg,
                    is_r12=is_r12,
                    target_app="librecad",
                    dxf_version=dxf_ver,
                )
                _track_xy(float(ti.insertion[0]), float(ti.insertion[1]))
                if ti.bbox:
                    x0, y0, x1, y1 = ti.bbox
                    _track_xy(float(x0), float(y0))
                    _track_xy(float(x1), float(y1))
                entity_count += created
                if created > 0 and opts.provenance_opts is not None:
                    try:
                        from pdfcadcore.source_provenance import record_text_span_provenance

                        record_text_span_provenance(
                            opts.provenance_opts,
                            page=int(page.page_data.page_number),
                            span=_text_span_dict(ti),
                            text=str(ti.text or ""),
                            created_entity_type=_provenance_entity_type(opts.text_mode),
                            import_mode=str(
                                getattr(opts.provenance_opts, "import_mode", "") or ""
                            ),
                            text_mode=str(opts.text_mode or ""),
                        )
                    except (ImportError, TypeError, ValueError):
                        pass

        if opts.include_images:
            for placement in page.images:
                img_path = Path(placement.path)
                if not img_path.is_file():
                    continue

                image_def = image_def_cache.get(str(img_path))
                if image_def is None:
                    size_px = _image_size_pixels(str(img_path))
                    image_def = doc.add_image_def(
                        filename=str(img_path),
                        size_in_pixel=size_px,
                        name=f"IMG_{len(image_def_cache) + 1}",
                    )
                    image_def_cache[str(img_path)] = image_def

                layer = _layer_name(page.page_data.page_number, "IMAGES", None, opts)
                _ensure_layer(doc, layer, None)
                msp.add_image(
                    image_def,
                    insert=(placement.x_mm, placement.y_mm + dy),
                    size_in_units=(placement.width_mm, placement.height_mm),
                    dxfattribs={"layer": layer},
                )
                _track_xy(float(placement.x_mm), float(placement.y_mm) + dy)
                _track_xy(float(placement.x_mm + placement.width_mm), float(placement.y_mm + placement.height_mm) + dy)
                entity_count += 1
                image_count += 1

        # Advance page placement offset for the next page.
        page_step = _page_stack_step(page.page_data.height, arrangement, gap_ratio)
        _stack_offset_y -= page_step

    # Persist extents + initial modelspace viewport so hosts open focused on geometry.
    if min_x <= max_x and min_y <= max_y:
        extmin = (float(min_x), float(min_y), 0.0)
        extmax = (float(max_x), float(max_y), 0.0)
        msp.dxf.extmin = extmin
        msp.dxf.extmax = extmax
        msp.dxf.limmin = (float(min_x), float(min_y))
        msp.dxf.limmax = (float(max_x), float(max_y))
        doc.header["$EXTMIN"] = extmin
        doc.header["$EXTMAX"] = extmax
        doc.header["$LIMMIN"] = (float(min_x), float(min_y))
        doc.header["$LIMMAX"] = (float(max_x), float(max_y))
        center = ((float(min_x) + float(max_x)) * 0.5, (float(min_y) + float(max_y)) * 0.5)
        height = max(1.0, float(max_y) - float(min_y))
        width = max(1.0, float(max_x) - float(min_x))
        doc.set_modelspace_vport(max(height, width) * 1.1, center=center)
        active = doc.viewports.get("*Active")
        if active:
            vp = active[0]
            vp.dxf.center = center
            vp.dxf.height = height * 1.1

    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(output))

    return DxfExportResult(
        output_path=str(output),
        entity_count=entity_count,
        layer_count=len(doc.layers),
        image_count=image_count,
    )


def _layer_name(page_number: int, source_layer: Optional[str], stroke_color,
                opts: DxfExportOptions) -> str:
    parts = []
    if opts.group_by_page:
        parts.append(f"P{page_number:03d}")
    if opts.prefer_source_layers and source_layer:
        parts.append(_sanitize_layer(str(source_layer)))
    elif stroke_color is not None:
        parts.append(_color_key(stroke_color))
    return "_".join(parts) if parts else "PDF_IMPORT"


def _normalize_dxf_version(raw: str) -> str:
    allowed = {"R12", "R2000", "R2004", "R2007", "R2010", "R2013", "R2018"}
    normalized = (raw or "R2018").strip().upper()
    return normalized if normalized in allowed else "R2018"


def _page_stack_step(page_height: float, arrangement: str, gap_ratio: float) -> float:
    h = max(1.0, float(page_height or 0.0))
    if arrangement == "overlay":
        return 0.0
    if arrangement == "touch":
        return h
    if arrangement == "compact":
        return h * (1.0 + max(0.0, gap_ratio))
    return h * 1.2


def _sanitize_layer(name: str) -> str:
    out = [ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in name.strip()]
    value = "".join(out).strip("_")
    return value[:120] if value else "Layer"


def _color_key(rgb) -> str:
    r, g, b = (int(max(0, min(255, round(float(c) * 255)))) for c in rgb)
    return f"RGB_{r:03d}_{g:03d}_{b:03d}"


def _ensure_layer(doc: ezdxf.EzDxf, name: str, rgb) -> None:
    if doc.layers.has_entry(name):
        return
    kwargs = {}
    if rgb is not None:
        kwargs["true_color"] = rgb2int(tuple(int(max(0, min(255, round(float(c) * 255)))) for c in rgb))
    doc.layers.new(name=name, dxfattribs=kwargs)


def _apply_color(attribs: dict, rgb) -> None:
    if rgb is None:
        return
    r, g, b = (int(max(0, min(255, round(float(c) * 255)))) for c in rgb)
    # Invert near-white colors to black so geometry is visible on
    # LibreCAD's default white background.  Without this, white-on-white
    # entities are invisible and the user sees a blank/black screen.
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    if luminance > 230:
        r, g, b = 0, 0, 0
    attribs["true_color"] = rgb2int((r, g, b))


def _apply_lineweight(attribs: dict, width_pt) -> None:
    if width_pt is None:
        return
    width_mm = float(width_pt) * (25.4 / 72.0)
    lw = int(max(5, min(211, round(width_mm * 100))))  # hundredths of mm
    attribs["lineweight"] = lw


def _linetype_from_dash(doc: ezdxf.EzDxf, dash_pattern, cache: Dict[str, str]) -> Optional[str]:
    if not dash_pattern:
        return None

    values = _normalize_dash(dash_pattern)
    if len(values) < 2:
        return None

    key = ",".join(f"{v:.2f}" for v in values)
    cached = cache.get(key)
    if cached:
        return cached

    if len(values) % 2 == 1:
        values.append(values[-1])

    mm_vals = [max(0.1, v * (25.4 / 72.0)) for v in values]
    pattern = [sum(mm_vals)]
    for idx, val in enumerate(mm_vals):
        pattern.append(val if idx % 2 == 0 else -val)

    name = f"PDF_DASH_{len(cache) + 1}"
    try:
        doc.linetypes.add(name=name, pattern=pattern, description=f"PDF dash {key}")
    except Exception:
        return None

    cache[key] = name
    return name


def _normalize_dash(dash_pattern) -> list[float]:
    if isinstance(dash_pattern, str):
        vals = []
        token = ""
        for ch in dash_pattern:
            if ch.isdigit() or ch in {".", "-"}:
                token += ch
                continue
            if token:
                try:
                    vals.append(abs(float(token)))
                except ValueError:
                    pass
                token = ""
        if token:
            try:
                vals.append(abs(float(token)))
            except ValueError:
                pass
        return [v for v in vals if v > 0.0]

    if isinstance(dash_pattern, (list, tuple)):
        vals = []
        for item in dash_pattern:
            if isinstance(item, (int, float)):
                vals.append(abs(float(item)))
            elif isinstance(item, (list, tuple)):
                for nested in item:
                    if isinstance(nested, (int, float)):
                        vals.append(abs(float(nested)))
        return [v for v in vals if v > 0.0]

    return []


def _image_size_pixels(path: str) -> Tuple[int, int]:
    try:
        pix = fitz.Pixmap(path)
        return int(max(1, pix.width)), int(max(1, pix.height))
    except Exception:
        return (100, 100)
