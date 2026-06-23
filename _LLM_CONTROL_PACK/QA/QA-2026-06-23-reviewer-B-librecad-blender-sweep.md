# Reviewer B Sweep - LibreCAD and Blender

Date: 2026-06-23
Reviewer: B
Scope: `C:\1PDF-Importer-LibreCAD` and `C:\1PDF-Importer-Blender`
Role constraints: read-only source review. No source code edits, no commits, no pushes.

## Repos Inspected

- `C:\1PDF-Importer-LibreCAD`
- `C:\1PDF-Importer-Blender`

Focus areas:

- Git status and recent history
- Q&A mirrors and shared-core manifests
- CLI and import report behavior
- Text mode documentation and implementation consistency
- Packaging, versions, release workflows, and published release assets
- Obvious TODO/error risks and practical improvements

## Commands and Checks Run

LibreCAD:

- `git status --short --branch`
- `git log -5 --oneline --decorate`
- `python -m pytest`
- `python pdfcadcore_sync_check.py`
- `git status --short --ignored --untracked-files=normal`
- `gh run list --branch main --limit 5`
- `gh run list --workflow release.yml --limit 5`
- `gh release view v1.0.34 --json tagName,publishedAt,isDraft,isPrerelease,assets,url`
- Downloaded published `v1.0.34` release assets to a temp folder and inspected ZIP members:
  - `LibreCAD-PDF-Importer_v1.0.34.zip`
  - `LibreCAD-PDF-Importer-Windows-Portable_v1.0.34.zip`

Blender:

- `git status --short --branch`
- `git log -5 --oneline --decorate`
- `python -m pytest`
- `python pdfcadcore_sync_check.py`
- `git status --short --ignored --untracked-files=normal`
- `python scripts\smoke_release_zip.py "dist\Blender-PDF-Importer_*.zip"`
- `gh run list --branch main --limit 5`
- `gh run list --workflow release.yml --limit 5`
- `gh release view v1.0.34 --json tagName,publishedAt,isDraft,isPrerelease,assets,url`
- Downloaded published `Blender-PDF-Importer_v1.0.34.zip` to a temp folder and smoke-tested it with `scripts\smoke_release_zip.py`

Maintained-file scan:

- Used `git ls-files` plus `Select-String` for `TODO`, `FIXME`, `HACK`, `NotImplemented`, `deprecated`, and `DEPRECATED`.
- `rg` was not available in this shell, so PowerShell and Git file lists were used instead.

## Current Repo State

LibreCAD:

- Clean and aligned: `## main...origin/main`
- Current head: `7a563f4 docs: update Q&A cross-repo validation [skip release]`
- Current version consistency:
  - `pyproject.toml`: `1.0.34`
  - `pdf2dxf.py`: `1.0.34`
- Shared-core sync: `ALL IN SYNC`

Blender:

- Clean and aligned: `## main...origin/main`
- Current head: `c2f075e docs: update Q&A cross-repo validation [skip release]`
- Current version consistency:
  - `pyproject.toml`: `1.0.34`
  - `pdf_vector_importer/__init__.py`: `1.0.34`
  - `blender_pdf_vector_importer/__init__.py`: `1.0.34`
- Shared-core sync: `ALL IN SYNC`

## Validation Results

LibreCAD:

- `python -m pytest`: `39 passed`
- `python pdfcadcore_sync_check.py`: `ALL IN SYNC`
- Latest main CI: success for `docs: update Q&A cross-repo validation [skip release]`
- Release workflow for `v1.0.34`: success
- Published release assets present:
  - `LibreCAD-PDF-Importer-Windows-Portable_v1.0.34.zip`
  - `LibreCAD-PDF-Importer_v1.0.34.zip`
- Published source ZIP contains source/report paths such as `pdf2dxf.py`, `pdfcadcore/import_report.py`, and `librecad_pdf_importer/cli.py`.
- Published portable ZIP contains expected executable entrypoints: `lcpdf-gui.exe`, `pdf2dxf.exe`, and `lcpdf-batch.exe`.

Blender:

- `python -m pytest`: `36 passed`
- `python pdfcadcore_sync_check.py`: `ALL IN SYNC`
- Latest main CI: success for `docs: update Q&A cross-repo validation [skip release]`
- Release workflow for `v1.0.34`: success
- Published release asset present:
  - `Blender-PDF-Importer_v1.0.34.zip`
- Published `v1.0.34` ZIP smoke passed with `scripts\smoke_release_zip.py`.

## Findings

### Blockers

None found for current LibreCAD or Blender source readiness.

The repos are clean, tests pass, shared-core manifests are in sync, current versions are consistent, CI is green, and published `v1.0.34` release assets exist and passed the checks above.

### Non-Blocking Improvements

1. LibreCAD Inno Setup default version is stale.

   File: `C:\1PDF-Importer-LibreCAD\installer\librecad-pdf-importer.iss`

   The script defaults `AppVersion` to `1.0.25`, while current source and release version are `1.0.34`. This is not blocking current GitHub releases because the `v1.0.34` release currently publishes source and portable ZIP assets, not the installer EXE. It would become a packaging error if someone compiled the installer locally without passing an override.

   Proposed improvement: derive `AppVersion` from `pdf2dxf.py`/`pyproject.toml`, or document and enforce `ISCC /DAppVersion=1.0.34 installer\librecad-pdf-importer.iss` in the installer build path.

2. Local ignored `dist` artifacts are stale in both repos.

   LibreCAD local ignored `dist` contains old ZIPs up to `1.0.27`; Blender local ignored `dist` contains old ZIPs up to `1.0.31`. Published GitHub `v1.0.34` assets are correct, so this is not a customer-facing release blocker.

   Proposed improvement: either delete local ignored build outputs during cleanup passes or add a small verifier that warns when ignored local `dist` artifacts do not match the source version.

3. Blender README batch CLI wording can be clearer.

   File: `C:\1PDF-Importer-Blender\README.md`

   The README documents batch usage through `python -m blender_pdf_vector_importer.batch_cli`, while the Blender add-on release ZIP intentionally packages `pdf_vector_importer/` only. The standalone CLI is available from source/dev checkout, not from the add-on ZIP as currently packaged.

   Proposed improvement: clarify that batch CLI usage is source/dev only, or include the standalone CLI package in a separate published artifact if batch import is meant to be a downloadable product surface.

4. Text mode host-run evidence remains thinner than unit evidence.

   Blender has headless tests for mode routing and report fields, and LibreCAD has DXF/report tests. This sweep did not run a live Blender host import or LibreCAD GUI open because the task was source review and local validation. That is acceptable for readiness, but real-world testing should still include host-run checks for all text modes.

   Proposed improvement: add or document a host-run smoke matrix:
   - LibreCAD: generated DXF opens and text entities/outlines appear as expected.
   - Blender: labels, `3d_text`, glyphs, and geometry are visibly distinct where they should be.

5. Maintained-file TODO/deprecation hits are intentional, but vendored PyMuPDF creates scan noise.

   Blender tracks vendored PyMuPDF under `pdf_vector_importer/lib`, and its upstream internals contain many TODO/FIXME/deprecated strings. These are not project defects. The maintained-project hits are compatibility shims and BCS-ARCH-001 guardrail text.

   Proposed improvement: use a standard review scan command that excludes vendored runtime files by default, while preserving release smoke tests that ensure the vendored runtime is present.

## Text Mode Notes

LibreCAD:

- CLI accepts `labels`, `3d_text`, `glyphs`, and `geometry`.
- DXF export uses editable `TEXT` for labels/3d_text and uses `ezdxf` text-to-path conversion for glyphs/geometry where possible.
- README correctly states LibreCAD is 2D-only and does not promise true 3D text parity.

Blender:

- Versions are consistent across add-on and legacy package metadata.
- Text builder normalizes all four modes.
- `3d_text` sets extrusion.
- `glyphs` and `geometry` try to meshify text curves, falling back to the original text object if Blender evaluation fails.
- Remaining risk is host-run coverage, not a clear source defect from this sweep.

## Agreement / Disagreement Points

Agreement:

- No blocking source, sync, CI, or published-release failure was found in the LibreCAD or Blender repos.
- The current published `v1.0.34` release assets are present and consistent with the expected product split.
- The local stale ignored `dist` folders should not be mistaken for published-download state.
- The Inno Setup default version should be fixed before installer EXEs become a release asset.
- Blender CLI/batch packaging should be clarified before presenting it as a non-technical-user download path.

Disagreement:

- None at this time.

Questions for the group:

- Should the LibreCAD installer path be promoted to a first-class release artifact now? If yes, the Inno version default should be treated as a blocker before publishing an installer.
- Should Blender batch CLI be source/dev only, or should we publish a separate CLI-capable ZIP alongside the add-on ZIP?

## Reviewer B Readiness Position

Status: READY for current source and published ZIP release posture, with non-blocking improvements recorded above.

Do not block commit/push on LibreCAD or Blender based on this sweep. If the group decides installer EXEs or Blender standalone CLI downloads are part of the immediate non-technical-user release surface, then the related packaging improvements should be promoted before the next public download update.
