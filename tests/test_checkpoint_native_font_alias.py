"""Physical DXF regressions for LibreCAD 2.2's STYLE-name font lookup.

The lookup below follows RS_FontList::requestFont, not ezdxf's STYLE.font
interpretation. All drawing data is fictional; no native CAD program is run.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import ezdxf
import pymupdf
import pytest
from PIL import Image

import dxf_import_engine as engine
from librecad_pdf_importer import drawing_insert
from librecad_pdf_importer.drawing_copy import DrawingCopyError
from librecad_runtime import resolve_librecad_installation
from pdfcadcore.import_config import ImportConfig


def _native_lookup(style_name: str, available=("unicode", "standard")) -> str:
    """Exact name transformation and fallback in LibreCAD 2.2.1.5."""
    name = style_name.lower()
    if "#" in name and "_" in name:
        name = name[:name.index("_")]
    elif "#" in name:
        name = name[:name.index("#")]
    return name if name in available else "standard"


def _properties(style):
    return {key: value for key, value in style.dxf.all_existing_dxf_attribs().items()
            if key not in {"name", "handle", "owner"}}


def _styled_entities(doc):
    return [entity for entity in doc.entitydb.values()
            if entity.is_alive and entity.dxf.is_supported("style")
            and entity.dxf.get("style", "")]


def _checkpoint(path: Path, *, width=0.8, marker="D042", font="unicode",
                style_name="unicode", extra_style=None, image=False) -> Path:
    doc = ezdxf.new("R2010")
    style = doc.styles.add(style_name, font=font, dxfattribs={
        "width": width, "height": 0.0, "oblique": 3.0,
        "generation_flags": 2, "last_height": 4.0, "flags": 4,
    })
    if extra_style:
        extra_style(style)
    doc.appids.add("FONT_ALIAS_CONTROL")
    style.set_xdata("FONT_ALIAS_CONTROL", [(1000, marker)])
    doc.layers.new("P001_TEXT", dxfattribs={"color": 2})
    hidden = doc.layers.new("P001_TEXT_SEARCH", dxfattribs={"plot": 0})
    hidden.freeze()
    msp = doc.modelspace()
    common = {"style": style_name, "height": 3, "width": 0.9, "rotation": 17}
    msp.add_text(marker + " VISIBLE", dxfattribs={
        **common, "insert": (10, 20), "layer": "P001_TEXT",
    })
    msp.add_text(marker + " SEARCH", dxfattribs={
        **common, "insert": (11, 21), "layer": "P001_TEXT_SEARCH",
    })
    msp.add_mtext(marker + " MULTILINE", dxfattribs={
        "style": style_name, "char_height": 2.0, "insert": (14, 24),
        "layer": "P001_TEXT",
    })
    child = doc.blocks.new("Child")
    child.add_text(marker + " CHILD", dxfattribs={**common, "insert": (1, 2)})
    child.add_attdef("SHOP", (3, 4), text=marker + " DEFAULT", dxfattribs=common)
    child.add_line((0, 0), (width, 2))
    parent = doc.blocks.new("Parent")
    parent.add_blockref("Child", (5, 6))
    insertion = msp.add_blockref("Parent", (30, 40))
    insertion.add_attrib("SHOP", marker + " ATTRIBUTE", (31, 41), dxfattribs=common)
    doc.dimstyles.new("ShopDims", dxfattribs={"dimtxsty": style_name})
    dimension = msp.add_linear_dim(base=(0, 60), p1=(0, 0), p2=(20, 0),
                                   dimstyle="ShopDims")
    dimension.render()
    if image:
        pixels = path.with_suffix(".png")
        Image.new("RGBA", (3, 2), (10, 20, 30, 255)).save(pixels)
        definition = doc.add_image_def(filename=pixels.name, size_in_pixel=(3, 2))
        msp.add_image(definition, insert=(50, 60), size_in_units=(6, 4))
    msp.dxf.extmin = (0, 0, 0)
    msp.dxf.extmax = (100, 100, 0)
    doc.saveas(path)
    return path


def test_plain_xref_prefix_reproduces_the_native_font_fallback(tmp_path):
    source = ezdxf.readfile(_checkpoint(tmp_path / "page_0001.dxf"))
    target = ezdxf.new("R2010")
    engine.load_modelspace(source, target, conflict_policy=engine.ConflictPolicy.XREF_PREFIX)
    output = tmp_path / "old-assembly.dxf"
    target.saveas(output)
    reopened = ezdxf.readfile(output)
    visible, = [e for e in reopened.modelspace().query("TEXT") if e.dxf.text.endswith("VISIBLE")]
    assert _native_lookup("unicode") == "unicode"
    assert reopened.styles.get(visible.dxf.style).dxf.font == "unicode"
    assert visible.dxf.style == "page_0001$0$unicode"
    assert _native_lookup(visible.dxf.style) == "standard"


@pytest.mark.parametrize("pages", [1, 2])
def test_single_and_multipage_physical_dxf_preserve_native_font_and_resource_closure(
    tmp_path, pages,
):
    checkpoints = [_checkpoint(tmp_path / f"page_{index:04d}.dxf", width=0.8 + index / 10,
                               marker=f"D{index:03d}", image=True)
                   for index in range(1, pages + 1)]
    original_bytes = [path.read_bytes() for path in checkpoints]
    source_styles = [ezdxf.readfile(path).styles.get("unicode") for path in checkpoints]
    output = tmp_path / "assembled.dxf"
    engine._assemble_checkpoints(checkpoints, str(output))
    doc = ezdxf.readfile(output)
    aliases = [style for style in doc.styles if style.dxf.name.startswith("unicode#")]
    assert len(aliases) == pages
    assert len({style.dxf.name.lower() for style in aliases}) == pages
    for source_style, alias in zip(source_styles, aliases, strict=True):
        assert _properties(alias) == _properties(source_style)
        assert alias.get_xdata("FONT_ALIAS_CONTROL") == source_style.get_xdata("FONT_ALIAS_CONTROL")
        assert "_" not in alias.dxf.name
        assert _native_lookup(alias.dxf.name) == "unicode"
        assert alias.dxf.font == "unicode"
    # Includes generated dimension text plus TEXT, MTEXT, nested TEXT, ATTDEF,
    # and attached ATTRIB. Every group-7 reference resolves after physical readback.
    styled = _styled_entities(doc)
    native = [entity for entity in styled if "D0" in str(entity.dxf.get("text", ""))]
    assert {entity.dxftype() for entity in native} == {"TEXT", "MTEXT", "ATTDEF", "ATTRIB"}
    assert len(native) == 6 * pages
    for entity in native:
        assert entity.dxf.style in doc.styles
        assert _native_lookup(entity.dxf.style) == "unicode"
    for style in doc.dimstyles:
        if "ShopDims" in style.dxf.name:
            bound = doc.styles.get(style.dxf.dimtxsty)
            assert bound in aliases
    # Distinct blocks/layers keep their original page isolation and contents.
    for index in range(1, pages + 1):
        prefix = f"page_{index:04d}$0$"
        assert prefix + "Child" in doc.blocks
        assert prefix + "Parent" in doc.blocks
        assert doc.layers.get(prefix + "P001_TEXT_SEARCH").is_frozen()
        assert doc.layers.get(prefix + "P001_TEXT_SEARCH").dxf.plot == 0
        line, = doc.blocks.get(prefix + "Child").query("LINE")
        assert tuple(line.dxf.start) == (0, 0, 0)
        assert tuple(line.dxf.end) == pytest.approx((0.8 + index / 10, 2, 0))
    images = list(doc.modelspace().query("IMAGE"))
    assert len(images) == pages
    for checkpoint, image in zip(checkpoints, images, strict=True):
        source_image, = ezdxf.readfile(checkpoint).modelspace().query("IMAGE")
        assert tuple(image.dxf.u_pixel) == tuple(source_image.dxf.u_pixel)
        assert tuple(image.dxf.v_pixel) == tuple(source_image.dxf.v_pixel)
        asset = output.parent / image.image_def.dxf.filename
        assert asset.read_bytes() == checkpoints[0].with_suffix(".png").read_bytes()
    assert [path.read_bytes() for path in checkpoints] == original_bytes
    assert not doc.audit().has_errors


def test_target_style_collisions_and_existing_references_are_not_clobbered(tmp_path):
    source = ezdxf.readfile(_checkpoint(tmp_path / "page_0001.dxf"))
    target = ezdxf.new("R2010")
    collision = target.styles.add("unicode#bcs-1", font="other.lff", dxfattribs={"width": 1.7})
    existing = target.modelspace().add_text("UNCHANGED", dxfattribs={"style": collision.dxf.name})
    original = (collision.dxf.all_existing_dxf_attribs().copy(),
                existing.dxf.all_existing_dxf_attribs().copy())
    engine._load_checkpoint_modelspace(source, target)
    assert collision.dxf.all_existing_dxf_attribs() == original[0]
    assert existing.dxf.all_existing_dxf_attribs() == original[1]
    imported = [e for e in _styled_entities(target) if e.dxf.get("text") == "D042 VISIBLE"]
    assert len(imported) == 1
    assert imported[0].dxf.style == "unicode#bcs-2"
    assert _native_lookup(imported[0].dxf.style) == "unicode"


@pytest.mark.parametrize("kind", ["ATTRIB", "ATTDEF"])
def test_embedded_multiline_attribute_style_follows_alias_without_other_field_changes(tmp_path, kind):
    source = ezdxf.new("R2018")
    source.styles.add("unicode", font="unicode")
    if kind == "ATTRIB":
        block = source.blocks.new("Tags")
        block.add_line((0, 0), (1, 1))
        insertion = source.modelspace().add_blockref("Tags", (3, 5))
        attribute = insertion.add_attrib("TAG", "OLD", (10, 20))
    else:
        block = source.blocks.new("Tags")
        attribute = block.add_attdef("TAG", (10, 20), text="OLD")
        source.modelspace().add_blockref("Tags", (3, 5))
    mtext = source.modelspace().add_mtext("D042\\PSHOP", dxfattribs={
        "style": "unicode", "char_height": 2.5, "insert": (10, 20),
        "width": 8, "rotation": 17, "line_spacing_factor": 1.3,
    })
    attribute.embed_mtext(mtext)
    checkpoint = tmp_path / "page_0001.dxf"
    source.saveas(checkpoint)
    before = ezdxf.readfile(checkpoint)
    source_attribute, = [e for e in before.entitydb.values() if e.dxftype() == kind]
    original_mtext = source_attribute.virtual_mtext_entity()
    output = tmp_path / "assembled.dxf"
    engine._assemble_checkpoints([checkpoint], str(output))
    after = ezdxf.readfile(output)
    copied, = [e for e in after.entitydb.values() if e.dxftype() == kind]
    assert _native_lookup(copied.dxf.style) == "unicode"
    copied_mtext = copied.virtual_mtext_entity()
    assert copied_mtext.dxf.style == copied.dxf.style
    assert _native_lookup(copied_mtext.dxf.style) == "unicode"
    assert copied_mtext.text == original_mtext.text
    original_properties = original_mtext.dxf.all_existing_dxf_attribs()
    copied_properties = copied_mtext.dxf.all_existing_dxf_attribs()
    original_properties.pop("style")
    copied_properties.pop("style")
    assert copied_properties == original_properties


@pytest.mark.parametrize("font,style_name,extra", [
    ("arial.ttf", "unicode", None),
    ("C:/different/unicode.lff", "unicode", None),
    ("unicode", "other", None),
    ("unicode", "unicode_without_hash", None),
    ("unicode", "unicode#suffix_with_underscore", None),
    ("unicode", "unicode", lambda style: setattr(style.dxf, "flags", 1)),
    ("unicode", "unicode", lambda style: setattr(style.dxf, "bigfont", "other.shx")),
    ("unicode", "unicode", lambda style: style.set_extended_font_data("Arial")),
    ("unicode#alias.ttf", "unicode#bcs-1", None),
    ("unicode#alias.lff", "unicode#bcs-1", None),
    ("C:/unicode#bcs-1", "unicode#bcs-1", None),
    ("../unicode#bcs-1", "unicode#bcs-1", None),
    ("C:\\unicode#bcs-1", "unicode#bcs-1", None),
    ("unicode#alias_suffix", "unicode#bcs-1", None),
    ("BCPDF_unicode#bcs-1", "unicode#bcs-1", None),
    ("unicode#bcs-1", "unicode#bcs-1", lambda style: setattr(style.dxf, "flags", 1)),
    ("unicode#bcs-1", "unicode#bcs-1", lambda style: setattr(style.dxf, "bigfont", "other.shx")),
    ("unicode#bcs-1", "unicode#bcs-1", lambda style: style.set_extended_font_data("Arial")),
])
def test_uncertain_or_conflicting_style_resources_are_left_unchanged(
    tmp_path, font, style_name, extra,
):
    checkpoint = _checkpoint(tmp_path / "page_0001.dxf", font=font,
                             style_name=style_name, extra_style=extra)
    source = ezdxf.readfile(checkpoint)
    output = tmp_path / "assembled.dxf"
    engine._assemble_checkpoints([checkpoint], str(output))
    doc = ezdxf.readfile(output)
    imported_name = "page_0001$0$" + style_name
    assert imported_name in doc.styles
    assert _properties(doc.styles.get(imported_name)) == _properties(source.styles.get(style_name))
    assert not [style for style in doc.styles if style.dxf.name.startswith("unicode#bcs-")]
    visible, = [e for e in doc.modelspace().query("TEXT") if e.dxf.text.endswith("VISIBLE")]
    assert visible.dxf.style == imported_name


@pytest.mark.parametrize("style_name,font", [
    ("UNICODE", "unicode"), ("unicode#legacy", "unicode.lff"),
    ("unicode_0#legacy", "Unicode.LFF"),
    ("unicode#bcs-1", "unicode#bcs-1"),
    ("unicode#bcs-7", "UNICODE#legacy"),
    ("unicode#bcs-1", "unicode_test#x"),
])
def test_only_native_resolvable_source_names_qualify(tmp_path, style_name, font):
    source = _checkpoint(tmp_path / "with_underscores.dxf", style_name=style_name, font=font)
    output = tmp_path / "assembled.dxf"
    engine._assemble_checkpoints([source], str(output))
    doc = ezdxf.readfile(output)
    visible, = [e for e in doc.modelspace().query("TEXT") if e.dxf.text.endswith("VISIBLE")]
    assert _native_lookup(visible.dxf.style) == "unicode"
    assert doc.styles.get(visible.dxf.style).dxf.font == font


def test_xref_collision_mapping_uses_actual_source_name_and_keeps_loaded_handle(tmp_path):
    source = ezdxf.readfile(_checkpoint(tmp_path / "page_0001.dxf"))
    target = ezdxf.new("R2010")
    original = target.styles.add("page_0001$0$unicode", font="other.lff")
    original_handle = original.dxf.handle
    engine._load_checkpoint_modelspace(source, target)
    assert target.styles.get("page_0001$0$unicode").dxf.handle == original_handle
    assert target.styles.get("page_0001$0$unicode").dxf.font == "other.lff"
    native, = [s for s in target.styles if s.dxf.name.startswith("unicode#bcs-")]
    dimension_style = target.dimstyles.get("page_0001$0$ShopDims")
    assert target.styles.get(dimension_style.dxf.dimtxsty) is native


def test_multiple_qualified_source_styles_and_target_collisions_stay_distinct(tmp_path):
    source = ezdxf.new("R2010")
    source.styles.add("unicode", font="unicode", dxfattribs={"width": 0.7, "oblique": 3})
    source.styles.add("unicode#legacy", font="unicode.lff", dxfattribs={"width": 1.4, "oblique": 9})
    source.modelspace().add_text("FIRST", dxfattribs={"style": "unicode", "insert": (10, 20)})
    source.modelspace().add_text("SECOND", dxfattribs={"style": "unicode#legacy", "insert": (30, 40)})
    source_path = tmp_path / "page_0001.dxf"
    source.saveas(source_path)
    source = ezdxf.readfile(source_path)
    target = ezdxf.new("R2010")
    collisions = [
        target.styles.add("page_0001$0$unicode", font="other.ttf"),
        target.styles.add("page_0001$0$unicode#legacy", font="different.ttf"),
        target.styles.add("unicode#bcs-1", font="reserved.ttf"),
    ]
    # Assign normal STYLE table owners before comparing serialized properties.
    target.saveas(tmp_path / "target-before.dxf")
    untouched = [style.dxf.all_existing_dxf_attribs().copy() for style in collisions]
    engine._load_checkpoint_modelspace(source, target)
    output = tmp_path / "assembled.dxf"
    target.saveas(output)
    doc = ezdxf.readfile(output)
    assert [style.dxf.all_existing_dxf_attribs() for style in collisions] == untouched
    first, second = sorted(doc.modelspace().query("TEXT"), key=lambda e: e.dxf.text)
    assert first.dxf.style != second.dxf.style
    for entity, source_name in ((first, "unicode"), (second, "unicode#legacy")):
        assert _properties(doc.styles.get(entity.dxf.style)) == _properties(source.styles.get(source_name))
        assert _native_lookup(entity.dxf.style) == "unicode"
    assert tuple(first.dxf.insert) == (10, 20, 0)
    assert tuple(second.dxf.insert) == (30, 40, 0)


def test_changed_imported_style_cannot_be_misidentified_as_the_qualified_source(tmp_path, monkeypatch):
    source = _checkpoint(tmp_path / "page_0001.dxf")
    output = tmp_path / "assembled.dxf"
    output.write_bytes(b"PREVIOUS OUTPUT IS PRESERVED\n")
    real_load = engine.load_modelspace

    def changed(source_doc, target_doc, **kwargs):
        real_load(source_doc, target_doc, **kwargs)
        target_doc.styles.get("page_0001$0$unicode").dxf.width = 3.5

    monkeypatch.setattr(engine, "load_modelspace", changed)
    with pytest.raises(RuntimeError, match="loaded native text-style binding"):
        engine._assemble_checkpoints([source], str(output))
    assert output.read_bytes() == b"PREVIOUS OUTPUT IS PRESERVED\n"


def _base_for_copy(path):
    base = ezdxf.new("R2010")
    base.units = 4
    base.styles.add("unicode#bcs-1", font="base-font.ttf", dxfattribs={"width": 1.7})
    base.modelspace().add_text("BASE UNCHANGED", dxfattribs={
        "style": "unicode#bcs-1", "height": 5, "insert": (90, 100),
    })
    base.modelspace().add_line((80, 80), (120, 110))
    engine.frame_modelspace(base, (0, 0, 140, 140))
    base.saveas(path)
    return path


def test_saved_copy_keeps_native_nested_text_images_and_base_style_collision(tmp_path):
    base_path = _base_for_copy(tmp_path / "base.dxf")
    source = ezdxf.new("R2010")
    source.units = 4
    native = source.styles.add("unicode#bcs-1", font="unicode", dxfattribs={"width": 0.8})
    layer = source.layers.new("P001_TEXT_SEARCH", dxfattribs={"plot": 0})
    layer.freeze()
    source.modelspace().add_text("INCOMING SEARCH", dxfattribs={
        "style": native.dxf.name, "layer": layer.dxf.name, "insert": (2, 3), "height": 4,
    })
    child = source.blocks.new("Child")
    child.add_text("INCOMING NESTED", dxfattribs={"style": native.dxf.name, "insert": (4, 5)})
    child.add_attdef("SHOP", (6, 7), text="INCOMING DEFAULT", dxfattribs={"style": native.dxf.name})
    insertion = source.modelspace().add_blockref("Child", (10, 20))
    insertion.add_attrib("SHOP", "INCOMING ATTRIBUTE", (11, 21),
                          dxfattribs={"style": native.dxf.name})
    source.modelspace().add_mtext("INCOMING MULTILINE", dxfattribs={
        "style": native.dxf.name, "char_height": 3, "insert": (12, 22),
    })
    pixels = tmp_path / "shop.png"
    Image.new("RGBA", (3, 2), (10, 20, 30, 255)).save(pixels)
    definition = source.add_image_def(filename=pixels.name, size_in_pixel=(3, 2))
    source.modelspace().add_image(definition, insert=(30, 40), size_in_units=(6, 4))
    incoming = tmp_path / "incoming.dxf"
    engine.frame_modelspace(source, (0, 0, 60, 60))
    source.saveas(incoming)
    native = ezdxf.readfile(incoming).styles.get(native.dxf.name)
    input_bytes = [path.read_bytes() for path in (base_path, incoming, pixels)]
    result = drawing_insert.insert_into_saved_drawing_copy(base_path, incoming, tmp_path / "copy.dxf")
    copied = ezdxf.readfile(result.drawing)
    base_style = copied.styles.get("unicode#bcs-1")
    assert base_style.dxf.font == "base-font.ttf" and base_style.dxf.width == 1.7
    base_text, = [e for e in copied.modelspace().query("TEXT") if e.dxf.text == "BASE UNCHANGED"]
    assert base_text.dxf.style == "unicode#bcs-1" and tuple(base_text.dxf.insert) == (90, 100, 0)
    imported = [entity for entity in _styled_entities(copied)
                if str(entity.dxf.get("text", "")).startswith("INCOMING")]
    assert len(imported) == 5
    for entity in imported:
        assert entity.dxf.style != "unicode#bcs-1"
        assert _native_lookup(entity.dxf.style) == "unicode"
        assert _properties(copied.styles.get(entity.dxf.style)) == _properties(native)
    search, = [entity for entity in imported if entity.dxf.get("text") == "INCOMING SEARCH"]
    assert copied.layers.get(search.dxf.layer).is_frozen()
    assert copied.layers.get(search.dxf.layer).dxf.plot == 0
    image, = [e for e in copied.entitydb.values() if e.is_alive and e.dxftype() == "IMAGE"]
    linked = result.drawing.parent / image.image_def.dxf.filename
    assert linked.read_bytes() == pixels.read_bytes()
    assert tuple(image.dxf.insert) == (30, 40, 0)
    assert [path.read_bytes() for path in (base_path, incoming, pixels)] == input_bytes


@pytest.mark.parametrize("route", ["page-xref", "saved-copy"])
def test_native_saved_alias_font_field_survives_physical_copy_routes(tmp_path, route):
    incoming = _checkpoint(tmp_path / "page_0001.dxf", marker="D042",
                           style_name="unicode#bcs-1", font="unicode#bcs-1")
    source = ezdxf.readfile(incoming)
    source.units = 4
    if route == "saved-copy":
        # The PDF-only copy route deliberately refuses DIMENSION. The general
        # checkpoint fixture has one; remove it from this fictional input rather
        # than relaxing that unrelated product guard.
        for dimension in list(source.modelspace().query("DIMENSION")):
            source.modelspace().delete_entity(dimension)
    style = source.styles.get("unicode#bcs-1")
    # Exact normal native-save STYLE fields observed in LibreCAD 2.2.1.5,
    # with fictional text/geometry and an unrelated retained XDATA record.
    style.update_dxf_attribs({"flags": 0, "height": 0, "width": 1,
                             "oblique": 0, "generation_flags": 0,
                             "last_height": 1, "bigfont": ""})
    # Like a normal native-saved input, this copy fixture declares its frame;
    # the saved-copy route refuses to invent bounds for unmeasured native text.
    engine.frame_modelspace(source, (0, 0, 140, 140))
    source.saveas(incoming)
    before = incoming.read_bytes()
    source = ezdxf.readfile(incoming)
    style = source.styles.get("unicode#bcs-1")
    if route == "page-xref":
        output = tmp_path / "assembled.dxf"
        engine._assemble_checkpoints([incoming], str(output))
    else:
        base = _base_for_copy(tmp_path / "base.dxf")
        base_bytes = base.read_bytes()
        output = drawing_insert.insert_into_saved_drawing_copy(base, incoming,
                    tmp_path / "copy.dxf").drawing
        assert base.read_bytes() == base_bytes
    physical = ezdxf.readfile(output)
    imported = [entity for entity in _styled_entities(physical)
                if "D042" in str(entity.dxf.get("text", ""))]
    assert {entity.dxftype() for entity in imported} == {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}
    assert len(imported) == 6
    for entity in imported:
        alias = physical.styles.get(entity.dxf.style)
        assert _native_lookup(entity.dxf.style) == "unicode"
        assert _properties(alias) == _properties(style)
        assert alias.get_xdata("FONT_ALIAS_CONTROL") == style.get_xdata("FONT_ALIAS_CONTROL")
    if route == "saved-copy":
        assert physical.styles.get("unicode#bcs-1").dxf.font == "base-font.ttf"
        base_text, = [e for e in physical.modelspace().query("TEXT") if e.dxf.text == "BASE UNCHANGED"]
        assert base_text.dxf.style == "unicode#bcs-1"
    assert incoming.read_bytes() == before


def test_saved_copy_existing_geometry_guard_still_rejects_incoming_drift(tmp_path, monkeypatch):
    base = _base_for_copy(tmp_path / "base.dxf")
    source = ezdxf.new("R2010")
    source.units = 4
    source.styles.add("unicode", font="unicode")
    source.modelspace().add_text("INCOMING", dxfattribs={"style": "unicode", "insert": (2, 3)})
    incoming = tmp_path / "incoming.dxf"
    engine.frame_modelspace(source, (0, 0, 20, 20))
    source.saveas(incoming)
    original = base.read_bytes(), incoming.read_bytes()
    execute = drawing_insert.xref.Loader.execute

    def changed(loader, **kwargs):
        execute(loader, **kwargs)
        entity, = [e for e in loader.tdoc.entitydb.values()
                    if e.is_alive and e.dxftype() == "TEXT" and e.dxf.text == "INCOMING"]
        entity.dxf.insert = (700, 800, 0)

    monkeypatch.setattr(drawing_insert.xref.Loader, "execute", changed)
    target = tmp_path / "copy.dxf"
    with pytest.raises(DrawingCopyError, match="could not preserve"):
        drawing_insert.insert_into_saved_drawing_copy(base, incoming, target)
    assert not target.exists()
    assert (base.read_bytes(), incoming.read_bytes()) == original


@pytest.mark.parametrize("pages,editable", [(1, True), (2, True), (1, False), (2, False)])
def test_real_pdf_window_pipeline_keeps_requested_text_and_native_font_lookup(
    tmp_path, pages, editable, deterministic_exact_font,
):
    # Bind the lookup to the same controlled LFF resource the exporter certified.
    installation = resolve_librecad_installation()
    assert installation is not None
    assert Path(installation.installation_root) == deterministic_exact_font.parent / "portable-librecad"
    font = Path(installation.installation_root) / "resources/fonts/unicode.lff"
    assert font.is_file() and "LibreCAD Font 1" in font.read_text(encoding="utf-8")
    source = tmp_path / "fictional-shop.pdf"
    with pymupdf.open() as document:
        for index in range(pages):
            page = document.new_page(width=300, height=200)
            page.insert_text((20, 40), f"D{index:03d} SHOP", fontname="helv", fontsize=12)
        document.save(source)
    config = ImportConfig.auto()
    config.text_mode = "text"
    output = tmp_path / "assembled.dxf"
    stats = engine.convert(str(source), str(output), config=config, resumable=True,
                           editable_text=editable)
    doc = ezdxf.readfile(output)
    texts = list(doc.modelspace().query("TEXT"))
    assert len(texts) == pages
    assert sorted(e.dxf.text for e in texts) == [f"D{index:03d} SHOP" for index in range(pages)]
    for text in texts:
        assert _native_lookup(text.dxf.style) == "unicode"
        assert doc.styles.get(text.dxf.style).dxf.font == "unicode"
        layer = doc.layers.get(text.dxf.layer)
        assert layer.is_frozen() is (not editable)
        assert layer.dxf.plot == (1 if editable else 0)
    report = json.loads(Path(stats["import_report_path"]).read_text(encoding="utf-8"))
    assert stats["text_delivery"]["requested"] == "text"
    assert stats["text_delivery"]["delivered"] == ("text" if editable else "glyphs")
    assert report["searchable_text_companions"]["written"] == (0 if editable else pages)
    assert report["searchable_text_companions"]["failed"] == 0
    assert report["searchable_text_companions"]["mismatch"] == 0
    assert report["text_items_degraded_total"] == 0
    # The resume manifest still binds source/runtime/options; no font resource rewrite.
    manifest = json.loads((tmp_path / "assembled_resume/session.json").read_text(encoding="utf-8"))
    assert manifest["options"]["librecad_runtime_binding"]["unicode_lff"]["sha256"] == hashlib.sha256(font.read_bytes()).hexdigest()
    # The normal saved-drawing route must not re-prefix the repaired alias back
    # into a missing LFF name. Its existing strict semantic/base guards run too.
    base = _base_for_copy(tmp_path / "base.dxf")
    original = base.read_bytes(), output.read_bytes()
    result = drawing_insert.insert_into_saved_drawing_copy(base, output, tmp_path / "copy.dxf")
    merged = ezdxf.readfile(result.drawing)
    incoming_text = [e for e in _styled_entities(merged) if str(e.dxf.get("text", "")).startswith("D0")]
    assert len(incoming_text) == pages
    for text in incoming_text:
        assert _native_lookup(text.dxf.style) == "unicode"
        assert merged.styles.get(text.dxf.style).dxf.font == "unicode"
        assert merged.layers.get(text.dxf.layer).is_frozen() is (not editable)
    assert merged.styles.get("unicode#bcs-1").dxf.font == "base-font.ttf"
    assert (base.read_bytes(), output.read_bytes()) == original
