"""The post-write verification re-opens a reduced copy of the serialized candidate.

Bulk geometry (LINE, LWPOLYLINE, ARC, ...) that no delivery or image references is
syntax-checked in a streaming pass and left out of the copy; everything the
verification inspects is re-read from the exact written bytes.  These tests pin what
the streaming pass must accept, what it must refuse, that the count proof catches a
vanished entity, and that a reduced copy can never refuse what the full file accepts.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Dict, List
from unittest.mock import patch

import ezdxf
import pytest

from librecad_pdf_importer.exporters import dxf_exporter as exporter

_HANDLE_TAG = re.compile(r"\n  5\r?\n([0-9A-Fa-f]+)\r?\n")


def _synthetic_dxf(path: Path, *, lines: int = 400) -> tuple[ezdxf.document.Drawing, list[str]]:
    doc = ezdxf.new("R2010")
    doc.styles.new(
        "BCS Unicode",
        dxfattribs={"font": "assets/00112233445566778899aabbccddeeff/fonts/x.ttf"},
    )
    msp = doc.modelspace()
    handles: list[str] = []
    for index in range(lines):
        entity = msp.add_line((index, 0.0), (index, 1.0), dxfattribs={"layer": "0"})
        handles.append(str(entity.dxf.handle))
    text = msp.add_text("3/8", dxfattribs={"layer": "0", "height": 2.5})
    outline = msp.add_lwpolyline([(0, 0), (1, 0), (1, 1)], dxfattribs={"layer": "0"})
    image_def = doc.add_image_def(
        filename="assets/00112233445566778899aabbccddeeff/images/tile.png",
        size_in_pixel=(10, 10),
    )
    doc.saveas(str(path))
    return doc, [str(text.dxf.handle), str(outline.dxf.handle), handles[0], str(image_def.dxf.handle)]


def _owner_handle(doc: ezdxf.document.Drawing) -> str:
    return str(doc.modelspace().block_record.dxf.handle)


def _index(path: Path) -> exporter._DxfRecordIndex:
    return exporter._DxfRecordIndex(path.read_bytes().decode("utf-8"))


def _entity_records(index: exporter._DxfRecordIndex, type_name: str) -> List[int]:
    """Record numbers of every ``type_name`` entity inside the ENTITIES section."""

    found: List[int] = []
    section = None
    for record in range(len(index)):
        kind = index.record_type(record)
        if kind == "SECTION":
            section = index.record_values(record, "2")[0]
        elif kind == "ENDSEC":
            section = None
        elif section == "ENTITIES" and kind == type_name:
            found.append(record)
    return found


def _handle_of(record_text: str) -> str:
    match = _HANDLE_TAG.search(record_text)
    assert match, record_text[:80]
    return match.group(1)


def _rewrite(path: Path, transforms: Dict[int, Callable[[str], str]]) -> None:
    """Rebuild the file record by record, transforming the listed records' text."""

    index = _index(path)
    parts = []
    for record in range(len(index)):
        text = index.record_text(record)
        transform = transforms.get(record)
        parts.append(transform(text) if transform else text)
    path.write_bytes("".join(parts).encode("utf-8"))


def _swap_handle(new_handle: str) -> Callable[[str], str]:
    return lambda text: _HANDLE_TAG.sub(
        lambda match: match.group(0).replace(match.group(1), new_handle), text, count=1
    )


def test_record_index_reproduces_the_file_byte_for_byte(tmp_path: Path) -> None:
    path = tmp_path / "candidate.dxf"
    _synthetic_dxf(path, lines=25)
    original = path.read_bytes().decode("utf-8")
    index = exporter._DxfRecordIndex(original)
    assert "".join(index.record_text(record) for record in range(len(index))) == original
    assert index.record_type(0) == "SECTION"
    # The HEADER section has no group-0 tags inside it, so its variables ride
    # along in the SECTION record; the section name is the first code-2 value.
    assert index.record_values(0, "2")[0] == "HEADER"


def test_reduced_copy_keeps_addressed_records_and_leaves_out_only_validated_bulk(tmp_path: Path) -> None:
    path = tmp_path / "candidate.dxf"
    doc, keep = _synthetic_dxf(path)
    reduced, dropped = exporter._reduced_verification_copy(path, set(keep), _owner_handle(doc))
    assert dropped == 400 - 1  # one LINE handle is in the keep set
    copy = ezdxf.readfile(str(reduced))
    msp = copy.modelspace()
    assert len(msp) + dropped == len(doc.modelspace())
    present = {str(entity.dxf.handle) for entity in msp}
    assert set(keep[:3]) <= present
    assert {entity.dxftype() for entity in msp} == {"LINE", "TEXT", "LWPOLYLINE"}
    assert copy.objects.query("IMAGEDEF")[0].dxf.filename.endswith("tile.png")
    assert copy.styles.get("BCS Unicode").dxf.font.endswith("x.ttf")
    assert not copy.audit().has_errors


def test_full_redraw_order_does_not_pin_bulk_entities(tmp_path: Path) -> None:
    """Pages with images sort every entity; the table is copied, the geometry still leaves."""
    path = tmp_path / "sorted.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    lines = [msp.add_line((0, index), (1, index)) for index in range(3)]
    text = msp.add_text("A")
    msp.set_redraw_order([(str(entity.dxf.handle), f"{index:X}") for index, entity in enumerate(msp, 1)])
    doc.saveas(str(path))
    reduced, dropped = exporter._reduced_verification_copy(path, {str(lines[0].dxf.handle)}, _owner_handle(doc))
    assert dropped == 2
    copy = ezdxf.readfile(str(reduced))
    assert {str(entity.dxf.handle) for entity in copy.modelspace()} == {
        str(lines[0].dxf.handle),
        str(text.dxf.handle),
    }
    assert len(copy.objects.query("SORTENTSTABLE")[0]) == 4  # table copied verbatim
    assert not copy.audit().has_errors


def test_redraw_order_naming_a_missing_entity_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "sorted.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    line = msp.add_line((0, 0), (1, 0))
    msp.set_redraw_order([(str(line.dxf.handle), "1"), ("FFFFF0", "2")])
    doc.saveas(str(path))
    with pytest.raises(RuntimeError, match="redraw order references a missing entity FFFFF0"):
        exporter._reduced_verification_copy(path, set(), _owner_handle(doc))


def test_bulk_entities_outside_the_modelspace_are_kept(tmp_path: Path) -> None:
    path = tmp_path / "paper.dxf"
    doc = ezdxf.new("R2010")
    doc.modelspace().add_line((0, 0), (1, 0))
    paper_line = doc.paperspace().add_line((0, 0), (2, 0))
    doc.saveas(str(path))
    reduced, dropped = exporter._reduced_verification_copy(path, set(), _owner_handle(doc))
    assert dropped == 1
    copy = ezdxf.readfile(str(reduced))
    assert copy.entitydb.get(str(paper_line.dxf.handle)) is not None


def test_duplicate_bulk_handle_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "candidate.dxf"
    doc, keep = _synthetic_dxf(path, lines=40)
    index = _index(path)
    victim, donor = _entity_records(index, "LINE")[3:5]
    _rewrite(path, {donor: _swap_handle(_handle_of(index.record_text(victim)))})
    with pytest.raises(RuntimeError, match="repeats entity handle"):
        exporter._reduced_verification_copy(path, set(keep), _owner_handle(doc))


def test_bulk_record_sharing_a_handle_with_a_kept_entity_is_refused(tmp_path: Path) -> None:
    """The census covers every entity, so a LINE colliding with a TEXT handle never vanishes."""
    path = tmp_path / "candidate.dxf"
    doc, keep = _synthetic_dxf(path, lines=40)
    index = _index(path)
    victim = _entity_records(index, "LINE")[7]
    _rewrite(path, {victim: _swap_handle(keep[0])})
    with pytest.raises(RuntimeError, match="repeats entity handle"):
        exporter._reduced_verification_copy(path, set(keep), _owner_handle(doc))


def test_bulk_record_without_a_handle_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "candidate.dxf"
    doc, keep = _synthetic_dxf(path, lines=40)
    index = _index(path)
    victim = _entity_records(index, "LINE")[3]
    _rewrite(path, {victim: lambda text: _HANDLE_TAG.sub("\n", text, count=1)})
    with pytest.raises(RuntimeError, match="has 0 handle tags"):
        exporter._reduced_verification_copy(path, set(keep), _owner_handle(doc))


def test_bulk_record_with_a_malformed_handle_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "candidate.dxf"
    doc, keep = _synthetic_dxf(path, lines=40)
    index = _index(path)
    victim = _entity_records(index, "LINE")[3]
    _rewrite(path, {victim: _swap_handle("XYZ")})
    with pytest.raises(RuntimeError, match="malformed handle 'XYZ'"):
        exporter._reduced_verification_copy(path, set(keep), _owner_handle(doc))


def test_stray_line_falls_through_to_the_full_load_which_refuses_it(tmp_path: Path) -> None:
    """One stray line makes the whole file unpairable: no reduced copy, full load, refused."""
    path = tmp_path / "candidate.dxf"
    doc, keep = _synthetic_dxf(path, lines=10)
    index = _index(path)
    victim = _entity_records(index, "LINE")[0]
    _rewrite(path, {victim: lambda text: text + "999\r\n"})
    with pytest.raises(ezdxf.DXFStructureError):
        exporter._reopen_candidate_for_verification(
            path,
            keep_handles=set(keep),
            modelspace_owner_handle=_owner_handle(doc),
            entities_written=len(doc.modelspace()),
        )
    assert not path.with_name(path.name + ".verify").exists()


def test_count_proof_catches_a_vanished_entity(tmp_path: Path) -> None:
    path = tmp_path / "candidate.dxf"
    doc, keep = _synthetic_dxf(path, lines=40)
    index = _index(path)
    victim = _entity_records(index, "LINE")[0]
    _rewrite(path, {victim: lambda text: ""})
    with pytest.raises(RuntimeError, match="entity count changed"):
        exporter._reopen_candidate_for_verification(
            path,
            keep_handles=set(keep),
            modelspace_owner_handle=_owner_handle(doc),
            entities_written=len(doc.modelspace()),
        )


def test_reopened_candidate_reports_the_real_path_and_cleans_up(tmp_path: Path) -> None:
    path = tmp_path / "candidate.dxf"
    doc, keep = _synthetic_dxf(path, lines=10)
    candidate, auditor = exporter._reopen_candidate_for_verification(
        path,
        keep_handles=set(keep),
        modelspace_owner_handle=_owner_handle(doc),
        entities_written=len(doc.modelspace()),
    )
    assert candidate.filename == str(path)
    assert not path.with_name(path.name + ".verify").exists()
    assert len(candidate.modelspace()) == 3  # kept LINE + TEXT + LWPOLYLINE
    assert not auditor.has_errors


def test_unfamiliar_layout_falls_back_to_a_full_load(tmp_path: Path) -> None:
    path = tmp_path / "candidate.dxf"
    doc, keep = _synthetic_dxf(path, lines=10)
    original = path.read_bytes()
    path.write_bytes(b"999\r\ncomment before the first section\r\n" + original)
    candidate, auditor = exporter._reopen_candidate_for_verification(
        path,
        keep_handles=set(keep),
        modelspace_owner_handle=_owner_handle(doc),
        entities_written=len(doc.modelspace()),
    )
    assert len(candidate.modelspace()) == len(doc.modelspace())
    assert not auditor.has_errors


def test_reduced_audit_errors_fall_back_to_the_full_load(tmp_path: Path) -> None:
    """A reduced copy can never refuse what the full file would accept."""
    path = tmp_path / "candidate.dxf"
    doc, keep = _synthetic_dxf(path, lines=10)
    real_readfile = ezdxf.readfile
    loaded: list[str] = []

    def readfile(filename: str):
        loaded.append(str(filename))
        document = real_readfile(filename)
        if str(filename).endswith(".verify"):
            document.audit = lambda: SimpleNamespace(has_errors=True, errors=["synthetic"])
        return document

    with patch("librecad_pdf_importer.exporters.dxf_exporter.ezdxf.readfile", side_effect=readfile):
        candidate, auditor = exporter._reopen_candidate_for_verification(
            path,
            keep_handles=set(keep),
            modelspace_owner_handle=_owner_handle(doc),
            entities_written=len(doc.modelspace()),
        )
    assert [name.endswith(".verify") for name in loaded] == [True, False]
    assert len(candidate.modelspace()) == len(doc.modelspace())
    assert not auditor.has_errors
    assert not path.with_name(path.name + ".verify").exists()


def test_streaming_asset_scan_matches_a_full_load(tmp_path: Path) -> None:
    path = tmp_path / "prior.dxf"
    _synthetic_dxf(path, lines=5)
    image_paths, fonts = exporter._scan_asset_reference_paths(path)
    prior = ezdxf.readfile(str(path))
    assert image_paths == [str(image_def.dxf.filename) for image_def in prior.objects.query("IMAGEDEF")]
    assert fonts == [str(style.dxf.font) for style in prior.styles if str(style.dxf.font or "")]


def test_owned_sessions_from_prior_output_use_the_streaming_scan(tmp_path: Path) -> None:
    output = tmp_path / "prior.dxf"
    asset_parent = tmp_path / "prior_assets"
    session = asset_parent / "00112233445566778899aabbccddeeff"
    (session / "images").mkdir(parents=True)
    doc = ezdxf.new("R2010")
    doc.add_image_def(
        filename="prior_assets/00112233445566778899aabbccddeeff/images/tile.png",
        size_in_pixel=(1, 1),
    )
    doc.saveas(str(output))
    with patch("librecad_pdf_importer.exporters.dxf_exporter.ezdxf.readfile", side_effect=AssertionError("full load")):
        assert exporter._owned_sessions_referenced_by_output(output, asset_parent) == {session.resolve()}
