"""Exact native print rehome, physical callback preservation and negatives."""
import base64
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import Mock

import ezdxf
import pytest

from librecad_pdf_importer import drawing_insert as merge
from librecad_pdf_importer import native_plot_settings as plots
from librecad_pdf_importer.drawing_copy import DrawingCopyCancelled, DrawingCopyError

FIXTURE = Path(__file__).parent / "fixtures/librecad-2.2.1.5/public-glyphs-native-saved.dxf"
FIXTURE_SHA = "02a19de450536731d0409ea04a05a1fc648a5812641cbfabd4da4ffa83abaf69"
HANDLE = "DEADBEEF"


def author(path, *, mutation=None):
    document = ezdxf.new("R2010")
    document.units = 4
    document.modelspace().add_line((0, 0), (25, 0))
    if mutation == "valid_existing":
        valid_print_setup(document, "Existing workshop setup", "2x3", [1, 2, 3, 4])
    if mutation in {"physical_reference", "physical_standard_reference"}:
        record = document.objects.add_xrecord(owner=document.rootdict.dxf.handle)
        record.reset([(1005 if mutation == "physical_reference" else 340, HANDLE.lower())])
        document.rootdict.add("AUTHORED_REFERENCE", record)
    document.saveas(path)
    data = path.read_bytes().replace(b"\r\n", b"\n")
    raw = b"  0\nPLOTSETTINGS\n  5\nDEADBEEF\n100\nAcDbPlotSettings\n  6\n1x1\n 40\n0\n 41\n0\n 42\n0\n 43\n0\n"
    if mutation == "changed_value":
        raw = raw.replace(b" 40\n0\n", b" 40\n1\n")
    elif mutation == "extra_owner":
        raw += b"330\n0\n"
    elif mutation in {"owner_00", "owner_dangling", "owner_wrong_live", "owner_without_membership"}:
        owner = {"owner_00": "00", "owner_dangling": "BADC0DE",
            "owner_wrong_live": document.modelspace().query("LINE").first.dxf.handle,
            "owner_without_membership": document.rootdict["ACAD_PLOTSETTINGS"].dxf.handle}[mutation]
        # A real AcDbObject base-class pointer, not an ignored subclass tag.
        raw = raw.replace(b"100\nAcDbPlotSettings\n", b"330\n" + owner.encode() + b"\n100\nAcDbPlotSettings\n")
    marker = b"  2\nOBJECTS\n"
    start = data.index(marker) + len(marker)
    end = data.index(b"  0\nENDSEC\n", start)
    data = data[:end] + raw * (2 if mutation == "duplicate" else 1) + data[end:]
    path.write_bytes(data)
    return path


def retained(path):
    document = ezdxf.readfile(path)
    return document, merge._base_state(document), merge._dictionary_state(document), merge._header_state(document)


def test_real_native_exact_physical_bytes_are_archived_and_output_audit_is_clean(tmp_path):
    assert sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_SHA
    base = author(tmp_path / "base.dxf")
    original = {str(path): path.read_bytes() for path in (base, FIXTURE)}
    result = merge.insert_into_saved_drawing_copy(base, FIXTURE, tmp_path / "copy.dxf")
    archive = result.native_plot_settings_rehome
    assert archive["record_count"] == 2
    assert [row["role"] for row in archive["documents"]] == ["base", "incoming"]
    for row, path, handle in zip(archive["documents"], (base, FIXTURE), (HANDLE, "1F4"), strict=True):
        [plan] = row["records"]
        assert plan["handle"] == handle and plan["physical_and_parsed_incoming_references"] == 0
        assert row["original_input_sha256"] == sha256(original[str(path)]).hexdigest()
        physical = base64.b64decode(plan["physical_record_bytes_base64"], validate=True)
        assert physical in original[str(path)]
        assert sha256(physical).hexdigest() == plan["physical_record_sha256"]
        assert plots._hash_tags(plan["parsed_before_tags"]) == plan["parsed_before_tags_sha256"]
        assert row["before_rehome_state_sha256"] != row["expected_after_rehome_state_sha256"]
        before_tags = [(code, value) for code, value in plan["parsed_before_tags"] if code not in {330, 1}]
        after_tags = [(code, value) for code, value in plan["parsed_after_tags"] if code not in {330, 1}]
        assert before_tags == after_tags
        assert plan["setup_name"] == "Saved drawing print setup"
        assert plan["qualified_physical_parsed_and_rehomed_native_callback"] == {
            "plot_view_name": "1x1", "margins_mm": [0.0] * 4}
    drawing = ezdxf.readfile(result.drawing)
    [plot] = drawing.objects.query("PLOTSETTINGS")
    assert plot.dxf.handle == HANDLE
    dictionary = drawing.rootdict["ACAD_PLOTSETTINGS"]
    assert plot.dxf.owner == dictionary.dxf.handle
    assert dictionary[plot.dxf.page_setup_name] is plot
    assert plots.native_plot_callback_sequence(base) == plots.native_plot_callback_sequence(result.drawing)
    assert archive["print_callback_proof"]["expected_final_ordered_callbacks"] == [{
        "handle": HANDLE, "plot_view_name": "1x1", "margins_mm": [0.0] * 4}]
    audit = ezdxf.readfile(result.drawing).audit()
    assert not audit.errors and not audit.fixes
    records = [record for name, record in drawing.rootdict.items() if name.endswith("_PLOT_REHOME_LEDGER")]
    assert len(records) == 1
    assert all(tag.code == 1 and len(tag.value) <= 200 for tag in records[0].tags)
    assert json.loads("".join(tag.value for tag in records[0].tags)) == archive
    assert all(Path(path).read_bytes() == content for path, content in original.items())
    assert "Not established" in archive["native_Save_archive_retention"]


@pytest.mark.parametrize("mutation", ["physical_reference", "physical_standard_reference", "duplicate", "changed_value", "extra_owner",
    "owner_00", "owner_dangling", "owner_wrong_live", "owner_without_membership"])
@pytest.mark.parametrize("native_role", ["base", "incoming"])
def test_changed_unknown_duplicate_or_referenced_records_never_publish(tmp_path, mutation, native_role):
    native = author(tmp_path / "native.dxf", mutation=mutation)
    other = tmp_path / "other.dxf"
    document = ezdxf.new("R2010")
    document.units = 4
    document.modelspace().add_line((0, 0), (10, 0))
    document.saveas(other)
    base, incoming = (native, other) if native_role == "base" else (other, native)
    before = base.read_bytes()
    incoming_before = incoming.read_bytes()
    target = tmp_path / "copy.dxf"
    with pytest.raises(DrawingCopyError):
        merge.insert_into_saved_drawing_copy(base, incoming, target)
    assert base.read_bytes() == before and incoming.read_bytes() == incoming_before
    assert not target.exists()
    assert not list(tmp_path.glob(".drawing-merge-*"))


@pytest.mark.parametrize("kind", ["dictionary", "header", "parsed_pointer", "table_pointer"])
def test_complete_parsed_reference_closure_rejects_new_links_without_mutation(tmp_path, kind):
    path = author(tmp_path / "authored.dxf")
    document, state, dictionaries, headers = retained(path)
    if kind == "dictionary":
        dictionaries["AUTHORED"] = {"plot": HANDLE.lower()}
    elif kind == "header":
        headers["$CMATERIAL"] = HANDLE.lower()
    elif kind == "parsed_pointer":
        state["AUTHORED"] = [(1005, HANDLE.lower())]
    else:
        document.layers.head.dxf.owner = HANDLE.lower()
    before = path.read_bytes()
    direct = {key: dict(entity.dxfattribs()) for key, entity in document.entitydb.items() if entity.is_alive}
    with pytest.raises(DrawingCopyError, match="parsed drawing reference"):
        plots.qualify_native_plot_settings(path, document, state, dictionaries, headers)
    assert before == path.read_bytes()
    assert direct == {key: dict(entity.dxfattribs()) for key, entity in document.entitydb.items() if entity.is_alive}


def test_wrong_section_does_not_qualify_an_identical_record(tmp_path):
    path = author(tmp_path / "authored.dxf")
    data = path.read_bytes().replace(b"  2\nOBJECTS\n", b"  2\nENTITIES\n")
    path.write_bytes(data)
    assert plots._physical(path, None) == []


def test_handle_duplicate_outside_the_candidate_roster_is_rejected(tmp_path):
    path = author(tmp_path / "authored.dxf")
    document = ezdxf.readfile(path)
    handle = document.modelspace().query("LINE").first.dxf.handle
    data = path.read_bytes().replace(("  5\n" + handle + "\n").encode(), b"  5\nDEADBEEF\n", 1)
    path.write_bytes(data)
    with pytest.raises(DrawingCopyError, match="duplicated or referenced"):
        plots._physical(path, None)
    assert path.read_bytes() == data


def test_physical_cancellation_is_pure_and_never_returns_partial_plans(tmp_path):
    path = author(tmp_path / "authored.dxf")
    before = path.read_bytes()
    calls = []
    def cancel():
        calls.append(True)
        if len(calls) == 10:
            raise DrawingCopyCancelled("bounded physical cancellation")
    with pytest.raises(DrawingCopyCancelled):
        plots._physical(path, cancel)
    assert path.read_bytes() == before


@pytest.mark.parametrize("budget", ["MAX_TAGS", "MAX_RECORDS"])
def test_qualification_budgets_fail_before_mutation(tmp_path, monkeypatch, budget):
    path = author(tmp_path / "authored.dxf")
    document, state, dictionaries, headers = retained(path)
    before = path.read_bytes()
    monkeypatch.setattr(plots, budget, 1)
    with pytest.raises(DrawingCopyError, match="budget"):
        plots.qualify_native_plot_settings(path, document, state, dictionaries, headers)
    assert before == path.read_bytes() and document.entitydb.get(HANDLE).is_alive


def test_second_document_cancel_never_applies_the_first_document_plan(tmp_path, monkeypatch):
    base = author(tmp_path / "base.dxf")
    incoming = author(tmp_path / "incoming.dxf")
    before = base.read_bytes(), incoming.read_bytes()
    original = merge.qualify_native_plot_settings
    called = []
    def qualify(*args, **kwargs):
        called.append(str(args[0]))
        if len(called) == 2:
            raise DrawingCopyCancelled("deliberate second-document stop")
        return original(*args, **kwargs)
    applied = Mock()
    monkeypatch.setattr(merge, "qualify_native_plot_settings", qualify)
    monkeypatch.setattr(merge, "apply_native_plot_settings", applied)
    with pytest.raises(DrawingCopyCancelled):
        merge.insert_into_saved_drawing_copy(base, incoming, tmp_path / "copy.dxf")
    assert len(called) == 2 and not applied.called
    assert (base.read_bytes(), incoming.read_bytes()) == before
    assert not (tmp_path / "copy.dxf").exists()


def test_qualified_entity_change_cannot_be_rehomed(tmp_path):
    path = author(tmp_path / "authored.dxf")
    document, state, dictionaries, headers = retained(path)
    plans = plots.qualify_native_plot_settings(path, document, state, dictionaries, headers)
    document.entitydb[HANDLE].dxf.paper_width = 999
    with pytest.raises(DrawingCopyError, match="changed"):
        plots.apply_native_plot_settings(document, plans)
    assert document.entitydb[HANDLE].is_alive


def test_changed_standard_dictionary_cannot_apply_or_partially_rehome(tmp_path):
    path = author(tmp_path / "authored.dxf")
    document, state, dictionaries, headers = retained(path)
    plans = plots.qualify_native_plot_settings(path, document, state, dictionaries, headers)
    valid_print_setup(document, "Unexpected setup", "2x3", [1, 2, 3, 4])
    before = dict(document.entitydb[HANDLE].dxfattribs())
    with pytest.raises(DrawingCopyError, match="dictionary changed"):
        plots.apply_native_plot_settings(document, plans)
    assert document.entitydb[HANDLE].dxfattribs() == before


def valid_print_setup(document, name, tiling, margins):
    dictionary = document.rootdict["ACAD_PLOTSETTINGS"]
    entity = document.objects.new_entity("PLOTSETTINGS", dxfattribs={
        "owner": dictionary.dxf.handle, "page_setup_name": name,
        "plot_view_name": tiling, "left_margin": margins[0], "bottom_margin": margins[1],
        "right_margin": margins[2], "top_margin": margins[3]})
    dictionary.add(name, entity)
    return entity


def test_existing_print_callbacks_order_values_and_readable_name_collision_are_preserved(tmp_path):
    # Genuine standard owned setups surround two exact native orphan records.
    # Native addPlotSettings applies every callback, so dropping/reordering
    # either zero-valued record changes the final or intermediate print state.
    base = tmp_path / "base.dxf"
    document = ezdxf.new("R2010")
    document.units = 4
    document.modelspace().add_line((0, 0), (25, 0))
    first = valid_print_setup(document, "Saved drawing print setup", "2x3", [1, 2, 3, 4])
    last = valid_print_setup(document, "Workshop plot", "4x5", [5, 6, 7, 8])
    first_handle, last_handle = first.dxf.handle, last.dxf.handle
    document.saveas(base)
    data = base.read_bytes().replace(b"\r\n", b"\n")
    raw = b"  0\nPLOTSETTINGS\n  5\nDEADBEEF\n100\nAcDbPlotSettings\n  6\n1x1\n 40\n0\n 41\n0\n 42\n0\n 43\n0\n"
    marker = b"  0\nPLOTSETTINGS\n  5\n" + last_handle.encode() + b"\n"
    data = data.replace(marker, raw + marker, 1)
    end = data.index(b"  0\nENDSEC\n", data.index(b"  2\nOBJECTS\n"))
    data = data[:end] + raw.replace(b"DEADBEEF", b"DEADBEE0") + data[end:]
    base.write_bytes(data)
    incoming = author(tmp_path / "incoming.dxf")
    original = base.read_bytes(), incoming.read_bytes()
    result = merge.insert_into_saved_drawing_copy(base, incoming, tmp_path / "copy.dxf")
    expected = [
        {"handle": first_handle, "plot_view_name": "2x3", "margins_mm": [1.0, 2.0, 3.0, 4.0]},
        {"handle": HANDLE, "plot_view_name": "1x1", "margins_mm": [0.0] * 4},
        {"handle": last_handle, "plot_view_name": "4x5", "margins_mm": [5.0, 6.0, 7.0, 8.0]},
        {"handle": "DEADBEE0", "plot_view_name": "1x1", "margins_mm": [0.0] * 4}]
    assert plots.native_plot_callback_sequence(base) == expected
    assert plots.native_plot_callback_sequence(result.drawing) == expected
    rows = result.native_plot_settings_rehome["documents"]
    assert [plan["setup_name"] for plan in rows[0]["records"]] == [
        "Saved drawing print setup 2", "Saved drawing print setup 3"]
    output = ezdxf.readfile(result.drawing)
    assert list(output.rootdict["ACAD_PLOTSETTINGS"].keys()) == [
        "Saved drawing print setup", "Workshop plot", "Saved drawing print setup 2", "Saved drawing print setup 3"]
    assert (base.read_bytes(), incoming.read_bytes()) == original


def test_callback_defaults_and_last_native_value_are_bound_to_physical_tags(tmp_path):
    path = tmp_path / "callbacks.dxf"
    path.write_bytes(b"0\nSECTION\n2\nOBJECTS\n0\nPLOTSETTINGS\n5\nA\n6\n2x3\n6\n4x5\n40\n3\n40\n7\n1\nIgnored name\n330\nB\n0\nPLOTSETTINGS\n5\nC\n0\nENDSEC\n0\nEOF\n")
    assert plots.native_plot_callback_sequence(path) == [
        {"handle": "A", "plot_view_name": "4x5", "margins_mm": [7.0, 0.0, 0.0, 0.0]},
        {"handle": "C", "plot_view_name": "", "margins_mm": [0.0] * 4}]


@pytest.mark.parametrize("mutation", ["reorder", "extra_callback", "changed_margin", "changed_tiling"])
def test_final_physical_print_callback_changes_cannot_publish(tmp_path, monkeypatch, mutation):
    base = author(tmp_path / "base.dxf", mutation="valid_existing" if mutation == "reorder" else None)
    incoming = author(tmp_path / "incoming.dxf")
    original = base.read_bytes(), incoming.read_bytes()
    write = merge._write_merged_drawing
    def altered_write(document, stream):
        entity = document.entitydb[HANDLE]
        if mutation == "changed_margin":
            entity.dxf.left_margin = 5
        elif mutation == "changed_tiling":
            entity.dxf.plot_view_name = "2x3"
        elif mutation == "extra_callback":
            valid_print_setup(document, "Injected setup", "2x3", [1, 2, 3, 4])
        else:
            # Same entities/dictionary/tags, changed native callback order.
            existing = next(item for item in document.objects.query("PLOTSETTINGS") if item.dxf.handle != HANDLE)
            document.objects._entity_space.remove(existing)
            document.objects._entity_space.add(existing)
        write(document, stream)
    monkeypatch.setattr(merge, "_write_merged_drawing", altered_write)
    with pytest.raises(DrawingCopyError):
        merge.insert_into_saved_drawing_copy(base, incoming, tmp_path / "copy.dxf")
    assert not (tmp_path / "copy.dxf").exists()
    assert (base.read_bytes(), incoming.read_bytes()) == original
