"""Rehome only LibreCAD's exact unreferenced eight-tag native plot record.

No input file is edited and qualification does not export other entities.
The native host consumes even unreferenced records for print tiling/margins.
Preserve each object and every printing field; only ownership/name may change.
"""
from collections import Counter
import base64
import hashlib
import json
import math
from pathlib import Path

from ezdxf.lldxf.tagwriter import TagCollector

from .drawing_copy import DrawingCopyError, _hash_file, _ordinary_file

REFERENCES = set(range(320, 370)) | set(range(390, 400)) | {480, 481, 1005}
TEMPLATE = [(0, "PLOTSETTINGS"), (5, "@HANDLE@"), (100, "AcDbPlotSettings"),
            (6, "1x1"), (40, "0"), (41, "0"), (42, "0"), (43, "0")]
MAX_TAGS = 16_000_000
MAX_RECORDS = 1_000_000
MAX_LINE_BYTES = 1_048_576


def _callback_fields(tags):
    result = {"plot_view_name": "", "margins_mm": [0.0] * 4}
    for code, value in tags:
        if code == 6:
            result["plot_view_name"] = value
        elif code in {40, 41, 42, 43}:
            try:
                number = float(value)
            except (ValueError, TypeError) as error:
                raise DrawingCopyError("Native print callback has an invalid margin.") from error
            if not math.isfinite(number):
                raise DrawingCopyError("Native print callback has a nonfinite margin.")
            result["margins_mm"][code - 40] = number
    return result


def native_plot_callback_sequence(path, *, cancel_check=None):
    """Ordered physical callbacks under LibreCAD 2.2.1.5's pinned parser.

    DRW_PlotSettings ctor initializes the string empty and all margins zero;
    parseCode uses the last code6/40..43 value, ignoring name1/owner330.
    RS_FilterDXFRW applies EVERY OBJECTS PLOTSETTINGS in file order.
    This is print-setting provenance, not native visual/Save acceptance.
    """
    rows, section, row = [], None, None
    need_section = False
    count = 0
    with Path(path).open("rb") as stream:
        if stream.read(22).startswith(b"AutoCAD Binary DXF"):
            raise DrawingCopyError("Native print callback proof needs ASCII/UTF-8 DXF.")
        stream.seek(0)
        while True:
            if cancel_check:
                cancel_check()
            code_line = stream.readline(MAX_LINE_BYTES + 1)
            if not code_line:
                break
            value_line = stream.readline(MAX_LINE_BYTES + 1)
            if not value_line or len(code_line) > MAX_LINE_BYTES or len(value_line) > MAX_LINE_BYTES:
                raise DrawingCopyError("Incomplete or oversized print callback tags.")
            try:
                code = int(code_line.removeprefix(b"\xef\xbb\xbf").strip())
                value = value_line.decode("utf-8").rstrip("\r\n")
            except (ValueError, UnicodeError) as error:
                raise DrawingCopyError("Native print callback proof needs valid UTF-8 tags.") from error
            count += 1
            if count > MAX_TAGS or not 0 <= code <= 1071:
                raise DrawingCopyError("Native print callback proof exceeded its tag budget.")
            if code == 0:
                if row is not None:
                    rows.append(row)
                    if len(rows) > MAX_RECORDS:
                        raise DrawingCopyError("Native print callback proof exceeded its record budget.")
                row = None
                need_section = value == "SECTION"
                if value == "ENDSEC":
                    section = None
                elif value == "PLOTSETTINGS" and section == "OBJECTS":
                    row = {"handle": None, "plot_view_name": "", "margins_mm": [0.0] * 4}
            elif need_section and code == 2:
                section, need_section = value, False
            elif row is not None:
                if code == 5:
                    row["handle"] = value.strip().upper()
                elif code == 6:
                    row["plot_view_name"] = value
                elif code in {40, 41, 42, 43}:
                    try:
                        number = float(value)
                    except ValueError as error:
                        raise DrawingCopyError("Native print callback has an invalid margin.") from error
                    if not math.isfinite(number):
                        raise DrawingCopyError("Native print callback has a nonfinite margin.")
                    row["margins_mm"][code - 40] = number
        if row is not None:
            rows.append(row)
    return rows


def _hash_tags(tags):
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise DrawingCopyError("Native print-settings qualification found a nonfinite value.")
        if isinstance(value, (list, tuple)):
            for item in value:
                finite(item)
    finite(tags)
    return hashlib.sha256(json.dumps(tags, ensure_ascii=True, separators=(",", ":"),
        allow_nan=False).encode("ascii")).hexdigest()


def _physical(path, cancel_check):
    handles, references, candidates = Counter(), set(), []
    section = None
    count = records = 0

    def consume(tags, raw):
        nonlocal section, records
        if not tags:
            return
        kind = tags[0][1]
        if kind == "SECTION":
            section = next((value for code, value in tags if code == 2), None)
            return
        if kind == "ENDSEC":
            section = None
            return
        records += 1
        if records > MAX_RECORDS:
            raise DrawingCopyError("Native print-settings qualification exceeded its record budget.")
        if kind == "PLOTSETTINGS" and section == "OBJECTS":
            identity = [value for code, value in tags if code == 5]
            if len(identity) == 1:
                handle = identity[0].upper()
                normalized = [(code, "@HANDLE@" if code == 5 else value) for code, value in tags]
                if normalized == TEMPLATE and 0 < len(handle) <= 16 and all(ch in "0123456789ABCDEF" for ch in handle):
                    candidates.append((handle, tags, raw))
                    if len(candidates) > 32:
                        raise DrawingCopyError("Too many unreferenced native print-settings records to qualify.")

    with Path(path).open("rb") as stream:
        if stream.read(22).startswith(b"AutoCAD Binary DXF"):
            return []
        stream.seek(0)
        tags, raw = [], bytearray()
        while True:
            if cancel_check:
                cancel_check()
            code_line = stream.readline(MAX_LINE_BYTES + 1)
            if not code_line:
                break
            value_line = stream.readline(MAX_LINE_BYTES + 1)
            if not value_line or len(code_line) > MAX_LINE_BYTES or len(value_line) > MAX_LINE_BYTES:
                raise DrawingCopyError("Incomplete or oversized native print-settings tag data.")
            try:
                if count == 0 and code_line.startswith(b"\xef\xbb\xbf"):
                    code_line = code_line[3:]
                code, value = int(code_line.strip()), value_line.decode("utf-8").rstrip("\r\n")
            except (ValueError, UnicodeError) as error:
                raise DrawingCopyError("Native print-settings qualification needs valid ASCII/UTF-8 DXF tags.") from error
            count += 1
            if count > MAX_TAGS or not 0 <= code <= 1071:
                raise DrawingCopyError("Native print-settings qualification exceeded its tag budget.")
            if code in REFERENCES:
                references.add(value.strip().upper())
            if code == 0:
                consume(tags, bytes(raw))
                tags, raw = [], bytearray()
            if code in {5, 105} and tags and tags[0] != (0, "SECTION"):
                handles[value.strip().upper()] += 1
            # Only an exact eight-tag record can qualify. Keep one extra tag
            # to disqualify longer records; large unrelated entities stream
            # without accumulating their geometry or arbitrary source text.
            if len(tags) < 9:
                tags.append((code, value))
                raw.extend(code_line + value_line)
        consume(tags, bytes(raw))
    for handle, _tags, _raw in candidates:
        if handles[handle] != 1 or handle in references:
            raise DrawingCopyError("An unreferenced native print-settings record is duplicated or referenced. The original was kept.")
    return candidates


def qualify_native_plot_settings(path, document, entity_state, dictionaries, headers, *, cancel_check=None):
    """Bind exact raw bytes and complete physical/retained parsed references."""
    path = Path(path)
    _ordinary_file(path)
    before = _hash_file(path)
    candidates = _physical(path, cancel_check)
    handles = {row[0] for row in candidates}
    dictionary = document.rootdict.get("ACAD_PLOTSETTINGS")
    memberships = Counter()
    if dictionary is not None and dictionary.is_alive and dictionary.dxftype() == "DICTIONARY":
        for index, (_name, value) in enumerate(dictionary.items()):
            if index >= MAX_RECORDS:
                raise DrawingCopyError("Print-settings dictionary qualification exceeded its record budget.")
            if cancel_check:
                cancel_check()
            memberships[id(value)] += 1
    for index, entity in enumerate(document.entitydb.values()):
        if index >= MAX_RECORDS:
            raise DrawingCopyError("Parsed print-settings qualification exceeded its record budget.")
        if cancel_check:
            cancel_check()
        if (entity.is_alive and entity.dxftype() == "PLOTSETTINGS"
                and str(entity.dxf.handle) not in handles):
            owner = document.entitydb.get(entity.dxf.get("owner", ""))
            name = entity.dxf.get("page_setup_name", "")
            if (owner is None or not owner.is_alive or owner.dxftype() != "DICTIONARY"
                    or owner is not dictionary or owner.dxf.get("owner") != document.rootdict.dxf.handle
                    or not isinstance(name, str) or not name or owner.get(name) is not entity
                    or memberships[id(entity)] != 1):
                raise DrawingCopyError("Native print settings have unsupported ownership or standard dictionary membership. The original was kept.")
    if not candidates:
        if _hash_file(path) != before:
            raise DrawingCopyError("The drawing changed during print-settings qualification.")
        return []
    parsed_references = set()
    for tags in entity_state.values():
        for code, value in tags:
            if code in REFERENCES:
                parsed_references.add(str(value).upper())
    for entries in dictionaries.values():
        parsed_references.update(str(value).upper() for value in entries.values())
    # Conservatively reject a matching HEADER string even when the SDK's
    # generated header field is not present in the authored physical file.
    parsed_references.update(value.upper() for value in headers.values() if isinstance(value, str))
    for index, entity in enumerate(document.entitydb.values()):
        if index >= MAX_RECORDS:
            raise DrawingCopyError("Parsed print-settings qualification exceeded its record budget.")
        if cancel_check:
            cancel_check()
        if not entity.is_alive:
            continue
        for name, value in entity.dxfattribs().items():
            specification = entity.DXFATTRIBS.get(name)
            if specification is not None and specification.code in REFERENCES:
                parsed_references.add(str(value).upper())
    if handles & parsed_references:
        raise DrawingCopyError("Native print-settings metadata has a parsed drawing reference. The original was kept.")
    if (dictionary is None or dictionary.dxftype() != "DICTIONARY"
            or dictionary.dxf.get("owner") != document.rootdict.dxf.handle
            or str(dictionary.dxf.handle) not in dictionaries):
        raise DrawingCopyError("Native print settings need an existing valid standard dictionary.")
    expected_entries = dictionaries[str(dictionary.dxf.handle)]
    if {str(key): str(value.dxf.handle) for key, value in dictionary.items()} != expected_entries:
        raise DrawingCopyError("Native print settings dictionary changed before qualification.")
    names = set(expected_entries)
    plans = []
    for handle, tags, raw in candidates:
        entity = document.entitydb.get(handle)
        if entity is None or not entity.is_alive or entity.dxftype() != "PLOTSETTINGS" or entity.dxf.get("owner") not in {None, "0"}:
            raise DrawingCopyError("Native print-settings identity changed before qualification.")
        collector = TagCollector(optional=False)
        entity.export_dxf(collector)  # This exact print record has no geometry.
        parsed = [(tag.code, tag.value) for tag in collector.tags]
        if parsed != entity_state.get(handle):
            raise DrawingCopyError("Native print-settings changed after the retained snapshot.")
        name = "Saved drawing print setup"
        suffix = 2
        while name in names:
            name = "Saved drawing print setup " + str(suffix)
            suffix += 1
        names.add(name)
        expected = []
        changed = {330: 0, 1: 0}
        for code, value in parsed:
            if code == 330:
                if value != "0":
                    raise DrawingCopyError("Native print settings owner is not the qualified default.")
                changed[330] += 1
                value = str(dictionary.dxf.handle)
            elif code == 1:
                if value != "":
                    raise DrawingCopyError("Native print settings name is not the qualified default.")
                changed[1] += 1
                value = name
            expected.append((code, value))
        if changed != {330: 1, 1: 1}:
            raise DrawingCopyError("Native print settings have ambiguous ownership/name tags.")
        callback = _callback_fields(tags)
        if _callback_fields(parsed) != callback or _callback_fields(expected) != callback:
            raise DrawingCopyError("Native print rehome would change physical callback fields.")
        plans.append({"handle": handle, "physical_tag_sequence": tags,
            "physical_record_bytes_base64": base64.b64encode(raw).decode("ascii"),
            "physical_record_sha256": hashlib.sha256(raw).hexdigest(),
            "parsed_before_tags": parsed, "parsed_before_tags_sha256": _hash_tags(parsed),
            "owned_input_sha256": before, "physical_and_parsed_incoming_references": 0,
            "parsed_after_tags": expected, "parsed_after_tags_sha256": _hash_tags(expected),
            "dictionary_handle": str(dictionary.dxf.handle), "dictionary_entries_before": expected_entries,
            "setup_name": name,
            "qualified_physical_parsed_and_rehomed_native_callback": callback,
            "only_permitted_delta": {"owner_group330": {"before": "0", "after": str(dictionary.dxf.handle)},
                "setup_name_group1": {"before": "", "after": name},
                "standard_dictionary_entry_added": {name: handle}}})
    if cancel_check:
        cancel_check()
    if _hash_file(path) != before:
        raise DrawingCopyError("The drawing changed during print-settings qualification.")
    return plans


def apply_native_plot_settings(document, plans):
    order = [str(entity.dxf.handle) for entity in document.objects if entity.dxftype() == "PLOTSETTINGS"]
    # Validate ALL identities/dictionary reservations before changing any.
    dictionary = document.rootdict.get("ACAD_PLOTSETTINGS")
    if not plans:
        return
    if dictionary is None or dictionary.dxftype() != "DICTIONARY":
        raise DrawingCopyError("Qualified print-settings dictionary changed.")
    entries = {str(key): str(value.dxf.handle) for key, value in dictionary.items()}
    for plan in plans:
        entity = document.entitydb.get(plan["handle"])
        if entity is None or not entity.is_alive or entity.dxftype() != "PLOTSETTINGS":
            raise DrawingCopyError("A qualified native print-settings record changed.")
        collector = TagCollector(optional=False)
        entity.export_dxf(collector)
        if _hash_tags([(tag.code, tag.value) for tag in collector.tags]) != plan["parsed_before_tags_sha256"]:
            raise DrawingCopyError("A qualified native print-settings record changed.")
        if (str(dictionary.dxf.handle) != plan["dictionary_handle"] or entries != plan["dictionary_entries_before"]
                or plan["setup_name"] in entries):
            raise DrawingCopyError("Qualified print-settings dictionary changed.")
    for plan in plans:
        entity = document.entitydb[plan["handle"]]
        entity.dxf.owner = plan["dictionary_handle"]
        entity.dxf.page_setup_name = plan["setup_name"]
        dictionary.add(plan["setup_name"], entity)
        collector = TagCollector(optional=False)
        entity.export_dxf(collector)
        if _hash_tags([(tag.code, tag.value) for tag in collector.tags]) != plan["parsed_after_tags_sha256"]:
            raise DrawingCopyError("Owned print-setting rehome changed an undeclared field.")
    if [str(entity.dxf.handle) for entity in document.objects if entity.dxftype() == "PLOTSETTINGS"] != order:
        raise DrawingCopyError("Owned print-setting rehome changed callback order.")
    check_native_plot_rehome(document, plans)


def check_native_plot_rehome(document, plans):
    if not plans:
        return
    dictionary = document.rootdict.get("ACAD_PLOTSETTINGS")
    expected = dict(plans[0]["dictionary_entries_before"])
    for plan in plans:
        expected[plan["setup_name"]] = plan["handle"]
    if (dictionary is None or dictionary.dxftype() != "DICTIONARY"
            or str(dictionary.dxf.handle) != plans[0]["dictionary_handle"]
            or dictionary.dxf.get("owner") != document.rootdict.dxf.handle
            or {str(key): str(value.dxf.handle) for key, value in dictionary.items()} != expected):
        raise DrawingCopyError("Owned print-setting rehome changed its declared dictionary entries.")
