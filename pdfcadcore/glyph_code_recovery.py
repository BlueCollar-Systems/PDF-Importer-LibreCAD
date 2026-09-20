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

What this module does, per character, stopping at the first route that PROVES
the character:

1. ``pdf_to_unicode``  - the PDF's own ``/ToUnicode``. Normative. MuPDF already
   applies it, so a character MuPDF resolved is left exactly as it is and
   counted on this route; nothing here second-guesses it.
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

There is no fifth route. No offsets, no "standard Macintosh glyph order"
assumption, no encoding guesses.

Two rules govern everything else:

* **Substitution is all-or-nothing per span.** If one character of a span is
  unproven the ENTIRE span is left byte for byte as MuPDF delivered it. A
  half-recovered dimension like ``34' - 1?"`` reads as a measurement and is
  worse than raw garbage.
* **Nothing is ever presented as if the PDF had declared it.** Every span this
  module changes is recorded with the route that proved it, and every span it
  could not prove is recorded with the font, the location and the raw codes, so
  a host can tell the operator.

When no reference face for the declared family is installed, route 4 recovers
nothing and says so (reason ``no_reference_face_available``, naming the family
it looked for). It never falls back to a guess. ``BCS_GLYPH_REFERENCE_FONTS``
overrides the search: a path-separated list of directories or files, or the
single word ``none`` to switch reference matching off entirely.

Nothing in this module raises. A failure anywhere means "nothing is proven for
that font", which is recorded and reported like any other unproven span.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys

GLYPH_CODE_SCHEMA = "bcs.text_glyph_codes/1.0"

# The character MuPDF reports for a code its font/encoding chain maps to
# nothing. This is the detector, and the only one: the raw codes of an affected
# span are frequently printable ASCII, so scanning for control characters finds
# the obvious garbage and misses the plausible, legible, wrong text.
UNKNOWN_CHARACTER = 0xFFFD

ROUTE_TO_UNICODE = "pdf_to_unicode"
ROUTE_EMBEDDED_CMAP = "embedded_cmap"
ROUTE_POST_NAME = "post_glyph_name"
ROUTE_OUTLINE_IDENTITY = "outline_identity"

# Most speculative last: a span is reported on the weakest route it needed.
ROUTE_ORDER = (
    ROUTE_TO_UNICODE,
    ROUTE_EMBEDDED_CMAP,
    ROUTE_POST_NAME,
    ROUTE_OUTLINE_IDENTITY,
)

REPORT_ITEM_LIMIT = 200
_RAW_CODES_PER_ITEM = 48
_MAX_REFERENCE_FACES = 4
_FACE_TABLE_CACHE_LIMIT = 8

_DOCUMENT_RECORDS = "_bcs_glyph_code_records"
_DOCUMENT_PROOFS = "_bcs_glyph_code_font_proofs"
_PAGE_TRACE = "_bcs_glyph_code_page_trace"
# A pathological sheet must not turn the report into the document. Counting
# stops honestly rather than quietly.
_MAX_RECORDS = 20000
_OVERFLOW_KEY = (-1, (), ("record-limit",))

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


def _outline_drawer(font):
    """One way to draw a glyph, used identically on subset and reference.

    A subset stripped to its outlines routinely carries an ``hmtx`` table cut
    to the glyphs it kept while ``maxp`` still counts the original 3,000; the
    high-level glyph set refuses such a font outright. ``glyf`` alone draws it,
    composites included, and the reference face is drawn exactly the same way
    so the two command streams are comparable at all.
    """
    try:
        glyf = font["glyf"]
    except Exception:
        glyf = None
    if glyf is not None:
        def draw(glyph_name, pen):
            glyf[glyph_name].draw(pen, glyf)
        return draw
    glyph_set = font.getGlyphSet()

    def draw_from_set(glyph_name, pen):
        glyph_set[glyph_name].draw(pen)
    return draw_from_set


def _outline_signature(drawer, glyph_name, scale):
    from fontTools.pens.recordingPen import RecordingPen

    pen = RecordingPen()
    drawer(glyph_name, pen)
    parts = []
    for operator, arguments in pen.value:
        parts.append(operator)
        for point in arguments:
            if point is None:
                parts.append("*")
            else:
                parts.append("%.3f,%.3f" % (point[0] * scale, point[1] * scale))
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


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

        font = TTFont(BytesIO(data), lazy=True, fontNumber=0)
    except Exception as exc:
        proof.reason = "embedded_font_program_unreadable"
        proof.detail = "%s: %s" % (type(exc).__name__, exc)
        return proof

    try:
        wanted = {int(glyph_id) for glyph_id in needed_glyphs}
        # Route 2 - the font's own cmap.
        if _sfnt_has_table(data, b"cmap"):
            for glyph_id, codepoint in _embedded_cmap_characters(font).items():
                if glyph_id in wanted and glyph_id not in proof.characters:
                    proof.characters[glyph_id] = chr(codepoint)
                    proof.routes[glyph_id] = ROUTE_EMBEDDED_CMAP
        # Route 3 - real post table names.
        for glyph_id, codepoint in _post_name_characters(font, data).items():
            if glyph_id in wanted and glyph_id not in proof.characters:
                proof.characters[glyph_id] = chr(codepoint)
                proof.routes[glyph_id] = ROUTE_POST_NAME
        remaining = sorted(wanted - set(proof.characters))
        if remaining:
            _prove_by_outline(
                proof, font, remaining, widths, default_width, document, descendant_xref
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


def _prove_by_outline(proof, font, glyph_ids, widths, default_width, document, descendant_xref):
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
    for glyph_id in glyph_ids:
        if glyph_id < 0 or glyph_id >= len(order):
            continue
        try:
            signature = _outline_signature(drawer, order[glyph_id], scale)
        except Exception:
            continue
        declared = widths.get(int(glyph_id))
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
            proof.characters[glyph_id] = chr(answers.pop())
            proof.routes[glyph_id] = ROUTE_OUTLINE_IDENTITY


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


def _record_key(page_number, span, glyph_ids):
    box = span.get("bbox") or ()
    try:
        located = tuple(round(float(value), 2) for value in tuple(box)[:4])
    except Exception:
        located = ()
    return (int(page_number), located, tuple(glyph_ids))


def _store(records, key, record):
    if key in records or len(records) < _MAX_RECORDS:
        records[key] = record
        return
    records.setdefault(_OVERFLOW_KEY, {
        "page_number": int(record.get("page_number") or 0),
        "font_name": "",
        "source_xref": 0,
        "status": "unproven",
        "route": "",
        "routes": {},
        "reason": "record_limit_reached",
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
    by_origin = trace_entry.get("by_origin", {}) if trace_entry else {}
    clash = trace_entry.get("clash", set()) if trace_entry else set()
    known_count = int(trace_entry.get("known", 0)) if trace_entry else 0

    replacements = []
    glyph_ids = []
    routes = []
    unproven = 0
    bind_failed = False
    for _char, text, key in units:
        bound = by_origin.get(key) if key is not None and key not in clash else None
        if bound is None and key is None and known_count == 0 and proof.cid_is_gid:
            # No per-character origins (a plain text dictionary). Every one of
            # this font's drawn characters is unknown to MuPDF and the CMap is
            # Identity, so the delivered code IS the glyph index.
            bound = (UNKNOWN_CHARACTER, ord(text))
        if bound is None:
            if key is not None and key not in by_origin and text == " ":
                # A space the layout inserted between runs, with no glyph
                # behind it. It is not this font's code and is left alone.
                replacements.append(text)
                routes.append(ROUTE_TO_UNICODE)
                continue
            bind_failed = True
            break
        codepoint, glyph_id = bound
        if codepoint != UNKNOWN_CHARACTER:
            # The PDF proved this character itself; never second-guessed.
            replacements.append(text)
            routes.append(ROUTE_TO_UNICODE)
            continue
        glyph_ids.append(glyph_id)
        proven = proof.character(glyph_id)
        if proven is None:
            unproven += 1
            replacements.append(text)
            routes.append("")
        else:
            replacements.append(proven)
            routes.append(proof.route(glyph_id))

    if bind_failed:
        _store(records, _record_key(page_number, span, glyph_ids), _unproven_record(
            page_number, span, font_name, proof, glyph_ids,
            "characters_not_bound_to_glyph_ids", len(units),
        ))
        return
    if not glyph_ids:
        # Nothing on this span was a raw glyph code.
        return
    if unproven:
        # All or nothing: one unproven character leaves the whole span raw.
        _store(records, _record_key(page_number, span, glyph_ids), _unproven_record(
            page_number, span, font_name, proof, glyph_ids,
            proof.reason or "glyph_outline_not_proven", unproven,
        ))
        return

    _apply_span_text(span, has_chars, units, replacements)
    used = [route for route in routes if route]
    weakest = ROUTE_TO_UNICODE
    for route in used:
        if ROUTE_ORDER.index(route) > ROUTE_ORDER.index(weakest):
            weakest = route
    counts = {}
    for route in used:
        counts[route] = counts.get(route, 0) + 1
    _store(records, _record_key(page_number, span, glyph_ids), {
        "page_number": int(page_number),
        "font_name": font_name,
        "source_xref": int(proof.xref),
        "status": "recovered",
        "route": weakest,
        "routes": dict(sorted(counts.items())),
        "reason": "",
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
    return {
        "page_number": int(page_number),
        "font_name": font_name,
        "source_xref": int(proof.xref),
        "status": "unproven",
        "route": "",
        "routes": {},
        "reason": str(reason),
        "detail": str(proof.detail or ""),
        "glyphs": len(glyph_ids),
        "glyphs_unproven": int(unproven),
        "raw_codes": list(glyph_ids[:_RAW_CODES_PER_ITEM]),
        "raw_codes_truncated": len(glyph_ids) > _RAW_CODES_PER_ITEM,
        "looked_for_face": str(proof.looked_for or ""),
        "reference_faces": list(proof.reference_faces),
        "bbox_pdf": _bbox_of(span),
    }


def recover_glyph_codes_in_place(page, tdict) -> None:
    """Replace the raw glyph codes of every span this document proves.

    Mutates ``tdict`` in place: a span whose every unknown character is proven
    gets the proven characters, and every other span is left exactly as MuPDF
    delivered it. Both outcomes are recorded on the page's document and can be
    read back with :func:`glyph_code_issues`.

    Calling this twice for the same page is safe and does not double-count: a
    record is keyed by page, span box and raw codes.
    """
    try:
        _recover_page(page, tdict)
    except Exception as exc:
        document = _document_of(page)
        records = _records_of(document) if document is not None else None
        if records is None:
            return
        page_number = int(getattr(page, "number", 0) or 0) + 1
        records[(page_number, (), ("page",))] = {
            "page_number": page_number,
            "font_name": "",
            "source_xref": 0,
            "status": "unproven",
            "route": "",
            "routes": {},
            "reason": "glyph_code_recovery_failed",
            "detail": "%s: %s" % (type(exc).__name__, exc),
            "glyphs": 0,
            "glyphs_unproven": 0,
            "raw_codes": [],
            "raw_codes_truncated": False,
            "looked_for_face": "",
            "reference_faces": [],
            "bbox_pdf": [],
        }


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
    for font_name, wanted in needed.items():
        if not wanted:
            continue
        xref = font_xrefs.get(font_name)
        if xref is None:
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
                proof = proofs.get(font_name)
                if proof is None or not proof.in_scope:
                    continue
                try:
                    _recover_span(page_number, span, proof, trace.get(font_name), records)
                except Exception:
                    # One span that cannot be handled costs that span, and it
                    # keeps the characters the PDF delivered.
                    continue


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
    for row in recovered:
        route = str(row.get("route") or "")
        by_route[route] = by_route.get(route, 0) + 1
        for name, count in (row.get("routes") or {}).items():
            glyphs_by_route[name] = glyphs_by_route.get(name, 0) + int(count)
    by_reason = {}
    for row in unproven:
        reason = str(row.get("reason") or "unknown")
        by_reason[reason] = by_reason.get(reason, 0) + 1
    pages = sorted({int(row.get("page_number") or 0) for row in rows})
    return {
        "schema": GLYPH_CODE_SCHEMA,
        "pages": pages,
        "spans_examined": len(rows),
        "recovered": len(recovered),
        "unproven": len(unproven),
        "glyphs_recovered": sum(int(row.get("glyphs_recovered") or 0) for row in recovered),
        "glyphs_unproven": sum(int(row.get("glyphs") or 0) for row in unproven),
        "spans_by_route": dict(sorted(by_route.items())),
        "glyphs_by_route": dict(sorted(glyphs_by_route.items())),
        "by_reason": dict(sorted(by_reason.items())),
        "items": rows[:max(0, int(item_limit))],
        "items_truncated": len(rows) > max(0, int(item_limit)),
    }


def glyph_code_warning_count(block) -> int:
    """Unproven spans. A recovered span is a clean delivery and never warns."""
    if not isinstance(block, dict):
        return 0
    return int(block.get("unproven", 0) or 0)


def summarize_glyph_code_issues(issues, see: str = "") -> str:
    """One operator sentence for the whole import, or '' when nothing applied."""
    block = glyph_code_delivery_block(issues)
    if not block["spans_examined"]:
        return ""
    unproven = [row for row in block["items"] if row.get("status") != "recovered"]
    parts = []
    if block["recovered"]:
        routes = ", ".join(
            "%s x%d" % (name, count) for name, count in block["spans_by_route"].items()
        )
        parts.append(
            "%d text span(s) were delivered as raw glyph codes and their characters "
            "were recovered (%s), not read from the PDF" % (block["recovered"], routes)
        )
    if block["unproven"]:
        pages = ", ".join(str(page) for page in sorted(
            {int(row.get("page_number") or 0) for row in unproven}
        )[:8])
        fonts = ", ".join(sorted({str(row.get("font_name") or "?") for row in unproven})[:4])
        parts.append(
            "%d text span(s) use an embedded font with no usable Unicode map; their "
            "characters could not be proven and are shown as the PDF's raw glyph codes "
            "(font %s, page %s)" % (block["unproven"], fonts or "?", pages or "?")
        )
    if not parts:
        return ""
    return "; ".join(parts) + "." + ((" " + see) if see else "")
