# -*- coding: utf-8 -*-
# DEPRECATED compatibility shim — use pdfcadcore.recognition instead.
from __future__ import annotations
import warnings as _warnings
_warnings.warn(
    "PDFRecognition is deprecated; import from pdfcadcore.recognition instead.",
    DeprecationWarning,
    stacklevel=2,
)
from pdfcadcore.recognition import *  # noqa: F401,F403
