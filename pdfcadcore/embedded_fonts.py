"""Exact, in-memory font evidence recovered from one PDF page.

The catalog never searches the operating system for a similarly named font.
Raw CFF programs are directly usable by Blender.  When the free ``fontTools``
package is available, raw CFF is wrapped as deterministic OpenType and subset
TTF cmap tables are repaired from PyMuPDF text-trace glyph identities.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
from io import BytesIO
import math
import re
import struct
from types import MappingProxyType
from typing import Mapping, Optional


_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
_SAFE_POSTSCRIPT_NAME = re.compile(r"[^A-Za-z0-9._-]+")
MAX_EMBEDDED_FONT_BYTES = 64 * 1024 * 1024
MAX_EMBEDDED_FONT_GLYPHS = 65_535
MAX_EMBEDDED_FONT_TABLES = 512
MAX_EMBEDDED_FONT_WORK_UNITS = 2_000_000
_BASE14_FONT_CODES = {
    "Helvetica": "helv",
    "Helvetica-Bold": "hebo",
    "Helvetica-Oblique": "heit",
    "Helvetica-BoldOblique": "hebi",
    "Times-Roman": "tiro",
    "Times-Bold": "tibo",
    "Times-Italic": "tiit",
    "Times-BoldItalic": "tibi",
    "Courier": "cour",
    "Courier-Bold": "cobo",
    "Courier-Oblique": "coit",
    "Courier-BoldOblique": "cobi",
    "Symbol": "symb",
    "ZapfDingbats": "zadb",
}


class ExactFontSourceImpossible(ValueError):
    """The exact PDF font program cannot represent this source item."""


class ExactFontRuntimeUnavailable(RuntimeError):
    """The current free runtime cannot build the exact font asset."""


@dataclass(frozen=True)
class EmbeddedFontFailure:
    page_number: int
    span_font_name: str
    reason: str
    source_xref: Optional[int] = None
    error_type: str = ""
    detail: str = ""
    proof_category: str = ""


@dataclass(frozen=True)
class EmbeddedFontAsset:
    page_number: int
    span_font_name: str
    base_font_name: str
    source_xref: int
    resource_name: str
    source_font_type: str
    source_encoding: str
    source_format: str
    source_origin: str
    source_bytes: bytes = field(repr=False, compare=False)
    source_sha256: str
    usable_format: str
    usable_bytes: bytes = field(repr=False, compare=False)
    usable_sha256: str
    asset_id: str
    unicode_map_installed: bool = False
    units_per_em: int = 0
    ascender: int = 0
    descender: int = 0
    glyph_advances: tuple[int, ...] = field(default=(), repr=False)


def _without_subset_prefix(name: object) -> str:
    return _SUBSET_PREFIX.sub("", str(name or ""))


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def _validate_font_work_bounds(
    data: bytes,
    *,
    glyph_count: Optional[int] = None,
    table_count: Optional[int] = None,
    work_units: Optional[int] = None,
) -> None:
    """Reject font programs that exceed finite importer-owned work bounds."""
    byte_count = len(bytes(data or b""))
    if byte_count > int(MAX_EMBEDDED_FONT_BYTES):
        raise ExactFontSourceImpossible(
            f"embedded font size {byte_count} exceeds embedded-font byte limit "
            f"{int(MAX_EMBEDDED_FONT_BYTES)}"
        )
    if glyph_count is not None and int(glyph_count) > int(MAX_EMBEDDED_FONT_GLYPHS):
        raise ExactFontSourceImpossible(
            f"embedded font glyph count {int(glyph_count)} exceeds embedded-font "
            f"glyph limit {int(MAX_EMBEDDED_FONT_GLYPHS)}"
        )
    if table_count is not None and int(table_count) > int(MAX_EMBEDDED_FONT_TABLES):
        raise ExactFontSourceImpossible(
            f"embedded font table count {int(table_count)} exceeds embedded-font "
            f"table limit {int(MAX_EMBEDDED_FONT_TABLES)}"
        )
    if work_units is not None and int(work_units) > int(MAX_EMBEDDED_FONT_WORK_UNITS):
        raise ExactFontSourceImpossible(
            f"embedded font work estimate {int(work_units)} exceeds embedded-font "
            f"work limit {int(MAX_EMBEDDED_FONT_WORK_UNITS)}"
        )


def _fonttools_loadable(data: bytes) -> bool:
    from fontTools.ttLib import TTFont, TTLibError

    _validate_font_work_bounds(data)
    try:
        font = TTFont(BytesIO(data), lazy=False, recalcTimestamp=False)
        _validate_font_work_bounds(
            data,
            glyph_count=len(font.getGlyphOrder()),
            table_count=len(tuple(font.reader.keys())),
        )
        for tag in font.reader.keys():
            font[tag].compile(font)
        font.close()
        return True
    except (AttributeError, KeyError, OSError, TTLibError, TypeError, ValueError):
        return False


def _font_delivery_metrics(data: bytes) -> tuple[int, int, int, tuple[int, ...]]:
    """Return bounded metrics needed to map Blender font axes to PDF axes."""
    from fontTools.ttLib import TTFont, TTLibError

    _validate_font_work_bounds(data)
    font = None
    try:
        font = TTFont(BytesIO(data), lazy=False, recalcTimestamp=False)
        glyph_order = tuple(font.getGlyphOrder())
        _validate_font_work_bounds(
            data,
            glyph_count=len(glyph_order),
            table_count=len(tuple(font.reader.keys())),
            work_units=len(glyph_order) + len(tuple(font.reader.keys())),
        )
        units_per_em = int(font["head"].unitsPerEm)
        ascender = int(font["hhea"].ascent)
        descender = int(font["hhea"].descent)
        if not 16 <= units_per_em <= 16384:
            raise ExactFontSourceImpossible(
                f"usable font unitsPerEm is out of range: {units_per_em}"
            )
        if ascender <= descender:
            raise ExactFontSourceImpossible(
                f"usable font has invalid vertical metrics: {ascender}, {descender}"
            )
        hmtx = font["hmtx"].metrics
        advances = tuple(int(hmtx[name][0]) for name in glyph_order)
        if len(advances) != len(glyph_order) or any(value < 0 for value in advances):
            raise ExactFontSourceImpossible("usable font has invalid horizontal metrics")
        return units_per_em, ascender, descender, advances
    except ExactFontSourceImpossible:
        raise
    except (AttributeError, KeyError, OSError, TTLibError, TypeError, ValueError) as exc:
        raise ExactFontSourceImpossible(
            f"usable font delivery metrics are unavailable: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        if font is not None:
            font.close()


def _cff_units_per_em(font_matrix) -> int:
    try:
        scale = abs(float(font_matrix[0]))
    except (IndexError, TypeError, ValueError):
        scale = 0.001
    if not math.isfinite(scale) or scale <= 0.0:
        raise ExactFontSourceImpossible("raw CFF has no finite positive FontMatrix scale")
    units_per_em = int(round(1.0 / scale))
    if not 16 <= units_per_em <= 16384:
        raise ExactFontSourceImpossible(
            f"raw CFF unitsPerEm is out of range: {units_per_em}"
        )
    return units_per_em


def _cff_character_map(top_dict, glyph_order: list[str]) -> dict[int, str]:
    cmap: dict[int, str] = {}
    glyph_names = set(glyph_order)
    encoding = getattr(top_dict, "Encoding", None)
    if isinstance(encoding, (list, tuple)):
        for codepoint, glyph_name in enumerate(encoding):
            if glyph_name in glyph_names and glyph_name != ".notdef":
                cmap[codepoint] = glyph_name
    try:
        from fontTools.agl import toUnicode

        for glyph_name in glyph_order:
            if glyph_name == ".notdef":
                continue
            text = toUnicode(glyph_name)
            if len(text) == 1:
                cmap.setdefault(ord(text), glyph_name)
    except ImportError:
        pass
    return cmap


def _cff_to_otf_unchecked(source_bytes: bytes, base_font_name: str) -> bytes:
    from fontTools.cffLib import CFFFontSet
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.pens.basePen import NullPen

    _validate_font_work_bounds(source_bytes)
    cff = CFFFontSet()
    cff.decompile(BytesIO(source_bytes), None, isCFF2=False)
    if not cff.topDictIndex:
        raise ExactFontSourceImpossible("raw CFF has no top dictionary")
    top = cff.topDictIndex[0]
    glyph_order = list(top.charset)
    _validate_font_work_bounds(source_bytes, glyph_count=len(glyph_order))
    if not glyph_order or glyph_order[0] != ".notdef":
        raise ExactFontSourceImpossible(
            "raw CFF has no canonical .notdef-first glyph order"
        )

    work_units = 0
    for glyph_name in glyph_order:
        char_string = top.CharStrings[glyph_name]
        bytecode = getattr(char_string, "bytecode", None)
        program = getattr(char_string, "program", None)
        work_units += len(bytecode or program or ())
        _validate_font_work_bounds(source_bytes, work_units=work_units)
    cff.desubroutinize()

    units_per_em = _cff_units_per_em(getattr(top, "FontMatrix", None))
    char_strings = {name: top.CharStrings[name] for name in glyph_order}
    metrics: dict[str, tuple[int, int]] = {}
    for glyph_name, char_string in char_strings.items():
        char_string.draw(NullPen())
        advance = int(round(float(char_string.width)))
        bounds_pen = BoundsPen(None)
        char_string.draw(bounds_pen)
        left = int(round(float(bounds_pen.bounds[0]))) if bounds_pen.bounds else 0
        metrics[glyph_name] = (advance, left)

    font_bbox = [float(v) for v in getattr(top, "FontBBox", (0, 0, 0, 0))]
    if len(font_bbox) != 4:
        font_bbox = [0.0, 0.0, 0.0, 0.0]
    descent = int(math.floor(min(font_bbox[1], 0.0)))
    ascent = int(math.ceil(max(font_bbox[3], float(units_per_em))))
    safe_name = _SAFE_POSTSCRIPT_NAME.sub("-", base_font_name).strip("-") or "EmbeddedFont"
    weight = str(getattr(top, "Weight", "Regular") or "Regular")

    builder = FontBuilder(units_per_em, isTTF=False)
    builder.font["head"].created = 2_082_844_800
    builder.font["head"].modified = 2_082_844_800
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap(_cff_character_map(top, glyph_order))
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=ascent, descent=descent)
    builder.setupNameTable({
        "familyName": base_font_name,
        "styleName": weight,
        "uniqueFontIdentifier": f"PDF embedded {safe_name}",
        "fullName": base_font_name,
        "psName": safe_name,
        "version": "Version 1.000",
    })
    builder.setupOS2(
        sTypoAscender=ascent,
        sTypoDescender=descent,
        usWinAscent=max(ascent, 0),
        usWinDescent=max(-descent, 0),
    )
    builder.setupPost()
    private_dict = {
        key: value
        for key, value in getattr(top.Private, "rawDict", {}).items()
        if key != "Subrs"
    }
    builder.setupCFF(
        safe_name,
        {
            "FullName": base_font_name,
            "FamilyName": base_font_name,
            "Weight": weight,
            "FontBBox": font_bbox,
            "FontMatrix": list(getattr(top, "FontMatrix", (0.001, 0, 0, 0.001, 0, 0))),
            "Notice": str(getattr(top, "Notice", "") or ""),
        },
        char_strings,
        private_dict,
    )
    builder.setupDummyDSIG()
    output = BytesIO()
    builder.font.save(output, reorderTables=False)
    return output.getvalue()


def _cff_to_otf(source_bytes: bytes, base_font_name: str) -> bytes:
    """Wrap source-data parser failures without masking resource failures."""

    from fontTools.ttLib import TTLibError

    try:
        return _cff_to_otf_unchecked(source_bytes, base_font_name)
    except ExactFontSourceImpossible:
        raise
    except (
        EOFError,
        KeyError,
        OSError,
        TTLibError,
        TypeError,
        ValueError,
        struct.error,
    ) as exc:
        raise ExactFontSourceImpossible(
            f"raw CFF parse failed: {type(exc).__name__}: {exc}"
        ) from exc


def _install_pdf_unicode_cmap_unchecked(
    usable_bytes: bytes,
    unicode_to_glyph_id: Mapping[int, int],
) -> tuple[bytes, bool]:
    if not unicode_to_glyph_id:
        return usable_bytes, False
    from fontTools.ttLib import TTFont, newTable
    from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

    font = TTFont(BytesIO(usable_bytes), lazy=False, recalcTimestamp=False)
    try:
        glyph_order = font.getGlyphOrder()
        existing = dict(font.getBestCmap() or {}) if "cmap" in font else {}
        for codepoint, glyph_id in unicode_to_glyph_id.items():
            if not 0 <= int(glyph_id) < len(glyph_order):
                raise ExactFontSourceImpossible(
                    f"PDF glyph id {glyph_id} outside glyph order"
                )
            existing[int(codepoint)] = glyph_order[int(glyph_id)]

        table = newTable("cmap")
        table.tableVersion = 0
        table.tables = []
        bmp = {cp: name for cp, name in existing.items() if 0 <= cp <= 0xFFFF}
        if bmp:
            subtable = CmapSubtable.newSubtable(4)
            subtable.platformID = 3
            subtable.platEncID = 1
            subtable.language = 0
            subtable.cmap = bmp
            table.tables.append(subtable)
        full = {cp: name for cp, name in existing.items() if 0 <= cp <= 0x10FFFF}
        if full:
            subtable = CmapSubtable.newSubtable(12)
            subtable.platformID = 3
            subtable.platEncID = 10
            subtable.language = 0
            subtable.cmap = full
            table.tables.append(subtable)
        if not table.tables:
            raise ExactFontSourceImpossible(
                "exact PDF Unicode-to-glyph map is empty"
            )
        font["cmap"] = table
        output = BytesIO()
        font.save(output, reorderTables=False)
        return output.getvalue(), True
    finally:
        font.close()


def _install_pdf_unicode_cmap(
    usable_bytes: bytes,
    unicode_to_glyph_id: Mapping[int, int],
) -> tuple[bytes, bool]:
    """Install PDF glyph identity while classifying source parse failures."""

    from fontTools.ttLib import TTLibError

    try:
        return _install_pdf_unicode_cmap_unchecked(
            usable_bytes, unicode_to_glyph_id
        )
    except ExactFontSourceImpossible:
        raise
    except (
        EOFError,
        KeyError,
        OSError,
        TTLibError,
        TypeError,
        ValueError,
        struct.error,
    ) as exc:
        raise ExactFontSourceImpossible(
            "embedded font cmap repair failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


def _usable_font(
    source_bytes: bytes,
    source_format: str,
    base_font_name: str,
    unicode_map: Mapping[int, int],
) -> tuple[str, bytes, bool]:
    _validate_font_work_bounds(source_bytes)
    source_format = source_format.lower().lstrip(".")
    source_has_cmap = (
        source_format in {"ttf", "otf"}
        and _sfnt_has_table(source_bytes, b"cmap")
    )
    if not unicode_map and not source_has_cmap:
        raise ExactFontSourceImpossible(
            "exact PDF Unicode map unavailable for font without existing cmap"
        )
    try:
        if source_format == "cff":
            usable_format = "otf"
            usable_bytes = _cff_to_otf(source_bytes, base_font_name)
        elif source_format in {"ttf", "otf"}:
            usable_format = source_format
            usable_bytes = source_bytes
        else:
            raise ExactFontSourceImpossible(
                f"unsupported embedded font format: {source_format or '<empty>'}"
            )
        usable_bytes, cmap_installed = _install_pdf_unicode_cmap(usable_bytes, unicode_map)
        if not _fonttools_loadable(usable_bytes):
            raise ExactFontSourceImpossible(
                f"embedded {usable_format} font program is not loadable"
            )
        return usable_format, usable_bytes, cmap_installed
    except ImportError:
        raise ExactFontRuntimeUnavailable(
            "free FontTools runtime required to validate or repair this exact embedded font"
        ) from None


def _sfnt_has_table(data: bytes, tag: bytes) -> bool:
    if len(data) < 12:
        return False
    try:
        count = int.from_bytes(data[4:6], "big")
        for offset in range(12, 12 + count * 16, 16):
            if data[offset : offset + 4] == tag:
                return True
    except (IndexError, TypeError, ValueError):
        return False
    return False


def _font_program_name_aliases(data: bytes, source_format: str) -> set[str]:
    """Return exact family/full/PostScript names declared by an SFNT program."""

    if str(source_format).lower().lstrip(".") not in {"ttf", "otf"}:
        return set()
    from fontTools.ttLib import TTFont, TTLibError

    font = None
    try:
        font = TTFont(BytesIO(data), lazy=False, recalcTimestamp=False)
        _validate_font_work_bounds(
            data,
            glyph_count=len(font.getGlyphOrder()),
            table_count=len(tuple(font.reader.keys())),
        )
        if "name" not in font:
            return set()
        aliases = set()
        for record in font["name"].names:
            if int(record.nameID) not in {1, 4, 6, 16, 17}:
                continue
            try:
                name = _without_subset_prefix(record.toUnicode()).strip()
            except (UnicodeDecodeError, UnicodeError, ValueError):
                continue
            if name:
                aliases.add(name)
        return aliases
    except (AttributeError, KeyError, OSError, TTLibError, TypeError, ValueError):
        return set()
    finally:
        if font is not None:
            font.close()


def _merged_trace_glyph_map(
    aliases: set[str],
    glyph_maps: Mapping[str, Mapping[int, int]],
    ambiguous_maps: set[str],
) -> tuple[dict[int, int], tuple[str, ...]]:
    trace_names = tuple(sorted(name for name in aliases if name in glyph_maps))
    if any(name in ambiguous_maps for name in trace_names):
        raise ExactFontSourceImpossible(
            "PDF Unicode maps one character to multiple glyph ids"
        )
    merged: dict[int, int] = {}
    for name in trace_names:
        for codepoint, glyph_id in glyph_maps[name].items():
            previous = merged.get(int(codepoint))
            if previous is not None and previous != int(glyph_id):
                raise ExactFontSourceImpossible(
                    "font-name aliases disagree on PDF Unicode glyph identity"
                )
            merged[int(codepoint)] = int(glyph_id)
    return merged, trace_names


def _base14_renderer_program(base_font_name: str) -> bytes:
    code = _BASE14_FONT_CODES.get(base_font_name)
    if not code:
        return b""
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        import fitz as pymupdf  # type: ignore
    return bytes(pymupdf.Font(fontname=code).buffer)


def _page_unicode_glyph_maps(
    page,
) -> tuple[dict[str, dict[int, int]], set[str], Optional[tuple[str, str]]]:
    mappings: dict[str, dict[int, int]] = {}
    ambiguous: set[str] = set()
    try:
        traces = page.get_texttrace()
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        return mappings, ambiguous, (type(exc).__name__, str(exc))
    for trace in traces or ():
        font_name = _without_subset_prefix(trace.get("font"))
        if not font_name:
            continue
        mapping = mappings.setdefault(font_name, {})
        for record in trace.get("chars") or ():
            try:
                codepoint, glyph_id = int(record[0]), int(record[1])
            except (IndexError, TypeError, ValueError):
                ambiguous.add(font_name)
                continue
            previous = mapping.get(codepoint)
            if previous is not None and previous != glyph_id:
                ambiguous.add(font_name)
            else:
                mapping[codepoint] = glyph_id
    return mappings, ambiguous, None


class EmbeddedFontCatalog:
    def __init__(self, page_number: int, assets, failures) -> None:
        self.page_number = int(page_number)
        self._assets = MappingProxyType(dict(assets))
        self._failures = MappingProxyType(dict(failures))

    @property
    def assets(self) -> tuple[EmbeddedFontAsset, ...]:
        return tuple(self._assets.values())

    @property
    def failures(self) -> tuple[EmbeddedFontFailure, ...]:
        return tuple(self._failures.values())

    def for_span(self, span_font_name: str) -> Optional[EmbeddedFontAsset]:
        return self._assets.get(str(span_font_name or ""))

    def failure_for_span(self, span_font_name: str) -> EmbeddedFontFailure:
        name = str(span_font_name or "")
        specific = self._failures.get(name)
        if specific is not None:
            return specific
        page_failure = self._failures.get("")
        if page_failure is not None:
            return replace(page_failure, span_font_name=name)
        return EmbeddedFontFailure(
            self.page_number,
            name,
            "no_exact_embedded_font_match",
            proof_category="source_font_absent_for_item",
        )

    @classmethod
    def from_page(cls, page, page_number: int) -> "EmbeddedFontCatalog":
        assets: dict[str, EmbeddedFontAsset] = {}
        failures: dict[str, EmbeddedFontFailure] = {}
        ambiguous_names: set[str] = set()
        glyph_maps, ambiguous_maps, trace_failure = _page_unicode_glyph_maps(page)
        try:
            records = tuple(page.get_fonts(full=True))
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            failures[""] = EmbeddedFontFailure(
                int(page_number), "", "page_font_inventory_failed", None,
                type(exc).__name__, str(exc),
                "runtime_inventory_unavailable_for_item",
            )
            return cls(page_number, assets, failures)
        if not records and trace_failure is not None:
            error_type, detail = trace_failure
            failures[""] = EmbeddedFontFailure(
                int(page_number), "", "page_text_trace_inventory_failed", None,
                error_type, detail,
                "runtime_inventory_unavailable_for_item",
            )
            return cls(page_number, assets, failures)

        document = getattr(page, "parent", None)
        for record in records:
            try:
                xref = int(record[0])
                source_format = str(record[1] or "").lower().lstrip(".")
                source_type = str(record[2] or "")
                base_name = _without_subset_prefix(record[3])
                resource_name = str(record[4] or "")
                source_encoding = str(record[5] or "")
            except (IndexError, TypeError, ValueError) as exc:
                failures[""] = EmbeddedFontFailure(
                    int(page_number), "", "invalid_page_font_record", None,
                    type(exc).__name__, str(exc),
                    "source_inventory_invalid_for_page",
                )
                return cls(page_number, {}, failures)
            if base_name in ambiguous_names:
                continue
            if document is None or not hasattr(document, "extract_font"):
                failures[base_name] = EmbeddedFontFailure(
                    int(page_number), base_name, "source_document_unavailable", xref,
                    "SourceDocumentUnavailable",
                    "PDF page parent does not expose extract_font",
                    proof_category="runtime_source_document_unavailable_for_item",
                )
                continue

            if trace_failure is not None:
                error_type, detail = trace_failure
                failures[base_name] = EmbeddedFontFailure(
                    int(page_number), base_name,
                    "page_text_trace_inventory_failed", xref,
                    error_type, detail,
                    "runtime_inventory_unavailable_for_item",
                )
                continue

            try:
                extracted_name, extracted_format, extracted_type, data = (
                    document.extract_font(xref)
                )
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                failures[base_name] = EmbeddedFontFailure(
                    int(page_number), base_name,
                    "embedded_font_asset_build_failed", xref,
                    type(exc).__name__, str(exc),
                    "runtime_source_font_extraction_unavailable_for_item",
                )
                continue

            try:
                source_bytes = bytes(data)
                source_origin = "embedded_pdf_font"
                if not source_bytes:
                    source_bytes = _base14_renderer_program(base_name)
                    if not source_bytes:
                        raise ExactFontSourceImpossible(
                            "embedded font stream is empty"
                        )
                    source_origin = "pdf_base14_renderer_font"
                    extracted_format = "cff"
                    extracted_type = "Base14 renderer Type1"
                extracted_base = _without_subset_prefix(extracted_name)
                name_aliases = {base_name}
                name_aliases.update(
                    _font_program_name_aliases(source_bytes, extracted_format or source_format)
                )
                if extracted_base and extracted_base not in name_aliases:
                    raise ExactFontSourceImpossible(
                        f"font inventory/extraction identity mismatch: {base_name!r} != {extracted_base!r}"
                    )
                if extracted_base:
                    name_aliases.add(extracted_base)
                source_format = str(extracted_format or source_format).lower().lstrip(".")
                source_type = str(extracted_type or source_type)
                unicode_map, trace_names = _merged_trace_glyph_map(
                    name_aliases, glyph_maps, ambiguous_maps
                )
                usable_format, usable_bytes, cmap_installed = _usable_font(
                    source_bytes,
                    source_format,
                    base_name,
                    unicode_map,
                )
                source_sha = _digest(source_bytes)
                usable_sha = _digest(usable_bytes)
                units_per_em, ascender, descender, glyph_advances = (
                    _font_delivery_metrics(usable_bytes)
                )
                asset = EmbeddedFontAsset(
                    page_number=int(page_number),
                    span_font_name=base_name,
                    base_font_name=base_name,
                    source_xref=xref,
                    resource_name=resource_name,
                    source_font_type=source_type,
                    source_encoding=source_encoding,
                    source_format=source_format,
                    source_origin=source_origin,
                    source_bytes=source_bytes,
                    source_sha256=source_sha,
                    usable_format=usable_format,
                    usable_bytes=usable_bytes,
                    usable_sha256=usable_sha,
                    asset_id=f"sha256:{usable_sha}",
                    unicode_map_installed=cmap_installed,
                    units_per_em=units_per_em,
                    ascender=ascender,
                    descender=descender,
                    glyph_advances=glyph_advances,
                )
            except ExactFontSourceImpossible as exc:
                failures[base_name] = EmbeddedFontFailure(
                    int(page_number), base_name, "embedded_font_asset_build_failed",
                    xref, type(exc).__name__, str(exc),
                    "source_specific_impossibility",
                )
                continue
            except ExactFontRuntimeUnavailable as exc:
                failures[base_name] = EmbeddedFontFailure(
                    int(page_number), base_name, "embedded_font_asset_build_failed",
                    xref, type(exc).__name__, str(exc),
                    "runtime_capability_unavailable_for_item",
                )
                continue
            except (AttributeError, ImportError, OSError, RuntimeError) as exc:
                failures[base_name] = EmbeddedFontFailure(
                    int(page_number), base_name, "embedded_font_asset_build_failed",
                    xref, type(exc).__name__, str(exc),
                    "runtime_capability_unavailable_for_item",
                )
                continue
            delivery_names = trace_names or (base_name,)
            for delivery_name in delivery_names:
                previous = assets.get(delivery_name)
                if previous is not None and previous.asset_id != asset.asset_id:
                    assets.pop(delivery_name, None)
                    ambiguous_names.add(delivery_name)
                    failures[delivery_name] = EmbeddedFontFailure(
                        int(page_number), delivery_name,
                        "ambiguous_exact_embedded_font_match", xref,
                        proof_category="source_font_ambiguous_for_item",
                    )
                    continue
                assets[delivery_name] = replace(
                    asset, span_font_name=delivery_name
                )
                failures.pop(delivery_name, None)
            if base_name not in ambiguous_names:
                failures.pop(base_name, None)
        return cls(page_number, assets, failures)


__all__ = ["EmbeddedFontAsset", "EmbeddedFontCatalog", "EmbeddedFontFailure"]
