"""Real DXF/image persistence and fail-closed filesystem copy tests; no CAD host."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import ezdxf
import pymupdf
import pytest

from librecad_pdf_importer import drawing_copy as copying


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def drawing(tmp_path):
    source_folder = tmp_path / "original"
    images = source_folder / "images"
    images.mkdir(parents=True)
    png = images / "original pixels.png"
    jpeg = images / "original color.jpeg"
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 12, 7), False)
    pixmap.clear_with(210)
    pixmap.set_pixel(2, 3, (12, 45, 220))
    png.write_bytes(pixmap.tobytes("png"))
    jpeg.write_bytes(pixmap.tobytes("jpeg"))
    doc = ezdxf.new("R2010")
    doc.units = 4
    doc.layers.new("Native edits", dxfattribs={"color": 3, "lineweight": 50})
    doc.styles.new("Native font", dxfattribs={"font": "unicode.lff", "width": 0.8})
    doc.modelspace().add_line((1, 2), (13, 9), dxfattribs={"layer": "Native edits"})
    doc.modelspace().add_text("Native edit: images/original pixels.png", dxfattribs={
        "insert": (7, 8), "height": 2.5, "rotation": 13, "style": "Native font",
    })
    first = doc.add_image_def("images/original pixels.png", size_in_pixel=(12, 7))
    second = doc.add_image_def("images/original color.jpeg", size_in_pixel=(12, 7))
    doc.modelspace().add_image(first, insert=(2, 3), size_in_units=(24, 14), rotation=17)
    block = doc.blocks.new("Native block")
    block.add_image(first, insert=(1, 1), size_in_units=(12, 7))
    doc.modelspace().add_blockref("Native block", (60, 10), dxfattribs={"rotation": 23})
    doc.layout().add_image(second, insert=(4, 4), size_in_units=(12, 7))
    # A definition with no IMAGE reference must not make the tool read unrelated data.
    orphan = doc.add_image_def("/unrelated/private/orphan.png", size_in_pixel=(10, 10))
    source = source_folder / "native edited drawing.dxf"
    doc.saveas(source)
    destination = tmp_path / "copies"
    destination.mkdir()
    original_files = {p: digest(p) for p in (source, png, jpeg)}
    return SimpleNamespace(source=source, png=png, jpeg=jpeg, destination=destination,
                           target=destination / "shared drawing.dxf", before=original_files,
                           orphan_handle=orphan.dxf.handle, root=tmp_path)


def normalized_paths(path):
    """Independent byte comparison normalizes only IMAGEDEF filename values."""
    lines = path.read_bytes().splitlines(keepends=True)
    record_type = None
    for index in range(0, len(lines), 2):
        code = int(lines[index])
        if code == 0:
            record_type = lines[index + 1].strip()
        if record_type == b"IMAGEDEF" and code == 1:
            lines[index + 1] = b"<image filename>\n"
    return b"".join(lines)


def assert_sources_unchanged(state):
    assert {path: digest(path) for path in state.before} == state.before


def assert_no_partial_copy(state):
    assert not state.target.exists()
    assert list(state.destination.iterdir()) == []
    assert_sources_unchanged(state)


def test_copy_preserves_native_edits_and_all_referenced_image_pixels(drawing, tmp_path):
    state = drawing
    result = copying.copy_drawing_with_images(state.source, state.target)
    assert result.image_files == 2 and result.image_references == 3
    assert result.source_sha256 == state.before[state.source]
    assert normalized_paths(state.source) == normalized_paths(result.drawing)
    copied = ezdxf.readfile(result.drawing)
    assert copied.units == 4 and copied.layers.get("Native edits").dxf.lineweight == 50
    assert copied.styles.get("Native font").dxf.width == 0.8
    assert list(copied.modelspace().query("TEXT"))[0].dxf.text.endswith("original pixels.png")
    assert copied.entitydb[state.orphan_handle].dxf.filename == "/unrelated/private/orphan.png"
    definitions, _ = copying._image_definitions(copied)
    expected = {digest(state.png), digest(state.jpeg)}
    for definition in definitions.values():
        reference = Path(definition.dxf.filename)
        assert not reference.is_absolute() and ".." not in reference.parts
        asset = result.drawing.parent / reference
        assert digest(asset) in expected
        assert copying._image_signature(asset)[:2] == (12, 7)
    assert_sources_unchanged(state)
    # A complete portable bundle remains usable without the original sources.
    relocated = tmp_path / "relocated"
    relocated.mkdir()
    shutil.copy2(result.drawing, relocated / result.drawing.name)
    shutil.copytree(result.image_folder, relocated / result.image_folder.name)
    for original in state.before:
        original.unlink()
    reopened = ezdxf.readfile(relocated / result.drawing.name)
    for definition in copying._image_definitions(reopened)[0].values():
        assert digest(relocated / definition.dxf.filename) in expected


def test_missing_relative_links_require_explicit_original_folder(drawing):
    state = drawing
    moved = state.destination / "native-save-as.dxf"
    shutil.copy2(state.source, moved)
    with pytest.raises(copying.ImageSourcesRequired) as error:
        copying.copy_drawing_with_images(moved, state.target)
    assert len(error.value.references) == 2 and not state.target.exists()
    result = copying.copy_drawing_with_images(moved, state.target,
                                             image_folder=state.source.parent)
    assert result.image_files == 2
    assert_sources_unchanged(state)


def test_explicit_image_folder_supports_old_relative_directory_prefix(drawing):
    state = drawing
    moved = state.destination / "native-save-as.dxf"
    shutil.copy2(state.source, moved)
    result = copying.copy_drawing_with_images(moved, state.target, image_folder=state.png.parent)
    assert result.image_files == 2


@pytest.mark.parametrize("kind", ["absolute", "traversal"])
def test_external_image_links_are_not_read_without_explicit_folder(drawing, monkeypatch, kind):
    state = drawing
    outside = state.root / "outside"
    outside.mkdir()
    image = outside / "chosen.png"
    shutil.copy2(state.png, image)
    document = ezdxf.readfile(state.source)
    definition = next(iter(copying._image_definitions(document)[0].values()))
    definition.dxf.filename = str(image) if kind == "absolute" else "../outside/chosen.png"
    document.saveas(state.source)
    state.before[state.source] = digest(state.source)
    real_signature = copying._image_signature
    read = []

    def checked(path):
        read.append(path)
        return real_signature(path)

    monkeypatch.setattr(copying, "_image_signature", checked)
    with pytest.raises(copying.ImageSourcesRequired):
        copying.copy_drawing_with_images(state.source, state.target)
    assert read == []
    result = copying.copy_drawing_with_images(state.source, state.target, image_folder=outside)
    assert result.image_files == 2 and image in read
    assert_sources_unchanged(state)


@pytest.mark.parametrize("existing", ["original", "drawing", "image_folder"])
def test_existing_data_is_never_overwritten(drawing, monkeypatch, existing):
    state = drawing
    target = state.target
    marker = None
    if existing == "original":
        target = state.source
    elif existing == "drawing":
        target.write_bytes(b"existing drawing")
        marker = target
    else:
        monkeypatch.setattr(copying.uuid, "uuid4", lambda: SimpleNamespace(hex="a" * 32))
        folder = state.destination / "shared_drawing_images_aaaaaaaaaaaa"
        folder.mkdir()
        marker = folder / "unrelated.txt"
        marker.write_bytes(b"existing data")
    before = marker.read_bytes() if marker else None
    with pytest.raises(copying.DrawingCopyError):
        copying.copy_drawing_with_images(state.source, target)
    if marker:
        assert marker.read_bytes() == before
    assert_sources_unchanged(state)


@pytest.mark.parametrize("fault", ["pixel_mismatch", "copy_bytes", "asset_publish", "drawing_publish"])
def test_failure_at_each_delivery_stage_removes_only_owned_partial_files(
    drawing, monkeypatch, fault,
):
    state = drawing
    real_signature = copying._image_signature
    real_hash = copying._hash_file
    real_publish = copying._publish_file
    corrupted = False

    def signature(path):
        result = real_signature(path)
        if fault == "pixel_mismatch" and ".drawing-copy-" in str(path):
            return (*result[:-1], "different pixels")
        return result

    def file_hash(path):
        nonlocal corrupted
        if fault == "copy_bytes" and ".drawing-copy-" in str(path) and path.suffix == ".png":
            if not corrupted:
                path.write_bytes(b"corrupt image copy")
                corrupted = True
        return real_hash(path)

    def publish(source, target):
        real_publish(source, target)
        if fault == "asset_publish" and target.suffix == ".png":
            raise OSError("asset publish failed after rename")
        if fault == "drawing_publish" and target == state.target:
            raise OSError("drawing publish failed after rename")

    monkeypatch.setattr(copying, "_image_signature", signature)
    monkeypatch.setattr(copying, "_hash_file", file_hash)
    monkeypatch.setattr(copying, "_publish_file", publish)
    with pytest.raises(copying.DrawingCopyError):
        copying.copy_drawing_with_images(state.source, state.target)
    assert_no_partial_copy(state)


def test_competing_destination_publication_is_preserved(drawing, monkeypatch):
    state = drawing
    real_publish = copying._publish_file

    def competing(source, target):
        if target == state.target:
            target.write_bytes(b"someone else's saved drawing")
        return real_publish(source, target)

    monkeypatch.setattr(copying, "_publish_file", competing)
    with pytest.raises(copying.DrawingCopyError):
        copying.copy_drawing_with_images(state.source, state.target)
    assert state.target.read_bytes() == b"someone else's saved drawing"
    assert list(state.destination.iterdir()) == [state.target]
    assert_sources_unchanged(state)


@pytest.mark.parametrize("when", ["before", "after_asset_publish"])
def test_cancellation_keeps_sources_and_removes_partial_copy(drawing, when):
    state = drawing

    def cancel():
        return when == "before" or bool(list(state.destination.glob("*_images_*/*.png")))

    with pytest.raises(copying.DrawingCopyCancelled):
        copying.copy_drawing_with_images(state.source, state.target, cancel_requested=cancel)
    assert_no_partial_copy(state)


def test_wrong_image_dimensions_do_not_create_a_finished_copy(drawing):
    state = drawing
    doc = ezdxf.readfile(state.source)
    next(iter(copying._image_definitions(doc)[0].values())).dxf.image_size = (99, 99)
    doc.saveas(state.source)
    state.before[state.source] = digest(state.source)
    with pytest.raises(copying.DrawingCopyError, match="dimensions"):
        copying.copy_drawing_with_images(state.source, state.target)
    assert_no_partial_copy(state)


def test_binary_drawing_without_images_is_copied_verbatim(tmp_path):
    source = tmp_path / "original.dxf"
    target = tmp_path / "copy.dxf"
    doc = ezdxf.new("R2010")
    doc.modelspace().add_line((1, 2), (8, 9))
    doc.saveas(source, fmt="bin")
    result = copying.copy_drawing_with_images(source, target)
    assert source.read_bytes() == target.read_bytes() and result.image_files == 0


def test_binary_image_drawing_has_actionable_ascii_copy_error(drawing):
    state = drawing
    document = ezdxf.readfile(state.source)
    document.saveas(state.source, fmt="bin")
    state.before[state.source] = digest(state.source)
    with pytest.raises(copying.DrawingCopyError, match="ASCII DXF"):
        copying.copy_drawing_with_images(state.source, state.target)
    assert_no_partial_copy(state)


def test_link_to_an_outside_folder_is_not_followed(drawing):
    state = drawing
    outside = state.root / "outside"
    outside.mkdir()
    shutil.copy2(state.png, outside / state.png.name)
    link = state.source.parent / "linked"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        pytest.skip("Creating directory links requires Windows developer mode or elevation.")
    doc = ezdxf.readfile(state.source)
    next(iter(copying._image_definitions(doc)[0].values())).dxf.filename = f"linked/{state.png.name}"
    doc.saveas(state.source)
    state.before[state.source] = digest(state.source)
    with pytest.raises(copying.ImageSourcesRequired):
        copying.copy_drawing_with_images(state.source, state.target)
    assert_no_partial_copy(state)


def test_transparent_png_pixels_and_encoded_bytes_survive_copy(drawing):
    state = drawing
    rgba = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 12, 7), True)
    rgba.clear_with(255)
    rgba.set_pixel(0, 0, (0, 0, 0, 0))
    rgba.set_pixel(1, 1, (10, 20, 30, 128))
    state.png.write_bytes(rgba.tobytes("png"))
    state.before[state.png] = digest(state.png)
    expected = copying._image_signature(state.png)
    result = copying.copy_drawing_with_images(state.source, state.target)
    copied = next(result.image_folder.glob("*.png"))
    assert digest(copied) == state.before[state.png]
    assert copying._image_signature(copied) == expected and expected[3] == 1
    assert_sources_unchanged(state)


@pytest.mark.parametrize("fault", ["permission", "partial_disk_write"])
def test_copy_io_failures_preserve_sources_and_cleanup_staging(drawing, monkeypatch, fault):
    state = drawing
    real_open = Path.open

    class FullDisk:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self.stream.__exit__(*exc)

        def fileno(self):
            return self.stream.fileno()

        def write(self, content):
            self.stream.write(content[:2])
            self.stream.flush()
            raise OSError("disk full after partial image write")

    def failing_open(path, mode="r", *args, **kwargs):
        if mode == "xb" and path.suffix == ".png":
            if fault == "permission":
                raise PermissionError("image copy denied")
            return FullDisk(real_open(path, mode, *args, **kwargs))
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    with pytest.raises(copying.DrawingCopyError, match="original was kept"):
        copying.copy_drawing_with_images(state.source, state.target)
    assert_no_partial_copy(state)


def test_image_changed_after_its_copy_is_rejected_before_publication(drawing, monkeypatch):
    state = drawing
    real_patch = copying._patch_paths

    def changed(*args, **kwargs):
        real_patch(*args, **kwargs)
        state.png.write_bytes(state.png.read_bytes() + b"a concurrent image edit")

    monkeypatch.setattr(copying, "_patch_paths", changed)
    with pytest.raises(copying.DrawingCopyError, match="source image changed"):
        copying.copy_drawing_with_images(state.source, state.target)
    assert not state.target.exists() and list(state.destination.iterdir()) == []
    assert digest(state.source) == state.before[state.source]


def test_missing_source_and_wrong_target_extension_are_actionable(drawing):
    state = drawing
    with pytest.raises(copying.DrawingCopyError, match="original was kept"):
        copying.copy_drawing_with_images(state.source.with_name("missing.dxf"), state.target)
    with pytest.raises(copying.DrawingCopyError, match="ending in .dxf"):
        copying.copy_drawing_with_images(state.source, state.target.with_suffix(".pdf"))
    assert_no_partial_copy(state)


def test_changed_reserved_asset_directory_is_preserved_and_never_receives_more_images(
    drawing, monkeypatch,
):
    state = drawing
    real_publish = copying._publish_file
    replacement = []
    moved = state.root / "externally-moved-owned-images"

    def replaced(source, target):
        real_publish(source, target)
        if target.suffix == ".png":
            folder = target.parent
            folder.rename(moved)
            folder.mkdir()
            replacement.append((folder, copying._directory_identity(folder)))

    monkeypatch.setattr(copying, "_publish_file", replaced)
    with pytest.raises(copying.DrawingCopyError, match="folder changed"):
        copying.copy_drawing_with_images(state.source, state.target)
    folder, identity = replacement[0]
    assert copying._directory_identity(folder) == identity and list(folder.iterdir()) == []
    assert not state.target.exists() and len(list(moved.iterdir())) == 1
    assert_sources_unchanged(state)


def test_cleanup_does_not_remove_a_replacement_staging_directory(drawing, monkeypatch):
    state = drawing
    real_hash = copying._hash_file
    replacement = []

    def replaced(path):
        result = real_hash(path)
        if path.suffix == ".dxf" and ".drawing-copy-" in str(path) and not replacement:
            stage = path.parent
            stage.rename(state.root / "externally-moved-staging")
            stage.mkdir()
            replacement.append((stage, copying._directory_identity(stage)))
            raise OSError("fault after staging folder was replaced")
        return result

    monkeypatch.setattr(copying, "_hash_file", replaced)
    with pytest.raises(copying.DrawingCopyError, match="fault after staging"):
        copying.copy_drawing_with_images(state.source, state.target)
    folder, identity = replacement[0]
    assert copying._directory_identity(folder) == identity and list(folder.iterdir()) == []
    assert not state.target.exists()
    assert_sources_unchanged(state)


@pytest.mark.parametrize("version", ["AC1015", "AC1024"])
def test_legacy_encoding_unicode_image_names_and_crlf_native_records_are_preserved(
    drawing, version,
):
    state = drawing
    renamed = state.png.with_name("pixels \u00e9.png")
    old_png = state.png
    old_png.rename(renamed)
    del state.before[old_png]
    state.png = renamed
    state.before[renamed] = digest(renamed)
    document = ezdxf.readfile(state.source)
    document.dxfversion = version
    for definition in copying._image_definitions(document)[0].values():
        if definition.dxf.filename.endswith("original pixels.png"):
            definition.dxf.filename = "images/pixels \u00e9.png"
    document.saveas(state.source)
    data = state.source.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    state.source.write_bytes(data)
    state.before[state.source] = digest(state.source)
    result = copying.copy_drawing_with_images(state.source, state.target)
    assert normalized_paths(state.source) == normalized_paths(result.drawing)
    assert ezdxf.readfile(result.drawing).dxfversion == version
    assert digest(next(result.image_folder.glob("*.png"))) == state.before[renamed]
    assert_sources_unchanged(state)
