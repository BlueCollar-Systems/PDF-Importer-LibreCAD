# Reviewer A repo-wide readiness sweep: SketchUp + FreeCAD

Date: 2026-06-23

Scope requested: `C:\1PDF-Importer-SketchUp` and `C:\1PDF-Importer-FreeCAD`, including their Q&A mirrors and shared-core manifests. No source code changes, commits, or pushes were made.

## Repos inspected

### SketchUp

- Repo: `C:\1PDF-Importer-SketchUp`
- Branch/status: `main...origin/main`, clean
- HEAD: `6737a4d chore: bump version to 3.7.56`
- Tag/release version in source: `3.7.56`
- Recent CI/release surface from GitHub:
  - `su-pdfimporter-ci`: success on `6737a4d`
  - `corpus-placement`: success on `6737a4d`
  - `auto-release`: skipped on version-bump commit, expected
- GitHub release check: `v3.7.56` exists and has `SketchUp-PDF-Importer_v3.7.56.rbz`

### FreeCAD

- Repo: `C:\1PDF-Importer-FreeCAD`
- Branch/status: `main...origin/main`, clean
- HEAD: `921bef0 docs: update Q&A cross-repo validation [skip release]`
- Latest release tag/source version: `v4.0.40` / `4.0.40`
- Recent CI/release surface from GitHub:
  - `fc-pdfimporter-ci`: success on `921bef0`
  - `windows-release`: success for `v4.0.40`
  - `auto-release`: skipped on version-bump commit, expected
- GitHub release check: `v4.0.40` exists and has:
  - `FreeCAD-PDF-Importer_v4.0.40.zip`
  - `FreeCAD-PDF-Importer-Setup_v4.0.40.exe`

## Commands/checks run

- `git status --short --branch`
- `git log -5 --oneline --decorate`
- Attempted `rg` file/text scan; `rg` is not installed on this machine, so PowerShell and `git ls-files` fallback scans were used.
- Tracked-file risk marker scan for `TODO`, `FIXME`, `XXX`, `HACK`, `NotImplemented`, and `raise NotImplemented`.
- Version/package consistency spot checks in README, metadata/package files, pyproject/package XML, and workflows.
- Q&A index/mirror inspection:
  - `C:\Users\Rowdy Payton\Desktop\PDFTest Files\Q&A\Q&A_INDEX.md`
  - `C:\1PDF-Importer-SketchUp\_LLM_CONTROL_PACK\QA\Q&A_INDEX.md`
  - `C:\1PDF-Importer-FreeCAD\_LLM_CONTROL_PACK\QA\Q&A_INDEX.md`
- Release asset checks with `gh release view v3.7.56` and `gh release view v4.0.40`.
- Workflow checks with `gh run list --limit 8`.
- SketchUp validation:
  - `ruby -v`
  - `ruby -c extracted/sketchup_ext/bc_pdf_vector_importer.rb`
  - `ruby -c extracted/sketchup_ext/bc_pdf_vector_importer/metadata.rb`
  - `ruby -c extracted/sketchup_ext/bc_pdf_vector_importer/main.rb`
  - `ruby -c extracted/sketchup_ext/bc_pdf_vector_importer/qa_report.rb`
  - `ruby test/qa_report_test.rb`
  - `ruby test/corpus_harness_test.rb`
  - `ruby test/corpus_paths_test.rb`
  - `ruby test/corpus_strict_timing_test.rb`
  - `ruby test/smoke_test.rb`
- FreeCAD validation:
  - `python --version`
  - `python -m pytest`
  - `python pdfcadcore_sync_check.py`

## Findings

### Blocking findings

None found for importer source, packaging version consistency, release availability, or shared-core sync.

### Non-blocking findings / proposed improvements

1. SketchUp smoke package check is developer-machine dependent.
   - `test/smoke_test.rb` scans every root `*.rbz`.
   - This local checkout has many ignored old RBZ files through `v3.7.55`; the actual current release asset is `v3.7.56` on GitHub.
   - Result today: smoke still passes, but it spends time validating stale local packages and the test result changes depending on whatever ignored artifacts are present.
   - Proposed improvement: make the smoke package check deterministic by validating only the current metadata version artifact when explicitly present, or by accepting a `SMOKE_RBZ`/`PACKAGE_UNDER_TEST` path. Treat a clean source checkout with no package as pass, as it already does.

2. FreeCAD pytest passes but emits a Windows temp cleanup exception after success.
   - Test result: `60 passed, 1 warning`.
   - After pytest exits, it prints a `PermissionError` for `.pytest_tmp\root\pytest-of-Rowdy Payton\pytest-current`.
   - Exit code is still `0`, repo status remains clean, and `.pytest_tmp/` is ignored.
   - Proposed improvement: adjust pytest temp/cache behavior so Windows cleanup is quiet and repeatable. Options: remove stale `.pytest_tmp` during local cleanup, stop using `.pytest_tmp/cache` as pytest cache dir if it creates fragile numbered temp state, or set a disposable `--basetemp` outside the repo during local/CI validation.

3. Q&A mirror completeness is behind the Desktop Q&A index.
   - Desktop `Q&A_INDEX.md` now starts with `Repo Scan & Commit Status (2026-06-23)` and says all repos are clean/pushed.
   - The SketchUp and FreeCAD `_LLM_CONTROL_PACK\QA\Q&A_INDEX.md` mirrors still contain the older detailed Round 2 index and do not show that latest short repo-scan index entry.
   - This is not an importer-code blocker, but it is a process/documentation issue if the repo mirrors are intended to be complete source-of-truth mirrors.
   - Proposed improvement: either mirror the latest Desktop Q&A index/report into both repos, or explicitly document that repo Q&A mirrors are curated excerpts rather than full parity copies.

4. Local ignored release artifacts are stale/cluttered.
   - SketchUp local root/dist contains older ignored RBZ files; no local `v3.7.56` RBZ was found, but GitHub release `v3.7.56` has the correct asset.
   - FreeCAD local root/dist contains older ignored ZIP/EXE files; GitHub release `v4.0.40` has the correct ZIP and Setup EXE.
   - Not a release blocker because GitHub Releases are the intended download layer.
   - Proposed improvement: add or run a local artifact cleanup script before future sweeps to avoid confusing local ignored files with website-ready release assets.

## Validation results

### SketchUp

- Ruby: `ruby 3.4.4`
- Syntax checks: OK
- `test/qa_report_test.rb`: `4 runs, 20 assertions, 0 failures`
- `test/corpus_harness_test.rb`: `2 runs, 3 assertions, 0 failures`
- `test/corpus_paths_test.rb`: `3 runs, 6 assertions, 0 failures`
- `test/corpus_strict_timing_test.rb`: exit `0`; no output in default non-strict mode
- `test/smoke_test.rb`: `ALL CHECKS PASSED (59 checks)`

### FreeCAD

- Python: `3.12.10`
- `python -m pytest`: `60 passed, 1 warning`
- Post-test stderr: pytest temp cleanup `PermissionError` under `.pytest_tmp`; non-zero failure not observed.
- `python pdfcadcore_sync_check.py`: `ALL IN SYNC`

## Agreement / disagreement points

### Agreement

- Agree that both target repos are clean and aligned with `origin/main`.
- Agree that the current public releases exist and carry the expected current downloadable assets.
- Agree that no tracked TODO/FIXME/HACK/NotImplemented marker was found in the inspected source surface.
- Agree that FreeCAD shared-core sync is green.
- Agree that these repos are ready for continued real-world retesting from a source/CI/package-availability standpoint.

### Disagreement / caveats

- I do not agree that the repo Q&A mirrors are fully current unless the mirror policy is "curated excerpts only." If they are meant to mirror Desktop Q&A source-of-truth state, they need a small sync pass.
- I do not agree that SketchUp package smoke validation is as deterministic as it could be while it scans all ignored local RBZ files.
- I would not ignore the FreeCAD pytest temp cleanup exception forever. It is not a code blocker today, but it is noisy enough to confuse future readiness checks.

## Reviewer A readiness call

No blocking source or packaging errors found in SketchUp or FreeCAD. Recommended next actions are documentation/process cleanup only: sync or clarify Q&A mirrors, make SketchUp smoke artifact selection deterministic, and quiet FreeCAD pytest temp cleanup.
