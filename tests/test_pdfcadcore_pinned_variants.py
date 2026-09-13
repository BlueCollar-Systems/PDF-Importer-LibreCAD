from pathlib import Path
import importlib.util
import hashlib


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
