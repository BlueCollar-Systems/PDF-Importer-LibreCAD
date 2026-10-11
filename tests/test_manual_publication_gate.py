"""Keep publication explicit while ordinary pushes and PRs retain CI."""
from pathlib import Path


def test_publication_requires_manual_dispatch_and_ci_still_runs():
    workflows = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    release = (workflows / "auto-release.yml").read_text(encoding="utf-8")
    trigger = release.split("on:", 1)[1].split("env:", 1)[0]
    assert "workflow_dispatch:" in trigger
    assert "push:" not in trigger and "pull_request:" not in trigger
    assert "if: github.event_name == 'workflow_dispatch'" in release
    if "  publish:" in release:
        publish = release.split("  publish:", 1)[1]
        assert "if: github.event_name == 'workflow_dispatch' &&" in publish
    ci = (workflows / "lc-pdfimporter-ci.yml").read_text(encoding="utf-8")
    assert "  push:" in ci and "  pull_request:" in ci
