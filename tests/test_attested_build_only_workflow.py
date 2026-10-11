"""Keep the real auto-release acceptance proof while stopping false dispatches."""
from pathlib import Path


def test_build_only_default_cannot_publish_or_mutate_releases():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/auto-release.yml").read_text(encoding="utf-8")
    trigger = workflow.split("on:", 1)[1].split("env:", 1)[0]
    assert "publish_release:" in trigger
    assert "type: boolean" in trigger and "default: false" in trigger
    builder, publisher = workflow.split("  publish:\n", 1)
    assert "if: github.event_name == 'workflow_dispatch' && inputs.publish_release == true && needs.release.result == 'success' && needs.release.outputs.release == 'true'" in publisher
    assert "contents: write" not in builder
    for mutation in ("gh release create", "audit-existing-tag", "POST /repos/{owner}/{repo}/dispatches"):
        assert mutation not in builder
        assert mutation in publisher
    # The false run still creates the true signer and deliberately retains an
    # unaccepted candidate through the existing failed-run acceptance contract.
    assert "uses: actions/attest@508db95dd578ae2727ebd6217d5ba78e4fbda05d" in builder
    assert "run: python scripts/verify_release_artifacts.py" in builder
    assert "if: failure() && steps.verify.outcome == 'failure'" in builder
    assert "name: failed-release-candidate-${{ github.run_id }}-${{ github.run_attempt }}" in builder


def test_candidate_acceptance_verifier_is_not_bypassed_for_false_input():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/auto-release.yml").read_text(encoding="utf-8")
    verify = workflow.split("- name: Verify exact accepted release bytes", 1)[1].split("- name:", 1)[0]
    assert "inputs.publish_release" not in verify
    assert "if: steps.preflight.outputs.release == 'true'" in verify
    verifier = (root / "scripts/verify_release_artifacts.py").read_text(encoding="utf-8")
    assert 'EXPECTED_WORKFLOW = "auto-release"' in verifier
    assert '"conclusion": "failure"' in verifier
    assert 'if changed != {allowed_manifest}:' in verifier


def test_publisher_only_retry_downloads_the_original_producer_artifact():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/auto-release.yml").read_text(encoding="utf-8")
    builder, publisher = workflow.split("  publish:\n", 1)
    assert 'verified_artifact: ${{ steps.candidate.outputs.verified_artifact }}' in builder
    assert 'name: ${{ steps.candidate.outputs.verified_artifact }}' in builder
    assert 'VERIFIED_ARTIFACT: ${{ needs.release.outputs.verified_artifact }}' in publisher
    assert '--name "$VERIFIED_ARTIFACT"' in publisher
    assert '--name "verified-release-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"' not in publisher
