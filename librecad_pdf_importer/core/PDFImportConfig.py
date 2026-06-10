# -*- coding: utf-8 -*-
# DEPRECATED compatibility shim — use pdfcadcore.import_config instead.
from __future__ import annotations
import warnings as _warnings
_warnings.warn(
    "PDFImportConfig is deprecated; import from pdfcadcore.import_config instead.",
    DeprecationWarning,
    stacklevel=2,
)
from pdfcadcore.import_config import *  # noqa: F401,F403
