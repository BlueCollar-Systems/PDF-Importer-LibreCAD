# -*- coding: utf-8 -*-
# DEPRECATED compatibility shim — use pdfcadcore.geometry_cleanup instead.
from __future__ import annotations
import warnings as _warnings
_warnings.warn(
    "PDFGeometryCleanup is deprecated; import from pdfcadcore.geometry_cleanup instead.",
    DeprecationWarning,
    stacklevel=2,
)
from pdfcadcore.geometry_cleanup import *  # noqa: F401,F403
