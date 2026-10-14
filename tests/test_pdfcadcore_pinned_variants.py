from pathlib import Path
import importlib.util
import json
import pytest


def checker_module():
    path = Path(__file__).resolve().parents[1] / "pdfcadcore_sync_check.py"
    spec = importlib.util.spec_from_file_location("sync_reviewed_host_variant_test", path)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    return checker


def test_specialized_core_is_hash_checked_and_never_replaced_by_canonical(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "pdfcadcore_sync_check.py"
    spec = importlib.util.spec_from_file_location("sync_pinned_test", path)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    canonical = tmp_path / "canonical"
    host = tmp_path / "host"
    canonical.mkdir()
    host.mkdir()
    (canonical / "primitive_extractor.py").write_text("canonical\n")
    target = host / "primitive_extractor.py"
    target.write_text("specialized\n")
    expected = checker.sha256_file(target)
    manifest = {"primitive_extractor.py": checker.sha256_file(canonical / "primitive_extractor.py")}
    monkeypatch.setattr(checker, "KNOWN_DIVERGENCES", {"BL": {"primitive_extractor.py": expected}})
    assert checker.check_repo_core("BL", host, manifest, False, canonical) == []
    target.write_text("changed\n")
    assert checker.check_repo_core("BL", host, manifest, True, canonical)
    assert target.read_text() == "changed\n"
    target.unlink()
    assert checker.check_repo_core("BL", host, manifest, True, canonical)
    assert not target.exists()


def test_actual_host_core_matches_canonical_manifest_plus_exact_reviewed_variants():
    checker = checker_module()
    host = checker.detect_local_repo()
    manifest = checker.load_manifest()
    core = checker.local_core_dir(host)
    assert checker.check_repo_core(host, core, manifest, False, core) == []
    expected_core = {name: digest for name, digest in manifest.items()
                     if name not in {checker.SELF_NAME, "repo_context_builder_core.py"}}
    assert checker.build_manifest(host, core, manifest) == expected_core
    assert "FC" not in checker.KNOWN_DIVERGENCES
    assert checker.KNOWN_DIVERGENCES["LC"]["import_report.py"] == (
        "2b573416954fea578535c9a820bc9cc873bed2ce11bf7de926575db1cfa950f0")
    assert checker.KNOWN_DIVERGENCES["BL"]["import_report.py"] == (
        "90c0c0b5d109131befc4e97eb52db9ca6615f834e8d0d0d10fbe733b6d34c9d1")


def report_fixture(tmp_path, monkeypatch):
    checker = checker_module()
    canonical = tmp_path / "canonical"
    host = tmp_path / "host"
    canonical.mkdir()
    host.mkdir()
    (canonical / "import_report.py").write_text("fictional canonical report\n")
    target = host / "import_report.py"
    target.write_text("fictional reviewed host report\n")
    monkeypatch.setattr(checker, "KNOWN_DIVERGENCES", {
        "LC": {"import_report.py": checker.sha256_file(target)}})
    manifest = {"import_report.py": checker.sha256_file(canonical / "import_report.py")}
    return checker, canonical, host, target, manifest


def test_exact_reviewed_report_is_accepted_and_never_replaced_by_fix(tmp_path, monkeypatch):
    checker, canonical, host, target, manifest = report_fixture(tmp_path, monkeypatch)
    before = target.read_bytes()
    assert checker.check_repo_core("LC", host, manifest, True, canonical) == []
    assert target.read_bytes() == before


@pytest.mark.parametrize("change", ["mutated", "missing"])
def test_mutated_or_missing_reviewed_report_fails_without_destructive_fix(tmp_path, monkeypatch, change):
    checker, canonical, host, target, manifest = report_fixture(tmp_path, monkeypatch)
    if change == "mutated":
        target.write_text("fictional unreviewed edit\n")
        before = target.read_bytes()
    else:
        target.unlink()
    assert checker.check_repo_core("LC", host, manifest, True, canonical)
    if change == "mutated":
        assert target.read_bytes() == before
    else:
        assert not target.exists()


def test_pin_cannot_exempt_an_unlisted_core_file(tmp_path, monkeypatch):
    checker, canonical, host, target, _ = report_fixture(tmp_path, monkeypatch)
    before = target.read_bytes()
    errors = checker.check_repo_core("LC", host, {}, True, canonical)
    assert any("unexpected core file not in manifest" in error for error in errors)
    assert target.read_bytes() == before


def test_unpinned_shared_core_fix_still_copies_the_canonical_file(tmp_path, monkeypatch):
    checker = checker_module()
    monkeypatch.setattr(checker, "KNOWN_DIVERGENCES", {})
    canonical = tmp_path / "canonical"
    host = tmp_path / "host"
    canonical.mkdir()
    host.mkdir()
    source = canonical / "atomic_io.py"
    target = host / "atomic_io.py"
    source.write_text("fictional canonical shared core\n")
    target.write_text("fictional drift\n")
    manifest = {"atomic_io.py": checker.sha256_file(source)}
    assert checker.check_repo_core("LC", host, manifest, True, canonical)
    assert target.read_bytes() == source.read_bytes()
    assert checker.check_repo_core("LC", host, manifest, False, canonical) == []


def test_write_manifest_preserves_canonical_hash_for_an_exact_host_variant(tmp_path, monkeypatch):
    checker, _, host, target, manifest = report_fixture(tmp_path, monkeypatch)
    host_hash = checker.sha256_file(target)
    assert host_hash != manifest["import_report.py"]
    assert checker.build_manifest("LC", host, manifest) == manifest


@pytest.mark.parametrize("change", ["mutated", "missing", "missing-canonical", "bad-canonical"])
def test_write_manifest_never_silently_repins_or_loses_a_variant(tmp_path, monkeypatch, change):
    checker, _, host, target, manifest = report_fixture(tmp_path, monkeypatch)
    if change == "mutated":
        target.write_text("fictional unreviewed report\n")
    elif change == "missing":
        target.unlink()
    elif change == "missing-canonical":
        manifest.clear()
    else:
        manifest["import_report.py"] = "not-a-canonical-hash"
    with pytest.raises(ValueError):
        checker.build_manifest("LC", host, manifest)


def test_write_manifest_cli_preserves_file_on_unreviewed_variant(tmp_path, monkeypatch):
    checker, _, host, target, manifest = report_fixture(tmp_path, monkeypatch)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest) + "\n")
    before = manifest_path.read_bytes()
    monkeypatch.setattr(checker, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(checker, "SCRIPT_DIR", tmp_path)
    monkeypatch.setattr(checker, "detect_local_repo", lambda: "LC")
    monkeypatch.setattr(checker, "local_core_dir", lambda repo: host)
    target.write_text("fictional unreviewed report\n")
    assert checker.main(["--write-manifest", "--skip-cross-repo"]) == 1
    assert manifest_path.read_bytes() == before
