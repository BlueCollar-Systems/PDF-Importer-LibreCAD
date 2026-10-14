"""Actual LibreCAD save metadata must not block a lossless saved-copy import."""
from hashlib import sha256
from pathlib import Path

import ezdxf
from ezdxf.math import Vec3
import pytest

from librecad_pdf_importer import drawing_insert as module
from librecad_pdf_importer.drawing_copy import DrawingCopyError

FIXTURE = Path(__file__).parent / "fixtures/librecad-2.2.1.5/public-glyphs-native-saved.dxf"
FIXTURE_SHA = "02a19de450536731d0409ea04a05a1fc648a5812641cbfabd4da4ffa83abaf69"


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def physical_header_keys(path):
    # ezdxf creates a fresh FINGERPRINTGUID in memory when a native file omits
    # it. Compare every authored header record rather than a reader-generated
    # value from a separate read of the same input.
    lines = path.read_text(encoding="utf-8").splitlines()
    keys = set()
    for code, value in zip(lines[::2], lines[1::2], strict=True):
        if code.strip() == "0" and value.strip() == "ENDSEC":
            break
        if code.strip() == "9":
            keys.add(value.strip())
    return keys


def pair(tmp_path):
    incoming = tmp_path / "incoming.dxf"
    doc = ezdxf.new("R2007")
    doc.units = 4
    doc.modelspace().add_line((0, 0), (5, 4), dxfattribs={"true_color": 0x123456})
    doc.saveas(incoming)
    return incoming


@pytest.mark.parametrize("native_role", ["base", "incoming"])
def test_actual_native_saved_drawing_preserves_geometry_limits_and_resources(tmp_path, native_role):
    assert digest(FIXTURE) == FIXTURE_SHA
    native = ezdxf.readfile(FIXTURE)
    assert native.header["$PSTYLEMODE"] == 1
    assert native.entitydb.get("F") is None
    assert all(layer.dxf.plotstyle_handle == "F" for layer in native.layers)
    assert tuple(native.header["$LIMMAX"]) != tuple(native.modelspace().dxf.limmax)
    other = pair(tmp_path)
    base, incoming = (FIXTURE, other) if native_role == "base" else (other, FIXTURE)
    before = digest(base), digest(incoming)
    original_base = ezdxf.readfile(base)
    base_state = module._base_state(original_base)
    header_state = {key: value for key, value in module._header_state(original_base).items()
                    if key in physical_header_keys(base)}
    source = ezdxf.readfile(incoming)
    source_semantic = module._semantic_digest(source.modelspace().entities_in_redraw_order(), source)
    target = tmp_path / "copy.dxf"
    result = module.insert_into_saved_drawing_copy(base, incoming, target)
    reopened = ezdxf.readfile(target)
    ledger = result.planar_insert_repair_ledger
    for row in ledger["documents"][0]["repairs"]:
        assert sum(code == 43 and value == 0 for code, value in base_state[row["handle"]]) == 1
        base_state[row["handle"]] = [(code, value) for code, value in base_state[row["handle"]] if code != 43]
    for row in ledger["documents"][1]["repairs"]:
        assert source.entitydb[row["handle"]].dxf.zscale == 0
        source.entitydb[row["handle"]].dxf.zscale = 1
    source_semantic = module._semantic_digest(source.modelspace().entities_in_redraw_order(), source)
    module._check_base_state(reopened, base_state)
    # The only new header delta is the independently expected union of the
    # native sheet and the public incoming line, regardless of merge role.
    header_state["$EXTMIN"] = [0.0, 0.0, 0.0]
    header_state["$EXTMAX"] = list(native.header["$EXTMAX"])
    module._check_headers(reopened, header_state)
    assert result.drawing_bounds_provenance["merged"]["minimum"] == [0.0, 0.0, 0.0]
    assert result.drawing_bounds_provenance["merged"]["maximum"] == list(native.header["$EXTMAX"])
    assert module._semantic_digest(reopened.blocks.get(result.block_name).entities_in_redraw_order(), reopened) == source_semantic
    assert tuple(reopened.header["$LIMMAX"]) == tuple(original_base.header["$LIMMAX"])
    assert Vec3(reopened.modelspace().dxf.limmax) == Vec3(original_base.modelspace().dxf.limmax)
    assert (digest(base), digest(incoming)) == before


@pytest.mark.parametrize("change", ["named_mode", "missing_mode", "arbitrary_handle", "wrong_resource_type", "lowercase_wrong_resource", "wrong_default", "extra_named_style", "custom_normal", "missing_normal"])
def test_inactive_alias_qualification_rejects_active_custom_and_malformed_resources(change):
    doc = ezdxf.readfile(FIXTURE)
    handle = "F"
    dictionary = doc.rootdict.get("ACAD_PLOTSTYLENAME")
    normal = dictionary.get("Normal")
    if change == "named_mode":
        doc.header["$PSTYLEMODE"] = 0
    elif change == "missing_mode":
        del doc.header["$PSTYLEMODE"]
    elif change == "arbitrary_handle":
        handle = "DEADBEEF"
    elif change in {"wrong_resource_type", "lowercase_wrong_resource"}:
        line = doc.modelspace().add_line((0, 0), (1, 1))
        assert doc.entitydb.reset_handle(line, "F")
        if change == "lowercase_wrong_resource":
            handle = "f"
    elif change == "wrong_default":
        dictionary.dxf.default = "DEADBEEF"
    elif change == "extra_named_style":
        dictionary.add("CUSTOM", normal)
    elif change == "custom_normal":
        doc.appids.add("PUBLIC_STYLE_CONTROL")
        normal.set_xdata("PUBLIC_STYLE_CONTROL", [(1000, "custom named style")])
    else:
        dictionary.remove("Normal")
    with pytest.raises(DrawingCopyError, match="unresolved ACDBPLACEHOLDER"):
        module._resolved_layer_reference(doc, handle, "ACDBPLACEHOLDER", {})


def test_materials_never_use_the_inactive_plotstyle_alias():
    doc = ezdxf.readfile(FIXTURE)
    with pytest.raises(DrawingCopyError, match="unresolved MATERIAL"):
        module._resolved_layer_reference(doc, "F", "MATERIAL", {})


def test_header_limit_export_keeps_layout_and_full_header_checks_strict(tmp_path):
    doc = ezdxf.readfile(FIXTURE)
    expected_header = module._header_state(doc)
    expected_base = module._base_state(doc)
    target = tmp_path / "header-limits.dxf"
    with target.open("x", encoding=doc.output_encoding) as stream:
        module._write_merged_drawing(doc, stream)
    reopened = ezdxf.readfile(target)
    module._check_base_state(reopened, expected_base)
    module._check_headers(reopened, expected_header)
    reopened.header["$LIMMAX"] = (101, 102)
    with pytest.raises(DrawingCopyError, match="header setting"):
        module._check_headers(reopened, expected_header)


@pytest.mark.parametrize("change", ["lineweight", "width", "scale", "rotation", "count", "text_width", "text_oblique"])
def test_native_optional_default_spelling_keeps_nondefault_values_strict(change):
    doc = ezdxf.readfile(FIXTURE)
    before = module._semantic_digest(doc.modelspace().entities_in_redraw_order(), doc)
    if change == "lineweight":
        doc.modelspace().query("HATCH").first.dxf.lineweight = 25
    elif change == "width":
        doc.modelspace().query("LWPOLYLINE").first.dxf.const_width = 1
    elif change in {"scale", "rotation", "count"}:
        entity = doc.modelspace().query("INSERT").first
        setattr(entity.dxf, {"scale": "xscale", "rotation": "rotation", "count": "column_count"}[change], 2)
    else:
        entity = doc.modelspace().query("TEXT").first
        setattr(entity.dxf, "width" if change == "text_width" else "oblique", 2)
    assert module._semantic_digest(doc.modelspace().entities_in_redraw_order(), doc) != before


@pytest.mark.parametrize("kind", ["TEXT", "MTEXT", "ATTRIB"])
@pytest.mark.parametrize("change", ["font", "width", "flags"])
def test_default_standard_style_still_binds_actual_font_width_and_flags(kind, change):
    doc = ezdxf.new("R2007")
    if kind == "TEXT":
        entity = doc.modelspace().add_text("PUBLIC visible text")
    elif kind == "MTEXT":
        entity = doc.modelspace().add_mtext("PUBLIC visible text")
    else:
        definition = doc.blocks.new("PUBLIC_ATTRIB_BLOCK")
        definition.add_line((0, 0), (1, 1))
        instance = doc.modelspace().add_blockref(definition.name, (0, 0))
        entity = instance.add_attrib("PUBLIC_TAG", "PUBLIC visible text", (0, 0))
    entity.dxf.style = "Standard"
    before = module._semantic_digest([entity], doc)
    style = doc.styles.get("Standard")
    setattr(style.dxf, change, {"font": "PUBLIC_DIFFERENT_FACE.ttf", "width": 2.0, "flags": 4}[change])
    assert module._semantic_digest([entity], doc) != before


@pytest.mark.parametrize("kind", ["TEXT", "MTEXT", "ATTRIB"])
def test_explicit_and_omitted_default_style_resolve_the_same_resource(kind):
    doc = ezdxf.new("R2007")
    if kind == "TEXT":
        entity = doc.modelspace().add_text("PUBLIC visible text")
    elif kind == "MTEXT":
        entity = doc.modelspace().add_mtext("PUBLIC visible text")
    else:
        definition = doc.blocks.new("PUBLIC_ATTRIB_BLOCK")
        instance = doc.modelspace().add_blockref(definition.name, (0, 0))
        entity = instance.add_attrib("PUBLIC_TAG", "PUBLIC visible text", (0, 0))
    entity.dxf.discard("style")
    implicit = module._semantic_digest([entity], doc)
    entity.dxf.style = "Standard"
    assert module._semantic_digest([entity], doc) == implicit


@pytest.mark.parametrize("kind", ["TEXT", "MTEXT", "ATTRIB", "ATTDEF"])
def test_incoming_default_font_is_transported_without_changing_base_standard(tmp_path, kind):
    base, source, target = [tmp_path / name for name in ("base.dxf", "source.dxf", "copy.dxf")]
    doc = ezdxf.new("R2007")
    doc.units = 4
    doc.styles.get("Standard").dxf.font = "PUBLIC_BASE_FACE.ttf"
    doc.styles.get("Standard").dxf.width = 1.5
    doc.modelspace().add_text("PUBLIC base text")
    doc.header["$EXTMIN"], doc.header["$EXTMAX"] = (-5, -5, 0), (200, 200, 0)
    with base.open("x", encoding=doc.output_encoding) as stream:
        module._write_merged_drawing(doc, stream)
    incoming = ezdxf.new("R2007")
    incoming.units = 4
    incoming.styles.get("Standard").dxf.font = "PUBLIC_SOURCE_FACE.ttf"
    incoming.styles.get("Standard").dxf.width = 0.75
    if kind == "TEXT":
        entity = incoming.modelspace().add_text("PUBLIC incoming text")
    elif kind == "MTEXT":
        entity = incoming.modelspace().add_mtext("PUBLIC incoming text")
    else:
        block = incoming.blocks.new("PUBLIC_ATTRIBUTE_BLOCK")
        reference = incoming.modelspace().add_blockref(block.name, (1, 2))
        entity = reference.add_attrib("PUBLIC_TAG", "PUBLIC incoming text", (1, 2)) if kind == "ATTRIB" else block.add_attdef("PUBLIC_TAG", (0, 0), "PUBLIC incoming definition")
    entity.dxf.discard("style")
    incoming.header["$EXTMIN"], incoming.header["$EXTMAX"] = (-10, -10, 0), (250, 250, 0)
    with source.open("x", encoding=incoming.output_encoding) as stream:
        module._write_merged_drawing(incoming, stream)
    before = digest(base), digest(source)
    result = module.insert_into_saved_drawing_copy(base, source, target)
    merged = ezdxf.readfile(target)
    assert merged.styles.get("Standard").dxf.font == "PUBLIC_BASE_FACE.ttf"
    assert merged.styles.get("Standard").dxf.width == 1.5
    outer = merged.blocks.get(result.block_name)
    if kind in {"TEXT", "MTEXT"}:
        transported = outer.query(kind).first
    elif kind == "ATTRIB":
        transported = outer.query("INSERT").first.attribs[0]
    else:
        transported = merged.blocks.get(outer.query("INSERT").first.dxf.name).query("ATTDEF").first
    style = merged.styles.get(transported.dxf.style)
    assert style.dxf.font == "PUBLIC_SOURCE_FACE.ttf" and style.dxf.width == 0.75
    assert (digest(base), digest(source)) == before
