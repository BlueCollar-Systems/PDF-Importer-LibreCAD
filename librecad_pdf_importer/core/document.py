"""Host-neutral document extraction for PDF importer adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
import tempfile
from typing import Iterable, List, Optional

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 preferred name
except ImportError:
    import fitz  # Legacy fallback

from pdfcadcore.document_profiler import profile as profile_page
from pdfcadcore.fitz_loader import safe_open
from pdfcadcore.geometry_cleanup import circle_fit
from pdfcadcore.primitive_extractor import extract_page
from pdfcadcore.primitives import PageData

MM_PER_PT = 25.4 / 72.0

# Auto-mode visual-fidelity heuristics (ported from host importers).
AUTO_GLYPH_DRAWING_THRESHOLD = 1500
AUTO_GLYPH_FILL_RATIO = 0.75
AUTO_GLYPH_TINY_RECT_RATIO = 0.45
AUTO_GLYPH_TEXT_BLOCK_THRESHOLD = 50
AUTO_GLYPH_WORD_THRESHOLD = 400
AUTO_GLYPH_STROKE_SPARSE_RATIO = 0.05

AUTO_FILL_DRAWING_THRESHOLD = 400
AUTO_FILL_HEAVY_RATIO = 0.60
AUTO_FILL_STROKE_MAX = 0.22
AUTO_FILL_PURE_RATIO = 0.95
AUTO_FILL_PURE_STROKE_MAX = 0.02
AUTO_FILL_PURE_MIN_GROUPS = 12
AUTO_FILL_PURE_MIN_ITEMS = 24
AUTO_FILL_PURE_LARGE_RECT_RATIO = 0.03


@dataclass
class ImagePlacement:
    page_number: int
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    path: str
    xref: int


@dataclass
class ExtractedPage:
    page_data: PageData
    profile: object
    images: List[ImagePlacement] = field(default_factory=list)
    resolved_mode: Optional[str] = None       # "vector" | "raster" | "hybrid"
    resolved_reason: Optional[str] = None     # human-readable


@dataclass
class DocumentExtraction:
    pdf_path: str
    pages: List[ExtractedPage] = field(default_factory=list)
    requested_mode: str = "auto"              # BCS-ARCH-001 user request

    @property
    def primitive_count(self) -> int:
        return sum(len(p.page_data.primitives) for p in self.pages)

    @property
    def text_count(self) -> int:
        return sum(len(p.page_data.text_items) for p in self.pages)

    @property
    def image_count(self) -> int:
        return sum(len(p.images) for p in self.pages)

    def summary(self) -> dict:
        per_page_auto = [
            {
                "page": p.page_data.page_number,
                "resolved": p.resolved_mode or "vector",
                "reason": p.resolved_reason or "",
            }
            for p in self.pages
        ]
        counts: dict[str, int] = {}
        for entry in per_page_auto:
            counts[entry["resolved"]] = counts.get(entry["resolved"], 0) + 1
        parts = [f"{n} {k}" for k, n in sorted(counts.items())]
        auto_summary = f"{len(self.pages)} pages: " + ", ".join(parts) if parts else f"{len(self.pages)} pages"
        return {
            "pdf_path": self.pdf_path,
            "pages": len(self.pages),
            "primitives": self.primitive_count,
            "text_items": self.text_count,
            "images": self.image_count,
            "profiles": [
                {
                    "page": p.page_data.page_number,
                    "primary_type": getattr(p.profile, "primary_type", "unknown"),
                    "scores": getattr(p.profile, "scores", {}),
                }
                for p in self.pages
            ],
            "auto_mode": {
                "requested": self.requested_mode,
                "per_page": per_page_auto,
                "summary": auto_summary,
            },
        }


@dataclass
class ExtractionOptions:
    pages: Optional[Iterable[int] | str] = None
    scale: float = 1.0
    flip_y: bool = True
    import_text: bool = True
    import_images: bool = True
    import_mode: str = "auto"
    raster_fallback: bool = True
    raster_dpi: int = 200
    detect_arcs: bool = True
    arc_fit_tol_mm: float = 0.20
    min_arc_span_deg: float = 8.0
    min_segment_mm: float = 0.0
    max_text_items_per_page: Optional[int] = None
    image_dir: Optional[str] = None


def parse_pages_spec(spec: Optional[Iterable[int] | str], page_count: int) -> List[int]:
    if spec is None:
        return list(range(1, page_count + 1))
    if isinstance(spec, str):
        s = spec.strip().lower()
        if not s or s in {"1", "first"}:
            return [1]
        if s in {"all", "*", "a"}:
            return list(range(1, page_count + 1))
        pages: list[int] = []
        for token in s.split(","):
            token = token.strip()
            if not token:
                continue
            if "-" in token:
                left, right = token.split("-", 1)
                try:
                    a = int(left)
                    b = int(right)
                except ValueError:
                    continue
                if a > b:
                    a, b = b, a
                pages.extend(range(a, b + 1))
                continue
            try:
                pages.append(int(token))
            except ValueError:
                continue
        uniq = sorted({p for p in pages if 1 <= p <= page_count})
        return uniq or [1]
    out = sorted({int(p) for p in spec if 1 <= int(p) <= page_count})
    return out or [1]


def extract_document(pdf_path: str, options: Optional[ExtractionOptions] = None) -> DocumentExtraction:
    opts = options or ExtractionOptions()
    pdf_path = str(Path(pdf_path).expanduser().resolve())

    image_dir = Path(opts.image_dir).expanduser().resolve() if opts.image_dir else None
    if opts.import_images and image_dir is None:
        image_dir = Path(tempfile.mkdtemp(prefix="bc_lc_pdf_images_"))
    if image_dir is not None:
        image_dir.mkdir(parents=True, exist_ok=True)

    mode = _normalize_import_mode(opts.import_mode)
    extracted: list[ExtractedPage] = []

    with safe_open(pdf_path) as doc:
        pages = parse_pages_spec(opts.pages, len(doc))
        for page_number in pages:
            page = doc.load_page(page_number - 1)
            effective_mode = mode
            resolved_reason = ""

            if mode == "auto":
                drawings = page.get_drawings()
                text_blocks = page.get_text("blocks") or []
                text_words = page.get_text("words") or []
                auto_decision = _classify_auto_page(
                    drawings,
                    text_blocks_count=len(text_blocks),
                    text_words_count=len(text_words),
                    page_area=_rect_area(page.rect),
                )
                auto_type = auto_decision.get("type", "vectors")
                if auto_type in {"glyph_flood", "fill_art", "raster_candidate"}:
                    effective_mode = "raster"
                    resolved_reason = f"{auto_type}: {auto_decision.get('reason','')}"
                else:
                    effective_mode = "vector"
                    resolved_reason = "Standard vector content"
            elif mode == "vector":
                resolved_reason = "User forced vector mode"
            elif mode == "raster":
                resolved_reason = "User forced raster mode"
            elif mode == "hybrid":
                resolved_reason = "User forced hybrid mode"

            page_data = extract_page(page, page_number, scale=opts.scale, flip_y=opts.flip_y)

            include_vectors = effective_mode in {"vector", "hybrid"}
            if include_vectors:
                if opts.min_segment_mm > 0:
                    _prune_micro_segments(page_data, opts.min_segment_mm)
                if not opts.import_text:
                    page_data.text_items = []
                elif opts.max_text_items_per_page is not None:
                    cap = int(max(0, opts.max_text_items_per_page))
                    if len(page_data.text_items) > cap:
                        page_data.text_items = page_data.text_items[:cap]
                if opts.detect_arcs:
                    _promote_arcs(page_data, opts.arc_fit_tol_mm, opts.min_arc_span_deg)
            else:
                page_data.primitives = []
                page_data.text_items = []

            if mode == "auto" and effective_mode != "raster" and opts.raster_fallback:
                if _looks_like_text_cloud_page(len(page_data.primitives), len(page_data.text_items)):
                    effective_mode = "raster"
                    resolved_reason = "Text-cloud page -- fallback to raster"
                elif _looks_like_page_frame_only(page_data):
                    effective_mode = "raster"
                    resolved_reason = "Page frame only -- fallback to raster"
                if effective_mode == "raster":
                    page_data.primitives = []
                    page_data.text_items = []

            profile = profile_page(page_data)
            images = []
            if opts.import_images:
                if effective_mode in {"raster", "hybrid"}:
                    rendered = _render_page_raster(page, page_number, opts, image_dir)
                    if rendered is not None:
                        images.append(rendered)
                elif effective_mode == "vector":
                    images = _extract_images(doc, page, page_number, opts, image_dir)
                    if opts.raster_fallback and (not page_data.primitives or _looks_like_page_frame_only(page_data)) and not images:
                        rendered = _render_page_raster(page, page_number, opts, image_dir)
                        if rendered is not None:
                            images.append(rendered)
                            effective_mode = "raster"
                            resolved_reason = "Vector empty -- raster fallback"

            extracted.append(ExtractedPage(
                page_data=page_data,
                profile=profile,
                images=images,
                resolved_mode=effective_mode,
                resolved_reason=resolved_reason,
            ))

    return DocumentExtraction(
        pdf_path=pdf_path,
        pages=extracted,
        requested_mode=mode,
    )


def _normalize_import_mode(raw: str | None) -> str:
    """Normalize a mode string to BCS-ARCH-001: auto | vector | raster | hybrid."""
    mode = (raw or "auto").strip().lower()
    if mode == "vector":
        return "vector"
    if mode == "raster":
        return "raster"
    if mode == "hybrid":
        return "hybrid"
    return "auto"


def _promote_arcs(page_data: PageData, arc_fit_tol_mm: float, min_arc_span_deg: float) -> None:
    for primitive in page_data.primitives:
        if primitive.type not in {"polyline", "closed_loop"}:
            continue
        pts = primitive.points or []
        if len(pts) < 6:
            continue
        fit = circle_fit(pts)
        if not fit:
            continue
        cx, cy, radius, rms = fit
        if rms > arc_fit_tol_mm or radius <= 0:
            continue

        angles = [math.degrees(math.atan2(y - cy, x - cx)) for x, y in pts]
        unwrapped = _unwrap_angles(angles)
        span = max(unwrapped) - min(unwrapped)

        if primitive.closed and span >= 330.0:
            primitive.type = "circle"
            primitive.center = (cx, cy)
            primitive.radius = radius
            primitive.start_angle = 0.0
            primitive.end_angle = 360.0
            continue

        if span < min_arc_span_deg:
            continue

        primitive.type = "arc"
        primitive.center = (cx, cy)
        primitive.radius = radius
        primitive.start_angle = _wrap_angle(unwrapped[0])
        primitive.end_angle = _wrap_angle(unwrapped[-1])
        primitive.closed = False


def _prune_micro_segments(page_data: PageData, min_segment_mm: float) -> None:
    if min_segment_mm <= 0:
        return
    kept = []
    for primitive in page_data.primitives:
        if primitive.type == "line" and len(primitive.points or []) == 2:
            (x0, y0), (x1, y1) = primitive.points
            if math.hypot(x1 - x0, y1 - y0) < min_segment_mm:
                continue
        kept.append(primitive)
    page_data.primitives = kept


def _wrap_angle(value: float) -> float:
    while value < 0.0:
        value += 360.0
    while value >= 360.0:
        value -= 360.0
    return value


def _unwrap_angles(values: list[float]) -> list[float]:
    if not values:
        return []
    unwrapped = [values[0]]
    for angle in values[1:]:
        prev = unwrapped[-1]
        candidate = angle
        while candidate - prev > 180.0:
            candidate -= 360.0
        while candidate - prev < -180.0:
            candidate += 360.0
        unwrapped.append(candidate)
    return unwrapped


def _rect_area(rect) -> float:
    try:
        if rect is None:
            return 0.0
        if hasattr(rect, "width") and hasattr(rect, "height"):
            return max(0.0, float(rect.width) * float(rect.height))
        if len(rect) >= 4:
            return max(0.0, abs(float(rect[2]) - float(rect[0])) * abs(float(rect[3]) - float(rect[1])))
    except (TypeError, ValueError):
        return 0.0
    return 0.0


def _classify_auto_page(
    drawings: list[dict],
    *,
    text_blocks_count: int,
    text_words_count: int,
    page_area: float,
) -> dict:
    if not drawings:
        return {"type": "raster_candidate", "reason": "No vector drawings."}

    total = len(drawings)
    has_fill = 0
    has_stroke = 0
    fill_only = 0
    tiny_rects = 0
    total_items = 0
    max_rect_ratio = 0.0

    for d in drawings:
        f = d.get("fill")
        s = d.get("color") or d.get("stroke")
        if f is not None:
            has_fill += 1
        if s is not None:
            has_stroke += 1
        if f is not None and s is None:
            fill_only += 1

        items = d.get("items", []) or []
        total_items += len(items)

        rect = d.get("rect")
        rect_area = _rect_area(rect)
        if rect_area > 0 and page_area > 0:
            max_rect_ratio = max(max_rect_ratio, rect_area / page_area)
        if len(items) == 1 and items[0][0] == "re":
            if rect_area <= 36.0:
                tiny_rects += 1

    fill_ratio = has_fill / float(max(total, 1))
    stroke_ratio = has_stroke / float(max(total, 1))
    fill_only_ratio = fill_only / float(max(total, 1))
    tiny_rect_ratio = tiny_rects / float(max(total, 1))

    if (
        total >= AUTO_GLYPH_DRAWING_THRESHOLD
        and fill_ratio >= AUTO_GLYPH_FILL_RATIO
        and tiny_rect_ratio >= AUTO_GLYPH_TINY_RECT_RATIO
        and stroke_ratio <= AUTO_GLYPH_STROKE_SPARSE_RATIO
    ):
        return {"type": "glyph_flood", "reason": "Dense filled glyph-like vectors."}

    # Average items per drawing — glyph vectors typically have 1-3 items each,
    # while real drawings (garden plans, floor plans) have many more
    avg_items = total_items / float(max(total, 1))

    if (
        total >= AUTO_GLYPH_DRAWING_THRESHOLD
        and (text_blocks_count >= AUTO_GLYPH_TEXT_BLOCK_THRESHOLD or text_words_count >= AUTO_GLYPH_WORD_THRESHOLD)
        and stroke_ratio <= AUTO_GLYPH_STROKE_SPARSE_RATIO
        and fill_ratio >= AUTO_GLYPH_FILL_RATIO
        and tiny_rect_ratio >= 0.10
        and avg_items <= 8.0
    ):
        return {"type": "glyph_flood", "reason": "Text-dense glyph vector flood."}

    if (
        total >= AUTO_FILL_DRAWING_THRESHOLD
        and fill_only_ratio >= AUTO_FILL_HEAVY_RATIO
        and stroke_ratio <= AUTO_FILL_STROKE_MAX
        and avg_items <= 5.0
    ):
        return {"type": "fill_art", "reason": "Fill-dominant decorative vectors."}

    if (
        fill_only_ratio >= AUTO_FILL_PURE_RATIO
        and stroke_ratio <= AUTO_FILL_PURE_STROKE_MAX
        and total >= AUTO_FILL_PURE_MIN_GROUPS
        and (total_items >= AUTO_FILL_PURE_MIN_ITEMS or max_rect_ratio >= AUTO_FILL_PURE_LARGE_RECT_RATIO)
        and avg_items <= 5.0
    ):
        return {"type": "fill_art", "reason": "Pure-fill decorative vectors."}

    return {"type": "vectors", "reason": "Normal vector content."}


def _looks_like_text_cloud_page(primitives_count: int, text_count: int) -> bool:
    if text_count < 180:
        return False
    return (text_count / float(max(primitives_count, 1))) >= 2.5


def _primitive_bbox_area_ratio(prim, page_area_mm2: float) -> float:
    if page_area_mm2 <= 1e-9:
        return 0.0
    try:
        if getattr(prim, "bbox", None):
            x0, y0, x1, y1 = prim.bbox
            return max(0.0, (abs(float(x1) - float(x0)) * abs(float(y1) - float(y0))) / page_area_mm2)
    except (TypeError, ValueError):
        return 0.0
    try:
        pts = list(getattr(prim, "points", []) or [])
        if len(pts) >= 3:
            xs = [float(p[0]) for p in pts]
            ys = [float(p[1]) for p in pts]
            return max(0.0, ((max(xs) - min(xs)) * (max(ys) - min(ys))) / page_area_mm2)
    except (TypeError, ValueError):
        return 0.0
    return 0.0


def _looks_like_page_frame_only(page_data: PageData) -> bool:
    prims = list(getattr(page_data, "primitives", []) or [])
    if not prims or len(prims) > 12:
        return False
    text_count = len(list(getattr(page_data, "text_items", []) or []))
    if text_count > 12:
        return False
    page_area = max(float(getattr(page_data, "width", 0.0) or 0.0) * float(getattr(page_data, "height", 0.0) or 0.0), 1.0)
    big_frames = 0
    for prim in prims:
        ratio = _primitive_bbox_area_ratio(prim, page_area)
        if ratio >= 0.88:
            big_frames += 1
    return big_frames >= 1


def _extract_images(doc: fitz.Document, page: fitz.Page, page_number: int,
                    options: ExtractionOptions, image_dir: Optional[Path]) -> List[ImagePlacement]:
    placements: list[ImagePlacement] = []
    if image_dir is None:
        return placements

    page_height = float(page.rect.height)
    seen: set[int] = set()
    for img_info in page.get_images(full=True):
        xref = int(img_info[0])
        if xref in seen:
            continue
        seen.add(xref)

        try:
            pix = fitz.Pixmap(doc, xref)
            color_space_n = None
            try:
                color_space_n = int(getattr(getattr(pix, "colorspace", None), "n", 0))
            except (TypeError, ValueError):
                color_space_n = None

            needs_rgb = pix.alpha or pix.n != 3 or (color_space_n is not None and color_space_n != 3)
            if needs_rgb:
                pix = fitz.Pixmap(fitz.csRGB, pix)

            img_path = image_dir / f"page_{page_number:03d}_xref_{xref}.png"
            pix.save(str(img_path))
        except (RuntimeError, OSError, ValueError, TypeError):
            continue

        rects = page.get_image_rects(xref)
        for rect in rects:
            x0, y0, x1, y1 = float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)
            left = min(x0, x1)
            right = max(x0, x1)

            if options.flip_y:
                bottom_pt = page_height - max(y0, y1)
                top_pt = page_height - min(y0, y1)
            else:
                bottom_pt = min(y0, y1)
                top_pt = max(y0, y1)

            placements.append(
                ImagePlacement(
                    page_number=page_number,
                    x_mm=left * MM_PER_PT * options.scale,
                    y_mm=bottom_pt * MM_PER_PT * options.scale,
                    width_mm=(right - left) * MM_PER_PT * options.scale,
                    height_mm=(top_pt - bottom_pt) * MM_PER_PT * options.scale,
                    path=str(img_path),
                    xref=xref,
                )
            )

    return placements


def _render_page_raster(page: fitz.Page, page_number: int, options: ExtractionOptions,
                        image_dir: Optional[Path]) -> Optional[ImagePlacement]:
    if image_dir is None:
        return None

    dpi = int(max(36, options.raster_dpi or 200))
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    try:
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img_path = image_dir / f"page_{page_number:03d}_raster_{dpi}dpi.png"
        pix.save(str(img_path))
    except (RuntimeError, OSError, ValueError, TypeError):
        return None

    width_mm = float(page.rect.width) * MM_PER_PT * options.scale
    height_mm = float(page.rect.height) * MM_PER_PT * options.scale
    return ImagePlacement(
        page_number=page_number,
        x_mm=0.0,
        y_mm=0.0,
        width_mm=width_mm,
        height_mm=height_mm,
        path=str(img_path),
        xref=-1,
    )

