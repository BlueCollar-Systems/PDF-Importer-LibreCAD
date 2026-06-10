# -*- coding: utf-8 -*-
# PDFRecognition.py — Pipeline orchestrator
# BlueCollar Systems — BUILT. NOT BOUGHT.
"""
Modes: none, generic, auto
Generic recognition runs document profiling, circle/boundary detection,
table/title block detection, and dimension association.
"""
from __future__ import annotations
from .PDFPrimitives import PageData, RecognitionConfig
from . import PDFGenericRecognizer as generic_rec
from . import PDFDocumentProfiler as profiler


def run(page_data: PageData, mode: str = "auto", config: RecognitionConfig = None):
    if config is None:
        config = RecognitionConfig()
    if mode == "none":
        return {"generic": None, "mode_used": "none"}

    generic = generic_rec.analyze(page_data, config)

    if mode == "auto":
        profile = profiler.profile(page_data)
        effective = profile.primary_type if profile else "generic"
    else:
        effective = mode

    return {"generic": generic, "mode_used": effective}

