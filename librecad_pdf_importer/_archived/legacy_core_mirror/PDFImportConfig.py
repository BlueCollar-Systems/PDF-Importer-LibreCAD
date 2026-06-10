# -*- coding: utf-8 -*-
# PDFImportConfig.py — Versioned import configuration
# BlueCollar Systems — BUILT. NOT BOUGHT.
"""
Centralised, versioned import configuration for the PDF Vector Importer.

Parallels the SketchUp importer's versioned config pattern so that saved
profiles, presets, and future Phase-2 options all live in one place.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, fields
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────────────────────────
# Cleanup presets  (tolerance values in mm)
# ──────────────────────────────────────────────────────────────────────
CLEANUP_PRESETS: Dict[str, Dict[str, float]] = {
    "conservative": {
        "merge_tol": 0.5,
        "collinear_tol": 0.25,
        "min_seg": 0.25,
    },
    "balanced": {
        "merge_tol": 0.1,
        "collinear_tol": 0.05,
        "min_seg": 0.05,
    },
    "aggressive": {
        "merge_tol": 0.01,
        "collinear_tol": 0.005,
        "min_seg": 0.01,
    },
}


# ──────────────────────────────────────────────────────────────────────
# ImportConfig dataclass
# ──────────────────────────────────────────────────────────────────────
@dataclass
class ImportConfig:
    """Versioned import configuration for the PDF Vector Importer.

    All fields mirror the options accepted by ``PDFImporterCore.ImportOptions``
    plus Phase-2 additions (arc_mode, cleanup_level, lineweight_mode,
    grouping_mode).
    """

    VERSION: str = "2.0"

    # ── Core geometry options (Phase 1 — existing) ───────────────────
    pages: Optional[List[int]] = None
    scale_to_mm: bool = True
    user_scale: float = 1.0
    flip_y: bool = True
    join_tol: float = 0.1
    min_seg_len: float = 0.0
    curve_step_mm: float = 0.5
    make_faces: bool = True
    import_text: bool = True
    text_mode: str = "3d_text"              # "labels" | "3d_text" | "glyphs" | "geometry"
    strict_text_fidelity: bool = True
    group_by_color: bool = True
    assign_linewidth: bool = True
    map_dashes: bool = True
    verbose: bool = True
    create_top_group: bool = True
    hatch_to_faces: bool = True
    hatch_mode: str = "import"              # "import" | "skip" | "group"
    ignore_images: bool = False
    raster_fallback: bool = True
    raster_dpi: int = 200
    import_mode: str = "auto"               # "auto" | "vector" | "raster" | "hybrid"
    max_bezier_segments: int = 128

    # ── Arc reconstruction (Phase 1) ─────────────────────────────────
    detect_arcs: bool = True
    arc_fit_tol_mm: float = 0.08
    min_arc_angle_deg: float = 5.0
    arc_sampling_pts: int = 7

    # ── Layering (Phase 1) ───────────────────────────────────────────
    layer_mode: str = "auto"                # "auto" | "ocg" | "color" | "none"

    # ── Object-count management (Phase 1) ────────────────────────────
    compound_batch_size: int = 200
    heavy_page_threshold: int = 3000

    # ── Phase 2 options ──────────────────────────────────────────────
    arc_mode: str = "auto"
    # "auto"     — heuristic per-path (current behaviour)
    # "preserve" — keep arcs found by PyMuPDF as-is
    # "rebuild"  — always run arc-fit on polylines
    # "polyline" — skip arc detection entirely

    cleanup_level: str = "balanced"
    # "conservative" | "balanced" | "aggressive"
    # Maps to tolerance values via CLEANUP_PRESETS.

    lineweight_mode: str = "ignore"
    # "ignore"          — all geometry same lineweight
    # "preserve"        — set ViewObject linewidth from PDF stroke width
    # "group"           — group objects by lineweight
    # "map_to_layers"   — create layers based on lineweight ranges

    grouping_mode: str = "per_page"
    # "single"                — everything in one group
    # "per_page"              — one group per PDF page (current default)
    # "per_layer"             — one group per OCG / colour layer
    # "per_color"             — one group per stroke/fill colour
    # "nested_page_layer"     — page > layer hierarchy
    # "nested_page_lineweight"— page > lineweight hierarchy

    # ─────────────────────────────────────────────────────────────────
    # Serialisation
    # ─────────────────────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        """Return a plain dict compatible with ``PDFImporterCore.ImportOptions``.

        Phase-2 keys are included so that downstream code can opt-in to them
        without breaking older code that simply ignores unknown keys.
        """
        d = asdict(self)
        # VERSION is metadata, not an ImportOptions field
        d.pop("VERSION", None)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ImportConfig":
        """Create an ``ImportConfig`` from a saved dict (profile loading).

        Unknown keys are silently ignored so that profiles saved by a newer
        version can still be loaded by an older one.
        """
        valid_keys = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**filtered)

    # ─────────────────────────────────────────────────────────────────
    # Cleanup tolerance helpers
    # ─────────────────────────────────────────────────────────────────
    def get_cleanup_tolerances(self) -> Dict[str, float]:
        """Return the tolerance dict for the current ``cleanup_level``.

        Falls back to 'balanced' if the level name is unrecognised.
        """
        return dict(CLEANUP_PRESETS.get(self.cleanup_level,
                                        CLEANUP_PRESETS["balanced"]))

    # ─────────────────────────────────────────────────────────────────
    # Mode constructors (BCS-ARCH-001)
    # Four modes only: auto, vector, raster, hybrid.
    # Parameter values come from the canonical pdfcadcore.ImportConfig
    # consolidated table — this local copy must not diverge.
    # ─────────────────────────────────────────────────────────────────
    @classmethod
    def auto(cls) -> "ImportConfig":
        """Auto mode (default). Strategy chosen per page at extract time."""
        return cls(import_mode="auto")

    @classmethod
    def vector(cls) -> "ImportConfig":
        """Vector mode. Extract all vector geometry faithfully."""
        return cls(import_mode="vector", raster_fallback=False)

    @classmethod
    def raster(cls) -> "ImportConfig":
        """Raster mode. Place page as high-DPI image."""
        return cls(
            import_mode="raster",
            import_text=False,
            detect_arcs=False,
            make_faces=False,
            map_dashes=False,
            hatch_mode="skip",
        )

    @classmethod
    def hybrid(cls) -> "ImportConfig":
        """Hybrid mode. Vectors where clean; raster where lossy."""
        return cls(
            import_mode="hybrid",
            ignore_images=False,
            raster_fallback=True,
        )
