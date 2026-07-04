# -*- coding: utf-8 -*-
# import_config.py -- Versioned import configuration
# BlueCollar Systems -- BUILT. NOT BOUGHT.
"""
Centralised import configuration for PDF Vector Importers.
Shared across FreeCAD, Blender, and LibreCAD hosts.

BCS-ARCH-001 compliance (authoritative; see _LLM_CONTROL_PACK/BCS-ARCH-001.md):

- Four modes only: auto (default), vector, raster, hybrid.
- Text rendering is a separate orthogonal control:
  labels, 3d_text, glyphs, geometry.
- Every mode targets indistinguishable-from-source fidelity.
  Modes differ only in extraction strategy on different input types;
  they do NOT differ in quality target.
- No preset-specific parameter tuning. Every parameter has one correct
  value.

The deprecated preset names (fast, general, technical, shop,
raster_vector, raster_only, max) have been removed. Do not re-introduce
them under any name.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, fields
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------
# Cleanup tolerances (tolerance values in mm).
# BCS-ARCH-001 Rule 5: one correct value per parameter. "balanced" is
# retained as the tightest *safe* level — "aggressive" can collapse
# real hairline geometry; "conservative" is too loose to meet the
# "indistinguishable from source" quality bar.
# --------------------------------------------------------------------
CLEANUP_PRESETS: Dict[str, Dict[str, float]] = {
    "balanced": {
        "merge_tol": 0.1,
        "collinear_tol": 0.05,
        "min_seg": 0.05,
    },
}


@dataclass
class ImportConfig:
    """Import configuration for PDF Vector Importers (BCS-ARCH-001)."""

    VERSION: str = "3.0"

    # ---- Core geometry options ----------------------------------
    pages: Optional[List[int]] = None
    scale_to_mm: bool = True
    user_scale: float = 1.0
    flip_y: bool = True
    # Consolidated to the tightest value ("max_fidelity" old value).
    join_tol: float = 0.05
    min_seg_len: float = 0.0
    curve_step_mm: float = 0.2
    make_faces: bool = True
    import_text: bool = True

    # Text rendering (orthogonal to mode). One of:
    #   "labels"   -- host-native text objects, editable as text
    #   "3d_text"  -- extruded geometric text (host support varies)
    #   "glyphs"   -- non-editable outline geometry for visual fidelity
    #   "geometry" -- text fully converted to non-editable geometry
    text_mode: str = "3d_text"

    strict_text_fidelity: bool = True
    group_by_color: bool = True
    assign_lineweight: bool = True
    map_dashes: bool = True
    verbose: bool = True
    create_top_group: bool = True
    hatch_to_faces: bool = True
    hatch_mode: str = "group"               # "import" | "skip" | "group"
    ignore_images: bool = False
    raster_fallback: bool = True
    raster_dpi: int = 300
    # Mode (BCS-ARCH-001). One of:
    #   "auto"   -- default; pick strategy per page from classifier
    #   "vector" -- force vector extraction
    #   "raster" -- force raster rendering
    #   "hybrid" -- mixed vectors + raster regions
    import_mode: str = "auto"
    # Optional host-side 3D generation. 2D hosts keep this as report-only
    # awareness; FreeCAD/Blender/SketchUp can create solids when enabled.
    model3d_mode: str = "off"              # "off" | "auto" | "extrude"
    model3d_depth_mm: float = 3.175        # default 1/8 in plate thickness
    max_bezier_segments: int = 128

    # ---- Arc reconstruction -------------------------------------
    detect_arcs: bool = True
    arc_fit_tol_mm: float = 0.05
    min_arc_angle_deg: float = 5.0
    arc_sampling_pts: int = 7

    # ---- Layering -----------------------------------------------
    layer_mode: str = "auto"                # "auto" | "ocg" | "color" | "none"

    # ---- Object-count management --------------------------------
    compound_batch_size: int = 200
    heavy_page_threshold: int = 3000

    # ---- Phase 2 options ----------------------------------------
    arc_mode: str = "auto"
    cleanup_level: str = "balanced"
    lineweight_mode: str = "preserve"
    grouping_mode: str = "per_page"

    # ---- Auto-mode resolution record (populated at extract time) ----
    # When import_mode == "auto", the extractor classifies each page and
    # resolves to "vector"/"raster"/"hybrid". These fields record the
    # per-document summary so host adapters can report to the user.
    auto_resolved_mode: Optional[str] = None
    auto_reason: Optional[str] = None

    # --------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("VERSION", None)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ImportConfig":
        valid_keys = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**filtered)

    def get_cleanup_tolerances(self) -> Dict[str, float]:
        return dict(CLEANUP_PRESETS.get(self.cleanup_level,
                                        CLEANUP_PRESETS["balanced"]))

    # ---- Mode constructors (BCS-ARCH-001) -----------------------
    # These are the ONLY named constructors that exist. Deprecated
    # preset constructors (fast, general_vector, technical_drawing,
    # shop_drawing, full, max_fidelity) have been removed per
    # BCS-ARCH-001 and MUST NOT be reintroduced.
    @classmethod
    def auto(cls) -> "ImportConfig":
        """Auto mode (default). Strategy is chosen per page at extract time."""
        return cls(import_mode="auto")

    @classmethod
    def vector(cls) -> "ImportConfig":
        """Vector mode. Extract all vector geometry faithfully. No raster fallback."""
        return cls(import_mode="vector", raster_fallback=False)

    @classmethod
    def raster(cls) -> "ImportConfig":
        """Raster mode. Place page as high-DPI image. No vector extraction."""
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
        """Hybrid mode. Extract vectors where clean; raster where lossy."""
        return cls(
            import_mode="hybrid",
            ignore_images=False,
            raster_fallback=True,
        )
