# Blue Collar Systems Project Handoff - 2026-07-01

This is the project-wide handoff for a new contributor. Read this file first. It is intended to be complete enough that you can start improving, correcting, testing, and building across all repos without asking the owner for more direction.

## Mission

Blue Collar Systems is building practical, professional tools for fabricators, welders, detailers, builders, and CAD users. The current ecosystem includes PDF importers for SketchUp, FreeCAD, LibreCAD, and Blender; a Steel Logic structural-shape app; public steel shape packs; a website; release automation; and a shared test corpus.

The importers are not meant to pass only a few test PDFs. They must be able to process any reasonable PDF as accurately as possible, including layers, linework, fills, images, text, dimensions, leaders, forms/XObjects, scale data, raster/vector hybrids, and damaged/edge-case files. Test files are examples and regression anchors, not the whole purpose.

Core product standard:

- Maximum fidelity by default.
- No hidden "fast but less accurate" quality tiers.
- Every import mode must target the most accurate possible result for its strategy.
- Import mode and text rendering mode are orthogonal:
  - Import modes: Auto, Vector, Raster, Hybrid.
  - Text modes: Labels, 3D Text, Glyphs, Geometry/Outlines depending on host capability.
- All tools should run on any PC that can run the parent software, including older hardware and legacy host versions as far back as practical.
- Release packages must bundle required dependencies where allowed: Python packages, PyMuPDF, Poppler helpers, Ruby-compatible helpers, DXF libraries, etc.
- Non-technical users should be able to install and use the tools without installing system Python/Ruby/pip packages or hunting for dependencies.
- If you know a likely problem and know a safe solution, implement the solution. Do not leave preventable failures as notes.

## Coordination Rules

Authoritative Q&A folder:

```text
C:\Users\Rowdy Payton\Desktop\PDFTest Files\Q&A
```

As of this handoff, that folder only contains `Instructions 0607202613216.txt` plus this handoff. Historical Q&A was mirrored into repo control packs. The richest current mirror is:

```text
C:\1PDF-Importer-SketchUp\_LLM_CONTROL_PACK\QA
```

Important historical files to read when taking over:

- `QA-2026-06-24_COORDINATION-HUB.md`
- `QA-2026-06-24_worker-status-log.md`
- `Q&A_INDEX.md`
- `QA-2026-06-26_regression-popup-scale-alignment.md`
- `QA-2026-06-25_release-pipeline-p0-resolution.md`
- `QA-2026-06-24_human-confirmation-script.md`
- `QA-2026-06-24_third-party-project-briefing.md`
- `QA-2026-06-24_round6-corpus-and-features.md`

Working style:

- Check existing Q&A before starting so you do not duplicate old work.
- Post important findings, disagreements, and resolutions in Q&A.
- Anonymous reviewer style is accepted.
- For broad work, ask and answer hard questions in Q&A before committing.
- Do not wait for the owner to micromanage. The standing instruction is to proceed, improve, verify, commit, and push when work is safe and validation is green.
- Do not revert local changes you did not make. If a dirty file appears unrelated, inspect it and work around it.
- Use `[skip release]` for documentation-only commits that should not publish new product builds.
- Commit/push implementation only after tests and release gates appropriate to the changed repo have passed.

## Canonical Repos and Paths

Use these paths. Older names such as `C:\1SU-PDFimporter`, `C:\1FC-PDFimporter`, `C:\1LC-PDFimporter`, `C:\1BL-PDFimporter`, and `C:\1pdfcadcore` are stale or absent.

| Scope | Canonical path | GitHub repo |
| --- | --- | --- |
| SketchUp PDF Importer | `C:\1PDF-Importer-SketchUp` | `BlueCollar-Systems/PDF-Importer-SketchUp` |
| FreeCAD PDF Importer | `C:\1PDF-Importer-FreeCAD` | `BlueCollar-Systems/PDF-Importer-FreeCAD` |
| LibreCAD PDF Converter | `C:\1PDF-Importer-LibreCAD` | `BlueCollar-Systems/PDF-Importer-LibreCAD` |
| Blender PDF Importer | `C:\1PDF-Importer-Blender` | `BlueCollar-Systems/PDF-Importer-Blender` |
| Website | `C:\1BlueCollar-Website` | `BlueCollar-Systems/BlueCollar-Website` |
| Steel Logic app | `C:\1 Structural_Steel_Shapes_App` | structural steel app repo |
| Test corpus | `C:\1pdf-test-corpus` | `BlueCollar-Systems/pdf-test-corpus` |
| Local manifest/docs | `C:\Users\Rowdy Payton\Documents\PDF Importers` | local manifest repo |

Steel shape packs were consolidated:

- SketchUp `.skp` packs live under `C:\1PDF-Importer-SketchUp\steel_shapes`.
- DXF/DWG packs live under `C:\1PDF-Importer-FreeCAD\steel_shapes`.
- Standalone steel shape repos can be retired once confirmed unnecessary.

## Current Release Snapshot

Observed on 2026-07-01. Always verify again with `gh release view` before publishing.

| Product | Current public release | Asset(s) | Notes |
| --- | --- | --- | --- |
| SketchUp PDF Importer | `v3.7.75` | `SketchUp-PDF-Importer_v3.7.75.rbz` | Published 2026-06-26. No pre-import guidance popup. Ruby 2.2 gates green. |
| FreeCAD PDF Importer | `v4.0.54` | `FreeCAD-PDF-Importer-Setup_v4.0.54.exe`, `FreeCAD-PDF-Importer_v4.0.54.zip` | Windows setup and ZIP both published. PyMuPDF bundled. |
| LibreCAD PDF Converter | `v1.0.48` | `LibreCAD-PDF-Importer-Windows-Portable_v1.0.48.zip`, `LibreCAD-PDF-Importer_v1.0.48.zip` | Portable ZIP is the canonical non-technical install path. |
| Blender PDF Importer | `v1.0.51` | `Blender-PDF-Importer_v1.0.51.zip` | Add-on ZIP bundles private PyMuPDF runtime. |
| Steel Logic app | `1.0.9+11` in `pubspec.yaml` | Android/iOS primary; Windows portable possible | Not a PDF geometry importer. It complements importers via AISC lookup and future BOM/report bridge. |
| Website | `origin/main` latest observed `1a1c237` | Static Cloudflare Pages site | Current local checkout is on a non-main `devin/...` branch. See workspace notes. |
| Test corpus | `d478dda` | private corpus repo | Use `BCS_CORPUS_ROOT=C:\1pdf-test-corpus`. |

Release digests from GitHub:

```text
SketchUp v3.7.75 RBZ sha256:6c91d378fc32307b3a27fa71771bfbec6b9689643c99f58d8b1ed00cb6538c9d
FreeCAD v4.0.54 setup sha256:23ef64b81c62521a610c3d9293d7fb3c7fe864be6812e32a43d2265cbe18120d
FreeCAD v4.0.54 zip sha256:a09185aa6a4655b5ad1e3a8cecb29e22474979bed835894b1cfdd08a7013974b
LibreCAD v1.0.48 portable sha256:1a67001fe5a20265da3d7ed727bd3ca807a2234e1e5d3ca6355dce6954334d0c
LibreCAD v1.0.48 source zip sha256:760efbb9a0f9271098fe759ee7448a2d070fdc0f6471769099d37c2840e3843e
Blender v1.0.51 zip sha256:84ea620c6a04d85affffbc27260e2aa9ee15effb08c8dace563b84247b0f6660
```

## Current Workspace Notes

State observed 2026-07-01:

- `C:\1PDF-Importer-SketchUp` is on `main...origin/main` with a modified `extracted/sketchup_ext/bc_pdf_vector_importer/version_notice.rb`. `git diff` showed no content diff, only CRLF/LF warnings. Treat as line-ending-only until proven otherwise.
- `C:\1PDF-Importer-FreeCAD` is clean on `main...origin/main`.
- `C:\1PDF-Importer-LibreCAD` is on `main...origin/main` with a modified `scripts/smoke_portable_zip.py`. `git diff` showed no content diff, only CRLF/LF warnings. Treat as line-ending-only until proven otherwise.
- `C:\1PDF-Importer-Blender` is clean on `main...origin/main`.
- `C:\1BlueCollar-Website` is currently on branch `devin/1780145949-remove-broken-hash-gate`, synced with `origin/devin/1780145949-remove-broken-hash-gate` at `3ae8bdf`. `origin/main` exists separately and was fetched at `1a1c237`. Before website work, decide intentionally whether to keep working on the devin branch or switch/create a branch from `origin/main`.
- `C:\1 Structural_Steel_Shapes_App` is clean on `main...origin/main`.
- `C:\1pdf-test-corpus` is clean on `main...origin/main`.
- `C:\Users\Rowdy Payton\Documents\PDF Importers` is a local manifest repo on `main` with no remote status shown; its manifest files are historical and may not reflect latest release versions. Use GitHub releases and website metadata as live truth.

Do not clean or reset the two line-ending-only modified files unless you are deliberately normalizing line endings and can explain why.

## Architecture Overview

### Shared importer concepts

All importers should preserve:

- Page geometry and coordinate orientation.
- Vector paths, curves, arcs, circles, rectangles, faces/closed loops.
- Stroke/fill color, line weight, dash patterns where host supports them.
- PDF Optional Content Groups/layers.
- Raster pages and embedded images.
- Text placement, rotation, scaling, baseline, bbox behavior, and selected entity type.
- Scale detection confidence and plain-language warnings.
- Import report with human-readable summary and machine-readable details.

BCS-ARCH-001 rule:

- Auto, Vector, Raster, and Hybrid are strategies, not quality levels.
- No mode is allowed to silently sacrifice accuracy.
- If a mode falls back, it must report the fallback and why.

Text-mode contract:

- Labels: editable text/label entities where host supports them.
- 3D Text: host-native 3D text or extruded text where host supports it.
- Glyphs/Outlines/Geometry: vectorized text for exact visual fidelity.
- If host limitations force a fallback, the report must say so.

### Shared core

FreeCAD, LibreCAD, and Blender share a `pdfcadcore` family of code, with FreeCAD usually acting as the canonical source for synchronized shared files. Each repo has a `pdfcadcore_sync_check.py` and `pdfcadcore_sync_manifest.json`. When changing shared extraction/report code:

1. Patch the canonical copy.
2. Sync or manually apply the same change to the other shared-core repos.
3. Regenerate/update manifests as required.
4. Run sync checks in all affected repos.

SketchUp has a separate Ruby implementation for host compatibility, with Ruby 2.2 support required for SketchUp Make 2017.

## Recent Critical Resolutions

### SketchUp pre-import popup

The owner saw a SketchUp popup that mentioned LibreCAD and appeared every time. Final resolution:

- No pre-import guidance popup in SketchUp.
- `import_guidance.rb` removed.
- `ImportGuidance.maybe_show` removed from normal and Safe Mode imports.
- v3.7.75 RBZ verified to contain no `import_guidance.rb`, no `ImportGuidance`, and no "Before you import" text.
- Regression test: `test\pre_import_prompt_test.rb`.

Do not reintroduce any pre-file-picker prompt. Put guidance in the import dialog, Import Health, reports, compatibility docs, or website help instead.

### SketchUp labels/text alignment

Recent fixes restored:

- Labels mode creates native SketchUp labels instead of silently converting rotated labels to 3D/mesh text.
- Rotated label vectors are handled so leaders/bounding artifacts are reduced where SketchUp allows.
- BOM QUAN column single-digit quantities can stay vertical without forcing MARK/DESCRIPTION text vertical.
- Regression tests: `text_mode_placement_test.rb`, `text_label_placement_test.rb`, `text_category_placement_test.rb`.

Remaining risk: human visual retest on real shop PDFs is still required.

### FreeCAD text fitting and scaling

Recent fixes:

- Draft Labels and ShapeString 3D Text shrink conservatively to fit PDF text span bboxes when host font metrics would overflow.
- Raster/hybrid background placement uses effective import scale.
- Full suite passed at v4.0.54.

Remaining risk: dense dimension clusters and non-embedded font substitution should be field tested.

### Blender text-mode routing

Recent fixes:

- Legacy adapter now passes selected text mode to object creation.
- Labels and 3D Text remain font curves, with 3D Text distinct through extrusion behavior.
- Glyphs/Geometry convert through mesh evaluation where possible.

Remaining risk: true per-character glyph semantics are deferred; current docs should honestly describe text-run outline meshes.

### LibreCAD install path

Final product decision:

- The Windows portable ZIP is the canonical non-technical install path.
- Native LibreCAD plugin/menu integration is optional.
- LibreCAD has no real 3D text; do not imply it does.
- GUI professional import is Auto-oriented; CLI/batch exposes mode controls.

### Release pipeline P0s

Past P0 failures were real:

- FreeCAD `--latest` initially published a Linux PyMuPDF runtime from an Ubuntu runner.
- LibreCAD `--latest` initially published a source-only ZIP instead of the portable ZIP.
- Auto-release originally published without enough pre-release artifact tests.

Current resolution:

- FreeCAD and LibreCAD release gates run on Windows.
- FreeCAD release ZIP smoke verifies Windows PyMuPDF `.pyd` files and rejects Linux `.so` artifacts.
- LibreCAD release smoke verifies portable executables and `pdf2dxf.exe --help`.
- Release workflows use committed versions and `gh release create --target` rather than unsafe tag-push/version-bump assumptions.
- Website dispatch runs after release; website also syncs on a schedule.

Do not weaken release gates.

## Test Corpus

Canonical path:

```text
C:\1pdf-test-corpus
```

Set:

```powershell
$env:BCS_CORPUS_ROOT = 'C:\1pdf-test-corpus'
```

Useful commands:

```powershell
python C:\1pdf-test-corpus\tools\list_tier1.py --host SU --resolved
python C:\1pdf-test-corpus\tools\list_tier1.py --host FC --resolved
python C:\1pdf-test-corpus\tools\list_tier1.py --host LC --resolved
python C:\1pdf-test-corpus\tools\list_tier1.py --host BL --resolved
python C:\1pdf-test-corpus\tools\list_tier1.py --host app --resolved
python C:\1pdf-test-corpus\tools\validate_contract_schemas.py
python C:\1pdf-test-corpus\tools\dependency_audit.py --json C:\1pdf-test-corpus\tools\dependency_audit_report.json
```

Corpus rules:

- `tier1/web` and `tier2/web` redistributable files may be committed.
- `tier1/user` shop PDFs are gitignored and must not be committed.
- Proprietary/user PDFs are manifest-only unless the owner explicitly says otherwise.
- Use test files to reveal classes of failure; do not code only to one file.

Pre-test contracts from `C:\1pdf-test-corpus\PRETEST_ACCEPTANCE_CONTRACTS.md`:

- Ready Check.
- Text Entity Verification.
- Source Provenance.
- Import Recovery.

These contracts should become the next layer of product proof across importers, website Report Doctor, and Steel Logic support flows.

## Repo-Specific Handoff

### SketchUp PDF Importer

Path:

```text
C:\1PDF-Importer-SketchUp
```

Current version:

```text
PLUGIN_VERSION = 3.7.75
```

Primary goals:

- Best possible PDF-to-SketchUp fidelity from SketchUp Make 2017 through current SketchUp.
- Ruby 2.2 compatibility is mandatory.
- RBZ must work offline after download.
- Poppler helpers are bundled in Windows release RBZs.
- No SketchUp Make 2017 installer redistribution from the website; support the app, do not host Trimble/SketchUp installers.

Important files:

- `extracted/sketchup_ext/bc_pdf_vector_importer/main.rb`
- `extracted/sketchup_ext/bc_pdf_vector_importer/geometry_builder.rb`
- `extracted/sketchup_ext/bc_pdf_vector_importer/svg_text_renderer.rb`
- `extracted/sketchup_ext/bc_pdf_vector_importer/import_dialog.rb`
- `extracted/sketchup_ext/bc_pdf_vector_importer/import_health.rb`
- `test\pre_import_prompt_test.rb`
- `test\text_label_placement_test.rb`
- `test\text_mode_placement_test.rb`
- `tools\ruby22_syntax_check.rb`
- `tools\run_golden_oracle_test.rb`
- `tools\fetch_third_party_binaries.ps1`

Validation commands:

```powershell
ruby test\pre_import_prompt_test.rb
ruby test\ruby22_compat_test.rb
ruby test\smoke_test.rb
ruby test\text_mode_placement_test.rb
ruby test\text_label_placement_test.rb
ruby test\text_category_placement_test.rb
ruby test\corpus_placement_test.rb
python build_release.py
```

Before a public RBZ release:

1. Verify version consistency in loader, metadata, README badge.
2. Run Ruby 2.2 gate.
3. Build RBZ.
4. Inspect RBZ for required bundled helpers and absence of stale files.
5. Let GitHub `su-pdfimporter-ci`, `corpus-placement`, and `auto-release` finish green.
6. Verify website metadata points to the new RBZ.

Priority backlog:

- Human retest on SketchUp 2017 and current SketchUp with Tier-1 shop PDFs.
- Continue text/leader alignment hardening without changing entity contract.
- Large/heavy PDF performance on old PCs.
- Bounding box/leader visual artifacts for native labels where SketchUp API allows mitigation.
- Better per-object provenance from SketchUp entities back to PDF spans/layers.
- Implement Ready Check/Text Entity Verification/Import Recovery contract outputs.

### FreeCAD PDF Importer

Path:

```text
C:\1PDF-Importer-FreeCAD
```

Current version:

```text
pyproject.toml version = 4.0.54
```

Primary goals:

- FreeCAD import workbench that installs easily via Setup EXE or ZIP.
- Windows Setup EXE is preferred for non-technical users.
- Bundle PyMuPDF under private runtime paths so system Python is not required.
- Maintain shared `pdfcadcore` canonical behavior for FC/LC/BL.

Important files:

- `PDFVectorImporter\src\PDFImporterCore.py`
- `PDFVectorImporter\pdfcadcore\*`
- `preflight_check.py`
- `build_release.py`
- `build_windows_installer.py`
- `scripts\smoke_release_zip.py`
- `tests\test_pdf_importer_text_reconstruction.py`
- `tests\test_import_report_text_mode.py`
- `pdfcadcore_sync_check.py`

Validation commands:

```powershell
python -m pytest tests --basetemp $env:TEMP\pytest-fc
python -m py_compile PDFVectorImporter\src\PDFImporterCore.py
python build_release.py
python scripts\smoke_release_zip.py "dist\FreeCAD-PDF-Importer_v*.zip"
python build_windows_installer.py
```

Priority backlog:

- Human host retest in FreeCAD 0.21, 1.0, and 1.1 if available.
- Confirm label and ShapeString fit on dense dimensions, stacked fractions, and non-embedded fonts.
- Emit text entity verification report data.
- Improve source provenance sidecar.
- Harden install diagnostics for missing/blocked PyMuPDF DLLs and antivirus quarantine.
- Continue release smoke tests for Setup EXE as well as ZIP.

### LibreCAD PDF Converter

Path:

```text
C:\1PDF-Importer-LibreCAD
```

Current version:

```text
pyproject.toml version = 1.0.48
```

Primary goals:

- Convert PDF drawings to DXF for LibreCAD and other 2D CAD tools.
- Canonical user install is the Windows portable ZIP.
- No separate Python/pip/admin rights for normal users.
- Be honest that LibreCAD has no true 3D text.

Important files:

- `pdf2dxf.py`
- `dxf_import_engine.py`
- `dxf_text_builder.py`
- `gui.py`
- `build_windows_portable.py`
- `build_release.py`
- `scripts\smoke_portable_zip.py`
- `preflight_check.py`
- `pdfcadcore\*`
- `tests\*`

Validation commands:

```powershell
python -m pytest tests --basetemp $env:TEMP\pytest-lc
python build_windows_portable.py
python scripts\smoke_portable_zip.py "dist\LibreCAD-PDF-Importer-Windows-Portable_v*.zip"
python build_release.py
python pdfcadcore_sync_check.py
```

Priority backlog:

- Human retest with portable ZIP on a clean Windows PC.
- Verify DXF TEXT vs outlines behavior across LibreCAD, QCAD, AutoCAD/DraftSight if available.
- Improve GUI progress/error messages for non-technical users.
- Keep portable ZIP first on release page.
- Add Ready Check output and import recovery diagnostics.

### Blender PDF Importer

Path:

```text
C:\1PDF-Importer-Blender
```

Current version:

```text
pyproject.toml version = 1.0.51
```

Primary goals:

- Installable Blender add-on ZIP with bundled private PyMuPDF runtime.
- File > Import > PDF Vector workflow.
- Curves/collections/materials should preserve PDF organization and appearance as well as Blender allows.

Important files:

- `pdf_vector_importer\__init__.py`
- `pdf_vector_importer\operators.py`
- `blender_pdf_vector_importer\adapters\blender_adapter.py`
- `blender_pdf_vector_importer\batch_cli.py`
- `build_release.py`
- `preflight_check.py`
- `tests\test_legacy_adapter_text_modes.py`
- `pdfcadcore_sync_check.py`

Validation commands:

```powershell
python -m pytest tests --basetemp $env:TEMP\pytest-bl
python build_release.py
python pdfcadcore_sync_check.py
```

Priority backlog:

- Host-run validation inside Blender 3.6 LTS, 4.0-4.2, and current stable Blender.
- Confirm add-on install from ZIP, not just source tests.
- Improve text entity verification and honest glyph semantics.
- Batch import UX/reporting.
- Add import recovery diagnostics for failed/cancelled imports.

### Blue Collar Website

Path:

```text
C:\1BlueCollar-Website
```

Important current warning:

The local checkout is on:

```text
devin/1780145949-remove-broken-hash-gate
```

`origin/main` is separate and newer. Before website work, inspect:

```powershell
git status -sb
git branch -vv
git log --oneline --decorate origin/main -5
git log --oneline --decorate HEAD -5
```

Do not accidentally overwrite the devin branch. If working on production website content, switch or branch from `origin/main` deliberately.

Primary goals:

- Make Blue Collar Systems look trustworthy, current, and easy for non-technical users.
- Website download links should be dynamic/current through `repo-metadata.json`.
- Do not hardcode versioned release URLs in HTML except safe fallbacks.
- Keep install instructions clear: what to download, how to install, offline behavior, compatibility boundaries.
- Report Doctor should help users and support inspect `import_report.json`.
- Do not host third-party installers such as SketchUp Make 2017.

Important files:

- `index.html`
- `shapes.html`
- `feedback.html`
- `privacy.html`
- `nav.js`
- `styles.css`
- `repo-metadata.json`
- `tools\sync_repo_metadata.py`
- `tools\validate_static_metadata.py`
- `.github\workflows\website-ci.yml`

Validation commands:

```powershell
python tools\sync_repo_metadata.py
python tools\validate_static_metadata.py
```

GitHub workflow:

- `website-ci` runs static checks and deploys Cloudflare Pages.
- Importer releases dispatch `product-release`.
- Website also syncs metadata on cron.

Priority backlog:

- Verify all visible links use canonical repo names, not stale `SU-PDFimporter`/`FC-PDFimporter` labels.
- Improve install/help copy for non-technical users.
- Expand Report Doctor to recognize Ready Check, Text Entity Verification, Source Provenance, and Import Recovery contracts.
- Keep Shapes Hub current with steel shape release assets.
- Maintain privacy/trust/security pages.

### Steel Logic App

Path:

```text
C:\1 Structural_Steel_Shapes_App
```

Current version:

```text
pubspec.yaml: steel_logic 1.0.9+11
```

Primary goals:

- Mobile-first AISC v16.0 structural steel shape reference and inventory tool.
- Complement the PDF importers, not replace them.
- Fast lookup, measurement parsing, inventory, shape SVGs, and future import-report/BOM bridge.
- Local-first and shop-floor friendly.

Important files/folders:

- `lib\*`
- `test\*`
- `pubspec.yaml`
- `docs\Structural Steel Shapes App Master Brief v1.7.2.docx.docx`
- `tools\l10n_audit.dart`
- `tools\package_windows_release.ps1`
- `tools\verify_windows_release_artifacts.ps1`
- `Structural_Steel-shapes-database-v16.0.csv`

Validation commands:

```powershell
flutter analyze
flutter test
dart run tools/l10n_audit.dart
powershell -ExecutionPolicy Bypass -File .\tools\verify_windows_release_artifacts.ps1
```

Priority backlog:

- PDF callout lookup is the first importer/app bridge. Continue toward full BOM/import-report ingestion.
- Implement or refine `steellogic://shape/W12X26` deep links.
- Keep app clear that it is not a PDF geometry importer.
- Improve Report Doctor/app handoff so a user can click a PDF callout and find AISC shape data.
- Preserve localization, measurement, and no-silent-rounding standards.

### Test Corpus

Path:

```text
C:\1pdf-test-corpus
```

Primary goals:

- Shared PDFs and metadata for repeatable cross-host testing.
- Keep redistributable public files in git.
- Keep proprietary/user shop PDFs out of git.
- Provide acceptance contracts and dependency audit tooling.

Priority backlog:

- Add more legally safe public PDFs that stress layers, clipping, rotated text, embedded fonts, malformed files, CAD exports, scans, and hybrid drawings.
- Build host-specific oracle checks rather than screenshot-only validation.
- Use test corpus in release gates where feasible without bloating CI.

### Local Manifest Repo

Path:

```text
C:\Users\Rowdy Payton\Documents\PDF Importers
```

This repo contains early source-of-truth manifest files:

- `pdf-importer-manifest.md`
- `pdf-importer-manifest.json`
- `dependency-packaging-audit.md`

Warning: these files are historical and may show old release assets. Update them before using as current truth. Live truth is GitHub Releases plus website `repo-metadata.json`.

## Human Interactive Confirmation Gate

The next big gate is human interactive testing in real host apps. Automated tests are green for current releases, but they do not prove visual/semantic behavior inside all parent applications.

Minimum human test matrix:

- SketchUp Make 2017 and current SketchUp.
- FreeCAD 0.21, 1.0, and 1.1 where possible.
- LibreCAD with the portable ZIP on a clean PC.
- Blender 3.6 LTS and current stable Blender.
- Steel Logic app for callout lookup and shape reference flows.
- Website downloads from the live site, not local files.

Use test PDFs:

- `1017 - Rev 0.pdf`
- `BOUND SET SEALED DRAWINGS 18 FEB 2026.pdf`
- `SCOMBINED.pdf`
- Corpus Tier-1 web PDFs.
- At least one raster-only scan.
- At least one hybrid raster/vector PDF.
- At least one encrypted or intentionally refused PDF to prove recovery.

For each test, record:

- Host software version and OS/hardware.
- Downloaded installer/ZIP/RBZ filename.
- Import mode and text mode.
- Whether geometry came in as geometry.
- Whether labels came in as labels.
- Whether 3D Text came in as 3D Text.
- Whether glyphs/outlines came in as vectorized glyphs/outlines.
- Scale confidence and whether actual measured geometry is correct.
- Import time and object count.
- Whether any warning was understandable.
- Import report path.
- Screenshots before/after.
- Any crash/cancel/recovery behavior.

## Immediate Best Next Work

Start here if no newer instruction exists:

1. Create/update a Q&A session from this handoff.
2. Normalize or intentionally preserve the two line-ending-only dirty files:
   - SketchUp `version_notice.rb`.
   - LibreCAD `scripts/smoke_portable_zip.py`.
3. Decide website branch strategy:
   - Preserve `devin/1780145949-remove-broken-hash-gate`.
   - For production website work, branch from `origin/main`.
4. Run a current all-repo readiness sweep.
5. Run current release artifact checks, not just source tests.
6. Implement the pre-test acceptance contracts incrementally:
   - first `actual_text_entity_types` in import reports;
   - then Ready Check output;
   - then Import Recovery diagnostics;
   - then Source Provenance sidecars.
7. Prepare human test sheets and make the first human confirmation pass easier.
8. Continue app/importer bridge:
   - import report -> Steel Logic callout lookup;
   - BOM/table extraction -> app search;
   - deep links from reports/website into app.
9. Keep improving performance for heavy PDFs and older PCs without sacrificing accuracy.
10. Keep dependency packaging airtight and release pipelines adversarially tested.

## Commit and Release Guidance

Before committing:

```powershell
git status -sb
git diff --check
```

Before pushing importer code:

- Run targeted tests for touched area.
- Run full suite when shared core, parser, release, installer, or text placement changes.
- Build/smoke release artifact if packaging changed.
- Update Q&A and mirrors if the change resolves a coordinated question.

Before public release:

- Confirm version files are aligned.
- Confirm release workflow is not skipped accidentally.
- Confirm GitHub release asset exists and has the expected name.
- Confirm website `repo-metadata.json` updates.
- Confirm live website displays current version/download.

Use `[skip release]` only for docs/QA updates that should not publish product artifacts.

## Things Not to Do

- Do not code only to the latest user screenshot or one PDF.
- Do not reduce accuracy silently for speed.
- Do not reintroduce SketchUp pre-import guidance popups.
- Do not claim all text modes are 100 percent verified until host-level semantic tests prove it.
- Do not host SketchUp Make 2017 installer on the website.
- Do not commit proprietary shop PDFs.
- Do not publish release assets without artifact smoke tests.
- Do not reset/revert someone else's dirty work without explicit direction.
- Do not let website copy drift to old repo names or stale versions.

## Definition of Done

A change is done only when:

- The behavior is implemented.
- Tests or artifact checks prove the behavior.
- Relevant Q&A status is updated.
- Release artifacts are correct if public downloads are affected.
- Website metadata is current if public downloads are affected.
- User-facing copy is honest about host limitations.
- Known preventable problems are fixed, not merely documented.

The long-term finish line is not "current tests pass." The finish line is a family of tools that a non-technical shop user can download on a normal PC, install without help, run on real drawings, and trust to preserve the drawing as accurately as the parent software allows.

