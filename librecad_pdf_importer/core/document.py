"""Host-neutral document extraction for PDF importer adapters."""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import math
from pathlib import Path
import tempfile
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

import numpy as np

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 preferred name
except ImportError:
    import fitz  # Legacy fallback

from pdfcadcore.document_profiler import profile as profile_page
from pdfcadcore.fitz_loader import safe_open
from pdfcadcore.geometry_cleanup import circle_fit
from pdfcadcore.primitive_extractor import (
    _page_rotation_transform,
    _transform_pdf_point,
    _transform_pdf_vector,
    extract_page,
)
from pdfcadcore.primitives import PageData
from conversion_control import check_cancel, report_progress

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

# Dense inline-image PDFs (BI / ID / EI operators) must not create tens of
# thousands of host IMAGE entities. Smaller rectilinear sets remain editable.
INLINE_IMAGE_COMPOSITE_THRESHOLD = 256
INLINE_IMAGE_COMPOSITE_MAX_PIXELS = 16_000_000
XOBJECT_IMAGE_COMPOSITE_THRESHOLD = 256
PAGE_RASTER_MAX_PIXELS = 16_000_000
PAGE_RASTER_MAX_DIMENSION = 8_192
PAGE_RASTER_MAX_JOB_PIXELS = 134_217_728
PAGE_RASTER_MIN_DPI = 36.0


@dataclass
class ImagePlacement:
    page_number: int
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    path: str
    xref: int
    source_kind: str = "xobject_image"
    source_instance_count: int = 1
    source_bbox_pdf: Optional[Tuple[float, float, float, float]] = None
    source_number: Optional[int] = None
    source_digest: str = ""
    pixel_size: Optional[Tuple[int, int]] = None
    alpha_kind: str = "unknown"
    alpha_bbox_px: Optional[Tuple[int, int, int, int]] = None
    alpha_present: Optional[bool] = None
    affine_pdf: Optional[Tuple[float, float, float, float, float, float]] = None
    affine_model: Optional[Tuple[float, float, float, float, float, float]] = None
    masked_text_bboxes_pdf: Tuple[Tuple[float, float, float, float], ...] = ()


@dataclass
class ExtractedPage:
    page_data: PageData
    profile: object
    images: List[ImagePlacement] = field(default_factory=list)
    resolved_mode: Optional[str] = None       # "vector" | "raster" | "hybrid"
    resolved_reason: Optional[str] = None     # human-readable
    raster_fallback_failed: bool = False       # raster delivery failed; vector/text was retained


@dataclass
class DocumentExtraction:
    pdf_path: str
    pages: List[ExtractedPage] = field(default_factory=list)
    requested_mode: str = "auto"              # BCS-ARCH-001 user request
    _temporary_image_workspace: Optional[tempfile.TemporaryDirectory] = field(
        default=None,
        repr=False,
        compare=False,
    )

    def cleanup_temporary_assets(self) -> None:
        """Reclaim importer-owned source assets without touching caller-owned paths."""
        workspace = self._temporary_image_workspace
        self._temporary_image_workspace = None
        if workspace is not None:
            workspace.cleanup()

    def __enter__(self) -> "DocumentExtraction":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.cleanup_temporary_assets()

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
        image_delivery_pages = []
        image_source_kinds: dict[str, int] = {}
        image_source_instances = 0
        for page in self.pages:
            page_source_kinds: dict[str, int] = {}
            page_source_instances = 0
            for placement in page.images:
                source_kind = str(placement.source_kind or "xobject_image")
                source_count = max(1, int(placement.source_instance_count or 1))
                page_source_kinds[source_kind] = (
                    page_source_kinds.get(source_kind, 0) + source_count
                )
                image_source_kinds[source_kind] = (
                    image_source_kinds.get(source_kind, 0) + source_count
                )
                page_source_instances += source_count
                image_source_instances += source_count
            image_delivery_pages.append(
                {
                    "page": page.page_data.page_number,
                    "placements": len(page.images),
                    "source_instances": page_source_instances,
                    "source_kinds": page_source_kinds,
                }
            )
        return {
            "pdf_path": self.pdf_path,
            "pages": len(self.pages),
            "primitives": self.primitive_count,
            "text_items": self.text_count,
            "images": self.image_count,
            "image_delivery": {
                "placements": self.image_count,
                "source_instances": image_source_instances,
                "source_kinds": image_source_kinds,
                "per_page": image_delivery_pages,
            },
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


def _classify_pixmap_alpha(
    pixmap,
    *,
    rows_per_chunk: int = 256,
) -> Tuple[str, Tuple[int, int, int, int]]:
    """Classify visible support without allocating a second full-size raster."""

    width = int(pixmap.width)
    height = int(pixmap.height)
    if width <= 0 or height <= 0:
        raise ValueError("image pixmap dimensions are invalid")
    full_box = (0, 0, width, height)
    if not bool(pixmap.alpha):
        return "opaque", full_box

    channels = int(pixmap.n)
    stride = int(getattr(pixmap, "stride", width * channels))
    raw_samples = getattr(pixmap, "samples_mv", None)
    if raw_samples is None:
        raw_samples = pixmap.samples
    rows = np.frombuffer(raw_samples, dtype=np.uint8).reshape(height, stride)
    pixels = rows[:, : width * channels].reshape(height, width, channels)
    alpha = pixels[:, :, channels - 1]
    nonzero_count = 0
    partial = False
    left = width
    top = height
    right = 0
    bottom = 0
    chunk_rows = max(1, int(rows_per_chunk))
    for start in range(0, height, chunk_rows):
        block = alpha[start : min(height, start + chunk_rows)]
        visible = block != 0
        count = int(np.count_nonzero(visible))
        if count == 0:
            continue
        nonzero_count += count
        partial = partial or bool(np.any((block > 0) & (block < 255)))
        visible_rows = np.flatnonzero(np.any(visible, axis=1))
        visible_columns = np.flatnonzero(np.any(visible, axis=0))
        top = min(top, start + int(visible_rows[0]))
        bottom = max(bottom, start + int(visible_rows[-1]) + 1)
        left = min(left, int(visible_columns[0]))
        right = max(right, int(visible_columns[-1]) + 1)

    if nonzero_count == 0:
        return "zero", (0, 0, 0, 0)
    bbox = (left, top, right, bottom)
    if partial:
        return "compositing_required", bbox
    bbox_area = (right - left) * (bottom - top)
    if nonzero_count == bbox_area:
        if bbox == full_box:
            return "opaque", full_box
        return "rectangular_opaque", bbox
    return "binary_mask", bbox


@dataclass
class ExtractionOptions:
    pages: Optional[Iterable[int] | str] = None
    scale: float = 1.0
    flip_y: bool = True
    import_text: bool = True
    requested_text_representation: str = "text"
    import_images: bool = True
    import_mode: str = "auto"
    raster_fallback: bool = True
    raster_dpi: int = 200
    detect_arcs: bool = True
    arc_fit_tol_mm: float = 0.20
    arc_sampling_pts: int = 7
    min_arc_span_deg: float = 8.0
    min_segment_mm: float = 0.0
    max_text_items_per_page: Optional[int] = None
    image_dir: Optional[str] = None
    cancel_requested: Optional[Callable[[], bool]] = None
    progress_callback: Optional[Callable[[str], None]] = None


def _prepare_vector_page_data(page_data: PageData, options: ExtractionOptions) -> None:
    """Apply the existing vector controls without changing text sizing."""
    if options.min_segment_mm > 0:
        _prune_micro_segments(page_data, options.min_segment_mm)
    if not options.import_text:
        page_data.text_items = []
    elif options.max_text_items_per_page is not None:
        cap = int(max(0, options.max_text_items_per_page))
        if len(page_data.text_items) > cap:
            page_data.text_items = page_data.text_items[:cap]
    if options.detect_arcs:
        _promote_arcs(page_data, options.arc_fit_tol_mm, options.min_arc_span_deg)


def _has_viable_vector_content(page_data: PageData) -> bool:
    return bool(page_data.primitives or page_data.text_items)


def _restore_viable_vector_content(
    page_data: PageData,
    retained_content,
    *,
    content_prepared: bool,
    options: ExtractionOptions,
) -> bool:
    if retained_content is None:
        return False
    primitives, text_items = retained_content
    page_data.primitives = list(primitives)
    page_data.text_items = list(text_items)
    if not content_prepared:
        _prepare_vector_page_data(page_data, options)
    return _has_viable_vector_content(page_data)


def _render_page_raster_safely(page, page_number: int, options: ExtractionOptions,
                               image_dir: Optional[Path],
                               masked_text_items: Sequence[object] = ()):
    """Return a page raster or a delivery-failure detail for recovery/reporting."""
    try:
        rendered = _render_page_raster(
            page,
            page_number,
            options,
            image_dir,
            masked_text_items=masked_text_items,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if rendered is None:
        return None, "renderer returned no placement"
    return rendered, ""

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
        if not uniq:
            raise ValueError(
                f"The requested page selection is outside this {page_count}-page PDF."
            )
        return uniq
    # ImportConfig.pages is the shared host contract and stores zero-based page
    # indices.  The extractor loop below intentionally uses human/PDF one-based
    # page numbers, so translate exactly once at this boundary.
    out = sorted(
        {
            int(index) + 1
            for index in spec
            if 0 <= int(index) < page_count
        }
    )
    if not out:
        raise ValueError(
            f"The requested page selection is outside this {page_count}-page PDF."
        )
    return out


def extract_document(
    pdf_path: str,
    options: Optional[ExtractionOptions] = None,
) -> DocumentExtraction:
    workspaces: list[tempfile.TemporaryDirectory] = []
    try:
        return _extract_document_impl(pdf_path, options, workspaces)
    except BaseException:
        for workspace in workspaces:
            workspace.cleanup()
        raise


def _extract_document_impl(
    pdf_path: str,
    options: Optional[ExtractionOptions],
    workspaces: list[tempfile.TemporaryDirectory],
) -> DocumentExtraction:
    opts = options or ExtractionOptions()
    pdf_path = str(Path(pdf_path).expanduser().resolve())

    image_workspace = None
    image_dir = Path(opts.image_dir).expanduser().resolve() if opts.image_dir else None
    if opts.import_images and image_dir is None:
        image_workspace = tempfile.TemporaryDirectory(prefix="bc_lc_pdf_images_")
        workspaces.append(image_workspace)
        image_dir = Path(image_workspace.name)
    if image_dir is not None:
        image_dir.mkdir(parents=True, exist_ok=True)

    mode = _normalize_import_mode(opts.import_mode)
    extracted: list[ExtractedPage] = []
    page_raster_job_pixels = 0

    with safe_open(pdf_path) as doc:
        pages = parse_pages_spec(opts.pages, len(doc))
        for page_position, page_number in enumerate(pages, start=1):
            check_cancel(opts.cancel_requested, f"before extracting page {page_number}")
            report_progress(
                opts.progress_callback,
                f"Extracting source page {page_number} ({page_position}/{len(pages)})",
            )
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
                    resolved_reason = auto_decision.get("reason") or "Standard vector content"
            elif mode == "vector":
                resolved_reason = "User forced vector mode"
            elif mode == "raster":
                resolved_reason = "User forced raster mode"
            elif mode == "hybrid":
                resolved_reason = "User forced hybrid mode"

            page_data = extract_page(
                page,
                page_number,
                scale=opts.scale,
                flip_y=opts.flip_y,
                arc_min_pts=max(3, int(opts.arc_sampling_pts)),
            )
            check_cancel(opts.cancel_requested, f"after vectors on page {page_number}")

            requested_text_representation = str(
                opts.requested_text_representation or "text"
            ).strip().lower()
            if requested_text_representation == "text3d":
                requested_text_representation = "3d_text"
            preserve_requested_text = bool(
                opts.import_text
                and requested_text_representation
                in {"text", "labels", "glyphs", "geometry", "3d_text", "raster"}
                and page_data.text_items
            )
            if preserve_requested_text and effective_mode == "raster":
                if mode == "auto":
                    effective_mode = "vector"
                    resolved_reason = (
                        f"Requested {requested_text_representation} text representation "
                        "retained; auto raster preemption disabled."
                    )
                else:
                    effective_mode = "hybrid"
                    resolved_reason = (
                        "User-forced raster page retained together with requested "
                        f"{requested_text_representation} text representation."
                    )

            include_vectors = effective_mode in {"vector", "hybrid"}
            retained_content = None
            retained_content_prepared = False
            if include_vectors:
                _prepare_vector_page_data(page_data, opts)
                if _has_viable_vector_content(page_data):
                    retained_content = (list(page_data.primitives), list(page_data.text_items))
                    retained_content_prepared = True
            else:
                if _has_viable_vector_content(page_data):
                    retained_content = (list(page_data.primitives), list(page_data.text_items))
                page_data.primitives = []
                page_data.text_items = []

            if (
                mode == "auto"
                and effective_mode != "raster"
                and opts.raster_fallback
                and not preserve_requested_text
            ):
                if _looks_like_text_cloud_page(len(page_data.primitives), len(page_data.text_items)):
                    effective_mode = "raster"
                    resolved_reason = "Text-cloud page -- fallback to raster"
                elif _looks_like_page_frame_only(page_data):
                    effective_mode = "raster"
                    resolved_reason = "Page frame only -- fallback to raster"
                if effective_mode == "raster":
                    if _has_viable_vector_content(page_data):
                        retained_content = (list(page_data.primitives), list(page_data.text_items))
                        retained_content_prepared = True
                    page_data.primitives = []
                    page_data.text_items = []

            profile = profile_page(page_data)
            images = []
            raster_failure_detail = ""
            check_cancel(opts.cancel_requested, f"before images on page {page_number}")
            if opts.import_images:
                if effective_mode in {"raster", "hybrid"}:
                    rendered, raster_failure_detail = _render_page_raster_safely(
                        page,
                        page_number,
                        opts,
                        image_dir,
                        masked_text_items=(
                            page_data.text_items if preserve_requested_text else ()
                        ),
                    )
                    if rendered is not None:
                        rendered_pixels = int(rendered.pixel_size[0]) * int(
                            rendered.pixel_size[1]
                        )
                        if (
                            page_raster_job_pixels + rendered_pixels
                            > PAGE_RASTER_MAX_JOB_PIXELS
                        ):
                            try:
                                Path(rendered.path).unlink(missing_ok=True)
                            except OSError:
                                pass
                            rendered = None
                            raster_failure_detail = (
                                "document raster budget exceeded; import fewer pages "
                                "per job"
                            )
                        else:
                            page_raster_job_pixels += rendered_pixels
                            images.append(rendered)
                            raster_failure_detail = ""
                elif effective_mode == "vector":
                    images = _extract_images(doc, page, page_number, opts, image_dir)
                    inline_placements = [
                        placement
                        for placement in images
                        if str(placement.source_kind).startswith("inline_image")
                    ]
                    inline_source_count = sum(
                        max(1, int(placement.source_instance_count or 1))
                        for placement in inline_placements
                    )
                    if inline_source_count:
                        if any(
                            placement.source_kind
                            in {
                                "inline_image_composite",
                                "inline_image_page_fidelity_required",
                            }
                            for placement in inline_placements
                        ):
                            delivery_detail = (
                                "one exact page-fidelity image surface"
                            )
                        else:
                            delivery_detail = (
                                f"{len(inline_placements)} individual image placements"
                            )
                        prior_reason = resolved_reason or "Vector content retained"
                        resolved_reason = (
                            f"{prior_reason}; preserved {inline_source_count} inline image "
                            f"instances as {delivery_detail} while retaining vector/text content"
                        )
                    has_text = bool(page_data.text_items)
                    vector_empty = not page_data.primitives and not has_text
                    if opts.raster_fallback and (vector_empty or _looks_like_page_frame_only(page_data)) and not images:
                        rendered, raster_failure_detail = _render_page_raster_safely(
                            page,
                            page_number,
                            opts,
                            image_dir,
                            masked_text_items=(
                                page_data.text_items if preserve_requested_text else ()
                            ),
                        )
                        if rendered is not None:
                            rendered_pixels = int(rendered.pixel_size[0]) * int(
                                rendered.pixel_size[1]
                            )
                            if (
                                page_raster_job_pixels + rendered_pixels
                                > PAGE_RASTER_MAX_JOB_PIXELS
                            ):
                                try:
                                    Path(rendered.path).unlink(missing_ok=True)
                                except OSError:
                                    pass
                                rendered = None
                                raster_failure_detail = (
                                    "document raster budget exceeded; import fewer "
                                    "pages per job"
                                )
                            else:
                                page_raster_job_pixels += rendered_pixels
                                images.append(rendered)
                                effective_mode = "raster"
                                resolved_reason = "Vector empty -- raster fallback"
                                raster_failure_detail = ""
            elif effective_mode in {"raster", "hybrid"}:
                raster_failure_detail = "image delivery disabled"

            raster_fallback_failed = False
            if raster_failure_detail:
                if not _restore_viable_vector_content(
                    page_data,
                    retained_content,
                    content_prepared=retained_content_prepared,
                    options=opts,
                ):
                    raise RuntimeError(
                        f"Page {page_number}: raster render failed ({raster_failure_detail}); "
                        "no viable vector/text representation remains."
                    )
                profile = profile_page(page_data)
                if effective_mode == "raster":
                    effective_mode = "vector"
                prior_reason = resolved_reason or "Raster representation requested"
                resolved_reason = (
                    f"{prior_reason}; raster render failed ({raster_failure_detail}); "
                    "retained vector/text representation"
                )
                raster_fallback_failed = True

            extracted.append(ExtractedPage(
                page_data=page_data,
                profile=profile,
                images=images,
                resolved_mode=effective_mode,
                resolved_reason=resolved_reason,
                raster_fallback_failed=raster_fallback_failed,
            ))
            report_progress(
                opts.progress_callback,
                f"Extracted source page {page_number} ({page_position}/{len(pages)})",
            )

    return DocumentExtraction(
        pdf_path=pdf_path,
        pages=extracted,
        requested_mode=mode,
        _temporary_image_workspace=image_workspace,
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
        if text_blocks_count > 0 or text_words_count > 0:
            return {"type": "text_only", "reason": "No vector drawings; preserving extractable text."}
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
    if primitives_count == 0:
        return False
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


def _svg_number(value: object) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("inline image transform contains a non-finite value")
    return format(number, ".17g")


def _inline_image_blocks(page: fitz.Page) -> list[tuple[dict, dict]]:
    """Return every displayed inline-image instance paired with decoded bytes."""

    get_image_info = getattr(page, "get_image_info", None)
    if not callable(get_image_info):
        # Test doubles and unsupported legacy bindings cannot claim inline-image
        # completeness; real supported PyMuPDF pages always provide this API.
        return []
    try:
        image_info = list(get_image_info(hashes=True, xrefs=True) or [])
    except (RuntimeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"inline image inventory failed: {exc}") from exc
    inline_info = [info for info in image_info if int(info.get("xref") or 0) == 0]
    if not inline_info:
        return []

    try:
        text_dictionary = page.get_text("dict") or {}
    except (RuntimeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"inline image byte extraction failed: {exc}") from exc
    blocks_by_number = {
        int(block.get("number")): block
        for block in (text_dictionary.get("blocks") or [])
        if int(block.get("type", -1)) == 1 and block.get("number") is not None
    }
    paired: list[tuple[dict, dict]] = []
    for info in inline_info:
        number = int(info.get("number", -1))
        block = blocks_by_number.get(number)
        if block is None:
            raise RuntimeError(
                f"inline image instance {number} has no decoded image block"
            )
        image_bytes = block.get("image")
        transform = block.get("transform")
        if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
            raise RuntimeError(f"inline image instance {number} has no image bytes")
        if not isinstance(transform, (list, tuple)) or len(transform) != 6:
            raise RuntimeError(f"inline image instance {number} has no affine transform")
        paired.append((info, block))
    return paired


def _inline_block_is_rectilinear(block: dict) -> bool:
    a, b, c, d, _e, _f = [float(value) for value in block["transform"]]
    tolerance = max(abs(a), abs(d), 1.0) * 1e-10
    return a > 0.0 and d > 0.0 and abs(b) <= tolerance and abs(c) <= tolerance


def _inline_delivery_image_bytes(block: dict) -> bytes:
    cached = block.get("_bcs_delivery_image_bytes")
    if isinstance(cached, bytes) and cached:
        return cached
    image_bytes = bytes(block["image"])
    mask_bytes = block.get("mask")
    if isinstance(mask_bytes, (bytes, bytearray)) and mask_bytes:
        try:
            base_pixmap = fitz.Pixmap(image_bytes)
            if not base_pixmap.alpha:
                mask_pixmap = fitz.Pixmap(bytes(mask_bytes))
                if (
                    int(base_pixmap.width) != int(mask_pixmap.width)
                    or int(base_pixmap.height) != int(mask_pixmap.height)
                ):
                    raise ValueError("inline image mask dimensions do not match")
                image_bytes = bytes(fitz.Pixmap(base_pixmap, mask_pixmap).tobytes("png"))
        except (RuntimeError, TypeError, ValueError) as exc:
            raise RuntimeError(f"inline image mask cannot be applied: {exc}") from exc
    block["_bcs_delivery_image_bytes"] = image_bytes
    return image_bytes


def _inline_source_digest(info: dict, block: dict) -> str:
    if block.get("mask"):
        return hashlib.sha256(_inline_delivery_image_bytes(block)).hexdigest()
    digest = info.get("digest")
    if isinstance(digest, (bytes, bytearray)) and digest:
        return bytes(digest).hex()
    return hashlib.sha256(_inline_delivery_image_bytes(block)).hexdigest()


def _extract_inline_images_individually(
    inline_blocks: list[tuple[dict, dict]],
    *,
    page: fitz.Page,
    page_number: int,
    options: ExtractionOptions,
    image_dir: Path,
) -> List[ImagePlacement]:
    """Deliver a tractable rectilinear inline set as reusable source assets."""

    placements: list[ImagePlacement] = []
    written_assets: dict[str, Path] = {}
    asset_profiles: dict[
        str,
        tuple[Tuple[int, int], str, Tuple[int, int, int, int], bool],
    ] = {}
    page_height = float(page.rect.height)
    for info, block in inline_blocks:
        number = int(info.get("number", -1))
        image_bytes = _inline_delivery_image_bytes(block)
        asset_digest = hashlib.sha256(image_bytes).hexdigest()
        asset_path = written_assets.get(asset_digest)
        if asset_path is None:
            extension = (
                "png"
                if block.get("mask")
                else str(block.get("ext") or "png").lower().lstrip(".")
            )
            if extension not in {"png", "jpg", "jpeg", "bmp", "gif", "tif", "tiff"}:
                extension = "png"
            try:
                decoded = fitz.Pixmap(image_bytes)
            except (RuntimeError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"inline image instance {number} cannot be decoded: {exc}"
                ) from exc
            if int(decoded.width) <= 0 or int(decoded.height) <= 0:
                raise RuntimeError(f"inline image instance {number} has invalid dimensions")
            alpha_kind, alpha_bbox = _classify_pixmap_alpha(decoded)
            asset_path = image_dir / f"page_{page_number:03d}_inline_{asset_digest}.{extension}"
            asset_path.write_bytes(image_bytes)
            written_assets[asset_digest] = asset_path
            asset_profiles[asset_digest] = (
                (int(decoded.width), int(decoded.height)),
                alpha_kind,
                alpha_bbox,
                bool(decoded.alpha),
            )

        pixel_size, alpha_kind, alpha_bbox, alpha_present = asset_profiles[asset_digest]

        bbox = fitz.Rect(info.get("bbox") or block.get("bbox"))
        if bbox.is_empty or bbox.is_infinite:
            raise RuntimeError(f"inline image instance {number} has an invalid bbox")
        left = min(float(bbox.x0), float(bbox.x1))
        right = max(float(bbox.x0), float(bbox.x1))
        if options.flip_y:
            bottom = page_height - max(float(bbox.y0), float(bbox.y1))
            top = page_height - min(float(bbox.y0), float(bbox.y1))
        else:
            bottom = min(float(bbox.y0), float(bbox.y1))
            top = max(float(bbox.y0), float(bbox.y1))
        placements.append(
            ImagePlacement(
                page_number=page_number,
                x_mm=left * MM_PER_PT * options.scale,
                y_mm=bottom * MM_PER_PT * options.scale,
                width_mm=(right - left) * MM_PER_PT * options.scale,
                height_mm=(top - bottom) * MM_PER_PT * options.scale,
                path=str(asset_path),
                xref=0,
                source_kind="inline_image",
                source_instance_count=1,
                source_bbox_pdf=(
                    float(bbox.x0),
                    float(bbox.y0),
                    float(bbox.x1),
                    float(bbox.y1),
                ),
                source_number=number,
                source_digest=_inline_source_digest(info, block),
                pixel_size=pixel_size,
                alpha_kind=alpha_kind,
                alpha_bbox_px=alpha_bbox,
                alpha_present=alpha_present,
            )
        )
    return placements


def _render_inline_image_composite(
    inline_blocks: list[tuple[dict, dict]],
    *,
    page: fitz.Page,
    page_number: int,
    options: ExtractionOptions,
    image_dir: Path,
) -> ImagePlacement:
    """Render only inline images through one transparent MuPDF SVG page."""

    definitions: list[str] = []
    uses: list[str] = []
    asset_ids: dict[str, str] = {}
    for _info, block in inline_blocks:
        image_bytes = _inline_delivery_image_bytes(block)
        asset_digest = hashlib.sha256(image_bytes).hexdigest()
        asset_id = asset_ids.get(asset_digest)
        if asset_id is None:
            asset_id = f"img{len(asset_ids)}"
            asset_ids[asset_digest] = asset_id
            extension = (
                "png"
                if block.get("mask")
                else str(block.get("ext") or "png").lower().lstrip(".")
            )
            mime_subtype = "jpeg" if extension in {"jpg", "jpeg"} else extension
            if mime_subtype not in {"png", "jpeg", "bmp", "gif", "tiff"}:
                mime_subtype = "png"
            encoded = base64.b64encode(image_bytes).decode("ascii")
            definitions.append(
                f'<image id="{asset_id}" width="1" height="1" '
                'preserveAspectRatio="none" '
                f'href="data:image/{mime_subtype};base64,{encoded}"/>'
            )
        transform = " ".join(_svg_number(value) for value in block["transform"])
        uses.append(f'<use href="#{asset_id}" transform="matrix({transform})"/>')

    page_rect = page.rect
    width = float(page_rect.width)
    height = float(page_rect.height)
    if width <= 0.0 or height <= 0.0:
        raise RuntimeError("inline image composite source page is empty")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_svg_number(width)}" height="{_svg_number(height)}" '
        f'viewBox="{_svg_number(page_rect.x0)} {_svg_number(page_rect.y0)} '
        f'{_svg_number(width)} {_svg_number(height)}">'
        f'<defs>{"".join(definitions)}</defs>{"".join(uses)}</svg>'
    ).encode("ascii")
    dpi = max(36, int(options.raster_dpi or 200))
    try:
        with fitz.open("svg", svg) as image_document:
            pixmap = image_document[0].get_pixmap(
                matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0),
                alpha=True,
            )
            if not pixmap.alpha:
                raise RuntimeError("inline image composite lost transparency")
            alpha_kind, alpha_bbox = _classify_pixmap_alpha(pixmap)
            asset_path = image_dir / (
                f"page_{page_number:03d}_inline_composite_"
                f"{len(inline_blocks)}_{dpi}dpi.png"
            )
            pixmap.save(str(asset_path))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"inline image composite render failed: {exc}") from exc

    return ImagePlacement(
        page_number=page_number,
        x_mm=0.0,
        y_mm=0.0,
        width_mm=width * MM_PER_PT * options.scale,
        height_mm=height * MM_PER_PT * options.scale,
        path=str(asset_path),
        xref=0,
        source_kind="inline_image_composite",
        source_instance_count=len(inline_blocks),
        source_bbox_pdf=(
            float(page_rect.x0),
            float(page_rect.y0),
            float(page_rect.x1),
            float(page_rect.y1),
        ),
        source_digest=_inline_composite_source_digest(inline_blocks),
        pixel_size=(int(pixmap.width), int(pixmap.height)),
        alpha_kind=alpha_kind,
        alpha_bbox_px=alpha_bbox,
        alpha_present=bool(pixmap.alpha),
    )


def _inline_composite_source_digest(
    inline_blocks: list[tuple[dict, dict]],
) -> str:
    digest = hashlib.sha256()
    for info, block in inline_blocks:
        digest.update(bytes.fromhex(_inline_source_digest(info, block)))
        transform = " ".join(_svg_number(value) for value in block["transform"])
        digest.update(transform.encode("ascii"))
    return digest.hexdigest()


def _inline_image_page_fidelity_marker(
    inline_blocks: list[tuple[dict, dict]],
    *,
    page: fitz.Page,
    page_number: int,
    options: ExtractionOptions,
) -> ImagePlacement:
    """Record compositing need without allocating a large transparent page raster."""

    page_rect = page.rect
    width = float(page_rect.width)
    height = float(page_rect.height)
    dpi = max(36, int(options.raster_dpi or 200))
    pixel_size = (
        max(1, int(math.ceil(width * dpi / 72.0))),
        max(1, int(math.ceil(height * dpi / 72.0))),
    )
    return ImagePlacement(
        page_number=page_number,
        x_mm=0.0,
        y_mm=0.0,
        width_mm=width * MM_PER_PT * options.scale,
        height_mm=height * MM_PER_PT * options.scale,
        path="",
        xref=0,
        source_kind="inline_image_page_fidelity_required",
        source_instance_count=len(inline_blocks),
        source_bbox_pdf=(
            float(page_rect.x0),
            float(page_rect.y0),
            float(page_rect.x1),
            float(page_rect.y1),
        ),
        source_digest=_inline_composite_source_digest(inline_blocks),
        pixel_size=pixel_size,
        alpha_kind="compositing_required",
        alpha_bbox_px=(0, 0, pixel_size[0], pixel_size[1]),
        alpha_present=True,
    )


def _extract_images(doc: fitz.Document, page: fitz.Page, page_number: int,
                    options: ExtractionOptions, image_dir: Optional[Path]) -> List[ImagePlacement]:
    placements: list[ImagePlacement] = []
    if image_dir is None:
        return placements

    inline_blocks = _inline_image_blocks(page)
    page_rect = page.rect
    page_height = float(page_rect.height)
    rotation_matrix = _page_rotation_transform(
        page_rect,
        getattr(page, "rotation_matrix", None),
    )
    seen: set[tuple[int, int]] = set()
    for img_info in page.get_images(full=True):
        xref = int(img_info[0])
        smask = int(img_info[1] or 0)
        image_key = (xref, smask)
        if image_key in seen:
            continue
        seen.add(image_key)

        try:
            base_pix = fitz.Pixmap(doc, xref)
            pix = base_pix
            if smask > 0 and not base_pix.alpha:
                # Only merge when PyMuPDF handed back an opaque image. When the
                # base pixmap already carries alpha, PyMuPDF has applied the
                # soft mask itself -- verified on a representative source where
                # the base alpha channel was byte-identical to the soft mask's
                # samples for every page image. Merging again is not
                # merely redundant: fz_new_pixmap_from_color_and_mask rejects a
                # colour pixmap that has an alpha channel, which aborted the
                # whole import for every text mode, not just raster.
                mask_pix = fitz.Pixmap(doc, smask)
                if (
                    int(base_pix.width) != int(mask_pix.width)
                    or int(base_pix.height) != int(mask_pix.height)
                ):
                    raise ValueError(
                        "embedded image soft-mask dimensions do not match the source image"
                    )
                pix = fitz.Pixmap(base_pix, mask_pix)

            color_space_n = None
            try:
                color_space_n = int(getattr(getattr(pix, "colorspace", None), "n", 0))
            except (TypeError, ValueError):
                color_space_n = None

            needs_rgb = (
                pix.n not in {3, 4}
                or (color_space_n is not None and color_space_n != 3)
            )
            if needs_rgb:
                pix = fitz.Pixmap(fitz.csRGB, pix)

            alpha_kind, alpha_bbox = _classify_pixmap_alpha(pix)
            if alpha_kind == "zero":
                # A fully transparent source image has no visible PDF
                # contribution. Emitting an IMAGE entity can expose its
                # otherwise invisible boundary in CAD hosts.
                continue

            mask_suffix = f"_smask_{smask}" if smask > 0 else ""
            img_path = image_dir / (
                f"page_{page_number:03d}_xref_{xref}{mask_suffix}.png"
            )
            pix.save(str(img_path))
            rects = page.get_image_rects(img_info, transform=True)
        except (RuntimeError, OSError, ValueError, TypeError) as exc:
            raise RuntimeError(
                f"page {page_number} image xref {xref} soft-mask {smask} "
                f"could not be extracted faithfully: {exc}"
            ) from exc

        for rect, image_matrix in rects:
            x0, y0, x1, y1 = float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)
            a, b, c, d, e, f = (float(value) for value in image_matrix)
            model_scale = MM_PER_PT * options.scale

            # ``get_image_rects(..., transform=True)`` returns the image CTM
            # in crop-local, unrotated PDF coordinates. Compose it with the
            # visible page /Rotate transform before the model Y flip so IMAGE
            # entities stay registered with vectors and text on rotated pages.
            display_e, display_f = _transform_pdf_point(e, f, rotation_matrix)
            display_a, display_b = _transform_pdf_vector(a, b, rotation_matrix)
            display_c, display_d = _transform_pdf_vector(c, d, rotation_matrix)
            display_corners = (
                (display_e, display_f),
                (display_e + display_a, display_f + display_b),
                (display_e + display_c, display_f + display_d),
                (
                    display_e + display_a + display_c,
                    display_f + display_b + display_d,
                ),
            )

            if options.flip_y:
                model_corners = tuple(
                    (x * model_scale, (page_height - y) * model_scale)
                    for x, y in display_corners
                )
                affine_model = (
                    (display_c + display_e) * model_scale,
                    (page_height - (display_d + display_f)) * model_scale,
                    display_a * model_scale,
                    -display_b * model_scale,
                    -display_c * model_scale,
                    display_d * model_scale,
                )
            else:
                model_corners = tuple(
                    (x * model_scale, y * model_scale)
                    for x, y in display_corners
                )
                affine_model = (
                    (display_c + display_e) * model_scale,
                    (display_d + display_f) * model_scale,
                    display_a * model_scale,
                    display_b * model_scale,
                    -display_c * model_scale,
                    -display_d * model_scale,
                )

            left = min(point[0] for point in model_corners)
            right = max(point[0] for point in model_corners)
            bottom = min(point[1] for point in model_corners)
            top = max(point[1] for point in model_corners)

            placements.append(
                ImagePlacement(
                    page_number=page_number,
                    x_mm=left,
                    y_mm=bottom,
                    width_mm=right - left,
                    height_mm=top - bottom,
                    path=str(img_path),
                    xref=xref,
                    source_kind="xobject_image",
                    source_instance_count=1,
                    source_bbox_pdf=(x0, y0, x1, y1),
                    pixel_size=(int(pix.width), int(pix.height)),
                    alpha_kind=alpha_kind,
                    alpha_bbox_px=alpha_bbox,
                    alpha_present=bool(pix.alpha),
                    affine_pdf=tuple(float(value) for value in image_matrix),
                    affine_model=affine_model,
                )
            )

    xobject_placements = [
        placement
        for placement in placements
        if placement.source_kind == "xobject_image"
    ]
    if len(xobject_placements) > XOBJECT_IMAGE_COMPOSITE_THRESHOLD:
        digest = hashlib.sha256()
        for placement in xobject_placements:
            digest.update(str(int(placement.xref)).encode("ascii"))
            digest.update(repr(tuple(placement.affine_pdf or ())).encode("ascii"))
        page_rect = page.rect
        dpi = max(36, int(options.raster_dpi or 200))
        pixel_size = (
            max(1, int(math.ceil(float(page_rect.width) * dpi / 72.0))),
            max(1, int(math.ceil(float(page_rect.height) * dpi / 72.0))),
        )
        placements = [
            placement
            for placement in placements
            if placement.source_kind != "xobject_image"
        ]
        placements.append(
            ImagePlacement(
                page_number=page_number,
                x_mm=0.0,
                y_mm=0.0,
                width_mm=float(page_rect.width) * MM_PER_PT * options.scale,
                height_mm=float(page_rect.height) * MM_PER_PT * options.scale,
                path="",
                xref=0,
                source_kind="xobject_image_page_fidelity_required",
                source_instance_count=len(xobject_placements),
                source_bbox_pdf=(
                    float(page_rect.x0),
                    float(page_rect.y0),
                    float(page_rect.x1),
                    float(page_rect.y1),
                ),
                source_digest=digest.hexdigest(),
                pixel_size=pixel_size,
                alpha_kind="compositing_required",
                alpha_bbox_px=(0, 0, pixel_size[0], pixel_size[1]),
                alpha_present=True,
            )
        )

    if inline_blocks:
        use_composite = (
            len(inline_blocks) > INLINE_IMAGE_COMPOSITE_THRESHOLD
            or not all(
                _inline_block_is_rectilinear(block) for _info, block in inline_blocks
            )
        )
        if use_composite:
            dpi = max(36, int(options.raster_dpi or 200))
            projected_pixels = (
                max(1, int(math.ceil(float(page.rect.width) * dpi / 72.0)))
                * max(1, int(math.ceil(float(page.rect.height) * dpi / 72.0)))
            )
            if projected_pixels > INLINE_IMAGE_COMPOSITE_MAX_PIXELS:
                placements.append(
                    _inline_image_page_fidelity_marker(
                        inline_blocks,
                        page=page,
                        page_number=page_number,
                        options=options,
                    )
                )
            else:
                placements.append(
                    _render_inline_image_composite(
                        inline_blocks,
                        page=page,
                        page_number=page_number,
                        options=options,
                        image_dir=image_dir,
                    )
                )
        else:
            placements.extend(
                _extract_inline_images_individually(
                    inline_blocks,
                    page=page,
                    page_number=page_number,
                    options=options,
                    image_dir=image_dir,
                )
            )

    return placements


def _render_page_raster(
    page: fitz.Page,
    page_number: int,
    options: ExtractionOptions,
    image_dir: Optional[Path],
    *,
    masked_text_items: Sequence[object] = (),
) -> Optional[ImagePlacement]:
    if image_dir is None:
        return None

    requested_dpi = max(PAGE_RASTER_MIN_DPI, float(options.raster_dpi or 200))
    width = float(page.rect.width)
    height = float(page.rect.height)
    if width <= 0.0 or height <= 0.0:
        raise ValueError("page raster has invalid physical dimensions")
    requested_zoom = requested_dpi / 72.0
    pixel_budget_zoom = math.sqrt(PAGE_RASTER_MAX_PIXELS / (width * height))
    dimension_budget_zoom = min(
        PAGE_RASTER_MAX_DIMENSION / width,
        PAGE_RASTER_MAX_DIMENSION / height,
    )
    zoom = min(requested_zoom, pixel_budget_zoom, dimension_budget_zoom)
    effective_dpi = zoom * 72.0
    if effective_dpi + 1e-9 < PAGE_RASTER_MIN_DPI:
        raise RuntimeError(
            "page exceeds the safe raster resource budget even at "
            f"{PAGE_RASTER_MIN_DPI:g} DPI"
        )
    dpi = int(round(effective_dpi))
    matrix = fitz.Matrix(zoom, zoom)

    filtered_document = None
    try:
        render_page = page
        if masked_text_items:
            parent = getattr(page, "parent", None)
            source_page_number = getattr(page, "number", None)
            if parent is None or source_page_number is None:
                raise ValueError("cannot isolate source text from a detached PDF page")
            filtered_document = fitz.open()
            filtered_document.insert_pdf(
                parent,
                from_page=int(source_page_number),
                to_page=int(source_page_number),
            )
            render_page = filtered_document[0]
            for item in masked_text_items:
                source_bbox = getattr(item, "source_bbox_pdf", None)
                if not source_bbox or len(source_bbox) < 4:
                    raise ValueError(
                        "cannot remove duplicate page-raster text without an exact source bbox"
                    )
                source_rect = fitz.Rect(
                    *[float(value) for value in source_bbox[:4]]
                )
                if source_rect.is_empty or source_rect.is_infinite:
                    raise ValueError("source text bbox is invalid for text isolation")
                render_page.add_redact_annot(
                    source_rect,
                    fill=False,
                    cross_out=False,
                )
            applied = render_page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_NONE,
                graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                text=fitz.PDF_REDACT_TEXT_REMOVE,
            )
            if not applied:
                raise RuntimeError("source text isolation did not apply")

        pix = render_page.get_pixmap(matrix=matrix, alpha=bool(masked_text_items))
        alpha_kind, alpha_bbox = _classify_pixmap_alpha(pix)
        img_path = image_dir / f"page_{page_number:03d}_raster_{dpi}dpi.png"
        pix.save(str(img_path))
    except (MemoryError, RuntimeError, OSError, ValueError, TypeError):
        return None
    finally:
        if filtered_document is not None:
            filtered_document.close()

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
        source_kind="page_raster",
        source_instance_count=1,
        source_bbox_pdf=(
            float(page.rect.x0),
            float(page.rect.y0),
            float(page.rect.x1),
            float(page.rect.y1),
        ),
        pixel_size=(int(pix.width), int(pix.height)),
        alpha_kind=alpha_kind,
        alpha_bbox_px=alpha_bbox,
        alpha_present=bool(pix.alpha),
        masked_text_bboxes_pdf=tuple(
            tuple(float(value) for value in item.source_bbox_pdf[:4])
            for item in masked_text_items
            if getattr(item, "source_bbox_pdf", None)
        ),
    )
