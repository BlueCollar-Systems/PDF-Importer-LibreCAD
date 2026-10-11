"""Paint-resource references can rebind when the base was saved by LibreCAD."""
from hashlib import sha256
from pathlib import Path

import ezdxf
from ezdxf.math import Matrix44
from ezdxf.lldxf.types import DXFTag
from ezdxf.sections.header import HeaderVar
import pytest
from PIL import Image

from librecad_pdf_importer import drawing_insert as module
from librecad_pdf_importer.drawing_copy import DrawingCopyError


def _hash(path):
    return sha256(path.read_bytes()).hexdigest()


def _base(path):
    # Match the serialized DXF2007/native-writer handle profile that exposed
    # the regression, without depending on local host installation or files.
    doc = ezdxf.new("R2007")
    doc.units = 4
    for kind, old_handle, new_handle in (("MATERIAL", "21", "20011"),
                                       ("ACDBPLACEHOLDER", "13", "20009")):
        resource = doc.entitydb[old_handle]
        assert resource.dxftype() == kind
        assert doc.entitydb.reset_handle(resource, new_handle)
        field = "material_handle" if kind == "MATERIAL" else "plotstyle_handle"
        for layer in doc.layers:
            if layer.dxf.get(field) == old_handle:
                setattr(layer.dxf, field, new_handle)
    doc.modelspace().add_line((0, 0), (100, 0))
    doc.saveas(path)


def _pdf(path, *, custom=False):
    doc = ezdxf.new("R2010")
    doc.units = 4
    layer = doc.layers.new("PAPER")
    if custom:
        material = doc.materials.new("Paper material")
        material.dxf.diffuse_color_value = 0x123456
        material.dxf.opacity = .65
        material.diffuse_mapper_matrix = Matrix44.scale(2, 3, 1)
        layer.dxf.material_handle = material.dxf.handle
    block = doc.blocks.new("NESTED")
    block.add_line((0, 0), (10, 20), dxfattribs={"layer": "PAPER", "true_color": 254})
    doc.modelspace().add_blockref("NESTED", (7, 9), dxfattribs={"layer": "PAPER"})
    doc.saveas(path)


@pytest.mark.parametrize("custom", [False, True])
def test_native_writer_resource_handles_and_names_rebind_without_paint_loss(tmp_path, custom):
    base, pdf, target = [tmp_path / name for name in ("base.dxf", "pdf.dxf", "copy.dxf")]
    _base(base)
    _pdf(pdf, custom=custom)
    original = _hash(base), _hash(pdf)
    result = module.insert_into_saved_drawing_copy(base, pdf, target)
    merged = ezdxf.readfile(target)
    assert merged.units == 4
    assert merged.layers.get("0").dxf.material_handle == "20011"
    assert merged.layers.get("0").dxf.plotstyle_handle == "20009"
    outer = merged.blocks.get(result.block_name)
    layer = merged.layers.get(outer.query("INSERT").first.dxf.layer)
    assert layer.dxf.plotstyle_handle == "20009"
    material = merged.entitydb[layer.dxf.material_handle]
    if custom:
        assert material.dxf.name != "Paper material"
        assert material.dxf.diffuse_color_value == 0x123456
        assert material.dxf.opacity == .65
        assert list(material.diffuse_mapper_matrix) == list(Matrix44.scale(2, 3, 1))
    else:
        assert material.dxf.handle == "20011"
    assert (_hash(base), _hash(pdf)) == original


@pytest.mark.parametrize("changed", ["diffuse_color_value", "opacity", "mapper_matrix"])
def test_rebound_material_paint_drift_is_rejected(tmp_path, monkeypatch, changed):
    base, pdf, target = [tmp_path / name for name in ("base.dxf", "pdf.dxf", "copy.dxf")]
    _base(base)
    _pdf(pdf, custom=True)
    original = _hash(base), _hash(pdf)
    execute = module.xref.Loader.execute

    def corrupt(loader, **kwargs):
        execute(loader, **kwargs)
        material = next(e for e in loader.tdoc.entitydb.values()
                        if e.is_alive and e.dxftype() == "MATERIAL" and e.dxf.name.startswith("BCPDF_"))
        if changed == "mapper_matrix":
            material.diffuse_mapper_matrix = Matrix44.scale(9, 3, 1)
        else:
            setattr(material.dxf, changed, .2 if changed == "opacity" else 0x654321)

    monkeypatch.setattr(module.xref.Loader, "execute", corrupt)
    with pytest.raises(DrawingCopyError, match="could not preserve"):
        module.insert_into_saved_drawing_copy(base, pdf, target)
    assert not target.exists()
    assert (_hash(base), _hash(pdf)) == original


def test_unresolved_incoming_plotstyle_is_not_ignored(tmp_path):
    base, pdf, target = [tmp_path / name for name in ("base.dxf", "pdf.dxf", "copy.dxf")]
    _base(base)
    _pdf(pdf)
    doc = ezdxf.readfile(pdf)
    doc.layers.get("PAPER").dxf.plotstyle_handle = "DEADBEEF"
    doc.saveas(pdf)
    original = _hash(base), _hash(pdf)
    with pytest.raises(DrawingCopyError, match="unresolved ACDBPLACEHOLDER"):
        module.insert_into_saved_drawing_copy(base, pdf, target)
    assert not target.exists()
    assert (_hash(base), _hash(pdf)) == original


def test_actual_native_saved_base_accepts_repeated_import_with_images_hidden_text_and_nested_glyphs(tmp_path):
    base = Path(__file__).parent / "fixtures/librecad-2.2.1.5/mm-merged-native-saved.dxf"
    assert _hash(base) == "ad44217f5923a9d6f1c2fb6c4de191913cc6a7c76f445e48c8257effdf47abcd"
    native = ezdxf.readfile(base)
    before = module._base_state(native)
    collision = next(block.name for block in native.blocks if not block.name.startswith("*"))
    doc = ezdxf.new("R2010")
    doc.units = 4
    doc.layers.new("SEARCH", dxfattribs={"flags": 1})
    glyph = doc.blocks.new(collision)
    glyph.add_solid([(0, 0), (8, 0), (0, 5), (8, 5)], dxfattribs={"true_color": 0xFEFEFE})
    glyph.add_line((0, 0), (8, 5), dxfattribs={"true_color": 1})
    doc.modelspace().add_blockref(collision, (3, 9))
    doc.modelspace().add_text("FICTIONAL hidden search", dxfattribs={"layer": "SEARCH"})
    originals = {}
    for name, color, position in (("red.png", (255, 0, 0), (20, 30)),
                                  ("blue.png", (0, 0, 255), (45, 30))):
        image = tmp_path / name
        Image.new("RGB", (8, 6), color).save(image)
        originals[image] = _hash(image)
        definition = doc.add_image_def(filename=name, size_in_pixel=(8, 6))
        picture = doc.modelspace().add_image(definition, insert=position,
            size_in_units=(20, 15), rotation=17)
        picture.set_boundary_path([(0, 0), (5, 0), (5, 4), (0, 4)])
    pdf, target = tmp_path / "mixed-pdf.dxf", tmp_path / "second-import.dxf"
    doc.saveas(pdf)
    originals[pdf] = _hash(pdf)
    result = module.insert_into_saved_drawing_copy(base, pdf, target)
    merged = ezdxf.readfile(target)
    module._check_base_state(merged, before)
    assert merged.units == native.units == 4
    for flag in ("$GRIDMODE", "$SNAPSTYLE"):
        assert merged.header.get(flag) == native.header.get(flag)
    outer = merged.blocks.get(result.block_name)
    nested = merged.blocks.get(outer.query("INSERT").first.dxf.name)
    assert nested.name != collision
    assert nested.query("SOLID").first.dxf.true_color == 0xFEFEFE
    assert merged.layers.get(outer.query("TEXT").first.dxf.layer).is_frozen()
    assert result.image_files == 2
    for picture in outer.query("IMAGE"):
        definition = merged.entitydb[picture.dxf.image_def_handle]
        assert not Path(definition.dxf.filename).is_absolute()
        assert _hash(target.parent / definition.dxf.filename) in originals.values()
        assert len(picture.boundary_path) == 5
    assert _hash(base) == "ad44217f5923a9d6f1c2fb6c4de191913cc6a7c76f445e48c8257effdf47abcd"
    assert all(_hash(path) == value for path, value in originals.items())


def _explicit_default_base():
    doc = ezdxf.new("R2010")
    doc.modelspace().add_line((0, 0), (10, 0), dxfattribs={"color": 256, "lineweight": -1})
    doc.modelspace().add_lwpolyline([(0, 0), (5, 6)], dxfattribs={"const_width": 0})
    doc.blocks.new("SHAPE").add_circle((0, 0), 2)
    doc.modelspace().add_blockref("SHAPE", (1, 2), dxfattribs={
        "xscale": 1, "yscale": 1, "zscale": 1, "rotation": 0, "row_count": 1, "column_count": 1})
    doc.viewports.get("*Active")[0].dxf.owner = doc.layers.head.dxf.handle
    doc.styles.get("Standard").dxf.owner = doc.layers.head.dxf.handle
    return doc


def test_declared_optional_defaults_and_native_owner_aliases_survive_writer(tmp_path):
    source = _explicit_default_base()
    expected = module._base_state(source)
    path = tmp_path / "default-spelling.dxf"
    source.saveas(path)
    reopened = ezdxf.readfile(path)
    module._check_base_state(reopened, expected)
    assert reopened.styles.get("Standard").dxf.owner == reopened.styles.head.dxf.handle


@pytest.mark.parametrize("changed", ["color", "end", "width", "scale", "style_owner", "viewport_center"])
def test_base_canonicalization_keeps_nondefault_geometry_paint_and_owners_strict(changed):
    doc = _explicit_default_base()
    expected = module._base_state(doc)
    if changed == "color":
        doc.modelspace().query("LINE").first.dxf.color = 1
    elif changed == "end":
        doc.modelspace().query("LINE").first.dxf.end = (11, 0)
    elif changed == "width":
        doc.modelspace().query("LWPOLYLINE").first.dxf.const_width = 1
    elif changed == "scale":
        doc.modelspace().query("INSERT").first.dxf.xscale = 2
    elif changed == "style_owner":
        doc.styles.get("Standard").dxf.owner = "DEADBEEF"
    else:
        doc.viewports.get("*Active")[0].dxf.center = (13, 14)
    with pytest.raises(DrawingCopyError, match="existing drawing entity or resource"):
        module._check_base_state(doc, expected)


@pytest.mark.parametrize("changed", ["$GRIDMODE", "$SNAPSTYLE", "$INSUNITS", "$DIMSCALE", "$EXTMIN"])
def test_native_header_flags_units_dimensions_and_arbitrary_bounds_stay_strict(changed):
    doc = ezdxf.readfile(Path(__file__).parent / "fixtures/librecad-2.2.1.5/mm-merged-native-saved.dxf")
    expected = module._header_state(doc)
    if changed in {"$GRIDMODE", "$SNAPSTYLE"}:
        doc.header.hdrvars[changed] = HeaderVar(DXFTag(70, 1))
    elif changed == "$EXTMIN":
        doc.header[changed] = (71, 72, 73)
    else:
        doc.header[changed] = 2
    with pytest.raises(DrawingCopyError, match="header setting"):
        module._check_headers(doc, expected)
