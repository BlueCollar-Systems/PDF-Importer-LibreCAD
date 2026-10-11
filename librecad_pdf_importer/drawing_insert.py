"""Import a converted PDF into a new editable copy of a saved DXF drawing.

LibreCAD 2.2.1.5's plugin block-from-disk API leaves cloned entities pointing
at a destroyed temporary drawing.  This file-based route uses no host pointers.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Callable
import uuid

import ezdxf
from ezdxf import units, xref
from ezdxf.entities import DXFTagStorage
from ezdxf.lldxf.tagwriter import TagCollector
from ezdxf.lldxf.const import acad_maint_ver
from ezdxf.sections.headervars import HEADER_VAR_MAP

from .drawing_copy import (
    DrawingCopyCancelled, DrawingCopyError, ImageSourcesRequired,
    _directory_identity, _check_directory,
    _hash_file, _image_definitions, _ordinary_file, _resolve_image, copy_drawing_with_images,
)

BASE_FLAG = "--librecad-saved-drawing"
MAX_DEPTH = 32
PDF_TYPES = {"LINE", "POINT", "CIRCLE", "ARC", "ELLIPSE", "LWPOLYLINE", "POLYLINE",
             "VERTEX", "SEQEND", "SOLID", "TRACE", "HATCH", "SPLINE", "INSERT",
             "ATTRIB", "ATTDEF", "TEXT", "MTEXT", "IMAGE"}


@dataclass(frozen=True)
class DrawingInsertResult:
    drawing: Path
    image_folder: Path | None
    image_files: int
    base_sha256: str
    pdf_sha256: str
    base_units: int
    pdf_units: int
    insertion_scale: float
    block_name: str
    imported_entities: int
    dxf_version: str


class PinnedConversionWorkspace:
    """Bind a newly created PDF-only workspace for its whole conversion job."""
    def __init__(self, path, identity):
        self.path = Path(path)
        self.identity = identity
        self.handle = None
        self.kernel = None
        self.check()
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            create = self.kernel.CreateFileW
            create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            create.restype = wintypes.HANDLE
            # Share reads/writes but omit FILE_SHARE_DELETE. The owned folder
            # cannot be renamed/replaced while the converter writes reports/assets.
            handle = create(str(self.path), 1, 3, None, 3, 0x02000000, None)
            if handle == ctypes.c_void_p(-1).value:
                raise DrawingCopyError("The PDF-only import folder could not be pinned. Choose another output folder.")
            self.handle = handle
            self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.kernel.CloseHandle.restype = wintypes.BOOL
            try:
                self.check()
            except BaseException:
                self.close()
                raise

    def check(self):
        _check_directory(self.path, self.identity)

    def close(self):
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def saved_drawing_from_argv(argv) -> str | None:
    args = list(argv)
    for index, arg in enumerate(args):
        if arg == BASE_FLAG:
            if index + 1 >= len(args) or not args[index + 1].strip():
                raise DrawingCopyError("Choose a saved DXF drawing to import into.")
            return str(Path(args[index + 1]).expanduser().resolve())
        if arg.startswith(BASE_FLAG + "="):
            if not arg.split("=", 1)[1].strip():
                raise DrawingCopyError("Choose a saved DXF drawing to import into.")
            return str(Path(arg.split("=", 1)[1]).expanduser().resolve())
    return None


def validate_copy_destination(base, pdf_input, destination) -> Path:
    target = Path(destination).expanduser()
    if os.path.lexists(target):
        raise DrawingCopyError("The output already exists. Choose a new drawing copy filename.")
    target = target.resolve()
    if target in {Path(base).expanduser().resolve(), Path(pdf_input).expanduser().resolve()}:
        raise DrawingCopyError("The drawing copy must have a different filename from both inputs.")
    if target.suffix.lower() != ".dxf" or not target.parent.is_dir():
        raise DrawingCopyError("Choose a new .dxf filename in an existing folder.")
    _directory_identity(target.parent)
    return target


def _plain(value):
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in sorted(value.items())}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return [_plain(v) for v in value]


def _tags(entity):
    return [(t.code, _plain(t.value)) for t in TagCollector.dxftags(entity)]


def _base_state(document):
    """Existing entities/resources stay bound to their original handles and names."""
    table_owners = {}
    # The native writer uses its LAYER-table owner for VPORT/STYLE records.
    # ezdxf repairs these two proven membership aliases on serialization.
    # An arbitrary changed owner is still compared and rejected.
    native_alias = document.layers.head.dxf.handle
    for table in (document.viewports, document.styles):
        for record in table:
            if record.dxf.get("owner") in {native_alias, table.head.dxf.handle}:
                table_owners[str(record.dxf.handle)] = table.head.dxf.handle

    def serialized(entity):
        collector = TagCollector(optional=False)
        entity.export_dxf(collector)
        owner = table_owners.get(str(entity.dxf.handle))
        depth = 0
        tags = []
        for tag in collector.tags:
            code, value = tag.code, tag.value
            if code == 102:
                if isinstance(value, str) and value.startswith("{"):
                    depth += 1
                elif value == "}":
                    depth = max(0, depth - 1)
            if code == 330 and depth == 0 and owner is not None:
                value = owner
            tags.append((code, _plain(value)))
        return tags

    def orphan_insert_terminator(entity):
        if entity.dxftype() != "SEQEND":
            return False
        owner = document.entitydb.get(entity.dxf.get("owner", ""))
        # ezdxf creates an in-memory SEQEND even for an INSERT with no ATTRIBs;
        # it is intentionally never serialized. Attached sequences stay strict.
        return owner is not None and owner.dxftype() == "INSERT" and not owner.attribs
    return {str(e.dxf.handle): serialized(e) for e in document.entitydb.values()
            if e.is_alive and not orphan_insert_terminator(e) and e.dxftype() not in {"DICTIONARY", "DICTIONARYVAR",
                "ACDBDICTIONARYWDFLT", "TABLE", "ENDTAB"}}


def _check_base_state(document, expected):
    actual = _base_state(document)
    for handle, tags in expected.items():
        if actual.get(handle) != tags:
            raise DrawingCopyError("The merge changed an existing drawing entity or resource. "
                                   "The original was kept; open the converted PDF separately.")


def _dictionary_state(document):
    return {str(e.dxf.handle): {str(key): str(value.dxf.handle)
            for key, value in e.items()}
            for e in document.entitydb.values() if e.is_alive and e.dxftype() in {
                "DICTIONARY", "ACDBDICTIONARYWDFLT"}}


def _check_dictionaries(document, expected):
    actual = _dictionary_state(document)
    for handle, entries in expected.items():
        if handle not in actual or any(actual[handle].get(key) != value for key, value in entries.items()):
            raise DrawingCopyError("The merge changed an existing drawing dictionary or resource link.")


def _header_state(document):
    # Writer timestamps/handle allocation and the declared output DXF version
    # are housekeeping; dimensions, units, scale and all other existing settings stay strict.
    excluded = {"$HANDSEED", "$TDCREATE", "$TDUCREATE", "$TDUPDATE", "$TDUUPDATE", "$ACADVER", "$VERSIONGUID"}
    return {key: _plain(document.header.get(key)) for key in document.header.varnames()
            if key not in excluded}


def _check_headers(document, expected):
    actual = _header_state(document)
    # The writer synchronizes these cached bounds from the modelspace LAYOUT.
    # Existing LAYOUT and VPORT records remain separately protected, including
    # their bounds and view settings. Arbitrary header changes still fail.
    bounds = {"$EXTMIN": _plain(document.modelspace().dxf.extmin),
              "$EXTMAX": _plain(document.modelspace().dxf.extmax)}
    if any(actual.get(key) != value and not (
            key in bounds and actual.get(key) == bounds[key]) for key, value in expected.items()):
        raise DrawingCopyError("The merge changed an existing drawing unit, dimension or header setting.")


def _write_merged_drawing(document, stream):
    """Retain LibreCAD's native integer grid flags omitted by ezdxf 1.4.4."""
    flags = {key: document.header.get(key) for key in ("$GRIDMODE", "$SNAPSTYLE")
             if key in document.header.varnames() and key not in HEADER_VAR_MAP}
    if not flags:
        document.write(stream)
        return
    if any(not isinstance(value, int) for value in flags.values()):
        raise DrawingCopyError("The saved drawing has unsupported native grid settings. "
                               "Save a standard DXF copy first.")
    export = document.header.export_dxf
    injected = []

    class NativeHeaderWriter:
        def __init__(self, writer):
            self.writer = writer

        def __getattr__(self, name):
            return getattr(self.writer, name)

        def write_str(self, text):
            # The pinned HeaderSection exports this exact terminal tag pair.
            if text == "  0\nENDSEC\n":
                for key, value in flags.items():
                    self.writer.write_tag2(9, key)
                    self.writer.write_tag2(70, value)
                injected.append(True)
            self.writer.write_str(text)

    def native_export(writer):
        export(NativeHeaderWriter(writer))

    # Only this owned document is wrapped; restore its class method even if
    # writing fails. No shared/global writer or header definitions are changed.
    document.header.export_dxf = native_export
    try:
        document.write(stream)
        if injected != [True]:
            raise DrawingCopyError("The DXF writer could not retain the native grid settings.")
    finally:
        del document.header.export_dxf


def _input_image_hashes(path, image_folder=None):
    document = ezdxf.readfile(path)
    definitions, _ = _image_definitions(document)
    allowed_folder = Path(image_folder).resolve() if image_folder else None
    assets = {}
    for definition in definitions.values():
        image = _resolve_image(str(definition.dxf.filename), path.parent, allowed_folder)
        if image is None:
            # The ordinary copy helper supplies the actionable, grouped missing-image error.
            continue
        assets[image] = _hash_file(image)
    return assets


@contextmanager
def _merge_stage(parent):
    stage = Path(tempfile.mkdtemp(prefix=".pdf-drawing-copy-", dir=parent)).resolve()
    assert stage.parent == parent and stage.name.startswith(".pdf-drawing-copy-")
    identity = _directory_identity(stage)
    owned_files, owned_directories = {}, {stage: identity}
    try:
        yield stage, owned_files, owned_directories
    finally:
        _cleanup_owned_stage(stage, identity, owned_files, owned_directories)


def _cleanup_owned_stage(stage, identity, owned_files, owned_directories):
        # A renamed/replaced root is no longer ours. Never follow it or delete
        # a competing marker; displaced scratch may remain for manual inspection.
    try:
        _check_directory(stage, identity)
    except (OSError, DrawingCopyError):
        return
    for path, (file_identity, digest) in owned_files.items():
        try:
            _check_directory(stage, identity)
            _check_directory(path.parent, owned_directories[path.parent])
            _ordinary_file(path)
            info = path.lstat()
            if (info.st_dev, info.st_ino) != file_identity:
                continue
            if digest and _hash_file(path) != digest:
                continue
            path.unlink()
        except (OSError, DrawingCopyError, KeyError):
            pass
    for path, directory_identity in sorted(owned_directories.items(), key=lambda item: len(item[0].parts), reverse=True):
        try:
            _check_directory(stage, identity)
            _check_directory(path, directory_identity)
            path.rmdir()  # Non-empty directories contain something we do not own.
        except (OSError, DrawingCopyError):
            pass


def _check_owned_stage(stage, identity, owned_files, owned_directories):
    _check_directory(stage, identity)
    for path, (expected_identity, digest) in owned_files.items():
        _check_directory(path.parent, owned_directories[path.parent])
        _ordinary_file(path)
        info = path.lstat()
        if (info.st_dev, info.st_ino) != expected_identity or (digest and _hash_file(path) != digest):
            raise DrawingCopyError("A private staged drawing or image changed during the merge.")


def preflight_saved_drawing(base, *, image_folder=None, expanded_entity_budget=1_000_000):
    """Reject unusable saved bases before starting the potentially long PDF job."""
    path = Path(base).expanduser().resolve()
    _ordinary_file(path)
    doc = ezdxf.readfile(path)
    _check_document(doc, expanded_entity_budget=expanded_entity_budget)
    try:
        units.conversion_factor(4, doc.units)
    except (TypeError, ValueError, IndexError) as exc:
        raise DrawingCopyError("Set known drawing units in LibreCAD and save the base drawing first.") from exc
    if not doc.units:
        raise DrawingCopyError("Set known drawing units in LibreCAD and save the base drawing first.")
    if doc.dxfversion < "AC1021":
        raise DrawingCopyError("Save the base drawing as DXF 2007 or newer in LibreCAD first, "
                               "or import the PDF as a separate drawing.")
    definitions, _ = _image_definitions(doc)
    folder = Path(image_folder).resolve() if image_folder else None
    missing = [str(d.dxf.filename) for d in definitions.values()
               if _resolve_image(str(d.dxf.filename), path.parent, folder) is None]
    if missing:
        raise ImageSourcesRequired(list(dict.fromkeys(missing)))
    return _hash_file(path)


def _check_document(document, *, pdf=False, max_records=None, expanded_entity_budget=None):
    if max_records is not None and len(document.entitydb) > max_records:
        raise DrawingCopyError(f"This drawing exceeds the requested {max_records:,}-record "
                               "merge budget. Increase the budget or split the selected pages.")
    for entity in document.entitydb.values():
        if not entity.is_alive:
            continue
        if isinstance(entity, DXFTagStorage) or entity.dxftype() in {
            "ACAD_PROXY_ENTITY", "ACAD_PROXY_OBJECT", "ACAD_TABLE", "UNDERLAY",
            "PDFUNDERLAY", "DGNUNDERLAY", "DWFUNDERLAY", "3DSOLID", "BODY", "REGION",
        }:
            raise DrawingCopyError(f"This drawing contains unsupported {entity.dxftype()} "
                                   "data. Save a standard editable DXF copy first.")
        if pdf and hasattr(entity, "graphic_properties") and entity.dxftype() not in PDF_TYPES:
            raise DrawingCopyError(f"The PDF DXF contains unsupported {entity.dxftype()} data.")
    for block in document.blocks:
        if block.block.is_xref or block.block.is_xref_overlay:
            raise DrawingCopyError("Linked external drawings are not supported by saved-copy "
                                   "import. Bind the external drawing first.")
    heights, expanded = {}, {}
    depth_limit = MAX_DEPTH - (1 if pdf else 0)  # The imported PDF gains one outer block.
    def block_depth(name, ancestors):
        key = name.casefold()
        if key in ancestors or name not in document.blocks:
            raise DrawingCopyError("The drawing contains a cyclic or unresolved block reference.")
        if key not in heights:
            if len(ancestors) >= depth_limit:
                raise DrawingCopyError("Block nesting exceeds the saved-copy limit of 32. "
                                       "Simplify the nested blocks or open the PDF separately.")
            contents = list(document.blocks.get(name))
            children = [e.dxf.name for e in contents if e.dxftype() == "INSERT"]
            heights[key] = 1 + max((block_depth(child, ancestors | {key}) for child in children), default=0)
            expanded[key] = sum(
                expanded[e.dxf.name.casefold()] * max(1, int(e.dxf.get("column_count", 1)))
                * max(1, int(e.dxf.get("row_count", 1))) if e.dxftype() == "INSERT" else 1
                for e in contents)
        if len(ancestors) + heights[key] > depth_limit:
            raise DrawingCopyError("Block nesting exceeds the saved-copy limit of 32.")
        return heights[key]
    for block in document.blocks:
        block_depth(block.name, set())
    root_count = sum(
        expanded[e.dxf.name.casefold()] * max(1, int(e.dxf.get("column_count", 1)))
        * max(1, int(e.dxf.get("row_count", 1))) if e.dxftype() == "INSERT" else 1
        for e in document.modelspace())
    if expanded_entity_budget is not None and root_count > expanded_entity_budget:
        raise DrawingCopyError(f"This drawing would render {root_count:,} repeated entities. "
                               "Enable 'Allow very large merged drawings (may be slow)', "
                               "choose fewer pages, or open the PDF as a separate drawing.")
    return root_count


def _resolved_layer_reference(document, handle, expected_type, cache):
    """Compare referenced paint content, not drawing-local resource handles."""
    key = ("layer-reference", expected_type, str(handle))
    if key not in cache:
        resource = document.entitydb.get(str(handle))
        if resource is None or resource.dxftype() != expected_type:
            raise DrawingCopyError(f"The PDF drawing has an unresolved {expected_type} "
                                   "layer resource. Open the PDF separately.")
        # Serialized material tags include defaults and mapper matrices that
        # all_existing_dxf_attribs() omits in native-saved drawings. Loader
        # rebinds material handles, replaces Normal plotstyle placeholders and
        # namespaces custom material names. Keep every other paint value.
        tags = []
        in_reactors = False
        for code, value in _tags(resource):
            if code == 102 and value == "{ACAD_REACTORS":
                in_reactors = True
                continue
            if in_reactors:
                if code == 102 and value == "}":
                    in_reactors = False
                continue
            if code not in {5, 330}:
                tags.append((code, value))
        system_name = None
        if expected_type == "MATERIAL":
            name = resource.dxf.name.upper()
            if name in {"GLOBAL", "BYLAYER", "BYBLOCK"}:
                system_name = name
            tags = [(code, value) for code, value in tags if code != 1]
        cache[key] = [expected_type, system_name, tags]
    return cache[key]


def _semantic(entity, document, ancestors, depth, cache=None):
    """Compare geometry, resolved resources, fill boundaries, and nested content."""
    if depth > MAX_DEPTH:
        raise DrawingCopyError("Block nesting exceeds the saved-copy limit of 32.")
    attrs = dict(entity.dxf.all_existing_dxf_attribs())
    if cache is None:
        cache = {}
    for key in ("handle", "owner", "paperspace", "image_def_handle", "image_def_reactor_handle"):
        attrs.pop(key, None)
    typ = entity.dxftype()
    resources = {}
    for field, table in (("layer", document.layers), ("style", document.styles),
                         ("linetype", document.linetypes)):
        name = attrs.pop(field, None)
        if name is not None and name in table:
            resource = table.get(name)
            data = dict(resource.dxf.all_existing_dxf_attribs())
            for key in ("handle", "owner", "name"):
                data.pop(key, None)
            if field == "layer":
                for reference, expected_type in (("material_handle", "MATERIAL"),
                                                  ("plotstyle_handle", "ACDBPLACEHOLDER")):
                    handle = data.pop(reference, None)
                    if handle is not None:
                        data[reference] = _resolved_layer_reference(
                            document, handle, expected_type, cache)
            resources[field] = _plain(data)
            if field == "linetype":
                resources["linetype_pattern"] = [(t.code, _plain(t.value))
                    for t in resource.pattern_tags.tags]
        elif name is not None:
            resources[field] = name
    extra = []
    if typ == "INSERT":
        name = attrs.pop("name")
        if name.casefold() in ancestors or name not in document.blocks:
            raise DrawingCopyError("The drawing contains a cyclic or unresolved block reference.")
        block = document.blocks.get(name)
        if name not in cache:
            payload = [_semantic(child, document, ancestors | {name.casefold()}, depth + 1, cache)
                       for child in block.entities_in_redraw_order()]
            cache[name] = hashlib.sha256(json.dumps(payload, sort_keys=True,
                ensure_ascii=True, separators=(",", ":")).encode("ascii")).hexdigest()
        extra = [_plain(block.block.dxf.base_point),
                 cache[name],
                 [_semantic(a, document, ancestors, depth + 1, cache) for a in entity.attribs]]
    elif typ == "IMAGE":
        definition = document.entitydb.get(entity.dxf.image_def_handle)
        if definition is None or definition.dxftype() != "IMAGEDEF":
            raise DrawingCopyError("The drawing has an unresolved image definition.")
        # Both staged inputs use decoded, byte-checked image copies.
        path = Path(str(definition.dxf.filename))
        if not path.is_absolute():
            path = Path(document.filename).parent / path
        extra = [_hash_file(path), _plain(definition.dxf.image_size),
                 _plain(entity.boundary_path)]
    else:
        # Exported non-attribute payload includes HATCH rings, polyline vertices,
        # SPLINE controls/knots, and MTEXT text. Resource names/handles are compared above.
        excluded = {5, 330, 67, 8, 6, 7, 340, 360, 102}
        extra = [(code, value) for code, value in _tags(entity) if code not in excluded]
    return _plain([typ, attrs, resources, extra])


def _semantic_digest(entities, document):
    cache = {}
    return hashlib.sha256(json.dumps(
        [_semantic(e, document, set(), 0, cache) for e in entities],
        sort_keys=True, ensure_ascii=True, separators=(",", ":"),
    ).encode("ascii")).hexdigest()


def _preserve_redraw_order(source):
    # ezdxf 1.4.4's resource loader omits SORTENTSTABLE. Put every incoming
    # layout into its effective paint order before copying, including glyph
    # blocks. The target's physical entity order then carries the same order.
    for layout in [source.modelspace(), *list(source.blocks)]:
        layout.entity_space.entities[:] = list(layout.entities_in_redraw_order())


def _isolate_special_layers(document, prefix):
    # Loader deliberately keeps 0/DEFPOINTS; give source entities independent
    # layer records so an existing off/frozen Layer 0 cannot hide the new PDF.
    for name in ("0", "DEFPOINTS"):
        if name not in document.layers:
            continue
        old = document.layers.get(name)
        attrs = dict(old.dxf.all_existing_dxf_attribs())
        for key in ("handle", "owner", "name"):
            attrs.pop(key, None)
        new_name = prefix + "_" + name
        document.layers.new(new_name, dxfattribs=attrs)
        for entity in document.entitydb.values():
            if entity.is_alive and entity.dxf.hasattr("layer") and entity.dxf.layer.casefold() == name.casefold():
                entity.dxf.layer = new_name


def insert_into_saved_drawing_copy(
    base, pdf_dxf, destination, *, base_image_folder=None,
    cancel_requested: Callable[[], bool] | None = None, max_records: int | None = None,
    expanded_entity_budget: int | None = 1_000_000,
    expected_base_sha256: str | None = None,
) -> DrawingInsertResult:
    """Never replace an input or existing destination; publish images and DXF last."""
    target = validate_copy_destination(base, pdf_dxf, destination)
    base_path, pdf_path = Path(base).resolve(), Path(pdf_dxf).resolve()
    _ordinary_file(base_path)
    _ordinary_file(pdf_path)
    base_sha, pdf_sha = _hash_file(base_path), _hash_file(pdf_path)
    if expected_base_sha256 is not None and base_sha != expected_base_sha256:
        raise DrawingCopyError("The saved drawing changed during PDF conversion. Save your edits "
                               "and retry. The original and PDF-only conversion were kept.")
    input_images = {**_input_image_hashes(base_path, base_image_folder), **_input_image_hashes(pdf_path)}

    def cancelled():
        if cancel_requested and cancel_requested():
            raise DrawingCopyCancelled("Saved drawing copy import cancelled. The original was kept.")

    cancelled()
    with _merge_stage(target.parent) as (stage, owned_files, owned_directories):
        stage_identity = owned_directories[stage]
        def register(result):
            _check_directory(stage, stage_identity)
            for path, identity, digest in result._owned_files:
                owned_files[path] = (identity, digest)
            owned_directories.update(result._owned_directories)
        _check_directory(stage, stage_identity)
        copied_base = copy_drawing_with_images(base_path, stage / "base.dxf",
            image_folder=base_image_folder, cancel_requested=cancel_requested)
        register(copied_base)
        _check_directory(stage, stage_identity)
        copied_pdf = copy_drawing_with_images(pdf_path, stage / "pdf.dxf",
            cancel_requested=cancel_requested)
        register(copied_pdf)
        _check_owned_stage(stage, stage_identity, owned_files, owned_directories)
        document = ezdxf.readfile(copied_base.drawing)
        source = ezdxf.readfile(copied_pdf.drawing)
        base_count = _check_document(document, max_records=max_records, expanded_entity_budget=expanded_entity_budget)
        pdf_count = _check_document(source, pdf=True, max_records=max_records, expanded_entity_budget=expanded_entity_budget)
        if expanded_entity_budget is not None and base_count + pdf_count > expanded_entity_budget:
            raise DrawingCopyError("The combined drawing exceeds the selected render budget. "
                                   "Enable 'Allow very large merged drawings (may be slow)', "
                                   "choose fewer pages, or open the PDF separately.")
        base_units, pdf_units = int(document.units), int(source.units)
        try:
            scale = (1.0 / 25.4 if (pdf_units, base_units) == (4, 1) else
                     25.4 if (pdf_units, base_units) == (1, 4) else
                     units.conversion_factor(pdf_units, base_units))
        except (TypeError, ValueError) as exc:
            raise DrawingCopyError("The saved drawing needs known drawing units. Set its units "
                                   "in LibreCAD, save it, and try again.") from exc
        if not base_units or not pdf_units:
            raise DrawingCopyError("Set known drawing units in LibreCAD and save the base drawing first.")
        if document.dxfversion < "AC1021":
            raise DrawingCopyError("Save the base drawing as DXF 2007 or newer in LibreCAD first. "
                                   "The saved-copy route preserves fills and linked images.")
        if source.dxfversion > document.dxfversion:
            document.dxfversion = source.dxfversion
            # The writer uses the maintenance revision declared by the new
            # format; this is version metadata, not a unit/dimension setting.
            document.header["$ACADMAINTVER"] = acad_maint_ver[document.dxfversion]
        prefix = "BCPDF_" + uuid.uuid4().hex[:12].upper()
        _isolate_special_layers(source, prefix)
        _preserve_redraw_order(source)
        source_semantic = _semantic_digest(source.modelspace().entities_in_redraw_order(), source)
        source_counts = Counter(e.dxftype() for e in source.modelspace())
        base_state = _base_state(document)
        base_dictionaries = _dictionary_state(document)
        base_headers = _header_state(document)
        block_name = prefix + "_PDF"
        block = document.blocks.new(block_name)
        loader = xref.Loader(source, document, conflict_policy=xref.ConflictPolicy.XREF_PREFIX)
        loader.load_modelspace(target_layout=block)
        cancelled()
        loader.execute(xref_prefix=prefix)
        _check_base_state(document, base_state)
        _check_dictionaries(document, base_dictionaries)
        _check_headers(document, base_headers)
        if Counter(e.dxftype() for e in block) != source_counts or _semantic_digest(block.entities_in_redraw_order(), document) != source_semantic:
            raise DrawingCopyError("The resource loader could not preserve every PDF entity, "
                                   "block, layer, text style or fill. Open the converted PDF separately.")
        # Keep the imported block on a fresh visible layer independent of the base's active layer.
        import_layer = prefix + "_IMPORT"
        document.layers.new(import_layer)
        document.modelspace().add_blockref(block_name, (0, 0),
            dxfattribs={"layer": import_layer, "xscale": scale, "yscale": scale, "zscale": scale})
        merged = stage / "merged.dxf"
        _check_directory(stage, stage_identity)
        document.filename = str(merged)
        with merged.open("x", encoding=document.output_encoding) as stream:
            info = os.fstat(stream.fileno())
            file_identity = (info.st_dev, info.st_ino)
            owned_files[merged] = (file_identity, "")
            _write_merged_drawing(document, stream)
        owned_files[merged] = (file_identity, _hash_file(merged))
        _check_directory(stage, stage_identity)
        reopened = ezdxf.readfile(merged)
        _check_base_state(reopened, base_state)
        _check_dictionaries(reopened, base_dictionaries)
        _check_headers(reopened, base_headers)
        if reopened.units != base_units or _semantic_digest(reopened.blocks.get(block_name).entities_in_redraw_order(), reopened) != source_semantic:
            raise DrawingCopyError("Merged drawing readback changed its units or PDF geometry.")
        cancelled()
        if _hash_file(base_path) != base_sha or _hash_file(pdf_path) != pdf_sha:
            raise DrawingCopyError("An input drawing changed during import. The original was kept.")
        for image, expected in input_images.items():
            cancelled()
            _ordinary_file(image)
            if _hash_file(image) != expected:
                raise DrawingCopyError("An original linked image changed during import. Try again.")
        _check_owned_stage(stage, stage_identity, owned_files, owned_directories)
        published = copy_drawing_with_images(merged, target, cancel_requested=cancel_requested)
        return DrawingInsertResult(published.drawing, published.image_folder, published.image_files,
            base_sha, pdf_sha, base_units, pdf_units, float(scale), block_name,
            sum(source_counts.values()), reopened.dxfversion)
