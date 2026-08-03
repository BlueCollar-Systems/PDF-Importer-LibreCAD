from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import ezdxf
import pytest
from PIL import Image

import dxf_import_engine
from conversion_control import ActivePageCancelled
from pdfcadcore.import_config import ImportConfig


def test_packaged_module_list_includes_resume_control() -> None:
    metadata = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert '"conversion_control"' in metadata


def test_resume_identity_does_not_require_a_loose_engine_source_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(dxf_import_engine, "__file__", str(tmp_path / "missing.py"))

    identity, payload = dxf_import_engine._resume_options_identity(
        ImportConfig.auto(), "R2010"
    )

    assert len(identity) == 64
    assert len(payload["engine_sha256"]) == 64


def test_resume_identity_uses_one_immutable_resolved_librecad_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sensitive_root = tmp_path / "Users" / "Resume User" / "PortableLibreCAD"
    executable = sensitive_root / "LibreCAD.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"exe-one")
    lff_path = sensitive_root / "resources" / "fonts" / "unicode.lff"
    lff_path.parent.mkdir(parents=True)
    lff_path.write_bytes(
        b"# Format: LibreCAD Font 1\n[0057]\n0,0;1,1\n"
    )
    monkeypatch.setenv("BCS_LIBRECAD_EXECUTABLE", str(executable))
    monkeypatch.setenv("BCS_LIBRECAD_UNICODE_LFF", str(lff_path))

    identity, payload = dxf_import_engine._resume_options_identity(
        ImportConfig.auto(),
        "R2010",
    )

    binding = payload["librecad_runtime_binding"]
    assert len(identity) == 64
    assert "librecad_executable" not in payload
    assert binding["contract_version"] == "bcs.librecad-runtime-binding/1"
    assert binding["executable_resolution_source"] == "environment_executable"
    assert binding["binding_verified"] is True
    assert binding["executable"]["size_bytes"] == executable.stat().st_size
    assert binding["executable"]["sha256"] == hashlib.sha256(
        executable.read_bytes()
    ).hexdigest()
    assert binding["unicode_lff"]["size_bytes"] == lff_path.stat().st_size
    assert binding["unicode_lff"]["sha256"] == hashlib.sha256(
        lff_path.read_bytes()
    ).hexdigest()
    assert "Resume User" not in binding["executable"]["path"]
    assert "Resume User" not in binding["unicode_lff"]["path"]
    shareable = dict(binding)
    shareable.pop("local_only_diagnostics")
    assert "Resume User" not in json.dumps(shareable)
    local = binding["local_only_diagnostics"]
    assert local["classification"] == "local_sensitive_paths"
    assert Path(local["librecad_executable_path"]) == executable.resolve()
    assert Path(local["librecad_lff_path"]) == lff_path.resolve()


def test_resume_identity_detects_same_stat_executable_and_lff_replacements(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_root = tmp_path / "portable-librecad"
    executable = install_root / "LibreCAD.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"exe-one")
    lff_path = install_root / "resources" / "fonts" / "unicode.lff"
    lff_path.parent.mkdir(parents=True)
    lff_path.write_bytes(
        b"# Format: LibreCAD Font 1\n[0057]\n0,0;1,1\n"
    )
    monkeypatch.setenv("BCS_LIBRECAD_EXECUTABLE", str(executable))
    monkeypatch.setenv("BCS_LIBRECAD_UNICODE_LFF", str(lff_path))
    config = ImportConfig.auto()

    first, _ = dxf_import_engine._resume_options_identity(config, "R2010")
    executable_stat = executable.stat()
    executable.write_bytes(b"exe-two")
    os.utime(
        executable,
        ns=(executable_stat.st_atime_ns, executable_stat.st_mtime_ns),
    )
    second, _ = dxf_import_engine._resume_options_identity(config, "R2010")
    lff_stat = lff_path.stat()
    replacement = lff_path.read_bytes().replace(b"0,0;1,1", b"#      ")
    assert len(replacement) == lff_stat.st_size
    lff_path.write_bytes(replacement)
    os.utime(lff_path, ns=(lff_stat.st_atime_ns, lff_stat.st_mtime_ns))
    third, _ = dxf_import_engine._resume_options_identity(config, "R2010")

    assert first != second
    assert second != third


def _write_checkpoint(path: str, page_index: int) -> None:
    doc = ezdxf.new("R2010")
    doc.modelspace().add_point((float(page_index), 0.0))
    doc.saveas(path)


def _fake_package_worker(calls: list[int]):
    def worker(input_path, output_path, config, dxf_version, progress_callback=None, **_kwargs):
        del input_path, dxf_version, progress_callback
        page_index = int(config.pages[0])
        calls.append(page_index)
        _write_checkpoint(output_path, page_index)
        return {
            "pages": 1,
            "entities": 1,
            "text_items": 0,
            "import_report_path": str(Path(output_path).with_suffix(".json")),
        }

    return worker


def test_resumable_conversion_checkpoints_and_skips_certified_pages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "three-pages.pdf"
    source.write_bytes(b"%PDF synthetic identity")
    output = tmp_path / "assembled.dxf"
    config = ImportConfig.auto()
    config.pages = [0, 1, 2]
    calls: list[int] = []
    messages: list[str] = []
    monkeypatch.setattr(dxf_import_engine, "_convert_via_package", _fake_package_worker(calls))

    first = dxf_import_engine.convert(
        str(source), str(output), config=config, resumable=True, progress_callback=messages.append
    )
    second = dxf_import_engine.convert(
        str(source), str(output), config=config, resumable=True, progress_callback=messages.append
    )

    assert calls == [0, 1, 2]
    assert first["pages"] == second["pages"] == 3
    assert first["resumed_pages"] == 0
    assert second["resumed_pages"] == 3
    assert len(ezdxf.readfile(output).modelspace()) == 3
    assert any("Page 3/3 certified" in message for message in messages)
    assert (tmp_path / "assembled_resume" / "session.json").is_file()


def test_cancel_keeps_certified_pages_and_resume_finishes_remaining_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "three-pages.pdf"
    source.write_bytes(b"%PDF synthetic identity")
    output = tmp_path / "assembled.dxf"
    config = ImportConfig.auto()
    config.pages = [0, 1, 2]
    calls: list[int] = []
    monkeypatch.setattr(dxf_import_engine, "_convert_via_package", _fake_package_worker(calls))

    with pytest.raises(dxf_import_engine.ConversionCancelled) as caught:
        dxf_import_engine.convert(
            str(source),
            str(output),
            config=config,
            resumable=True,
            cancel_requested=lambda: len(calls) >= 1,
        )

    assert caught.value.completed_pages == 1
    assert caught.value.total_pages == 3
    assert output.is_file()
    assert len(ezdxf.readfile(output).modelspace()) == 1

    stats = dxf_import_engine.convert(
        str(source),
        str(output),
        config=config,
        resumable=True,
        cancel_requested=lambda: False,
    )
    assert calls == [0, 1, 2]
    assert stats["pages"] == 3
    assert stats["resumed_pages"] == 1
    assert len(ezdxf.readfile(output).modelspace()) == 3


def test_resume_rejects_changed_options_without_destroying_certified_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "one-page.pdf"
    source.write_bytes(b"%PDF synthetic identity")
    output = tmp_path / "assembled.dxf"
    config = ImportConfig.auto()
    config.pages = [0]
    calls: list[int] = []
    monkeypatch.setattr(dxf_import_engine, "_convert_via_package", _fake_package_worker(calls))
    dxf_import_engine.convert(str(source), str(output), config=config, resumable=True)
    checkpoint = tmp_path / "assembled_resume" / "page_0001.dxf"
    checkpoint_bytes = checkpoint.read_bytes()

    changed = ImportConfig.auto()
    changed.pages = [0]
    changed.text_mode = "glyphs"
    with pytest.raises(dxf_import_engine.ResumeMismatchError, match="options"):
        dxf_import_engine.convert(str(source), str(output), config=changed, resumable=True)

    assert checkpoint.read_bytes() == checkpoint_bytes
    assert calls == [0]


def test_corrupt_checkpoint_is_never_treated_as_completed_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "one-page.pdf"
    source.write_bytes(b"%PDF synthetic identity")
    output = tmp_path / "assembled.dxf"
    config = ImportConfig.auto()
    config.pages = [0]
    calls: list[int] = []
    monkeypatch.setattr(dxf_import_engine, "_convert_via_package", _fake_package_worker(calls))
    dxf_import_engine.convert(str(source), str(output), config=config, resumable=True)
    checkpoint = tmp_path / "assembled_resume" / "page_0001.dxf"
    checkpoint.write_bytes(b"corrupt")

    dxf_import_engine.convert(str(source), str(output), config=config, resumable=True)

    assert calls == [0, 0]
    assert len(ezdxf.readfile(output).modelspace()) == 1


def test_explicit_restart_replaces_only_the_generated_resume_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "one-page.pdf"
    source.write_bytes(b"%PDF synthetic identity")
    output = tmp_path / "assembled.dxf"
    unrelated = tmp_path / "keep-me.txt"
    unrelated.write_text("owner data", encoding="utf-8")
    config = ImportConfig.auto()
    config.pages = [0]
    calls: list[int] = []
    monkeypatch.setattr(dxf_import_engine, "_convert_via_package", _fake_package_worker(calls))
    dxf_import_engine.convert(str(source), str(output), config=config, resumable=True)

    changed = ImportConfig.auto()
    changed.pages = [0]
    changed.text_mode = "glyphs"
    stats = dxf_import_engine.convert(
        str(source),
        str(output),
        config=changed,
        resumable=True,
        restart_on_resume_mismatch=True,
    )

    assert calls == [0, 0]
    assert stats["converted_pages"] == 1
    assert unrelated.read_text(encoding="utf-8") == "owner data"


def test_active_page_cancel_rolls_back_only_that_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "two-pages.pdf"
    source.write_bytes(b"%PDF synthetic identity")
    output = tmp_path / "assembled.dxf"
    config = ImportConfig.auto()
    config.pages = [0, 1]
    calls: list[int] = []

    def worker(
        input_path,
        output_path,
        page_config,
        dxf_version,
        progress_callback=None,
        **_kwargs,
    ):
        del input_path, dxf_version, progress_callback
        page_index = int(page_config.pages[0])
        calls.append(page_index)
        if page_index == 1:
            Path(output_path).write_bytes(b"partial active page")
            raise ActivePageCancelled("cancelled inside text build")
        _write_checkpoint(output_path, page_index)
        return {"pages": 1, "entities": 1, "text_items": 0}

    monkeypatch.setattr(dxf_import_engine, "_convert_via_package", worker)

    with pytest.raises(dxf_import_engine.ConversionCancelled) as caught:
        dxf_import_engine.convert(str(source), str(output), config=config, resumable=True)

    assert calls == [0, 1]
    assert caught.value.completed_pages == 1
    assert len(ezdxf.readfile(output).modelspace()) == 1
    assert not (tmp_path / "assembled_resume" / "page_0002.dxf").exists()


def test_completed_resume_reuses_the_verified_assembled_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "two-pages.pdf"
    source.write_bytes(b"%PDF synthetic identity")
    output = tmp_path / "assembled.dxf"
    config = ImportConfig.auto()
    config.pages = [0, 1]
    calls: list[int] = []
    assemblies: list[list[str]] = []
    real_assemble = dxf_import_engine._assemble_checkpoints

    def counted_assemble(checkpoints, output_path):
        assemblies.append([Path(path).name for path in checkpoints])
        return real_assemble(checkpoints, output_path)

    monkeypatch.setattr(dxf_import_engine, "_convert_via_package", _fake_package_worker(calls))
    monkeypatch.setattr(dxf_import_engine, "_assemble_checkpoints", counted_assemble)

    dxf_import_engine.convert(str(source), str(output), config=config, resumable=True)
    dxf_import_engine.convert(str(source), str(output), config=config, resumable=True)

    assert calls == [0, 1]
    assert assemblies == [["page_0001.dxf", "page_0002.dxf"]]


def test_missing_external_image_invalidates_certified_page_and_assembled_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "one-page.pdf"
    source.write_bytes(b"%PDF synthetic identity")
    output = tmp_path / "assembled.dxf"
    config = ImportConfig.auto()
    config.pages = [0]
    calls: list[int] = []

    def worker(
        input_path,
        output_path,
        page_config,
        dxf_version,
        progress_callback=None,
        **_kwargs,
    ):
        del input_path, page_config, dxf_version, progress_callback
        calls.append(0)
        checkpoint = Path(output_path)
        assets = checkpoint.with_name(f"{checkpoint.stem}_assets")
        assets.mkdir(parents=True, exist_ok=True)
        image = assets / "source.png"
        Image.new("RGBA", (3, 2), (10, 20, 30, 255)).save(image)
        doc = ezdxf.new("R2010")
        definition = doc.add_image_def(
            filename=f"{assets.name}/source.png",
            size_in_pixel=(3, 2),
        )
        doc.modelspace().add_image(definition, insert=(0, 0), size_in_units=(3, 2))
        doc.saveas(checkpoint)
        return {"pages": 1, "entities": 1, "text_items": 0}

    monkeypatch.setattr(dxf_import_engine, "_convert_via_package", worker)
    dxf_import_engine.convert(str(source), str(output), config=config, resumable=True)
    (tmp_path / "assembled_resume" / "page_0001_assets" / "source.png").unlink()
    for delivered in (tmp_path / "assembled_assets").rglob("*.png"):
        delivered.unlink()

    dxf_import_engine.convert(str(source), str(output), config=config, resumable=True)

    assert calls == [0, 0]
    delivered_assets = list((tmp_path / "assembled_assets").rglob("*.png"))
    assert len(delivered_assets) == 1


def test_assembly_rebases_image_assets_for_the_requested_output(
    tmp_path: Path,
) -> None:
    session = tmp_path / "assembled_resume"
    source_assets = session / "page_0001_assets"
    source_assets.mkdir(parents=True)
    source_image = source_assets / "source.png"
    Image.new("RGBA", (3, 2), (10, 20, 30, 255)).save(source_image)
    checkpoint = session / "page_0001.dxf"
    source_doc = ezdxf.new("R2010")
    image_def = source_doc.add_image_def(
        filename="page_0001_assets/source.png",
        size_in_pixel=(3, 2),
    )
    source_doc.modelspace().add_image(
        image_def,
        insert=(0, 0),
        size_in_units=(3, 2),
    )
    source_doc.saveas(checkpoint)
    output = tmp_path / "assembled.dxf"

    dxf_import_engine._assemble_checkpoints([checkpoint], str(output))

    assembled = ezdxf.readfile(output)
    definitions = list(assembled.objects.query("IMAGEDEF"))
    assert len(definitions) == 1
    delivered = (output.parent / definitions[0].dxf.filename).resolve()
    assert delivered.is_file()
    assert delivered.read_bytes() == source_image.read_bytes()
