# Release Candidate Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind every newly accepted LibreCAD release artifact cryptographically to its exact GitHub-hosted candidate workflow and source commit while preserving the deterministic two-push publication workflow.

**Architecture:** A workflow-generated provenance sidecar records candidate identity, immutable workflow SHA, ZIP digests, and the package-included Git payload digest, while one pinned GitHub artifact attestation cryptographically signs both ZIPs and the sidecar. Acceptance validates trusted certificate extensions and a common three-subject bundle, exact run/attempt retained bytes, strict JSON, reparse-safe extraction, and report/DXF-backed native smoke. Default schema-1.1 publication verification reconstructs the original canonical sidecar and re-authenticates the original run and attestation before a split least-privilege publisher can mint a release.

**Tech Stack:** Python 3.12.10, Git, GitHub Actions, deterministic ZIP tooling, pytest/unittest release tests.

## Global Constraints

- No CAD host launch and no private PDF access.
- Version 1.0.78 acceptance requires schema `bcs.release_artifacts/1.1`.
- Historical schema 1.0 remains verifiable for v1.0.77 compatibility only.
- The first code push must fail closed at artifact acceptance and retain the exact candidate for one day.
- The second push may change only `.release/accepted-artifacts.json` relative to the candidate payload.
- Default acceptance and schema-1.1 publication verification must run genuine `gh attestation verify --format json` for both ZIPs and the canonical sidecar, require a common bundle, and enforce the exact signer/source/run certificate identity; dependency injection is test-only and unavailable from the CLI.
- Default acceptance must authenticate the asserted GitHub run/attempt and byte-compare its retained candidate artifact; dependency injection is test-only and unavailable from the CLI.
- Workflow build permissions are `actions: read`, `contents: read`, `id-token: write`, `attestations: write`, and `artifact-metadata: write`; publication runs in a separate job with non-persisted checkout credentials, tokenless repository audit and transferred-ZIP rehash, and isolated tokened `gh` release steps.
- JSON readers reject duplicate/unknown keys, non-string runner values, non-finite numbers, and private/local diagnostic metadata.

---

### Task 1: Candidate provenance writer and validator

**Files:**
- Modify: `scripts/verify_release_artifacts.py`
- Test: `tests/test_release_artifact_verification.py`

**Interfaces:**
- Produces: `write_candidate_provenance(...) -> dict[str, Any]`
- Produces: `validate_candidate_provenance(...) -> Mapping[str, Any]`
- Consumes: canonical version, release build contract, GitHub environment, and built ZIPs.

- [x] **Step 1: Write failing tests** for required hosted identity fields, ZIP SHA/size, package payload digest, malformed sidecars, and wrong version/head/run.
- [x] **Step 2: Run the focused release-verifier tests** and confirm the new cases fail for missing interfaces.
- [x] **Step 3: Implement canonical sidecar serialization and validation** with exact field sets, finite values, confined paths, and atomic writes.
- [x] **Step 4: Run the focused tests** and confirm all provenance cases pass.

### Task 2: Clean candidate acceptance and safe extraction

**Files:**
- Modify: `scripts/verify_release_artifacts.py`
- Test: `tests/test_release_artifact_verification.py`

**Interfaces:**
- Consumes: `--accept --provenance <path>`.
- Produces: schema-1.1 `.release/accepted-artifacts.json` and a fresh `dist/windows-portable` tree.

- [x] **Step 1: Write failing tests** for a missing sidecar, wrong candidate SHA, dirty tracked file, stale extracted executable, ZIP traversal, drive-qualified member, duplicate conflict, and wrong executable layout.
- [x] **Step 2: Run the focused tests** and record the expected RED failures.
- [x] **Step 3: Implement acceptance checks** that require the exact clean candidate checkout, validate both ZIPs, extract into a repository-confined temporary directory, verify the four canonical executables, and atomically install the extracted tree.
- [x] **Step 4: Run the focused tests** and confirm every negative case fails closed and the valid case passes.

### Task 3: Manifest-only descendant verification

**Files:**
- Modify: `scripts/verify_release_artifacts.py`
- Test: `tests/test_release_artifact_verification.py`

**Interfaces:**
- Consumes: schema-1.1 manifest provenance and current Git checkout.
- Produces: verified artifact records only when the candidate payload is unchanged.

- [x] **Step 1: Write failing tests** for exact candidate, manifest-only descendant, unrelated tracked change, package-included change, and candidate not in current ancestry.
- [x] **Step 2: Run the focused tests** and confirm descendant validation is absent.
- [x] **Step 3: Implement candidate ancestry and changed-path gates** plus the build-release inclusion digest comparison.
- [x] **Step 4: Run the focused tests** and confirm only the exact candidate and manifest-only descendant pass.

### Task 4: Workflow retention and native-mode smoke

**Files:**
- Modify: `.github/workflows/auto-release.yml`
- Modify: `scripts/smoke_portable_zip.py`
- Test: `tests/test_release_workflows.py`
- Test: `tests/test_portable_zip_smoke.py`

**Interfaces:**
- Workflow invokes `--write-candidate-provenance` before normal verification.
- Smoke consumes explicit source/portable ZIP paths and a deterministic synthetic LibreCAD installation/LFF fixture.

- [x] **Step 1: Write failing workflow and smoke tests** requiring the sidecar upload and native Text plus Labels checks.
- [x] **Step 2: Run the focused tests** and confirm the old workflow/smoke fail them.
- [x] **Step 3: Update workflow and smoke** without launching LibreCAD or using private files.
- [x] **Step 4: Run focused workflow, smoke, and release-verifier tests** and confirm green.

### Task 5: Full verification and two-stage publication

**Files:**
- Modify: `.release/accepted-artifacts.json` only after downloading the failed hosted candidate.

**Interfaces:**
- Consumes: failed GitHub candidate ZIPs and sidecar from the exact first-push run.
- Produces: immutable v1.0.78 release whose downloaded bytes equal the accepted candidate.

- [x] **Step 1: Run full no-host tests, Ruff, sync/preflight, privacy scan, portable smoke, and `git diff --check`.**
- [x] **Step 2: Commit and push the reviewed v1.0.78 code/release-contract changes.**
- [ ] **Step 3: Confirm CI passes and auto-release stops only at the expected acceptance gate; download the exact retained candidate.**
- [ ] **Step 4: In a clean checkout at the candidate SHA, run `--accept --provenance`, verify the resulting manifest, and copy only that manifest into the main checkout.**
- [ ] **Step 5: Commit and push the manifest-only change; confirm rebuilt bytes, immutable release, fresh-download hashes, and website dispatch.**
- [ ] **Step 6: After the shared host lease becomes available, install the exact release and complete native Text/Labels save/reopen proof.**

### Task 6: Cryptographic attestation acceptance and publication reauthentication

**Files:**
- Modify: `.github/workflows/auto-release.yml`
- Modify: `scripts/verify_release_artifacts.py`
- Test: `tests/test_release_provenance.py`

**Interfaces:**
- Workflow uses `actions/attest@508db95dd578ae2727ebd6217d5ba78e4fbda05d # v4` once for both canonical ZIPs and `release-candidate-provenance.json`.
- Default acceptance and schema-1.1 verification call `gh attestation verify --format json` for all three subjects with exact repository, signer workflow/digest, source digest/ref, GitHub-hosted runner, trigger, and run-attempt certificate checks.

- [x] **Step 1: Write failing tests** for exact workflow permissions/action pin, three subjects, exact CLI/certificate policy, common bundle identity, historical result selection, and default fail-closed behavior.
- [x] **Step 2: Run focused tests and confirm RED** because acceptance originally trusted the self-asserted sidecar.
- [x] **Step 3: Implement pinned workflow attestations and default cryptographic verification** with a callback accepted only by direct offline unit-test calls.
- [x] **Step 4: Implement authenticated run/attempt lookup, attempt-specific artifact lookup, isolated retained-artifact byte comparison, and default schema-1.1 reauthentication.**
- [x] **Step 5: Run focused tests, including a two-commit forged-manifest regression, and confirm GREEN.**

### Task 7: Canonical extraction and exact schemas

**Files:**
- Modify: `scripts/verify_release_artifacts.py`
- Test: `tests/test_release_provenance.py`

**Interfaces:**
- Extraction computes `<lexical absolute root>/dist/windows-portable` internally.
- JSON validation requires exact key sets and JSON-native scalar types at every level.

- [x] **Step 1: Write failing tests** for non-canonical targets, symlink/junction/reparse ancestors, unknown/private keys, non-string runner fields, duplicate keys, and `NaN`/`Infinity`.
- [x] **Step 2: Run focused tests and confirm RED** at the missing fail-closed checks.
- [x] **Step 3: Implement lexical anchoring, reparse checks before every rename/removal, strict JSON parsing, and exact validators.**
- [x] **Step 4: Run focused tests and confirm GREEN.**

### Task 8: Report/DXF-backed native smoke

**Files:**
- Modify: `scripts/smoke_portable_zip.py`
- Test: `tests/test_release_smoke_native.py`

**Interfaces:**
- `_validate_representation_delivery(report_path, dxf_path=..., expected_executable=..., expected_lff=...)` validates report evidence against reopened DXF entities and exact handles.

- [x] **Step 1: Write failing tests** requiring live modelspace `TEXT` handles, delivered content, executable/LFF binding, SHA/coverage evidence, and serialized reopen proof for Text and Labels.
- [x] **Step 2: Run focused tests and confirm RED** because current smoke checks only summary fields.
- [x] **Step 3: Implement deep native validation and pass the synthetic installation paths from the smoke loop.**
- [x] **Step 4: Run focused and full release gates, `git diff --check`, and the complete test suite; do not commit, push, launch a host, or access private PDFs.**
