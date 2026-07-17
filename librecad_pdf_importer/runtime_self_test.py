"""Fail-closed runtime dependency probe used by source and frozen entrypoints."""

from __future__ import annotations


def load_fonttools_dependencies() -> None:
    """Import every FontTools API reached by the exact-font production path."""

    from fontTools.agl import toUnicode  # noqa: F401
    from fontTools.cffLib import CFFFontSet  # noqa: F401
    from fontTools.fontBuilder import FontBuilder  # noqa: F401
    from fontTools.pens.basePen import NullPen  # noqa: F401
    from fontTools.pens.boundsPen import BoundsPen, ControlBoundsPen  # noqa: F401
    from fontTools.pens.ttGlyphPen import TTGlyphPen  # noqa: F401
    from fontTools.ttLib import TTFont, newTable  # noqa: F401
    from fontTools.ttLib.tables._c_m_a_p import CmapSubtable  # noqa: F401


def load_runtime_dependencies() -> None:
    """Import the exact modules exercised by production representation delivery."""

    import ezdxf  # noqa: F401
    import librecad_pdf_importer  # noqa: F401
    import pdfcadcore  # noqa: F401

    try:
        import pymupdf as fitz  # noqa: F401
    except ImportError:
        import fitz  # type: ignore[no-redef]  # noqa: F401

    load_fonttools_dependencies()


def run_runtime_self_test() -> int:
    try:
        load_runtime_dependencies()
    except Exception as exc:
        print(f"LibreCAD PDF Importer self-test FAILED: {exc}")
        return 1
    print("LibreCAD PDF Importer self-test OK (PyMuPDF, ezdxf, FontTools)")
    return 0
