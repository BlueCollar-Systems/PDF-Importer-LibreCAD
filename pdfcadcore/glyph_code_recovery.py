"""Recover the characters of text a PDF delivers as raw glyph codes.

Some producers embed a Type0 font with ``/Encoding /Identity-H``,
``/CIDToGIDMap /Identity`` and no ``/ToUnicode``, over a subset font program
that carries neither a ``cmap`` nor a ``post`` table. The codes in the content
stream are then glyph indices into that subset and nothing in the PDF says what
they mean. MuPDF reports each such character as U+FFFD with its glyph id in
``page.get_texttrace()``, while the text dictionary substitutes the glyph id
itself as the character. A dimension therefore arrives as ``06-3`` where the
drawing says ``MS-3``: already wrong, already legible, and invisible to any
check that looks for control characters.

What this module does, per character:

1. The PDF's own ``/ToUnicode`` is normative and MuPDF has already applied it.
   A font that declares one is out of scope here; a character MuPDF resolved
   inside an in-scope font is left exactly as it is and counted as delivered,
   never as a route this module proved.
2. ``embedded_cmap``   - the embedded font program's own ``cmap``, reverse
   mapped glyph id -> codepoint.
3. ``post_glyph_name`` - the real ``post`` table's glyph names through AGL or
   ``uniXXXX``. Names fontTools SYNTHESISES from the glyph index
   (``glyph00019``) are fabricated and are never accepted.
4. ``outline_identity`` - the subset glyph's contour command list, hashed and
   looked up in a reference face's outline -> Unicode table built from that
   reference's own cmap. This is exact structural equality, not similarity and
   not recognition: it matches point for point or it does not match. The
   reference face is chosen by the PDF font's declared family, width and
   weight, the PDF's own ``/W`` advance for the glyph must agree with the
   reference glyph's advance, and the match must be unambiguous.
5. ``blank_glyph_advance`` - a glyph the subset draws with no contours at all,
   whose ``/W`` advance is a reference face's space advance. Every empty
   outline hashes alike in every face, so this is a convention rather than the
   structural equality route 4 rests on, and it is named separately for that
   reason.

There is no sixth route. No offsets, no "standard Macintosh glyph order"
assumption, no encoding guesses.

A name a font gives a glyph (routes 2 and 3) is a declaration, not a drawing.
A subsetter that reorders ``glyf`` without rewriting ``post`` leaves names that
contradict the outlines, and such a name reads as a plausible character. So a
route 2 or 3 answer is accepted only when the PDF's own ``/W`` advance for the
glyph agrees with that character's advance in a face-matched reference, and it
is refused outright when the glyph's outline proves a different character. The
drawing is what the fabricator reads.

Two rules govern everything else:

* **Substitution is all-or-nothing per span.** If one character of a span is
  unproven the ENTIRE span is left byte for byte as MuPDF delivered it. A
  half-recovered dimension like ``34' - 1?"`` reads as a measurement and is
  worse than raw garbage.
* **Nothing is ever presented as if the PDF had declared it.** Every span this
  module changes is recorded with the route that proved it, and every span it
  could not prove is recorded with the font, the location and the raw codes, so
  a host can tell the operator. A span this run could not examine at all is
  recorded as a limitation of the run, never as a failure of the document.

A glyph id is only ever read from ``page.get_texttrace()``, bound to a
delivered character by that character's own origin. It is never inferred from
the character a host was handed: a text dictionary without per-character
origins carries characters MuPDF's layout inserted, which no glyph drew, and
reading those as glyph indices fabricates letters. A host holding such a
dictionary recovers the RAWDICT instead and copies the result across with
:func:`copy_recovered_text`.

When no reference face for the declared family is installed, routes 2 to 5
recover nothing and say so (reason ``no_reference_face_available``, naming the
family it looked for). It never falls back to a guess.
``BCS_GLYPH_REFERENCE_FONTS`` overrides the search: a path-separated list of
directories or files, or the single word ``none`` to switch reference matching
off entirely.

Nothing in this module raises. A failure anywhere means "nothing is proven for
that font", which is recorded and reported like any other unproven span.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sys

GLYPH_CODE_SCHEMA = "bcs.text_glyph_codes/1.0"

# The character MuPDF reports for a code its font/encoding chain maps to
# nothing. This is the detector, and the only one: the raw codes of an affected
# span are frequently printable ASCII, so scanning for control characters finds
# the obvious garbage and misses the plausible, legible, wrong text.
UNKNOWN_CHARACTER = 0xFFFD

ROUTE_EMBEDDED_CMAP = "embedded_cmap"
ROUTE_POST_NAME = "post_glyph_name"
ROUTE_OUTLINE_IDENTITY = "outline_identity"
ROUTE_BLANK_ADVANCE = "blank_glyph_advance"

# Most speculative last: a span is reported on the weakest route it needed.
ROUTE_ORDER = (
    ROUTE_EMBEDDED_CMAP,
    ROUTE_POST_NAME,
    ROUTE_OUTLINE_IDENTITY,
    ROUTE_BLANK_ADVANCE,
)

# Characters this module did NOT prove and did NOT change. They are counted
# apart from the routes so that no report ever implies the PDF declared them.
DELIVERED_MUPDF_RESOLVED = "mupdf_resolved"
DELIVERED_LAYOUT_SPACE = "layout_space"

# An unproven span is either something this document does not say (a property
# of the PDF) or something this run could not look at (a property of the tool).
# The two must never be reported in the same sentence.
LIMITATION_REASONS = frozenset((
    "characters_not_bound_to_glyph_ids",
    "span_has_no_character_origins",
    "font_name_ambiguous_on_page",
    "font_not_found_on_page",
    "recovered_text_not_transferable",
    "glyph_code_recovery_failed",
    "record_limit_reached",
))

REPORT_ITEM_LIMIT = 200
_RAW_CODES_PER_ITEM = 48
_MAX_REFERENCE_FACES = 4
_FACE_TABLE_CACHE_LIMIT = 8

_DOCUMENT_RECORDS = "_bcs_glyph_code_records"
_DOCUMENT_PROOFS = "_bcs_glyph_code_font_proofs"
_PAGE_TRACE = "_bcs_glyph_code_page_trace"
_PAGE_CANDIDATE_FONTS = "_bcs_glyph_code_page_candidates"
# A pathological sheet must not turn the report into the document. Counting
# stops honestly rather than quietly.
_MAX_RECORDS = 20000
_OVERFLOW_KEY = (-1, ("record-limit",))

# Only a composite (Type0) or a Type3 font can hand MuPDF a code it maps to no
# character at all: a simple font carries a real text encoding. Reading the
# page's font dictionaries is far cheaper than a second text extraction, so a
# page that declares neither is never traced.
_UNMAPPABLE_FONT_TYPES = ("type0", "type3")

_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
_INDIRECT_REFERENCE = re.compile(r"(\d+)\s+(\d+)\s+R")
_UNI_NAME = re.compile(r"^uni([0-9A-Fa-f]{4,6})$")
_U_NAME = re.compile(r"^u([0-9A-Fa-f]{4,6})$")
_SYNTHETIC_NAME = re.compile(r"^glyph\d+$")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")

# Codepoints a recovered character may be. The reference table is built over
# this set only: it is what an engineering drawing carries, and it makes the
# "one unambiguous candidate" test a test over characters a fabricator reads
# rather than over every codepoint a system font happens to cover.
_ASCII_RANGE = tuple(range(0x20, 0x7F))
_LATIN1_RANGE = tuple(range(0xA0, 0x100))
_DRAWING_EXTRAS = (
    0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022,
    0x2032, 0x2033, 0x2044, 0x2070, 0x2122, 0x2126, 0x2205,
    0x2206, 0x220F, 0x2211, 0x2212, 0x221A, 0x221E, 0x2220,
    0x2229, 0x222B, 0x2248, 0x2260, 0x2264, 0x2265, 0x25A0,
    0x25B2, 0x25CA, 0x2713,
)
_CANDIDATE_CODEPOINTS = _ASCII_RANGE + _LATIN1_RANGE + _DRAWING_EXTRAS

# Private use areas. A reference cmap that "proves" one of these proves a
# picture, not a character (the Wingdings case), so they are never candidates.
_PRIVATE_USE = (
    (0xE000, 0xF8FF),
    (0xF0000, 0xFFFFD),
    (0x100000, 0x10FFFD),
)

# Style words carried inside a PostScript font name. They are identity, not
# decoration: ArialNarrow must never be matched against Arial.
_WEIGHT_WORDS = (
    ("extrabold", True), ("semibold", True), ("demibold", True),
    ("ultrabold", True), ("bold", True), ("black", False), ("heavy", False),
    ("light", False), ("thin", False), ("book", False), ("medium", False),
    ("regular", False), ("roman", False), ("normal", False),
)
_WIDTH_WORDS = ("extracondensed", "semicondensed", "narrow", "condensed", "extended", "expanded")
_ITALIC_WORDS = ("oblique", "italic")
_FOUNDRY_SUFFIXES = ("mt", "ps", "std", "pro", "itc", "adobe")

_REFERENCE_INDEX_CACHE = {}
_FACE_TABLE_CACHE = {}


class _quiet_fonttools:
    """Keep fontTools' own log records off the operator's console.

    This module opens every face on the host to read its name table, and a
    malformed one makes fontTools log a record - at ERROR level, for something
    it recovers from - rather than raise. Unattributed, beside this module's
    own operator line, that reads as a problem with the drawing. A face that
    cannot be read contributes nothing and says nothing, which is the contract.
    """

    __slots__ = ("_level",)

    def __enter__(self):
        logger = logging.getLogger("fontTools")
        self._level = logger.level
        logger.setLevel(logging.CRITICAL)
        return self

    def __exit__(self, *_exc):
        logging.getLogger("fontTools").setLevel(self._level)
        return False


def _without_subset_prefix(name) -> str:
    """``PFCJAI+Arial`` -> ``Arial``; anything else unchanged."""
    return _SUBSET_PREFIX.sub("", str(name or "")).strip()


def _is_private_use(codepoint: int) -> bool:
    for low, high in _PRIVATE_USE:
        if low <= codepoint <= high:
            return True
    return False


# ── the PDF's own declarations ──


def _xref_key(document, xref, key):
    try:
        kind, value = document.xref_get_key(int(xref), str(key))
    except Exception:
        return None, None
    if kind in (None, "null"):
        return None, None
    return str(kind), str(value)


def _first_indirect(value):
    if not value:
        return None
    match = _INDIRECT_REFERENCE.search(value)
    return int(match.group(1)) if match else None


def _resolved_key(document, xref, key):
    """A font dictionary key, following one level of indirection."""
    kind, value = _xref_key(document, xref, key)
    if kind == "xref":
        target = _first_indirect(value)
        if target is None:
            return None, None
        try:
            return "object", str(document.xref_object(target, compressed=True))
        except Exception:
            return None, None
    return kind, value


def _identity_encoding(document, font_xref, descendant_xref) -> bool:
    """True only for an Identity CMap, by name or by descendant /Ordering."""
    kind, value = _xref_key(document, font_xref, "Encoding")
    if kind == "name" and value.lstrip("/").startswith("Identity"):
        return True
    if descendant_xref is None:
        return False
    kind, value = _resolved_key(document, descendant_xref, "CIDSystemInfo")
    return bool(value) and "Ordering" in value and "Identity" in value


def _parse_width_array(text):
    """``[3[278] 20 28 556]`` -> ``{3: 278.0, 20..28: 556.0}``."""
    widths = {}
    if not text:
        return widths
    tokens = []
    for piece in re.findall(r"\[|\]|-?\d+(?:\.\d+)?", text):
        tokens.append(piece)
    # The outer brackets belong to the array itself.
    if tokens and tokens[0] == "[":
        tokens = tokens[1:]
    if tokens and tokens[-1] == "]":
        tokens = tokens[:-1]
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in ("[", "]"):
            index += 1
            continue
        first = int(float(token))
        index += 1
        if index < len(tokens) and tokens[index] == "[":
            index += 1
            code = first
            while index < len(tokens) and tokens[index] != "]":
                widths[code] = float(tokens[index])
                code += 1
                index += 1
            index += 1
            continue
        if index + 1 < len(tokens):
            last = int(float(tokens[index]))
            width = float(tokens[index + 1])
            index += 2
            if last >= first and last - first <= 65535:
                for code in range(first, last + 1):
                    widths[code] = width
    return widths


def _declared_widths(document, descendant_xref):
    if descendant_xref is None:
        return {}, 1000.0
    default = 1000.0
    kind, value = _xref_key(document, descendant_xref, "DW")
    if value:
        match = _NUMBER.search(value)
        if match:
            default = float(match.group(0))
    kind, value = _xref_key(document, descendant_xref, "W")
    if kind == "xref":
        target = _first_indirect(value)
        try:
            value = str(document.xref_object(target, compressed=True)) if target else ""
        except Exception:
            value = ""
    return _parse_width_array(value), default


def _descriptor_style(document, descendant_xref):
    """Italic and weight as the PDF's own FontDescriptor declares them."""
    italic = None
    bold = None
    if descendant_xref is None:
        return italic, bold
    kind, value = _xref_key(document, descendant_xref, "FontDescriptor")
    descriptor = _first_indirect(value) if kind == "xref" else None
    if descriptor is None:
        return italic, bold
    _, flags_text = _xref_key(document, descriptor, "Flags")
    if flags_text:
        match = _NUMBER.search(flags_text)
        if match:
            flags = int(float(match.group(0)))
            italic = bool(flags & 64)
            bold = bool(flags & (1 << 18))
    _, angle_text = _xref_key(document, descriptor, "ItalicAngle")
    if angle_text:
        match = _NUMBER.search(angle_text)
        if match and abs(float(match.group(0))) > 0.0:
            italic = True
    _, weight_text = _xref_key(document, descriptor, "FontWeight")
    if weight_text:
        match = _NUMBER.search(weight_text)
        if match:
            bold = float(match.group(0)) >= 600.0
    return italic, bold


# ── face identity ──


class _FaceStyle:
    """A font's identity reduced to what a reference face must also be."""

    __slots__ = ("base", "bold", "italic", "width", "weight_word")

    def __init__(self, base, bold, italic, width, weight_word):
        self.base = base
        self.bold = bool(bold)
        self.italic = bool(italic)
        self.width = width
        self.weight_word = weight_word

    def matches(self, other) -> bool:
        return (
            bool(self.base)
            and self.base == other.base
            and self.bold == other.bold
            and self.italic == other.italic
            and self.width == other.width
            and self.weight_word == other.weight_word
        )

    def describe(self) -> str:
        parts = [self.base or "?"]
        if self.width != "normal":
            parts.append(self.width)
        if self.weight_word:
            parts.append(self.weight_word)
        if self.bold:
            parts.append("bold")
        if self.italic:
            parts.append("italic")
        return " ".join(parts)


def _normalize_face_name(text) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _face_style(name_text, extra_style_text="", italic_hint=None, bold_hint=None) -> _FaceStyle:
    """Reduce a declared font name (plus any subfamily) to a comparable identity."""
    token = _normalize_face_name(name_text) + _normalize_face_name(extra_style_text)
    italic = False
    for word in _ITALIC_WORDS:
        if word in token:
            italic = True
            token = token.replace(word, "")
    width = "normal"
    for word in _WIDTH_WORDS:
        if word in token:
            width = "condensed" if word.endswith("condensed") else word
            token = token.replace(word, "")
    bold = False
    weight_word = ""
    for word, is_bold in _WEIGHT_WORDS:
        if word in token:
            token = token.replace(word, "")
            if is_bold:
                bold = True
            elif word in ("black", "heavy", "light", "thin"):
                weight_word = weight_word or word
    for suffix in _FOUNDRY_SUFFIXES:
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            token = token[: -len(suffix)]
    if italic_hint is not None:
        italic = italic or bool(italic_hint)
    if bold_hint is not None:
        bold = bold or bool(bold_hint)
    return _FaceStyle(token, bold, italic, width, weight_word)


def reference_font_directories():
    """Where a reference face may be found, most specific first."""
    override = os.environ.get("BCS_GLYPH_REFERENCE_FONTS", "")
    if override.strip().lower() == "none":
        return ()
    if override.strip():
        return tuple(part for part in override.split(os.pathsep) if part.strip())
    home = os.path.expanduser("~")
    if sys.platform.startswith("win"):
        candidates = [
            os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
        ]
    elif sys.platform == "darwin":
        candidates = ["/System/Library/Fonts", "/Library/Fonts",
                      os.path.join(home, "Library", "Fonts")]
    else:
        candidates = ["/usr/share/fonts", "/usr/local/share/fonts",
                      os.path.join(home, ".local", "share", "fonts"),
                      os.path.join(home, ".fonts")]
    return tuple(path for path in candidates if path and os.path.isdir(path))


def _iter_reference_files(directories):
    seen = set()
    for directory in directories:
        if os.path.isfile(directory):
            yield directory
            continue
        for root, _dirs, files in os.walk(directory):
            for name in sorted(files):
                if os.path.splitext(name)[1].lower() not in (".ttf", ".otf"):
                    continue
                path = os.path.join(root, name)
                key = os.path.normcase(path)
                if key in seen:
                    continue
                seen.add(key)
                yield path


def _reference_index(directories):
    """(path, style) for every reference face on the host, built once."""
    key = tuple(os.path.normcase(part) for part in directories)
    cached = _REFERENCE_INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    entries = []
    try:
        from fontTools.ttLib import TTFont
    except Exception:
        _REFERENCE_INDEX_CACHE[key] = ()
        return ()
    with _quiet_fonttools():
        for path in _iter_reference_files(directories):
            font = None
            try:
                font = TTFont(path, lazy=True, fontNumber=0)
                names = font["name"]
                family = names.getDebugName(16) or names.getDebugName(1) or ""
                subfamily = names.getDebugName(17) or names.getDebugName(2) or ""
                entries.append((path, _face_style(family, subfamily)))
            except Exception:
                continue
            finally:
                if font is not None:
                    try:
                        font.close()
                    except Exception:
                        pass
    entries = tuple(entries)
    _REFERENCE_INDEX_CACHE[key] = entries
    return entries


def clear_reference_font_cache() -> None:
    """Forget the indexed host faces and their outline tables.

    The index is built once per process because a host's installed fonts do
    not change during an import. A caller that installs or points at different
    reference faces says so here.
    """
    _REFERENCE_INDEX_CACHE.clear()
    _FACE_TABLE_CACHE.clear()


def _reference_faces_for(style):
    directories = reference_font_directories()
    if not directories:
        return (), 0
    index = _reference_index(directories)
    matches = [path for path, face_style in index if style.matches(face_style)]
    return tuple(sorted(matches)[:_MAX_REFERENCE_FACES]), len(index)


# ── outline identity ──


class _GlyfGlyph:
    """One ``glyf`` entry, drawable the way a decomposing pen expects."""

    __slots__ = ("_table", "_name")

    def __init__(self, table, name):
        self._table = table
        self._name = name

    def draw(self, pen):
        self._table[self._name].draw(pen, self._table)


class _GlyfGlyphSet:
    """``glyf`` presented as a glyph set, so a component can be followed."""

    __slots__ = ("_table",)

    def __init__(self, table):
        self._table = table

    def __getitem__(self, name):
        return _GlyfGlyph(self._table, name)


def _outline_drawer(font):
    """Record one glyph's contours, identically on subset and reference.

    A subset stripped to its outlines routinely carries an ``hmtx`` table cut
    to the glyphs it kept while ``maxp`` still counts the original 3,000; the
    high-level glyph set refuses such a font outright. ``glyf`` alone draws it,
    and the reference face is drawn exactly the same way so the two command
    streams are comparable at all.

    An accented glyph is a COMPOSITE: ``glyf`` records it as references to
    other glyphs, not as contours. The pen follows those references on both
    sides so the two compare as the contours they draw. A component the subset
    no longer carries raises rather than being skipped - half an outline must
    never be hashed as if it were the whole glyph.
    """
    from fontTools.pens.recordingPen import DecomposingRecordingPen

    try:
        glyf = font["glyf"]
    except Exception:
        glyf = None
    glyph_set = _GlyfGlyphSet(glyf) if glyf is not None else font.getGlyphSet()

    def record(glyph_name):
        pen = DecomposingRecordingPen(glyph_set)
        pen.skipMissingComponents = False
        glyph_set[glyph_name].draw(pen)
        return pen.value

    return record


def _outline_signature(drawer, glyph_name, scale):
    parts = []
    for operator, arguments in drawer(glyph_name):
        parts.append(operator)
        for point in arguments:
            if point is None:
                parts.append("*")
            else:
                parts.append("%.3f,%.3f" % (point[0] * scale, point[1] * scale))
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


# The signature of a glyph that draws nothing. Every blank glyph in every face
# hashes to it, so a match on it is a convention about advance width and not
# the structural equality the outline route rests on.
_EMPTY_OUTLINE_SIGNATURE = hashlib.sha256(b"").hexdigest()


def _face_outline_table(path):
    """``{outline signature: {codepoint: advance/1000em}}`` for one reference face."""
    try:
        stat = os.stat(path)
        key = (os.path.normcase(path), int(stat.st_mtime), int(stat.st_size))
    except OSError:
        return {}
    cached = _FACE_TABLE_CACHE.get(key)
    if cached is not None:
        return cached
    table = {}
    font = None
    try:
        from fontTools.ttLib import TTFont

        with _quiet_fonttools():
            font = TTFont(path, lazy=True, fontNumber=0)
            upem = float(font["head"].unitsPerEm or 1000)
            scale = 1000.0 / upem
            cmap = font.getBestCmap() or {}
            drawer = _outline_drawer(font)
            metrics = font["hmtx"]
            for codepoint in _CANDIDATE_CODEPOINTS:
                glyph_name = cmap.get(codepoint)
                if glyph_name is None or _is_private_use(codepoint):
                    continue
                try:
                    signature = _outline_signature(drawer, glyph_name, scale)
                    advance = float(metrics[glyph_name][0]) * scale
                except Exception:
                    continue
                table.setdefault(signature, {})[codepoint] = advance
    except Exception:
        table = {}
    finally:
        if font is not None:
            try:
                font.close()
            except Exception:
                pass
    if len(_FACE_TABLE_CACHE) >= _FACE_TABLE_CACHE_LIMIT:
        _FACE_TABLE_CACHE.clear()
    _FACE_TABLE_CACHE[key] = table
    return table


def _reference_advances(tables):
    """``{codepoint: (advance, ...)}`` over the matched reference faces."""
    advances = {}
    for table in tables:
        for candidates in table.values():
            for codepoint, advance in candidates.items():
                advances.setdefault(codepoint, []).append(advance)
    return advances


def _advance_agrees(advances, codepoint, declared_width, default_width) -> bool:
    """Whether the PDF's own advance for the glyph fits that character."""
    width = declared_width if declared_width is not None else default_width
    if width is None:
        return False
    for advance in advances.get(int(codepoint), ()):
        if abs(advance - width) <= 1.0:
            return True
    return False


def _unambiguous_candidate(candidates, declared_width, default_width):
    """One codepoint, or None. The PDF's own advance has to agree."""
    width = declared_width if declared_width is not None else default_width
    agreeing = [
        codepoint
        for codepoint, advance in sorted(candidates.items())
        if width is None or abs(advance - width) <= 1.0
    ]
    if not agreeing:
        return None
    if len(agreeing) == 1:
        return agreeing[0]
    ascii_only = [codepoint for codepoint in agreeing if 0x20 <= codepoint <= 0x7E]
    if len(ascii_only) == 1:
        return ascii_only[0]
    return None


# ── one PDF font, resolved once per document ──


class _FontProof:
    """What this document proves about one embedded font's glyph codes."""

    __slots__ = ("xref", "base_name", "in_scope", "reason", "detail",
                 "characters", "routes", "cid_is_gid", "reference_faces",
                 "looked_for", "attempted")

    def __init__(self, xref, base_name):
        self.xref = xref
        self.base_name = base_name
        self.in_scope = False
        self.reason = ""
        self.detail = ""
        self.characters = {}
        self.routes = {}
        self.cid_is_gid = False
        self.reference_faces = ()
        self.looked_for = ""
        self.attempted = frozenset()

    def character(self, glyph_id):
        return self.characters.get(int(glyph_id))

    def route(self, glyph_id):
        return self.routes.get(int(glyph_id), "")


def _embedded_cmap_characters(font):
    """Glyph id -> codepoint from the embedded program's own cmap, reversed."""
    reverse = {}
    ambiguous = set()
    try:
        cmap_table = font["cmap"]
    except Exception:
        return reverse
    order = font.getGlyphOrder()
    index_by_name = {name: position for position, name in enumerate(order)}
    for subtable in getattr(cmap_table, "tables", ()) or ():
        if int(getattr(subtable, "platformID", -1)) not in (0, 3):
            continue
        for codepoint, glyph_name in (getattr(subtable, "cmap", {}) or {}).items():
            glyph_id = index_by_name.get(glyph_name)
            if glyph_id is None or _is_private_use(int(codepoint)):
                continue
            previous = reverse.get(glyph_id)
            if previous is not None and previous != int(codepoint):
                ambiguous.add(glyph_id)
            reverse[glyph_id] = int(codepoint)
    for glyph_id in ambiguous:
        reverse.pop(glyph_id, None)
    return reverse


def _post_name_characters(font, data):
    """Glyph id -> codepoint from a REAL post table's names, through AGL.

    fontTools synthesises ``glyph00019`` style names from the glyph index when
    a font has no post table. Those are fabricated from the very index being
    decoded and prove nothing, so they are rejected by name and by the absence
    of the table in the file.
    """
    characters = {}
    if not _sfnt_has_table(data, b"post"):
        return characters
    try:
        post = font["post"]
        if float(getattr(post, "formatType", 0.0)) != 2.0:
            return characters
        order = font.getGlyphOrder()
    except Exception:
        return characters
    try:
        from fontTools.agl import toUnicode
    except Exception:
        toUnicode = None
    for glyph_id, glyph_name in enumerate(order):
        name = str(glyph_name or "")
        if not name or _SYNTHETIC_NAME.match(name):
            continue
        codepoint = None
        match = _UNI_NAME.match(name) or _U_NAME.match(name)
        if match:
            try:
                codepoint = int(match.group(1), 16)
            except ValueError:
                codepoint = None
        elif toUnicode is not None:
            text = toUnicode(name)
            if len(text) == 1:
                codepoint = ord(text)
        if codepoint is None or _is_private_use(codepoint):
            continue
        characters[glyph_id] = codepoint
    return characters


def _sfnt_has_table(data: bytes, tag: bytes) -> bool:
    """Whether the font file itself carries a table, without fontTools."""
    try:
        if len(data) < 12:
            return False
        import struct

        count = struct.unpack(">H", data[4:6])[0]
        for index in range(count):
            offset = 12 + index * 16
            if offset + 4 > len(data):
                return False
            if data[offset:offset + 4] == tag:
                return True
    except Exception:
        return False
    return False


def _resolve_font(document, xref, base_name, needed_glyphs):
    proof = _FontProof(int(xref), base_name)
    proof.attempted = frozenset(int(glyph_id) for glyph_id in needed_glyphs)
    kind, subtype = _xref_key(document, xref, "Subtype")
    if kind != "name" or subtype.lstrip("/") != "Type0":
        proof.reason = "font_is_not_type0"
        return proof
    to_unicode_kind, _ = _xref_key(document, xref, "ToUnicode")
    if to_unicode_kind is not None:
        proof.reason = "font_declares_to_unicode"
        return proof
    _, descendants = _xref_key(document, xref, "DescendantFonts")
    descendant_xref = _first_indirect(descendants)
    if not _identity_encoding(document, xref, descendant_xref):
        proof.reason = "font_encoding_is_not_identity"
        return proof
    # Past this point the font IS the defect: the codes are glyph indices and
    # the PDF declares nothing about what they mean.
    proof.in_scope = True
    _, cid_to_gid = _xref_key(document, descendant_xref, "CIDToGIDMap") if descendant_xref else (None, None)
    proof.cid_is_gid = cid_to_gid is None or str(cid_to_gid).lstrip("/").startswith("Identity")
    widths, default_width = _declared_widths(document, descendant_xref)

    data = b""
    try:
        data = bytes(document.extract_font(int(xref))[3] or b"")
    except Exception as exc:
        proof.reason = "embedded_font_program_unavailable"
        proof.detail = "%s: %s" % (type(exc).__name__, exc)
        return proof
    if not data:
        proof.reason = "embedded_font_program_absent"
        return proof

    font = None
    try:
        from fontTools.ttLib import TTFont
        from io import BytesIO

        with _quiet_fonttools():
            font = TTFont(BytesIO(data), lazy=True, fontNumber=0)
    except Exception as exc:
        proof.reason = "embedded_font_program_unreadable"
        proof.detail = "%s: %s" % (type(exc).__name__, exc)
        return proof

    try:
        wanted = {int(glyph_id) for glyph_id in needed_glyphs}
        # What the font NAMES each glyph. A name is a declaration, not the
        # drawing, so it is only ever a candidate here - it is corroborated or
        # refused against the outline and the PDF's own advance below.
        named = {}
        # Route 2 - the font's own cmap.
        if _sfnt_has_table(data, b"cmap"):
            for glyph_id, codepoint in _embedded_cmap_characters(font).items():
                if glyph_id in wanted:
                    named.setdefault(glyph_id, (codepoint, ROUTE_EMBEDDED_CMAP))
        # Route 3 - real post table names.
        for glyph_id, codepoint in _post_name_characters(font, data).items():
            if glyph_id in wanted:
                named.setdefault(glyph_id, (codepoint, ROUTE_POST_NAME))
        _prove_glyphs(
            proof, font, sorted(wanted), widths, default_width,
            document, descendant_xref, named,
        )
    except Exception as exc:
        proof.reason = proof.reason or "font_proof_failed"
        proof.detail = proof.detail or "%s: %s" % (type(exc).__name__, exc)
    finally:
        try:
            font.close()
        except Exception:
            pass
    return proof


def _prove_glyphs(proof, font, glyph_ids, widths, default_width,
                  document, descendant_xref, named):
    """Decide each glyph's character: the outline it draws, corroborated names.

    The outline is hashed against a face-matched reference (route 4, or route 5
    where the glyph draws nothing at all). A name the font gave the glyph
    (routes 2 and 3) is accepted only where the PDF's own ``/W`` advance agrees
    with that character in the same reference, and is refused outright where
    the outline proves a different character - a ``post`` table left stale by a
    subsetter names a glyph the file no longer draws.
    """
    italic_hint, bold_hint = _descriptor_style(document, descendant_xref)
    style = _face_style(proof.base_name, "", italic_hint, bold_hint)
    proof.looked_for = style.describe()
    faces, indexed = _reference_faces_for(style)
    proof.reference_faces = tuple(os.path.basename(path) for path in faces)
    if not faces:
        proof.reason = proof.reason or "no_reference_face_available"
        proof.detail = proof.detail or (
            "no installed face matches %r (%d faces indexed)" % (style.describe(), indexed)
        )
        return
    try:
        upem = float(font["head"].unitsPerEm or 1000)
    except Exception:
        upem = 1000.0
    scale = 1000.0 / (upem or 1000.0)
    drawer = _outline_drawer(font)
    order = font.getGlyphOrder()
    tables = [_face_outline_table(path) for path in faces]
    advances = _reference_advances(tables)
    for glyph_id in glyph_ids:
        if glyph_id < 0 or glyph_id >= len(order):
            continue
        declared = widths.get(int(glyph_id))
        try:
            signature = _outline_signature(drawer, order[glyph_id], scale)
        except Exception:
            signature = None
        drawn = None
        drawn_route = ""
        if signature is not None:
            answers = set()
            for table in tables:
                candidates = table.get(signature)
                if not candidates:
                    continue
                codepoint = _unambiguous_candidate(candidates, declared, default_width)
                if codepoint is not None:
                    answers.add(codepoint)
            # Two reference faces that disagree prove nothing between them.
            if len(answers) == 1:
                drawn = answers.pop()
                drawn_route = (
                    ROUTE_BLANK_ADVANCE
                    if signature == _EMPTY_OUTLINE_SIGNATURE
                    else ROUTE_OUTLINE_IDENTITY
                )
        candidate = named.get(glyph_id)
        if candidate is not None:
            codepoint, route = candidate
            if drawn is not None and drawn != codepoint:
                # The font's name for this glyph contradicts the outline the
                # file draws. Nothing here proves which is meant.
                continue
            if _advance_agrees(advances, codepoint, declared, default_width):
                proof.characters[glyph_id] = chr(codepoint)
                proof.routes[glyph_id] = route
                continue
            if drawn is None:
                continue
        if drawn is not None:
            proof.characters[glyph_id] = chr(drawn)
            proof.routes[glyph_id] = drawn_route


# ── per page ──


def _document_of(page):
    return getattr(page, "parent", None)


def _proof_cache(document):
    cache = getattr(document, _DOCUMENT_PROOFS, None)
    if not isinstance(cache, dict):
        cache = {}
        try:
            setattr(document, _DOCUMENT_PROOFS, cache)
        except Exception:
            return None
    return cache


def _records_of(document):
    records = getattr(document, _DOCUMENT_RECORDS, None)
    if not isinstance(records, dict):
        records = {}
        try:
            setattr(document, _DOCUMENT_RECORDS, records)
        except Exception:
            return None
    return records


def _page_candidate_fonts(page) -> bool:
    """Whether this page declares a font that can deliver an unmapped code.

    ``page.get_fonts()`` reads the page's font dictionaries; a second text
    extraction reads the whole content stream. A simple font always carries a
    real text encoding, so a page of nothing but TrueType and Type1 fonts can
    never reach MuPDF as U+FFFD and is answered here without tracing anything.
    """
    cached = getattr(page, _PAGE_CANDIDATE_FONTS, None)
    if isinstance(cached, bool):
        return cached
    try:
        records = tuple(page.get_fonts(full=True))
    except Exception:
        # Nothing was read, so nothing may be ruled out.
        return True
    found = any(
        str(record[2] or "").strip().lstrip("/").lower() in _UNMAPPABLE_FONT_TYPES
        for record in records
    )
    try:
        setattr(page, _PAGE_CANDIDATE_FONTS, found)
    except Exception:
        pass
    return found


def _page_font_xrefs(page):
    """Span font name -> the one PDF font xref it names, when unambiguous."""
    names = {}
    try:
        records = tuple(page.get_fonts(full=True))
    except Exception:
        return names
    for record in records:
        try:
            xref = int(record[0])
            base = _without_subset_prefix(record[3])
        except Exception:
            continue
        for name in (base, str(record[4] or "")):
            if not name:
                continue
            existing = names.get(name)
            if existing is None:
                names[name] = xref
            elif existing != xref:
                names[name] = None
    return names


def _trace_codepoint(char):
    if isinstance(char, dict):
        raw = char.get("unicode", char.get("c"))
    else:
        raw = char[0]
    return ord(raw) if isinstance(raw, str) else int(raw)


def _trace_has_unknown(traces) -> bool:
    """Whether MuPDF reported any drawn character as unmapped, cheaply."""
    for trace in traces or ():
        for char in trace.get("chars", ()) or ():
            try:
                if _trace_codepoint(char) == UNKNOWN_CHARACTER:
                    return True
            except Exception:
                continue
    return False


def _page_trace(page):
    """Per font: every drawn character's glyph id and whether MuPDF knew it.

    ``page.get_texttrace()`` is MuPDF's own verdict, character by character:
    ``ucs == 0xFFFD`` means the font and encoding chain produced no character
    for that code, and the glyph id sits right beside it. This is the detector
    and the source of the glyph ids; no CMap is parsed anywhere.
    """
    cached = getattr(page, _PAGE_TRACE, None)
    if isinstance(cached, dict):
        return cached
    by_font = {}
    try:
        traces = page.get_texttrace()
    except Exception:
        return by_font
    if not _trace_has_unknown(traces):
        # MuPDF resolved every character it drew, so there is nothing here to
        # bind and the per-character origin map is not worth building.
        try:
            setattr(page, _PAGE_TRACE, by_font)
        except Exception:
            pass
        return by_font
    for trace in traces or ():
        font_name = _without_subset_prefix(trace.get("font"))
        entry = by_font.setdefault(
            font_name, {"by_origin": {}, "clash": set(), "unknown": 0, "known": 0}
        )
        for char in trace.get("chars", ()) or ():
            try:
                if isinstance(char, dict):
                    raw_unicode = char.get("unicode", char.get("c"))
                    codepoint = ord(raw_unicode) if isinstance(raw_unicode, str) else int(raw_unicode)
                    glyph_id = int(char.get("glyph", char.get("gid")))
                    origin = char.get("origin")
                else:
                    codepoint = int(char[0])
                    glyph_id = int(char[1])
                    origin = char[2]
                key = (round(float(origin[0]), 3), round(float(origin[1]), 3))
            except Exception:
                continue
            if codepoint == UNKNOWN_CHARACTER:
                entry["unknown"] += 1
            else:
                entry["known"] += 1
            previous = entry["by_origin"].get(key)
            if previous is not None and previous != (codepoint, glyph_id):
                entry["clash"].add(key)
            entry["by_origin"][key] = (codepoint, glyph_id)
    try:
        setattr(page, _PAGE_TRACE, by_font)
    except Exception:
        pass
    return by_font


def _span_units(span):
    """(character, code, origin key) for every character the span delivers."""
    units = []
    chars = span.get("chars") or ()
    if chars:
        for char in chars:
            text = str(char.get("c", "") or "")
            if text == "":
                continue
            origin = char.get("origin")
            try:
                key = (round(float(origin[0]), 3), round(float(origin[1]), 3))
            except Exception:
                key = None
            units.append((char, text, key))
        return units, True
    for text in str(span.get("text", "") or ""):
        units.append((None, text, None))
    return units, False


def _apply_span_text(span, has_chars, units, replacements):
    if has_chars:
        for position, (char, _text, _key) in enumerate(units):
            if char is not None:
                char["c"] = replacements[position]
        if "text" in span:
            span["text"] = "".join(replacements)
        return
    span["text"] = "".join(replacements)


def _record_key(page_number, span):
    """One span, one record - wherever it was examined from.

    A host may hand this module two dictionaries for the same page (its own
    and the one a cross-check compares against). They describe the same spans,
    so the record is keyed by where the span is and nothing else; a second
    look at a span replaces the first only when it says more.
    """
    box = span.get("bbox") or ()
    try:
        located = tuple(round(float(value), 2) for value in tuple(box)[:4])
    except Exception:
        located = ()
    return (int(page_number), located)


def _record_rank(record):
    """How much a record says. A stronger verdict replaces a weaker one."""
    return (
        1 if record.get("status") == "recovered" else 0,
        int(record.get("glyphs") or 0),
    )


def merge_glyph_code_records(records, issues) -> None:
    """Merge issue rows into a host's own map, keeping the stronger verdict.

    A host that collects records itself uses this rather than its own key, so
    that one span is one row in its report too.
    """
    if not isinstance(records, dict):
        return
    for issue in issues or ():
        if not isinstance(issue, dict):
            continue
        key = (int(issue.get("page_number") or 0), tuple(issue.get("bbox_pdf") or ()))
        existing = records.get(key)
        if existing is None or _record_rank(issue) > _record_rank(existing):
            records[key] = issue


def _store(records, key, record):
    existing = records.get(key)
    if existing is not None:
        if _record_rank(record) > _record_rank(existing):
            records[key] = record
        return
    if len(records) < _MAX_RECORDS:
        records[key] = record
        return
    records.setdefault(_OVERFLOW_KEY, {
        "page_number": int(record.get("page_number") or 0),
        "font_name": "",
        "source_xref": 0,
        "status": "unproven",
        "route": "",
        "routes": {},
        "characters_left_as_delivered": {},
        "reason": "record_limit_reached",
        "limitation": True,
        "detail": "more than %d glyph-code spans in this document" % _MAX_RECORDS,
        "glyphs": 0,
        "glyphs_unproven": 0,
        "raw_codes": [],
        "raw_codes_truncated": False,
        "looked_for_face": "",
        "reference_faces": [],
        "bbox_pdf": [],
    })


def _recover_span(page_number, span, proof, trace_entry, records):
    font_name = str(span.get("font", "") or "")
    units, has_chars = _span_units(span)
    if not units:
        return
    if not has_chars:
        # A plain text dictionary carries no per-character origins, and a glyph
        # id may never be inferred from the character a host was handed: MuPDF's
        # layout inserts characters no glyph drew, and reading one of those as a
        # glyph index invents a letter. Such a host recovers the RAWDICT and
        # copies the result across with copy_recovered_text.
        _store(records, _record_key(page_number, span), _unproven_record(
            page_number, span, font_name, proof, (),
            "span_has_no_character_origins", len(units),
        ))
        return
    by_origin = trace_entry.get("by_origin", {}) if trace_entry else {}
    clash = trace_entry.get("clash", set()) if trace_entry else set()

    replacements = []
    glyph_ids = []
    routes = []
    delivered = []
    unproven = 0
    bind_failed = False
    for _char, text, key in units:
        bound = by_origin.get(key) if key is not None and key not in clash else None
        if bound is None:
            if key is not None and key not in by_origin and text == " ":
                # A space the layout inserted between runs, with no glyph
                # behind it. It is not this font's code and is left alone.
                replacements.append(text)
                delivered.append(DELIVERED_LAYOUT_SPACE)
                continue
            bind_failed = True
            break
        codepoint, glyph_id = bound
        if codepoint != UNKNOWN_CHARACTER:
            # MuPDF already had this character; never second-guessed.
            replacements.append(text)
            delivered.append(DELIVERED_MUPDF_RESOLVED)
            continue
        glyph_ids.append(glyph_id)
        proven = proof.character(glyph_id)
        if proven is None:
            unproven += 1
            replacements.append(text)
        else:
            replacements.append(proven)
            routes.append(proof.route(glyph_id))

    if bind_failed:
        _store(records, _record_key(page_number, span), _unproven_record(
            page_number, span, font_name, proof, glyph_ids,
            "characters_not_bound_to_glyph_ids", len(units),
        ))
        return
    if not glyph_ids:
        # Nothing on this span was a raw glyph code.
        return
    if unproven:
        # All or nothing: one unproven character leaves the whole span raw.
        _store(records, _record_key(page_number, span), _unproven_record(
            page_number, span, font_name, proof, glyph_ids,
            proof.reason or "glyph_outline_not_proven", unproven,
        ))
        return

    _apply_span_text(span, has_chars, units, replacements)
    used = [route for route in routes if route in ROUTE_ORDER]
    weakest = max(used, key=ROUTE_ORDER.index) if used else ROUTE_OUTLINE_IDENTITY
    counts = {}
    for route in used:
        counts[route] = counts.get(route, 0) + 1
    left = {}
    for marker in delivered:
        left[marker] = left.get(marker, 0) + 1
    _store(records, _record_key(page_number, span), {
        "page_number": int(page_number),
        "font_name": font_name,
        "source_xref": int(proof.xref),
        "status": "recovered",
        "route": weakest,
        "routes": dict(sorted(counts.items())),
        # Characters this module did NOT prove and did NOT change, counted
        # apart from the routes so no report implies the PDF declared them.
        "characters_left_as_delivered": dict(sorted(left.items())),
        "reason": "",
        "limitation": False,
        "glyphs": len(glyph_ids),
        "glyphs_recovered": len(glyph_ids),
        "raw_codes": list(glyph_ids[:_RAW_CODES_PER_ITEM]),
        "raw_codes_truncated": len(glyph_ids) > _RAW_CODES_PER_ITEM,
        "reference_faces": list(proof.reference_faces),
        "bbox_pdf": _bbox_of(span),
    })


def _bbox_of(span):
    try:
        return [round(float(value), 2) for value in tuple(span.get("bbox") or ())[:4]]
    except Exception:
        return []


def _unproven_record(page_number, span, font_name, proof, glyph_ids, reason, unproven):
    """One span left exactly as the PDF delivered it, and why.

    ``proof`` is None for a span this module declined to examine at all - an
    out-of-scope font, or a font name that means two subsets on one page.
    """
    return {
        "page_number": int(page_number),
        "font_name": font_name,
        "source_xref": int(proof.xref) if proof is not None else 0,
        "status": "unproven",
        "route": "",
        "routes": {},
        "characters_left_as_delivered": {},
        "reason": str(reason),
        # Whether this says something about the document or about this run.
        "limitation": str(reason) in LIMITATION_REASONS,
        "detail": str(proof.detail or "") if proof is not None else "",
        "glyphs": len(glyph_ids),
        "glyphs_unproven": int(unproven),
        "raw_codes": list(glyph_ids[:_RAW_CODES_PER_ITEM]),
        "raw_codes_truncated": len(glyph_ids) > _RAW_CODES_PER_ITEM,
        "looked_for_face": str(proof.looked_for or "") if proof is not None else "",
        "reference_faces": list(proof.reference_faces) if proof is not None else [],
        "bbox_pdf": _bbox_of(span),
    }


def recover_glyph_codes_in_place(page, tdict) -> None:
    """Replace the raw glyph codes of every span this document proves.

    Mutates ``tdict`` in place: a span whose every unknown character is proven
    gets the proven characters, and every other span is left exactly as MuPDF
    delivered it. Both outcomes are recorded on the page's document and can be
    read back with :func:`glyph_code_issues`.

    Calling this twice for the same page is safe and does not double-count: a
    record is keyed by page and span box, and a glyph id is only ever read from
    the trace, never from a character this call already recovered.
    """
    try:
        _recover_page(page, tdict)
    except Exception as exc:
        record_glyph_code_limitation(
            page, "glyph_code_recovery_failed", "%s: %s" % (type(exc).__name__, exc)
        )


def record_glyph_code_limitation(page, reason: str, detail: str = "") -> None:
    """Record that this RUN could not examine a page, not that the PDF failed.

    A host whose own dictionary cannot be recovered says so here, so the count
    stays honest and the operator line says it was the tool and not the sheet.
    """
    document = _document_of(page)
    records = _records_of(document) if document is not None else None
    if records is None:
        return
    page_number = int(getattr(page, "number", 0) or 0) + 1
    records[(page_number, ("page",))] = {
        "page_number": page_number,
        "font_name": "",
        "source_xref": 0,
        "status": "unproven",
        "route": "",
        "routes": {},
        "characters_left_as_delivered": {},
        "reason": str(reason),
        "limitation": True,
        "detail": str(detail or ""),
        "glyphs": 0,
        "glyphs_unproven": 0,
        "raw_codes": [],
        "raw_codes_truncated": False,
        "looked_for_face": "",
        "reference_faces": [],
        "bbox_pdf": [],
    }


def page_delivers_glyph_codes(page) -> bool:
    """Whether this page draws a character no font mapped to a character.

    Cheap and cached. A page declaring no composite or Type3 font is answered
    from its font dictionaries without any text extraction, so a host may ask
    before deciding to build a second, per-character dictionary of the page.
    """
    try:
        if not _page_candidate_fonts(page):
            return False
        return any(entry["unknown"] for entry in _page_trace(page).values())
    except Exception:
        return False


def _unexamined_glyph_ids(span, trace_entry):
    """The glyph ids of this span's characters MuPDF reported as unmapped."""
    units, has_chars = _span_units(span)
    if not has_chars or not trace_entry:
        return []
    by_origin = trace_entry.get("by_origin", {})
    glyph_ids = []
    for _char, _text, key in units:
        bound = by_origin.get(key) if key is not None else None
        if bound is not None and bound[0] == UNKNOWN_CHARACTER:
            glyph_ids.append(bound[1])
    return glyph_ids


def _report_unexamined(page_number, span, font_name, trace_entry, reason, records):
    """Record a span whose unmapped characters this module will not touch.

    Substitution stays as narrowly scoped as it is - a Type3 font, a partial
    ``/ToUnicode`` and a font name that means two different subsets on one page
    are all left exactly as delivered. Detection is structural and certain, so
    the span is still counted rather than passing as clean.
    """
    glyph_ids = _unexamined_glyph_ids(span, trace_entry)
    if not glyph_ids:
        return
    _store(records, _record_key(page_number, span), _unproven_record(
        page_number, span, font_name, None, glyph_ids, reason, len(glyph_ids),
    ))


def _recover_page(page, tdict) -> None:
    if not isinstance(tdict, dict):
        return
    document = _document_of(page)
    if document is None:
        return
    records = _records_of(document)
    if records is None:
        return
    page_number = int(getattr(page, "number", 0) or 0) + 1
    if not _page_candidate_fonts(page):
        # No composite or Type3 font on the page, so nothing it draws can
        # reach MuPDF unmapped. Answered without tracing the page at all.
        return
    trace = _page_trace(page)
    if not any(entry["unknown"] for entry in trace.values()):
        # MuPDF resolved every character it drew. Nothing here is in scope.
        return
    font_xrefs = _page_font_xrefs(page)
    cache = _proof_cache(document)
    if cache is None:
        cache = {}

    # Glyph ids this page actually needs proving, per font: a 3,000 span page
    # hashes each subset once.
    needed = {}
    for font_name, entry in trace.items():
        wanted = needed.setdefault(font_name, set())
        for codepoint, glyph_id in entry["by_origin"].values():
            if codepoint == UNKNOWN_CHARACTER:
                wanted.add(glyph_id)

    proofs = {}
    unresolved = {}
    for font_name, wanted in needed.items():
        if not wanted:
            continue
        if font_name not in font_xrefs:
            # The page's font dictionaries do not name the font that drew this
            # text, so there is nothing to read the subset out of.
            unresolved[font_name] = "font_not_found_on_page"
            continue
        xref = font_xrefs.get(font_name)
        if xref is None:
            # Two subsets of one family on this page answer to the same name.
            # Nothing may be proven for either, and the spans are reported
            # rather than passed over.
            unresolved[font_name] = "font_name_ambiguous_on_page"
            continue
        proof = cache.get(int(xref))
        if proof is None or not wanted <= proof.attempted:
            # One subset is hashed once per document, however many pages and
            # however many thousands of spans draw from it.
            previous = set(proof.attempted) if proof is not None else set()
            proof = _resolve_font(document, int(xref), font_name, previous | wanted)
            cache[int(xref)] = proof
        proofs[font_name] = proof

    for block in tdict.get("blocks", ()) or ():
        if block.get("type") != 0:
            continue
        for line in block.get("lines", ()) or ():
            for span in line.get("spans", ()) or ():
                font_name = _without_subset_prefix(span.get("font"))
                entry = trace.get(font_name)
                if not entry or not entry["unknown"]:
                    continue
                proof = proofs.get(font_name)
                try:
                    if font_name in unresolved:
                        _report_unexamined(
                            page_number, span, font_name, entry,
                            unresolved[font_name], records,
                        )
                    elif proof is None or not proof.in_scope:
                        _report_unexamined(
                            page_number, span, font_name, entry,
                            (proof.reason if proof is not None else "") or "font_out_of_scope",
                            records,
                        )
                    else:
                        _recover_span(page_number, span, proof, entry, records)
                except Exception:
                    # One span that cannot be handled costs that span, and it
                    # keeps the characters the PDF delivered.
                    continue


# ── handing the result to a host that reads a plain text dictionary ──


def copy_recovered_text(source_tdict, target_tdict):
    """Copy a recovered RAWDICT's span strings onto a plain text dictionary.

    ``page.get_text("dict")`` carries no per-character origins, and a glyph id
    may never be inferred from a delivered character. A host holding such a
    dictionary recovers the RAWDICT - the dictionary the shared extractor reads
    - and copies the result across span for span.

    A span is copied only where the two dictionaries agree on where it is,
    which font drew it and how many characters it has, so the two can never
    end up disagreeing about a character.

    Returns ``(copied, not_transferable)``.
    """
    copied = 0
    not_transferable = 0
    if not isinstance(source_tdict, dict) or not isinstance(target_tdict, dict):
        return copied, not_transferable
    source_blocks = list(source_tdict.get("blocks", ()) or ())
    target_blocks = list(target_tdict.get("blocks", ()) or ())
    for block_index in range(min(len(source_blocks), len(target_blocks))):
        source_block = source_blocks[block_index]
        target_block = target_blocks[block_index]
        if source_block.get("type") != 0 or target_block.get("type") != 0:
            continue
        source_lines = list(source_block.get("lines", ()) or ())
        target_lines = list(target_block.get("lines", ()) or ())
        for line_index in range(min(len(source_lines), len(target_lines))):
            source_spans = list(source_lines[line_index].get("spans", ()) or ())
            target_spans = list(target_lines[line_index].get("spans", ()) or ())
            for span_index in range(min(len(source_spans), len(target_spans))):
                source_span = source_spans[span_index]
                target_span = target_spans[span_index]
                chars = source_span.get("chars") or ()
                if not chars:
                    continue
                text = "".join(str(char.get("c", "") or "") for char in chars)
                current = str(target_span.get("text", "") or "")
                if text == current:
                    continue
                if (
                    len(text) != len(current)
                    or str(source_span.get("font", "")) != str(target_span.get("font", ""))
                    or _bbox_of(source_span) != _bbox_of(target_span)
                ):
                    not_transferable += 1
                    continue
                target_span["text"] = text
                copied += 1
    return copied, not_transferable


# ── reading the result back ──


def glyph_code_issues(page_or_document):
    """Every span this run examined, for one page or for the whole document."""
    document = _document_of(page_or_document)
    page_number = None
    if document is None:
        document = page_or_document
    else:
        page_number = int(getattr(page_or_document, "number", 0) or 0) + 1
    records = getattr(document, _DOCUMENT_RECORDS, None)
    if not isinstance(records, dict):
        return []
    rows = [dict(record) for record in records.values()]
    if page_number is not None:
        rows = [row for row in rows if int(row.get("page_number") or 0) == page_number]
    rows.sort(key=lambda row: (
        int(row.get("page_number") or 0),
        row.get("status") != "unproven",
        tuple(row.get("bbox_pdf") or ()),
    ))
    return rows


def glyph_code_delivery_block(issues, item_limit: int = REPORT_ITEM_LIMIT) -> dict:
    """The report block a host publishes: counts, routes, and unproven spans.

    Unproven spans sort first, so the item cap never hides the spans an
    operator has to look at.
    """
    rows = [dict(row) for row in (issues or ())]
    rows.sort(key=lambda row: (
        row.get("status") != "unproven",
        int(row.get("page_number") or 0),
        tuple(row.get("bbox_pdf") or ()),
    ))
    recovered = [row for row in rows if row.get("status") == "recovered"]
    unproven = [row for row in rows if row.get("status") != "recovered"]
    by_route = {}
    glyphs_by_route = {}
    left_as_delivered = {}
    for row in recovered:
        route = str(row.get("route") or "")
        by_route[route] = by_route.get(route, 0) + 1
        # Only the routes that PROVED a character. A character MuPDF already
        # had, and a space its layout inserted, are counted separately: an
        # in-scope font has no /ToUnicode by construction, so no count here may
        # ever read as one.
        for name, count in (row.get("routes") or {}).items():
            glyphs_by_route[name] = glyphs_by_route.get(name, 0) + int(count)
        for name, count in (row.get("characters_left_as_delivered") or {}).items():
            left_as_delivered[name] = left_as_delivered.get(name, 0) + int(count)
    by_reason = {}
    for row in unproven:
        reason = str(row.get("reason") or "unknown")
        by_reason[reason] = by_reason.get(reason, 0) + 1
    limitations = [row for row in unproven if row.get("limitation")]
    pages = sorted({int(row.get("page_number") or 0) for row in rows})
    return {
        "schema": GLYPH_CODE_SCHEMA,
        "pages": pages,
        "spans_examined": len(rows),
        "recovered": len(recovered),
        "unproven": len(unproven),
        # Of the unproven spans, those this RUN could not examine rather than
        # spans this document does not explain.
        "unproven_from_run_limitation": len(limitations),
        "glyphs_recovered": sum(int(row.get("glyphs_recovered") or 0) for row in recovered),
        "glyphs_unproven": sum(int(row.get("glyphs") or 0) for row in unproven),
        "spans_by_route": dict(sorted(by_route.items())),
        "glyphs_by_route": dict(sorted(glyphs_by_route.items())),
        "characters_left_as_delivered": dict(sorted(left_as_delivered.items())),
        "by_reason": dict(sorted(by_reason.items())),
        "items": rows[:max(0, int(item_limit))],
        "items_truncated": len(rows) > max(0, int(item_limit)),
    }


_BLOCK_COUNTS = (
    "spans_examined", "recovered", "unproven", "unproven_from_run_limitation",
    "glyphs_recovered", "glyphs_unproven",
)
_BLOCK_TALLIES = (
    "spans_by_route", "glyphs_by_route", "characters_left_as_delivered", "by_reason",
)


def merge_glyph_code_blocks(blocks, item_limit: int = REPORT_ITEM_LIMIT) -> dict:
    """One block for a document a host built page by page, or run by run.

    The counts add; the item lists concatenate and are capped again with the
    unproven spans first, so the cap never hides one. A host that merges as it
    goes keeps a bounded block rather than a list that grows with the document.
    """
    counts = {key: 0 for key in _BLOCK_COUNTS}
    tallies = {name: {} for name in _BLOCK_TALLIES}
    pages = set()
    items = []
    truncated = False
    for block in blocks or ():
        if not isinstance(block, dict):
            continue
        for key in counts:
            counts[key] += int(block.get(key) or 0)
        for name, tally in tallies.items():
            for label, count in (block.get(name) or {}).items():
                tally[label] = tally.get(label, 0) + int(count)
        for page in block.get("pages") or ():
            try:
                pages.add(int(page))
            except (TypeError, ValueError):
                continue
        items += [row for row in (block.get("items") or ()) if isinstance(row, dict)]
        truncated = truncated or bool(block.get("items_truncated"))
    items.sort(key=lambda row: row.get("status") == "recovered")
    cap = max(0, int(item_limit))
    return {
        "schema": GLYPH_CODE_SCHEMA,
        "pages": sorted(pages),
        **counts,
        **{name: dict(sorted(tally.items())) for name, tally in tallies.items()},
        "items": items[:cap],
        "items_truncated": truncated or len(items) > cap,
    }


def glyph_code_warning_count(block) -> int:
    """Unproven spans. A recovered span is a clean delivery and never warns."""
    if not isinstance(block, dict):
        return 0
    return int(block.get("unproven", 0) or 0)


def _where(rows) -> tuple:
    pages = ", ".join(str(page) for page in sorted(
        {int(row.get("page_number") or 0) for row in rows}
    )[:8])
    fonts = ", ".join(sorted({str(row.get("font_name") or "?") for row in rows})[:4])
    return fonts or "?", pages or "?"


def summarize_glyph_code_issues(issues, see: str = "") -> str:
    """One operator sentence for the whole import, or '' when nothing applied."""
    return summarize_glyph_code_block(glyph_code_delivery_block(issues), see)


def summarize_glyph_code_block(block, see: str = "") -> str:
    """The same sentence from an already-built block.

    A host that imported a document page by page has blocks rather than rows,
    and its counts have to be the block's own, not a recount of the capped
    item list.

    What this document does not say and what this run could not look at are
    never put in the same sentence: one is a property of the sheet and the
    other is a limitation of the tool.
    """
    if not isinstance(block, dict) or not block.get("spans_examined"):
        return ""
    unproven = [row for row in block.get("items") or () if row.get("status") != "recovered"]
    from_document = [row for row in unproven if not row.get("limitation")]
    from_run = [row for row in unproven if row.get("limitation")]
    # The counts are the block's; the item list only says which fonts and pages.
    limited = int(block.get("unproven_from_run_limitation") or 0)
    unreadable = max(0, int(block.get("unproven") or 0) - limited)
    parts = []
    if block.get("recovered"):
        routes = ", ".join(
            "%s x%d" % (name, count)
            for name, count in (block.get("spans_by_route") or {}).items()
        )
        parts.append(
            "%d text span(s) were delivered as raw glyph codes and their characters "
            "were recovered (%s), not read from the PDF" % (block["recovered"], routes)
        )
    if unreadable:
        fonts, pages = _where(from_document)
        parts.append(
            "%d text span(s) use an embedded font with no usable Unicode map; their "
            "characters could not be proven and are shown as the PDF's raw glyph codes "
            "(font %s, page %s)" % (unreadable, fonts, pages)
        )
    if limited:
        fonts, pages = _where(from_run)
        reasons = ", ".join(sorted({str(row.get("reason") or "?") for row in from_run})[:4])
        parts.append(
            "%d text span(s) were not examined for raw glyph codes by this run (%s) and "
            "are shown exactly as the PDF delivered them - a limitation of this import, "
            "not of the sheet (font %s, page %s)"
            % (limited, reasons or "?", fonts, pages)
        )
    if not parts:
        return ""
    return "; ".join(parts) + "." + ((" " + see) if see else "")
