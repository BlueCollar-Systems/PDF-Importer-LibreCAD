from pathlib import Path
import hashlib

import ezdxf
import pytest
from PIL import Image

from librecad_pdf_importer.drawing_copy import DrawingCopyError, DrawingCopyCancelled
from librecad_pdf_importer.drawing_insert import (
    insert_into_saved_drawing_copy, saved_drawing_from_argv, validate_copy_destination,
    PinnedConversionWorkspace,
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def drawing(path, unit, length):
    doc = ezdxf.new("R2010")
    doc.units = unit
    doc.modelspace().add_line((0, 0), (length, 0))
    doc.saveas(path)
    return doc


@pytest.mark.parametrize("base_unit,base_length,expected", [(4, 100, 25.4), (1, 4, 1), (6, .1, .0254)])
def test_real_units_and_original_geometry(tmp_path, base_unit, base_length, expected):
    base, pdf, out = [tmp_path / n for n in ("base.dxf", "pdf.dxf", "copy.dxf")]
    drawing(base, base_unit, base_length)
    drawing(pdf, 4, 25.4)
    before = digest(base), digest(pdf)
    result = insert_into_saved_drawing_copy(base, pdf, out)
    reopened = ezdxf.readfile(out)
    assert reopened.units == base_unit
    assert next(iter(reopened.modelspace().query("LINE"))).dxf.end.x == base_length
    inserted = next(iter(reopened.modelspace().query("INSERT")))
    leaf = next(iter(inserted.virtual_entities()))
    assert leaf.dxf.end.x == pytest.approx(expected)
    assert result.insertion_scale == pytest.approx(expected / 25.4)
    assert (digest(base), digest(pdf)) == before


def test_conflicting_nested_resources_hidden_text_and_order(tmp_path):
    base, pdf, out = [tmp_path / n for n in ("base.dxf", "pdf.dxf", "copy.dxf")]
    b = drawing(base, 1, 4)
    b.layers.get("0").off()
    b.layers.new("SEARCH", dxfattribs={"flags": 1, "color": 3})
    b.styles.new("Shared", dxfattribs={"font": "base-font.ttf"})
    b.linetypes.new("SharedDash", dxfattribs={"pattern": [.6, .3, -.3]})
    old = b.blocks.new("GLYPH")
    old.add_line((0, 0), (999, 0))
    b.modelspace().add_blockref("GLYPH", (0, 20))
    b.modelspace().add_text("BASE hidden", dxfattribs={"layer": "SEARCH", "style": "Shared"})
    b.saveas(base)
    p = drawing(pdf, 4, 25.4)
    p.layers.new("SEARCH", dxfattribs={"flags": 1, "color": 5})
    p.styles.new("Shared", dxfattribs={"font": "pdf-font.ttf"})
    p.linetypes.new("SharedDash", dxfattribs={"pattern": [3, 1.5, -1.5]})
    glyph = p.blocks.new("GLYPH")
    curves = [glyph.add_line((0, 0), (n, 0), dxfattribs={"linetype": "SharedDash"}) for n in (11, 22, 33)]
    glyph.set_redraw_order([(curves[2].dxf.handle, "1"), (curves[0].dxf.handle, "2"), (curves[1].dxf.handle, "3")])
    ref = p.modelspace().add_blockref("GLYPH", (0, 20))
    txt = p.modelspace().add_text("PDF hidden", dxfattribs={"layer": "SEARCH", "style": "Shared"})
    line = p.modelspace().query("LINE").first
    p.modelspace().set_redraw_order([(txt.dxf.handle, "1"), (ref.dxf.handle, "2"), (line.dxf.handle, "3")])
    p.saveas(pdf)
    result = insert_into_saved_drawing_copy(base, pdf, out)
    doc = ezdxf.readfile(out)
    assert doc.layers.get("0").is_off()
    assert doc.layers.get("SEARCH").dxf.color == 3 and doc.layers.get("SEARCH").is_frozen()
    assert doc.styles.get("Shared").dxf.font == "base-font.ttf"
    assert doc.blocks.get("GLYPH")[0].dxf.end.x == 999
    new = doc.blocks.get(result.block_name)
    assert [e.dxftype() for e in new.entities_in_redraw_order()] == ["TEXT", "INSERT", "LINE"]
    hidden = new.query("TEXT").first
    assert hidden.dxf.text == "PDF hidden" and doc.layers.get(hidden.dxf.layer).is_frozen()
    assert doc.styles.get(hidden.dxf.style).dxf.font == "pdf-font.ttf"
    nested = doc.blocks.get(new.query("INSERT").first.dxf.name)
    assert [e.dxf.end.x for e in nested.entities_in_redraw_order()] == [33, 11, 22]
    imported = doc.modelspace().query("INSERT")[-1]
    assert not doc.layers.get(imported.dxf.layer).is_off()


def test_both_image_sets_survive_file_relocation(tmp_path):
    source = tmp_path / "inputs"
    target = tmp_path / "delivery"
    source.mkdir(); target.mkdir()
    base, pdf = source / "base.dxf", source / "pdf.dxf"
    red, blue = source / "red.png", source / "blue.png"
    Image.new("RGB", (5, 7), (255, 0, 0)).save(red)
    Image.new("RGB", (11, 13), (0, 0, 255)).save(blue)
    for path, image, size in ((base, red, (5, 7)), (pdf, blue, (11, 13))):
        doc = drawing(path, 4, 10)
        definition = doc.add_image_def(filename=image.name, size_in_pixel=size, name="same-image")
        img = doc.modelspace().add_image(definition, insert=(2, 3), size_in_units=(10, 14), rotation=22)
        img.set_boundary_path([(0, 0), (2, 0), (2, 4), (0, 4)])
        doc.saveas(path)
    hashes = digest(base), digest(pdf), digest(red), digest(blue)
    result = insert_into_saved_drawing_copy(base, pdf, target / "copy.dxf")
    doc = ezdxf.readfile(result.drawing)
    images = [e for e in doc.entitydb.values() if e.is_alive and e.dxftype() == "IMAGE"]
    assert len(images) == 2
    pixels = set()
    for img in images:
        definition = doc.entitydb.get(img.dxf.image_def_handle)
        linked = result.drawing.parent / definition.dxf.filename
        assert linked.is_file() and not Path(definition.dxf.filename).is_absolute()
        pixels.add(Image.open(linked).convert("RGB").getpixel((0, 0)))
        assert len(img.boundary_path) == 5
    assert pixels == {(255, 0, 0), (0, 0, 255)}
    assert (digest(base), digest(pdf), digest(red), digest(blue)) == hashes


@pytest.mark.parametrize("unit,version", [(0, "R2010"), (4, "R12")])
def test_unknown_units_and_older_base_fail_without_publication(tmp_path, unit, version):
    base, pdf, out = [tmp_path / n for n in ("base.dxf", "pdf.dxf", "copy.dxf")]
    doc = ezdxf.new(version); doc.units = unit; doc.modelspace().add_line((0, 0), (1, 0)); doc.saveas(base)
    drawing(pdf, 4, 1)
    before = digest(base), digest(pdf)
    with pytest.raises(DrawingCopyError):
        insert_into_saved_drawing_copy(base, pdf, out)
    assert not out.exists() and (digest(base), digest(pdf)) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["base.dxf", "pdf.dxf"]


def test_cancel_and_existing_target_keep_all_inputs(tmp_path):
    base, pdf, out = [tmp_path / n for n in ("base.dxf", "pdf.dxf", "copy.dxf")]
    drawing(base, 4, 10); drawing(pdf, 4, 20)
    before = digest(base), digest(pdf)
    with pytest.raises(DrawingCopyCancelled):
        insert_into_saved_drawing_copy(base, pdf, out, cancel_requested=lambda: True)
    out.write_bytes(b"existing native edits")
    with pytest.raises(DrawingCopyError, match="already exists"):
        insert_into_saved_drawing_copy(base, pdf, out)
    assert out.read_bytes() == b"existing native edits" and (digest(base), digest(pdf)) == before


def test_flags_accept_unicode_paths_and_refuse_missing_base():
    assert saved_drawing_from_argv(["--librecad-saved-drawing", "fictional é drawing.dxf"]).endswith("fictional é drawing.dxf")
    assert saved_drawing_from_argv(["--librecad-handoff", "other.json"]) is None
    with pytest.raises(DrawingCopyError):
        saved_drawing_from_argv(["--librecad-saved-drawing"])


def test_high_reuse_dag_is_guarded_without_expanding_leaves(tmp_path):
    base, pdf, out = [tmp_path / n for n in ("base.dxf", "pdf.dxf", "copy.dxf")]
    drawing(base, 4, 100)
    source = ezdxf.new("R2010"); source.units = 4
    source.blocks.new("LEVEL0").add_line((0, 0), (1, 0))
    for level in range(1, 30):
        block = source.blocks.new(f"LEVEL{level}")
        block.add_blockref(f"LEVEL{level-1}", (0, 0))
        block.add_blockref(f"LEVEL{level-1}", (0, 0))
    source.modelspace().add_blockref("LEVEL29", (0, 0))
    source.saveas(pdf)
    with pytest.raises(DrawingCopyError, match="536,870,912 repeated entities"):
        insert_into_saved_drawing_copy(base, pdf, out)
    assert not out.exists()
    # Explicit opt-in tests the linear digest path; it never asks a native host to render this.
    result = insert_into_saved_drawing_copy(base, pdf, out, expanded_entity_budget=None)
    assert result.imported_entities == 1
    assert len(ezdxf.readfile(out).blocks) < 40


def test_native_dimensions_paperspace_headers_and_base_draw_order(tmp_path):
    base, pdf, out = [tmp_path / n for n in ("base.dxf", "pdf.dxf", "copy.dxf")]
    doc = drawing(base, 1, 4)
    doc.header["$MEASUREMENT"] = 0
    doc.header["$DIMTXT"] = .125
    line1 = doc.modelspace().query("LINE").first
    line2 = doc.modelspace().add_line((0, 2), (4, 2))
    doc.modelspace().set_redraw_order([(line2.dxf.handle, "1"), (line1.dxf.handle, "2")])
    dim = doc.modelspace().add_linear_dim(base=(0, 1), p1=(0, 0), p2=(4, 0),
        dimstyle="Standard", override={"dimtxt": .1})
    dim.render()
    paper = doc.layouts.new("FICTIONAL_SHEET")
    paper.add_text("BASE sheet", dxfattribs={"height": .25})
    doc.saveas(base)
    drawing(pdf, 4, 25.4)
    original = ezdxf.readfile(base)
    result = insert_into_saved_drawing_copy(base, pdf, out)
    actual = ezdxf.readfile(result.drawing)
    assert actual.header["$MEASUREMENT"] == 0 and actual.header["$DIMTXT"] == .125
    assert actual.layouts.get("FICTIONAL_SHEET").query("TEXT").first.dxf.text == "BASE sheet"
    assert [e.dxf.start.y for e in actual.modelspace().entities_in_redraw_order() if e.dxftype()=="LINE"] == [2, 0]
    old_dim = original.modelspace().query("DIMENSION").first
    new_dim = actual.modelspace().query("DIMENSION").first
    assert old_dim.dxf.all_existing_dxf_attribs() == new_dim.dxf.all_existing_dxf_attribs()


def test_r2007_base_upgrades_only_format_metadata(tmp_path):
    base, pdf, out = [tmp_path / n for n in ("base.dxf", "pdf.dxf", "copy.dxf")]
    doc = ezdxf.new("R2007"); doc.units = 1
    doc.header["$MEASUREMENT"] = 0; doc.header["$DIMTXT"] = .125
    doc.modelspace().add_line((0, 0), (4, 0)); doc.saveas(base)
    drawing(pdf, 4, 25.4)
    original = digest(base)
    result = insert_into_saved_drawing_copy(base, pdf, out)
    actual = ezdxf.readfile(result.drawing)
    assert actual.dxfversion == "AC1024" and actual.header["$ACADMAINTVER"] == 6
    assert actual.units == 1 and actual.header["$MEASUREMENT"] == 0 and actual.header["$DIMTXT"] == .125
    assert digest(base) == original


def test_stage_replacement_is_never_recursively_removed(tmp_path, monkeypatch):
    from librecad_pdf_importer import drawing_insert as module
    base, pdf, out = [tmp_path / n for n in ("base.dxf", "pdf.dxf", "copy.dxf")]
    drawing(base, 4, 10); drawing(pdf, 4, 20)
    displaced = tmp_path / "displaced-stage"
    replacement = []
    def swap_and_fail(source, destination, **kwargs):
        stage = Path(destination).parent
        stage.rename(displaced)
        stage.mkdir()
        marker = stage / "foreign-marker.txt"
        marker.write_text("foreign preserved")
        replacement.append(marker)
        raise DrawingCopyError("injected copy fault")
    monkeypatch.setattr(module, "copy_drawing_with_images", swap_and_fail)
    with pytest.raises(DrawingCopyError, match="injected copy fault"):
        insert_into_saved_drawing_copy(base, pdf, out)
    assert replacement[0].read_text() == "foreign preserved" and displaced.is_dir()
    assert not out.exists()


def test_concurrent_base_edit_is_preserved_and_not_published(tmp_path, monkeypatch):
    from librecad_pdf_importer import drawing_insert as module
    base, pdf, out = [tmp_path / n for n in ("base.dxf", "pdf.dxf", "copy.dxf")]
    drawing(base, 4, 10); drawing(pdf, 4, 20)
    execute = module.xref.Loader.execute
    changed = []
    def alter_after_load(loader, **kwargs):
        execute(loader, **kwargs)
        updated = ezdxf.readfile(base)
        updated.modelspace().add_line((2, 2), (3, 3))
        updated.saveas(base)
        changed.append(digest(base))
    monkeypatch.setattr(module.xref.Loader, "execute", alter_after_load)
    with pytest.raises(DrawingCopyError, match="input drawing changed"):
        insert_into_saved_drawing_copy(base, pdf, out)
    assert digest(base) == changed[0] and not out.exists()


def test_cancel_after_loader_keeps_inputs_and_no_finished_assets(tmp_path, monkeypatch):
    from librecad_pdf_importer import drawing_insert as module
    base, pdf, out = [tmp_path / n for n in ("base.dxf", "pdf.dxf", "copy.dxf")]
    drawing(base, 4, 10); drawing(pdf, 4, 20)
    execute = module.xref.Loader.execute
    stopped = []
    def stop_after_load(loader, **kwargs):
        execute(loader, **kwargs); stopped.append(True)
    monkeypatch.setattr(module.xref.Loader, "execute", stop_after_load)
    with pytest.raises(DrawingCopyCancelled):
        insert_into_saved_drawing_copy(base, pdf, out, cancel_requested=lambda: bool(stopped))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["base.dxf", "pdf.dxf"]


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows folder pin")
def test_pinned_workspace_cannot_be_swapped_during_conversion(tmp_path):
    from librecad_pdf_importer.drawing_copy import _directory_identity
    folder = tmp_path / "private-workspace"; folder.mkdir()
    guard = PinnedConversionWorkspace(folder, _directory_identity(folder))
    try:
        with pytest.raises(OSError):
            folder.rename(tmp_path / "displaced-workspace")
        guard.check()
        assert folder.is_dir()
    finally:
        guard.close()
    folder.rename(tmp_path / "released-workspace")


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows folder pin")
def test_pin_constructor_failure_releases_acquired_handle(tmp_path, monkeypatch):
    from librecad_pdf_importer.drawing_copy import _directory_identity
    folder = tmp_path / "private-workspace"; folder.mkdir()
    check = PinnedConversionWorkspace.check
    calls = []
    def fail_second(instance):
        calls.append(True)
        if len(calls) == 2:
            raise DrawingCopyError("injected post-acquisition check")
        check(instance)
    monkeypatch.setattr(PinnedConversionWorkspace, "check", fail_second)
    with pytest.raises(DrawingCopyError, match="post-acquisition"):
        PinnedConversionWorkspace(folder, _directory_identity(folder))
    folder.rename(tmp_path / "released-after-failure")


def test_converter_refuses_competing_output_at_final_publication(tmp_path):
    import pymupdf
    from dxf_import_engine import convert
    from pdfcadcore.import_config import ImportConfig
    source, output = tmp_path / "simple.pdf", tmp_path / "pdf-only.dxf"
    pdf = pymupdf.open(); page = pdf.new_page()
    page.draw_line((10, 10), (40, 20)); pdf.save(source); pdf.close()
    calls = []
    def before_publication():
        calls.append(True)
        # Start gate, assets/candidate gate, then final no-overwrite publication.
        if len(calls) == 4:
            output.write_bytes(b"competing native drawing")
    with pytest.raises(FileExistsError):
        convert(str(source), str(output), config=ImportConfig.auto(),
                output_must_not_exist=True, output_publication_guard=before_publication)
    assert output.read_bytes() == b"competing native drawing"
    assert calls == [True] * 4


def test_protected_asset_rollback_keeps_replaced_image(tmp_path, monkeypatch):
    import io
    import pymupdf
    from dxf_import_engine import convert
    from pdfcadcore.import_config import ImportConfig
    from librecad_pdf_importer.exporters import dxf_exporter as exporter
    image = io.BytesIO()
    Image.new("RGB", (8, 6), (255, 0, 0)).save(image, format="PNG")
    source = tmp_path / "picture.pdf"
    pdf = pymupdf.open(); page = pdf.new_page()
    page.insert_image(pymupdf.Rect(10, 10, 110, 85), stream=image.getvalue())
    pdf.save(source); pdf.close()
    retained = []
    original = exporter._reopen_candidate_for_verification
    def replace_then_fail(path, **kwargs):
        files = list(tmp_path.rglob("*.png"))
        assert files
        target = files[0]
        target.unlink()
        Image.new("RGB", (8, 6), (0, 0, 255)).save(target)
        retained.append((target, digest(target)))
        raise RuntimeError("injected image verification failure")
    monkeypatch.setattr(exporter, "_reopen_candidate_for_verification", replace_then_fail)
    output = tmp_path / "pdf-only.dxf"
    with pytest.raises(RuntimeError, match="injected image verification failure"):
        convert(str(source), str(output), config=ImportConfig.auto(), output_must_not_exist=True)
    assert not output.exists() and retained[0][0].is_file()
    assert digest(retained[0][0]) == retained[0][1]


def test_protected_local_cleanup_keeps_replaced_empty_session_directory(tmp_path, monkeypatch):
    import io
    import pymupdf
    from dxf_import_engine import convert
    from pdfcadcore.import_config import ImportConfig
    from librecad_pdf_importer.exporters import dxf_exporter as exporter
    image = io.BytesIO(); Image.new("RGB", (8, 6), (255, 0, 0)).save(image, format="PNG")
    source = tmp_path / "picture.pdf"
    pdf = pymupdf.open(); page = pdf.new_page()
    page.insert_image(pymupdf.Rect(10, 10, 110, 85), stream=image.getvalue())
    pdf.save(source); pdf.close()
    replacements = []
    def swap_then_fail(path, **kwargs):
        image_path = next(tmp_path.rglob("*.png"))
        session = image_path.parent.parent
        displaced = session.with_name(session.name + "-displaced")
        session.rename(displaced); session.mkdir()
        replacements.append((session, displaced))
        raise RuntimeError("injected session directory failure")
    monkeypatch.setattr(exporter, "_reopen_candidate_for_verification", swap_then_fail)
    output = tmp_path / "pdf-only.dxf"
    with pytest.raises(RuntimeError, match="injected session directory failure"):
        convert(str(source), str(output), config=ImportConfig.auto(), output_must_not_exist=True)
    assert not output.exists()
    assert replacements[0][0].is_dir() and replacements[0][1].is_dir()


def test_combined_render_budget_is_explicitly_optional(tmp_path):
    base, pdf, out = [tmp_path / n for n in ("base.dxf", "pdf.dxf", "copy.dxf")]
    for path in (base, pdf):
        doc = ezdxf.new("R2010"); doc.units = 4
        for n in range(7):
            doc.modelspace().add_line((0, n), (1, n))
        doc.saveas(path)
    with pytest.raises(DrawingCopyError, match="combined drawing exceeds"):
        insert_into_saved_drawing_copy(base, pdf, out, expanded_entity_budget=10)
    result = insert_into_saved_drawing_copy(base, pdf, out, expanded_entity_budget=None)
    assert result.imported_entities == 7
