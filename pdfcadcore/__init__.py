# -*- coding: utf-8 -*-
# pdfcadcore — Shared PDF vector import core
# BlueCollar Systems — BUILT. NOT BOUGHT.
"""
Host-neutral PDF vector extraction, recognition, and cleanup.
Used by FreeCAD, Blender, and LibreCAD importers.
"""
__version__ = "1.0.0"

from .primitives import (
    Primitive as Primitive,
    NormalizedText as NormalizedText,
    PageData as PageData,
    ParsedDimension as ParsedDimension,
    Region as Region,
    PageProfile as PageProfile,
    RecognitionConfig as RecognitionConfig,
    next_id as next_id,
    reset_ids as reset_ids,
)
from .import_config import ImportConfig as ImportConfig, CLEANUP_PRESETS as CLEANUP_PRESETS
from .primitive_extractor import extract_page as extract_page
from .auto_mode import classify_page_content as classify_page_content
from .hatch_detector import tag_hatch_primitives as tag_hatch_primitives
from .geometry_cleanup import (
    cleanup_primitives as cleanup_primitives,
    promote_circular_primitives as promote_circular_primitives,
)
from .qa_report import QAReport as QAReport, compute_counts_delta as compute_counts_delta
from .import_bounds import (
    ImportBounds as ImportBounds,
    compute_import_bounds as compute_import_bounds,
)
from .streaming import (
    iter_pages as iter_pages,
    PageProgress as PageProgress,
    DEFAULT_SOFT_BUDGET_S as DEFAULT_SOFT_BUDGET_S,
)
