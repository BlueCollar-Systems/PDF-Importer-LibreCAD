# -*- coding: utf-8 -*-
# DEPRECATED compatibility shim — use pdfcadcore.primitives instead.
from __future__ import annotations
import warnings as _warnings
_warnings.warn(
    "PDFPrimitives is deprecated; import from pdfcadcore.primitives instead.",
    DeprecationWarning,
    stacklevel=2,
)
from pdfcadcore.primitives import *  # noqa: F401,F403
