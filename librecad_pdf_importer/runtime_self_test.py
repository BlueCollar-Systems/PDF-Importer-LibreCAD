"""Fail-closed runtime dependency probe used by source and frozen entrypoints."""

from __future__ import annotations


PYMUPDF_RUNTIME_VERSION = "1.28.2"
TEXTTRACE_PROBE_ITERATIONS = 2048


def require_pymupdf_runtime(fitz) -> None:
    """Reject runtimes preceding the native text-trace lifetime repair."""

    version = str(getattr(fitz, "__version__", "") or getattr(fitz, "VersionBind", ""))
    if version != PYMUPDF_RUNTIME_VERSION:
        raise RuntimeError(
            f"PyMuPDF {PYMUPDF_RUNTIME_VERSION} is required; found {version or 'unknown'}. "
            "Install the declared runtime dependencies."
        )


def verify_texttrace_runtime(fitz) -> None:
    """Exercise native text traces repeatedly before runtime promotion."""

    require_pymupdf_runtime(fitz)
    expected = [f"TEXT_TRACE_{index:02d}" for index in range(10)]
    with fitz.open() as document:
        page = document.new_page(width=200, height=250)
        for index, text in enumerate(expected):
            page.insert_text((10, 20 + 20 * index), text, fontsize=8)
        for _ in range(TEXTTRACE_PROBE_ITERATIONS):
            spans = page.get_texttrace()
            actual = [
                "".join(chr(character[0]) for character in span["chars"])
                for span in spans
            ]
            if actual != expected:
                raise RuntimeError("PyMuPDF repeated text-trace verification failed")


def load_fonttools_dependencies() -> None:
    """Import every FontTools API reached by the exact-font production path."""

    from fontTools.agl import toUnicode  # noqa: F401
    from fontTools.cffLib import CFFFontSet  # noqa: F401
    from fontTools.fontBuilder import FontBuilder  # noqa: F401
    from fontTools.pens.basePen import NullPen  # noqa: F401
    from fontTools.pens.boundsPen import BoundsPen, ControlBoundsPen  # noqa: F401
    from fontTools.pens.recordingPen import RecordingPen  # noqa: F401
    from fontTools.pens.ttGlyphPen import TTGlyphPen  # noqa: F401
    from fontTools.ttLib import TTFont, newTable  # noqa: F401
    from fontTools.ttLib.tables._c_m_a_p import CmapSubtable  # noqa: F401


def load_runtime_dependencies() -> None:
    """Import the exact modules exercised by production representation delivery."""

    import ezdxf  # noqa: F401
    from ezdxf.addons import text2path  # noqa: F401
    from ezdxf.fonts import fonts as ezdxf_fonts  # noqa: F401
    from ezdxf.fonts.font_face import FontFace  # noqa: F401
    import numpy  # noqa: F401
    import librecad_pdf_importer  # noqa: F401
    import pdfcadcore  # noqa: F401

    try:
        import pymupdf as fitz  # noqa: F401
    except ImportError:
        import fitz  # type: ignore[no-redef]  # noqa: F401

    verify_texttrace_runtime(fitz)
    load_fonttools_dependencies()


def run_runtime_self_test() -> int:
    try:
        load_runtime_dependencies()
    except Exception as exc:
        print(f"LibreCAD PDF Importer self-test FAILED: {exc}")
        return 1
    print(
        "LibreCAD PDF Importer self-test OK "
        "(PyMuPDF, ezdxf font/text2path, FontTools, Matplotlib, NumPy)"
    )
    return 0
