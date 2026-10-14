"""Exact public native fixture and bounded zero-Z interoperability controls."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

import ezdxf
from ezdxf.disassemble import recursive_decompose
from ezdxf.entities import MText
from ezdxf.math import Matrix44
import pytest

from librecad_pdf_importer import drawing_insert as merge
from librecad_pdf_importer.drawing_copy import DrawingCopyCancelled, DrawingCopyError
from librecad_pdf_importer.planar_blocks import qualify_planar_insert_repairs
from plot_rehome_assertions import bind_print_rehome

FIXTURE = Path(__file__).parent / "fixtures/librecad-2.2.1.5/public-glyphs-native-saved.dxf"
FIXTURE_SHA = "02a19de450536731d0409ea04a05a1fc648a5812641cbfabd4da4ffa83abaf69"


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def scene():
    document = ezdxf.new("R2007")
    document.units = 4
    child = document.blocks.new("PUBLIC_CHILD")
    child.add_solid([(0, 0), (2, 0), (0, 3), (2, 3)], dxfattribs={"true_color": 0x123456})
    parent = document.blocks.new("PUBLIC_PARENT", base_point=(1, 2))
    parent.add_blockref(child.name, (4, 5), dxfattribs={"xscale": -2, "yscale": 3, "zscale": 0, "rotation": 17})
    for insert, sx, sy in (((8, 9), 2, .5), ((-5, 4), -3, 2)):
        document.modelspace().add_blockref(parent.name, insert,
            dxfattribs={"xscale": sx, "yscale": sy, "zscale": 0, "rotation": 31})
    # Normal constructors sanitize zero to1. Native DXF loading retains the
    # authored invalid scale, as the exact real fixture proves. Use the same
    # unprotected namespace write to simulate that parsed native value here.
    for entity in document.entitydb.values():
        if entity.is_alive and entity.dxftype() == "INSERT":
            entity.dxf.unprotected_set("zscale", 0.0)
    return document


def forward_points(document):
    """Independent direct matrices retain singular-source behavior."""
    points = []
    def walk(layout, parent):
        for entity in layout:
            if entity.dxftype() == "INSERT":
                walk(document.blocks.get(entity.dxf.name), entity.matrix44() @ parent)
            elif entity.dxftype() == "SOLID":
                points.extend(tuple(parent.transform(getattr(entity.dxf, "vtx" + str(index)))) for index in range(4))
    walk(document.modelspace(), Matrix44())
    return points


def allowed_state(original, records):
    expected = dict(original)
    for row in records:
        handle = row["handle"]
        tags = original[handle]
        assert sum(code == 43 and value == 0 for code, value in tags) == 1
        expected[handle] = [(code, value) for code, value in tags if code != 43]
        assert row["parsed_tags_before_sha256"] == merge._state_hash(tags)
        assert row["parsed_tags_after_sha256"] == merge._state_hash(expected[handle])
    return expected


@pytest.mark.parametrize("role", ["base", "incoming"])
def test_actual_native_fixture_repairs_15_inserts_with_physical_ledger_and_original_paint(role, tmp_path):
    assert digest(FIXTURE) == FIXTURE_SHA
    other = tmp_path / "other.dxf"
    document = ezdxf.new("R2007"); document.units = 4
    document.modelspace().add_line((0, 0), (5, 4), dxfattribs={"true_color": 0x123456})
    document.saveas(other)
    base, incoming = (FIXTURE, other) if role == "base" else (other, FIXTURE)
    source_hashes = digest(base), digest(incoming)
    original_base = ezdxf.readfile(base)
    original_state = merge._base_state(original_base)
    original_source = ezdxf.readfile(incoming)
    original_source_state = merge._base_state(original_source)
    original_planar = qualify_planar_insert_repairs(ezdxf.readfile(FIXTURE))
    assert len(original_planar) == 15
    assert merge._base_state(original_base) == original_state
    with pytest.raises(ZeroDivisionError):
        list(recursive_decompose(ezdxf.readfile(FIXTURE).modelspace()))
    target = tmp_path / "copy.dxf"
    result = merge.insert_into_saved_drawing_copy(base, incoming, target)
    physical = ezdxf.readfile(target)
    ledger = result.planar_insert_repair_ledger
    assert ledger["repair_count"] == 15 and ledger["original_inputs_unchanged"] is True
    assert [row["role"] for row in ledger["documents"]] == ["base", "incoming"]
    for row, path in zip(ledger["documents"], (base, incoming), strict=True):
        assert row["input_file_sha256"] == digest(path)
    base_expected = allowed_state(original_state, ledger["documents"][0]["repairs"])
    base_expected = bind_print_rehome(result, original_base, base_expected, physical, base, incoming)
    merge._check_base_state(physical, base_expected)
    source_expected = allowed_state(original_source_state, ledger["documents"][1]["repairs"])
    for row in ledger["documents"][1]["repairs"]:
        original_source.entitydb[row["handle"]].dxf.zscale = 1.0
    assert merge._base_state(original_source) == source_expected
    assert merge._semantic_digest(physical.blocks.get(result.block_name).entities_in_redraw_order(), physical) == \
        merge._semantic_digest(original_source.modelspace().entities_in_redraw_order(), original_source)
    leaf_counts = Counter(entity.dxftype() for entity in recursive_decompose(physical.modelspace()))
    assert leaf_counts["SOLID"] == 545
    solids = [entity for entity in physical.entitydb.values() if entity.is_alive and entity.dxftype() == "SOLID"]
    assert solids and all(entity.dxf.get("true_color") is None and entity.dxf.color == 7 for entity in solids)
    records = [record for _, record in physical.rootdict.items() if record.dxftype() == "XRECORD"
               and record.tags and all(tag.code == 1 for tag in record.tags)]
    persisted = [json.loads("".join(tag.value for tag in record.tags)) for record in records]
    assert ledger in persisted
    assert (digest(base), digest(incoming)) == source_hashes and digest(FIXTURE) == FIXTURE_SHA


def test_nested_shared_mirrored_nonuniform_ledger_changes_only43_and_exact_world_points(tmp_path):
    document = scene()
    before_points = forward_points(document)
    before = merge._base_state(document)
    plans = qualify_planar_insert_repairs(document)
    assert len(plans) == 3 and merge._base_state(document) == before
    expected, ledger = merge._planar_repair_expectations(before, plans, "base", "0" * 64, "1" * 64)
    merge._apply_planar_repairs(document, plans)
    merge._check_base_state(document, expected)
    assert expected == allowed_state(before, ledger["repairs"])
    assert forward_points(document) == before_points
    path = tmp_path / "physical.dxf"; document.saveas(path)
    physical = ezdxf.readfile(path)
    assert len(list(recursive_decompose(physical.modelspace()))) == 2
    assert forward_points(physical) == before_points
    physical.blocks.get("PUBLIC_CHILD").query("SOLID").first.dxf.true_color = 0x654321
    with pytest.raises(DrawingCopyError, match="existing drawing"):
        merge._check_base_state(physical, expected)


@pytest.mark.parametrize("change", ["tilt", "local_z", "insert_z", "base_z", "thickness", "array",
    "missing", "cycle", "unknown", "nonfinite", "overflow", "attribute_z", "polyline_vertex_z", "spline_tangent_z", "image_vector_z"])
def test_unqualified_closures_fail_without_mutation(change):
    document = scene()
    child = document.blocks.get("PUBLIC_CHILD")
    parent = document.blocks.get("PUBLIC_PARENT")
    instance = document.modelspace().query("INSERT").first
    if change == "tilt": instance.dxf.extrusion = (1, 0, 0)
    elif change == "local_z": child.query("SOLID").first.dxf.vtx0 = (0, 0, 1)
    elif change == "insert_z": instance.dxf.insert = (1, 2, 1)
    elif change == "base_z": parent.block.dxf.base_point = (0, 0, 1)
    elif change == "thickness": child.query("SOLID").first.dxf.thickness = 1
    elif change == "array": instance.dxf.column_count = 2
    elif change == "missing": instance.dxf.name = "PUBLIC_MISSING"
    elif change == "cycle": child.add_blockref(parent.name, (0, 0))
    elif change == "unknown": child.add_ray((0, 0), (1, 1))
    elif change == "nonfinite": instance.dxf.xscale = float("nan")
    elif change == "overflow": instance.dxf.xscale = 1e308
    elif change == "attribute_z": instance.add_attrib("PUBLIC_TAG", "public", (0, 0, 1))
    elif change == "polyline_vertex_z": child.add_polyline3d([(0, 0, 0), (1, 2, 1)])
    elif change == "spline_tangent_z":
        spline = child.add_open_spline([(0, 0), (1, 2), (3, 4), (5, 6)])
        spline.dxf.start_tangent = (1, 2, 1)
    else:
        definition = document.add_image_def(filename="PUBLIC_MISSING.png", size_in_pixel=(2, 2))
        image = child.add_image(definition, (0, 0), (2, 2)); image.dxf.u_pixel = (1, 0, 1)
    before = merge._base_state(document)
    with pytest.raises(DrawingCopyError):
        qualify_planar_insert_repairs(document)
    assert merge._base_state(document) == before


def test_depth_work_budget_and_mid_proof_cancel_are_bounded_and_pure():
    document = scene(); before = merge._base_state(document)
    for options in ({"max_depth": 1}, {"max_records": 1}):
        with pytest.raises(DrawingCopyError): qualify_planar_insert_repairs(document, **options)
    calls = 0
    def cancelled():
        nonlocal calls
        calls += 1
        if calls == 8:
            raise DrawingCopyCancelled("public mid-proof stop")
    with pytest.raises(DrawingCopyCancelled): qualify_planar_insert_repairs(document, cancel_check=cancelled)
    assert calls == 8 and merge._base_state(document) == before


def test_invalid_incoming_qualifies_neither_mutation_nor_publication(tmp_path, monkeypatch):
    base, incoming, target = [tmp_path / name for name in ("base.dxf", "incoming.dxf", "copy.dxf")]
    scene().saveas(base)
    invalid = scene(); invalid.blocks.get("PUBLIC_CHILD").query("SOLID").first.dxf.vtx0 = (0, 0, 1)
    invalid.saveas(incoming)
    originals = digest(base), digest(incoming)
    mutations = []
    monkeypatch.setattr(merge, "_apply_planar_repairs", lambda *args: mutations.append(args))
    with pytest.raises(DrawingCopyError): merge.insert_into_saved_drawing_copy(base, incoming, target)
    assert not mutations and not target.exists() and (digest(base), digest(incoming)) == originals
    assert {path.name for path in tmp_path.iterdir()} == {"base.dxf", "incoming.dxf"}


def curved_scene():
    document = scene(); child = document.blocks.get("PUBLIC_CHILD")
    child.add_circle((4, 5), 2)
    child.add_arc((4, 5), 2, 10, 280)
    child.add_ellipse((4, 5), major_axis=(3, 2), ratio=.5)
    child.add_open_spline([(0, 0), (1, 2), (3, 4), (5, 6)])
    child.add_lwpolyline([(0, 0, 0, 0, 1), (2, 0, 0, 0, 0)], format="xyseb")
    child.add_polyline2d([(0, 0), (1, 1), (2, 0)])
    child.add_text("PUBLIC text", dxfattribs={"insert": (1, 2), "align_point": (3, 4)})
    child.add_mtext("PUBLIC paragraph", dxfattribs={"insert": (3, 4), "text_direction": (1, 2, 0)})
    child.add_attdef("PUBLIC_TAG", (2, 3), "public attribute definition")
    parent = document.blocks.get("PUBLIC_PARENT").query("INSERT").first
    parent.add_attrib("PUBLIC_TAG", "public attached attribute", (2, 3))
    hatch = child.add_hatch()
    edges = hatch.paths.add_edge_path()
    edges.add_line((0, 0), (3, 4))
    edges.add_arc((3, 4), radius=2)
    edges.add_ellipse((3, 4), major_axis=(2, 1), ratio=.5)
    edges.add_spline(control_points=[(0, 0), (1, 2), (3, 4), (5, 6)],
                     knot_values=[0, 0, 0, 0, 1, 1, 1, 1], degree=3,
                     start_tangent=(1, 2), end_tangent=(3, 4))
    hatch.paths.add_polyline_path([(0, 0, 1), (2, 0, 0)], is_closed=True)
    definition = document.add_image_def(filename="PUBLIC_IMAGE.png", size_in_pixel=(2, 2))
    child.add_image(definition, (0, 0), (2, 2))
    return document


def test_curved_payloads_attributes_images_and_font_bindings_are_fully_preserved():
    document = curved_scene(); before = merge._base_state(document)
    plans = qualify_planar_insert_repairs(document)
    assert len(plans) == 3 and merge._base_state(document) == before
    expected, ledger = merge._planar_repair_expectations(before, plans, "base", "0" * 64, "1" * 64)
    merge._apply_planar_repairs(document, plans)
    merge._check_base_state(document, expected)
    assert expected == allowed_state(before, ledger["repairs"])


@pytest.mark.parametrize("change", ["spline_control", "spline_fit", "hatch_weight", "hatch_tangent",
                                    "text_alignment", "mtext_direction", "ancestor_z"])
def test_curved_or_shared_context_definitions_are_not_inferred_from_a_point_roster(change):
    document = curved_scene(); child = document.blocks.get("PUBLIC_CHILD")
    if change == "spline_control":
        spline = child.query("SPLINE").first
        spline.control_points = [(0, 0, 1), (1, 2, 0), (3, 4, 0), (5, 6, 0)]
    elif change == "spline_fit": child.query("SPLINE").first.fit_points = [(0, 0, 1)]
    elif change in {"hatch_weight", "hatch_tangent"}:
        edge = next(edge for edge in child.query("HATCH").first.paths[0].edges if type(edge).__name__ == "SplineEdge")
        if change == "hatch_weight": edge.weights = [-1, 1, 1, 1]
        else: edge.start_tangent = (1, float("inf"))
    elif change == "text_alignment": child.query("TEXT").first.dxf.align_point = (0, 0, 1)
    elif change == "mtext_direction": child.query("MTEXT").first.dxf.text_direction = (1, 2, 1)
    else:
        outer = document.blocks.new("PUBLIC_ANCESTOR")
        outer.add_blockref("PUBLIC_PARENT", (0, 0, 1))
        document.modelspace().add_blockref(outer.name, (0, 0))
    before = merge._base_state(document)
    with pytest.raises(DrawingCopyError): qualify_planar_insert_repairs(document)
    assert merge._base_state(document) == before


def test_original_snapshots_reject_a_mutation_during_qualification_before_repair(tmp_path, monkeypatch):
    base, incoming, target = [tmp_path / name for name in ("base.dxf", "incoming.dxf", "copy.dxf")]
    scene().saveas(base); scene().saveas(incoming)
    originals = digest(base), digest(incoming)
    qualifier = merge.qualify_planar_insert_repairs
    def altered(document, **options):
        plans = qualifier(document, **options)
        document.blocks.get("PUBLIC_CHILD").query("SOLID").first.dxf.true_color = 0x654321
        return plans
    monkeypatch.setattr(merge, "qualify_planar_insert_repairs", altered)
    applied = []
    monkeypatch.setattr(merge, "_apply_planar_repairs", lambda *args: applied.append(args))
    with pytest.raises(DrawingCopyError, match="existing drawing"):
        merge.insert_into_saved_drawing_copy(base, incoming, target)
    assert not applied and not target.exists() and (digest(base), digest(incoming)) == originals


def hidden_text_scene(kind, *, hidden_z=1, version=None):
    """Public authored definitions whose hidden payload is outside block iteration."""
    document = ezdxf.new(version or ("R2007" if kind == "columns" else "R2018"))
    document.units = 4
    block = document.blocks.new("PUBLIC_HIDDEN_TEXT")
    insert = document.modelspace().add_blockref(block.name, (0, 0))
    insert.dxf.unprotected_set("zscale", 0.0)
    if kind == "columns":
        text = block.add_mtext_static_columns(["PUBLIC first", "PUBLIC second"],
            width=4, gutter_width=1, height=5, dxfattribs={"insert": (0, 0)})
        if text.columns.linked_columns:
            text.columns.linked_columns[0].dxf.insert = (5, 0, hidden_z)
    else:
        text = (block.add_attdef("PUBLIC_TAG", (0, 0), "PUBLIC definition")
                if kind == "attdef" else insert.add_attrib("PUBLIC_TAG", "PUBLIC value", (0, 0)))
        embedded = MText.new(dxfattribs={"insert": (0, 0, hidden_z), "char_height": 1})
        embedded.text = "PUBLIC multiline"
        text.embed_mtext(embedded)
        # The ordinary TEXT coordinates are valid, while the actual embedded
        # MTEXT remains nonplanar. A point roster of outer attrs is incomplete.
        text.dxf.insert = (0, 0, 0)
        text.dxf.align_point = (0, 0, 0)
    return document, text


def direct_entity_fields(document, text):
    """Read fields directly: TagCollector itself could synchronize columns."""
    fields = {str(entity.dxf.handle): merge._plain(entity.dxfattribs())
              for entity in document.entitydb.values() if entity.is_alive}
    if text.dxftype() == "MTEXT":
        fields["hidden_columns"] = [merge._plain(column.dxfattribs())
                                    for column in text.columns.linked_columns]
    else:
        fields["hidden_mtext"] = merge._plain(text.virtual_mtext_entity().dxfattribs())
    return fields


@pytest.mark.parametrize("kind", ["attdef", "attrib", "columns"])
def test_physically_saved_hidden_nonzero_z_payload_is_rejected_before_serialization(kind, tmp_path, monkeypatch):
    document, _ = hidden_text_scene(kind)
    path = tmp_path / "public-hidden-text.dxf"
    document.saveas(path)
    original_sha = digest(path)
    physical = ezdxf.readfile(path)
    text = (physical.query("MTEXT").first if kind == "columns" else
            physical.query("ATTDEF").first if kind == "attdef" else
            physical.modelspace().query("INSERT").first.attribs[0])
    position = (text.columns.linked_columns[0].dxf.insert if kind == "columns"
                else text.virtual_mtext_entity().dxf.insert)
    assert position.z == 1 and text.dxf.insert.z == 0
    root = physical.modelspace().query("INSERT").first
    assert root.dxf.zscale == 0
    if kind != "attrib":
        # These real stored definitions change Z under the proposed scale
        # delta even though all ordinary outer text coordinates are flat.
        assert root.matrix44().transform(position).z == 0
        repaired = root.copy(); repaired.dxf.zscale = 1
        assert repaired.matrix44().transform(position).z == 1
    before = direct_entity_fields(physical, text)
    def unexpected_export(*args):
        pytest.fail("Unsupported hidden text must be screened before tag export")
    monkeypatch.setattr(type(text), "export_dxf", unexpected_export)
    monkeypatch.setattr(type(root), "export_dxf", unexpected_export)
    with pytest.raises(DrawingCopyError, match="complete geometry"):
        qualify_planar_insert_repairs(physical)
    assert direct_entity_fields(physical, text) == before and digest(path) == original_sha


@pytest.mark.parametrize("kind,version", [("attdef", "R2018"), ("attrib", "R2018"),
                                        ("columns", "R2007"), ("columns", "R2018")])
def test_even_flat_hidden_text_is_conservatively_unqualified_and_qualifier_is_pure(kind, version, monkeypatch):
    document, text = hidden_text_scene(kind, hidden_z=0, version=version)
    if kind == "columns" and text.columns.linked_columns:
        linked = text.columns.linked_columns[0]
        # MTEXT.preprocess_export copies common fields from the main MTEXT.
        # A direct attribute snapshot catches that side effect independently.
        linked.dxf.layer = "PUBLIC_INDEPENDENT_COLUMN"
        linked.dxf.color = 3
    before = direct_entity_fields(document, text)
    def unexpected_export(*args):
        pytest.fail("Hidden text and its INSERT must not enter the tag serializer")
    monkeypatch.setattr(type(text), "export_dxf", unexpected_export)
    monkeypatch.setattr(type(document.modelspace().query("INSERT").first), "export_dxf", unexpected_export)
    with pytest.raises(DrawingCopyError, match="complete geometry"):
        qualify_planar_insert_repairs(document)
    assert direct_entity_fields(document, text) == before


@pytest.mark.parametrize("kind", ["attdef", "attrib", "columns"])
@pytest.mark.parametrize("role", ["base", "incoming"])
def test_hidden_text_never_publishes_or_applies_partial_scale_repairs(kind, role, tmp_path, monkeypatch):
    other, invalid, target = [tmp_path / name for name in ("other.dxf", "hidden.dxf", "copy.dxf")]
    scene().saveas(other)
    hidden, _ = hidden_text_scene(kind)
    hidden.saveas(invalid)
    base, incoming = (invalid, other) if role == "base" else (other, invalid)
    originals = digest(base), digest(incoming)
    applied = []
    monkeypatch.setattr(merge, "_apply_planar_repairs", lambda *args: applied.append(args))
    with pytest.raises(DrawingCopyError):
        merge.insert_into_saved_drawing_copy(base, incoming, target)
    assert not applied and not target.exists() and (digest(base), digest(incoming)) == originals
    assert {path.name for path in tmp_path.iterdir()} == {"other.dxf", "hidden.dxf"}
