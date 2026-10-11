"""Copy an existing DXF and its linked images without rewriting native edits."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import tempfile
from typing import Callable
import uuid

import ezdxf
import pymupdf


class DrawingCopyError(RuntimeError):
    """A drawing cannot be copied safely; the original is never changed."""


class ImageSourcesRequired(DrawingCopyError):
    """The operator must explicitly choose a folder for unresolved image links."""

    def __init__(self, references: list[str]):
        self.references = references
        super().__init__(
            "Some linked images are missing or outside the selected drawing's folder. "
            "Choose the folder containing the original drawing or its image files.\n\n"
            + "\n".join(references)
        )


class DrawingCopyCancelled(DrawingCopyError):
    """A requested stop leaves the original and any existing destination unchanged."""


@dataclass(frozen=True)
class DrawingCopyResult:
    drawing: Path
    image_folder: Path | None
    image_files: int
    image_references: int
    source_sha256: str


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    current = path.stat()
    signatures = [(s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
                  for s in (before, after, current)]
    if signatures[0] != signatures[1] or signatures[0] != signatures[2]:
        raise DrawingCopyError(f"A source file changed while it was read: {path}")
    return digest.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _ordinary_file(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise DrawingCopyError(f"Not an ordinary drawing/image file: {path}")


def _directory_identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise DrawingCopyError(f"Not an ordinary copy folder: {path}")
    return info.st_dev, info.st_ino


def _check_directory(path: Path, expected: tuple[int, int]) -> None:
    if _directory_identity(path) != expected:
        raise DrawingCopyError(f"The copy folder changed during the operation: {path}")


def _image_signature(path: Path) -> tuple:
    try:
        image = pymupdf.Pixmap(str(path))
    except Exception as exc:  # noqa: BLE001 - decoder errors are user-facing copy failures
        raise DrawingCopyError(f"Linked image cannot be decoded: {path}: {exc}") from exc
    if image.width <= 0 or image.height <= 0:
        raise DrawingCopyError(f"Image has no usable pixels: {path}")
    return (image.width, image.height, image.n, image.alpha, image.stride,
            hashlib.sha256(image.samples_mv).hexdigest())


def _resolve_image(reference: str, drawing_folder: Path, image_folder: Path | None) -> Path | None:
    if not reference or "\0" in reference:
        return None
    raw = Path(reference.replace("\\", "/"))
    windows_absolute = bool(PureWindowsPath(reference).drive)
    roots = [drawing_folder] + ([image_folder] if image_folder is not None else [])
    if raw.is_absolute() or windows_absolute:
        candidates = [raw] if raw.is_absolute() or os.name == "nt" else []
    else:
        candidates = [root / raw for root in roots]
    # Picking an actual image folder also supports a drawing whose old relative
    # prefix names the original asset directory. There is no recursive search.
    if image_folder is not None:
        candidates.append(image_folder / raw.name)
    for candidate in candidates:
        resolved = candidate.resolve()
        if any(_inside(resolved, root) for root in roots) and resolved.is_file():
            _ordinary_file(resolved)
            return resolved
    return None


def _image_definitions(document) -> tuple[dict, list[tuple]]:
    definitions = {}
    images = []
    for entity in document.entitydb.values():
        if entity.is_alive and entity.dxftype() == "IMAGE":
            handle = str(entity.dxf.image_def_handle)
            definition = document.entitydb.get(handle)
            if definition is None or definition.dxftype() != "IMAGEDEF":
                raise DrawingCopyError(f"Drawing has an unresolved IMAGE definition: {handle}")
            definitions[handle.upper()] = definition
            images.append((str(entity.dxf.handle), entity.dxf.all_existing_dxf_attribs()))
    return definitions, images


def _patch_paths(source: Path, copied, replacements: dict[str, str], expected_sha: str,
                 check_cancel: Callable[[], None]) -> None:
    """Change only each referenced IMAGEDEF's group-1 filename line.

    Every other byte, including all geometry, layers, styles, units and native
    edits, is copied verbatim. This avoids an exporter normalizing the drawing.
    """
    digest = hashlib.sha256()
    seen = set()
    with source.open("rb") as original:
        if original.read(22).startswith(b"AutoCAD Binary DXF") and replacements:
            raise DrawingCopyError("Linked images in binary DXF need an ASCII DXF copy. "
                                   "Save the drawing as ASCII DXF in LibreCAD, then copy it.")
        original.seek(0)
        record = []

        def write_record():
            check_cancel()
            if record and record[0][0] == 0 and record[0][2].strip() == b"IMAGEDEF":
                handles = [value.strip().decode("ascii").upper()
                           for code, _, value in record if code == 5]
                matching = [handle for handle in handles if handle in replacements]
                if matching:
                    handle = matching[0]
                    if len(handles) != 1 or len(matching) != 1 or handle in seen:
                        raise DrawingCopyError("Ambiguous IMAGEDEF handles in the drawing.")
                    slots = [index for index, item in enumerate(record) if item[0] == 1]
                    if len(slots) != 1:
                        raise DrawingCopyError("Ambiguous IMAGEDEF filenames in the drawing.")
                    index = slots[0]
                    code, code_line, value = record[index]
                    newline = value[len(value.rstrip(b"\r\n")):]
                    record[index] = (code, code_line, replacements[handle].encode("ascii") + newline)
                    seen.add(handle)
            for _, code_line, value in record:
                copied.write(code_line)
                copied.write(value)

        if not replacements:
            while chunk := original.read(1024 * 1024):
                check_cancel()
                digest.update(chunk)
                copied.write(chunk)
        else:
            while code_line := original.readline():
                value = original.readline()
                digest.update(code_line)
                digest.update(value)
                if not value:
                    raise DrawingCopyError("The ASCII DXF has an incomplete tag.")
                try:
                    code = int(code_line.strip())
                except ValueError as exc:
                    raise DrawingCopyError("The ASCII DXF has an invalid group code.") from exc
                if code == 0:
                    write_record()
                    record = []
                record.append((code, code_line, value))
            write_record()
    if digest.hexdigest() != expected_sha or seen != set(replacements):
        raise DrawingCopyError("The drawing changed or its image links could not be bound exactly.")


def _publish_file(staged: Path, destination: Path) -> None:
    # Windows rename is atomic and refuses an existing destination; POSIX
    # hard-link publication provides the same no-overwrite contract.
    if os.name == "nt":
        os.rename(staged, destination)
    else:
        os.link(staged, destination)
        staged.unlink()


def _copy_drawing_with_images(
    source: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    image_folder: str | os.PathLike[str] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> DrawingCopyResult:
    """Copy only explicitly selected drawing/image sources; publish the DXF last."""
    original = Path(source).expanduser().resolve()
    selected_target = Path(destination).expanduser()
    if os.path.lexists(selected_target):
        raise DrawingCopyError("The destination already exists. Choose a new drawing filename.")
    target = selected_target.resolve()
    if target == original:
        raise DrawingCopyError("Choose a copy filename different from the original drawing.")
    if target.suffix.lower() != ".dxf":
        raise DrawingCopyError("Choose a destination filename ending in .dxf.")
    if not target.parent.is_dir():
        raise DrawingCopyError("The destination folder does not exist.")
    parent_identity = _directory_identity(target.parent)
    _ordinary_file(original)
    explicit_folder = Path(image_folder).expanduser().resolve() if image_folder else None
    if explicit_folder is not None and not explicit_folder.is_dir():
        raise DrawingCopyError("The selected original image folder does not exist.")

    def check_cancel():
        if cancel_requested and cancel_requested():
            raise DrawingCopyCancelled("Drawing copy cancelled. The original was kept.")

    check_cancel()
    source_sha = _hash_file(original)
    document = ezdxf.readfile(original)
    definitions, images = _image_definitions(document)
    resolved = {}
    missing = []
    for handle, definition in definitions.items():
        reference = str(definition.dxf.filename)
        path = _resolve_image(reference, original.parent, explicit_folder)
        if path is None:
            missing.append(reference)
        else:
            resolved[handle] = path
    if missing:
        raise ImageSourcesRequired(list(dict.fromkeys(missing)))
    if _hash_file(original) != source_sha:
        raise DrawingCopyError("The selected drawing changed while its links were read.")

    token = uuid.uuid4().hex[:12]
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", target.stem)[:50] or "drawing"
    asset_name = f"{stem}_images_{token}"
    final_assets = target.parent / asset_name
    if resolved and os.path.lexists(final_assets):
        raise DrawingCopyError("The destination image folder already exists. Choose another copy.")
    stage = Path(tempfile.mkdtemp(prefix=".drawing-copy-", dir=target.parent))
    owned_files: dict[Path, tuple[tuple[int, int], str]] = {}
    owned_directories = {stage: _directory_identity(stage)}
    completed = False
    try:
        paths = list(dict.fromkeys(resolved.values()))
        filenames = {}
        signatures = {}
        source_hashes = {}
        if paths:
            _check_directory(stage, owned_directories[stage])
            (stage / asset_name).mkdir()
            owned_directories[stage / asset_name] = _directory_identity(stage / asset_name)
        for index, path in enumerate(paths, 1):
            check_cancel()
            signature = _image_signature(path)
            digest = _hash_file(path)
            suffix = path.suffix.lower()
            if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
                suffix = ".img"
            filename = f"image-{index:04d}{suffix}"
            copied = stage / asset_name / filename
            _check_directory(stage, owned_directories[stage])
            _check_directory(copied.parent, owned_directories[copied.parent])
            # Register the exact owned file even if writing it stops midway.
            with path.open("rb") as incoming, copied.open("xb") as outgoing:
                info = os.fstat(outgoing.fileno())
                owned_files[copied] = ((info.st_dev, info.st_ino), "")
                while chunk := incoming.read(1024 * 1024):
                    check_cancel()
                    outgoing.write(chunk)
            identity = owned_files[copied][0]
            owned_files[copied] = (identity, _hash_file(copied))
            if owned_files[copied][1] != digest or _hash_file(path) != digest:
                raise DrawingCopyError(f"An image changed while it was copied: {path}")
            if _image_signature(copied) != signature:
                raise DrawingCopyError(f"Copied image pixels do not match the original: {path}")
            filenames[path] = filename
            signatures[path] = signature
            source_hashes[path] = digest
        replacements = {handle: f"{asset_name}/{filenames[path]}"
                        for handle, path in resolved.items()}
        staged_dxf = stage / target.name
        _check_directory(stage, owned_directories[stage])
        with staged_dxf.open("xb") as outgoing:
            info = os.fstat(outgoing.fileno())
            identity = (info.st_dev, info.st_ino)
            owned_files[staged_dxf] = (identity, "")
            _patch_paths(original, outgoing, replacements, source_sha, check_cancel)
        owned_files[staged_dxf] = (identity, _hash_file(staged_dxf))
        reopened = ezdxf.readfile(staged_dxf)
        new_definitions, new_images = _image_definitions(reopened)
        if images != new_images or definitions.keys() != new_definitions.keys():
            raise DrawingCopyError("Copy readback changed the drawing's IMAGE geometry or identity.")
        for handle, definition in new_definitions.items():
            before = definitions[handle].dxf.all_existing_dxf_attribs()
            after = definition.dxf.all_existing_dxf_attribs()
            before.pop("filename", None)
            after.pop("filename", None)
            if before != after or definition.dxf.filename != replacements[handle]:
                raise DrawingCopyError("Copy readback changed an image definition.")
            path = resolved[handle]
            size = tuple(map(float, tuple(definition.dxf.image_size)[:2]))
            if size != tuple(map(float, signatures[path][:2])):
                raise DrawingCopyError(f"Linked image dimensions do not match its definition: {path}")
        check_cancel()
        if _hash_file(original) != source_sha:
            raise DrawingCopyError("The original drawing changed before the copy was completed.")
        for path, expected in source_hashes.items():
            check_cancel()
            _ordinary_file(path)
            if _hash_file(path) != expected:
                raise DrawingCopyError(f"A source image changed before publication: {path}")
        # Reserve the image directory atomically; even an empty existing folder
        # is never replaced. Each image and finally the DXF is published without overwrite.
        if paths:
            _check_directory(target.parent, parent_identity)
            final_assets.mkdir()
            owned_directories[final_assets] = _directory_identity(final_assets)
            for path in paths:
                check_cancel()
                old = stage / asset_name / filenames[path]
                new = final_assets / filenames[path]
                _check_directory(target.parent, parent_identity)
                _check_directory(old.parent, owned_directories[old.parent])
                _check_directory(final_assets, owned_directories[final_assets])
                owned_files[new] = owned_files[old]
                _publish_file(old, new)
                owned_files.pop(old)
            _check_directory(final_assets, owned_directories[final_assets])
            for path in paths:
                copied = final_assets / filenames[path]
                if _hash_file(copied) != source_hashes[path] or _image_signature(copied) != signatures[path]:
                    raise DrawingCopyError("Published image bytes or pixels changed before the DXF copy.")
        check_cancel()
        _check_directory(target.parent, parent_identity)
        _check_directory(stage, owned_directories[stage])
        if paths:
            _check_directory(final_assets, owned_directories[final_assets])
        owned_files[target] = owned_files[staged_dxf]
        _publish_file(staged_dxf, target)
        owned_files.pop(staged_dxf)
        completed = True
        return DrawingCopyResult(target, final_assets if paths else None, len(paths), len(images),
                                 source_sha)
    except (DrawingCopyError, OSError, ValueError, ezdxf.DXFError) as exc:
        if isinstance(exc, DrawingCopyError):
            raise
        raise DrawingCopyError(f"Could not copy the drawing: {exc}. The original was kept.") from exc
    finally:
        # Delete only exact files created by this operation, never recursively
        # deleting a directory or following an unrelated image link.
        for path, (identity, digest) in owned_files.items():
            if completed and not _inside(path, stage):
                continue
            try:
                _ordinary_file(path)
                info = path.lstat()
                if (info.st_dev, info.st_ino) != identity:
                    continue  # A competing publication owns this path.
                if digest and _hash_file(path) != digest:
                    continue  # An outside actor changed it; do not remove their data.
                path.unlink()
            except (OSError, DrawingCopyError):
                pass
        for path, identity in reversed(list(owned_directories.items())):
            if completed and path == final_assets:
                continue
            try:
                _check_directory(path, identity)
                path.rmdir()
            except (OSError, DrawingCopyError):
                pass  # Unknown/new files in a reserved folder are never removed.


def copy_drawing_with_images(
    source: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    image_folder: str | os.PathLike[str] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> DrawingCopyResult:
    """Copy a drawing and its images, with actionable errors and no source writes."""
    try:
        return _copy_drawing_with_images(source, destination, image_folder=image_folder,
                                        cancel_requested=cancel_requested)
    except DrawingCopyError:
        raise
    except (OSError, ValueError, ezdxf.DXFError) as exc:
        raise DrawingCopyError(f"Could not copy the drawing: {exc}. The original was kept.") from exc
