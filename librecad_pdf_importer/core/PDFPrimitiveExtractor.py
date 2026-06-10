# -*- coding: utf-8 -*-
# DEPRECATED compatibility shim — use pdfcadcore.primitive_extractor instead.
from __future__ import annotations
import warnings as _warnings
_warnings.warn(
    "PDFPrimitiveExtractor is deprecated; import from pdfcadcore.primitive_extractor instead.",
    DeprecationWarning,
    stacklevel=2,
)
from pdfcadcore.primitive_extractor import *  # noqa: F401,F403
