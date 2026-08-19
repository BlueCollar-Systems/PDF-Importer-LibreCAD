"""EOFError from fontTools must be treated as a malformed embedded font.

Why EOFError specifically, and why it is equivalent to the struct.error case already
guarded here (confirmed before this change, not assumed):

* fontTools raises EOFError from exactly ONE site in the whole library --
  ``cffLib.readSID``: "Unexpected end of file while reading SID" -- when a CFF Encoding
  supplement stops mid-read. Its only possible meaning is font data that ended early,
  which is the same class of failure as ``struct.error``.
* The two CFF->OTF tuples in this same module already list EOFError as a malformed-source
  failure, so the module's own precedent treats it that way.
* All three functions guarded below reach cffLib: they call ``getGlyphOrder()`` /
  ``getGlyphSet()``, and for an OTF source the glyph order comes from the CFF charset.
* ``EOFError`` subclasses only ``Exception``. It is not caught by any other name in these
  tuples, so before this change it propagated and aborted the whole page's text -- exactly
  the failure ``struct.error`` produced.

Honest limit: EOFError could not be reached by truncating a real TTF or CFF/OTF (65 and
127 truncation points respectively produced only AssertionError, struct.error and
TTLibError). It needs a font carrying a custom Encoding supplement. These locks therefore
inject the exception at the fontTools boundary rather than synthesising such a font, which
tests the guard without pretending to a fixture that was never built.
"""
from __future__ import annotations

import pytest

from pdfcadcore import embedded_fonts


class _RaisesEOF:
    """Stand-in for TTFont that fails the way cffLib.readSID does."""

    def __init__(self, *args, **kwargs):
        raise EOFError("Unexpected end of file while reading SID")


@pytest.fixture()
def _fonttools_raises_eof(monkeypatch):
    import fontTools.ttLib as ttlib

    monkeypatch.setattr(ttlib, "TTFont", _RaisesEOF)
    return ttlib


def test_fonttools_loadable_reports_unloadable_instead_of_raising(_fonttools_raises_eof):
    assert embedded_fonts._fonttools_loadable(b"not-a-font") is False


def test_font_program_name_aliases_returns_empty_instead_of_raising(_fonttools_raises_eof):
    assert embedded_fonts._font_program_name_aliases(b"not-a-font", "otf") == set()


def test_font_delivery_metrics_converts_to_exact_font_source_impossible(
    _fonttools_raises_eof,
):
    """This one converts rather than returning: the caller needs the proof object."""
    with pytest.raises(embedded_fonts.ExactFontSourceImpossible) as excinfo:
        embedded_fonts._font_delivery_metrics(b"not-a-font")
    assert "EOFError" in str(excinfo.value)


def test_eoferror_is_not_already_covered_by_the_other_guarded_names():
    """If EOFError ever became a subclass of another guarded name this lock is redundant.

    It is not: EOFError -> Exception -> BaseException. The explicit entry is required.
    """
    import struct

    from fontTools.ttLib import TTLibError

    assert not issubclass(
        EOFError,
        (AssertionError, AttributeError, KeyError, OSError, TTLibError, TypeError,
         ValueError, struct.error),
    )


def test_all_three_tuples_list_eoferror():
    """Guards against a future edit dropping it from one copy only."""
    import inspect

    source = inspect.getsource(embedded_fonts)
    guarded = source.count("        EOFError,\n")
    assert guarded >= 5, (
        f"expected EOFError in all five malformed-source tuples, found {guarded}")
