# -*- coding: utf-8 -*-
# DEPRECATED compatibility shim — use pdfcadcore.validation instead.
from __future__ import annotations
import warnings as _warnings
_warnings.warn(
    "PDFValidation is deprecated; import from pdfcadcore.validation instead.",
    DeprecationWarning,
    stacklevel=2,
)
from pdfcadcore.validation import *  # noqa: F401,F403
