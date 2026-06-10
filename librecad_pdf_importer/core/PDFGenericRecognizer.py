# -*- coding: utf-8 -*-
# DEPRECATED compatibility shim — use pdfcadcore.generic_recognizer instead.
from __future__ import annotations
import warnings as _warnings
_warnings.warn(
    "PDFGenericRecognizer is deprecated; import from pdfcadcore.generic_recognizer instead.",
    DeprecationWarning,
    stacklevel=2,
)
from pdfcadcore.generic_recognizer import *  # noqa: F401,F403
