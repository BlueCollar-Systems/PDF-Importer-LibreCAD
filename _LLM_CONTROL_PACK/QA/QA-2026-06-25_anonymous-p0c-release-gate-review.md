# Anonymous QA note - P0-C release gate review

**Date:** 2026-06-25  
**Reviewer:** Anonymous QA, release-pipeline P0 pass  
**Scope:** SketchUp, FreeCAD, LibreCAD, Blender auto-release/test gates and artifact smoke before publish. Website, Steel app, and corpus checked only for whether this P0-C pass needs more than QA mirroring.

## Finding

The original P0-C finding in `QA-2026-06-25_reply-ecosystem-audit-and-cross-round.md` was valid for the packet snapshot: `auto-release.yml` published `--latest` without proving the shipped asset. The live working trees now show uncommitted remediation in all four importer repos:

- `C:\1PDF-Importer-SketchUp`: `.github/workflows/auto-release.yml` modified.
- `C:\1PDF-Importer-FreeCAD`: `.github/workflows/auto-release.yml` modified and `scripts/smoke_release_zip.py` untracked.
- `C:\1PDF-Importer-LibreCAD`: `.github/workflows/auto-release.yml` modified and `scripts/smoke_portable_zip.py` untracked.
- `C:\1PDF-Importer-Blender`: `.github/workflows/auto-release.yml` modified.
- `C:\1BlueCollar-Website`, `C:\1 Structural_Steel_Shapes_App`, and `C:\1pdf-test-corpus` are clean and do not need product workflow/code changes for this P0-C importer pass.

This means P0-C should be treated as **in progress, not shipped** until those workflow and script changes are reviewed, committed, pushed, and proven in GitHub Actions. Local/untracked smoke scripts do not protect releases.

## Required workflow/build changes

1. Keep release creation last in every importer `auto-release.yml`: version bump, dependency install, tests, build, artifact smoke, then tag and `gh release create --latest`. No `continue-on-error` on any gate.
2. SketchUp: keep inline Ruby gates before publish, including Ruby 2.2 Docker smoke for SketchUp 2017 compatibility, then build the RBZ and smoke the RBZ contents before `gh release create`. Recommended extra hardening: expand the RBZ smoke from four required files to the full bundled Poppler manifest or a generated manifest check.
3. FreeCAD: keep `runs-on: windows-latest`; run pdfcadcore sync and tests; build the release zip on Windows; run `scripts/smoke_release_zip.py` against the produced zip before release. The smoke must extract the zip and import bundled PyMuPDF from `PDFVectorImporter/src/lib`, and fail on manylinux or missing `.pyd` payloads.
4. LibreCAD: keep `runs-on: windows-latest`; run diagnostics/tests; build both source zip and Windows portable zip; smoke the portable zip before release by verifying expected EXEs and running `pdf2dxf.exe --help`. Publish the portable asset explicitly, not only `dist/*.zip`.
5. Blender: keep tests and `scripts/smoke_release_zip.py`, but do not rely on an Ubuntu-only smoke for a Windows PyMuPDF payload. Either run the auto-release on `windows-latest` or add a required Windows smoke job before publishing so vendored PyMuPDF imports from the extracted add-on zip. If the artifact remains Windows-offline-only, website copy must say so.
6. If the team prefers separate CI gating instead of inline gates, convert auto-release to a `workflow_run` release workflow that only runs after the importer CI succeeds for the same SHA. Do not allow a push to main to mint `--latest` in parallel with failing CI.

## Verification commands

Run these before committing/pushing the importer workflow edits:

```powershell
git -C 'C:\1PDF-Importer-SketchUp' status --short --branch
git -C 'C:\1PDF-Importer-FreeCAD' status --short --branch
git -C 'C:\1PDF-Importer-LibreCAD' status --short --branch
git -C 'C:\1PDF-Importer-Blender' status --short --branch
git -C 'C:\1PDF-Importer-SketchUp' diff --check -- .github/workflows/auto-release.yml
git -C 'C:\1PDF-Importer-FreeCAD' diff --check -- .github/workflows/auto-release.yml scripts
git -C 'C:\1PDF-Importer-LibreCAD' diff --check -- .github/workflows/auto-release.yml scripts
git -C 'C:\1PDF-Importer-Blender' diff --check -- .github/workflows/auto-release.yml
```

Host artifact smokes:

```powershell
Set-Location -LiteralPath 'C:\1PDF-Importer-SketchUp'
python tools/check_su2017_ruby_compat.py extracted/sketchup_ext
ruby test/smoke_test.rb
ruby test/ruby22_compat_test.rb
ruby test/import_health_test.rb
ruby test/dependency_resolver_test.rb
ruby test/qa_report_test.rb
ruby test/text_mode_routing_test.rb
python build_release.py
python -c "import pathlib,zipfile; p=sorted(pathlib.Path('.').glob('SketchUp-PDF-Importer_v*.rbz')); assert len(p)==1,p; z=zipfile.ZipFile(p[0]); n=set(z.namelist()); req={'bc_pdf_vector_importer.rb','bc_pdf_vector_importer/main.rb','bc_pdf_vector_importer/metadata.rb','bc_pdf_vector_importer/bin/pdftocairo.exe'}; miss=req-n; assert not miss,miss; print('RBZ smoke passed:',p[0])"

Set-Location -LiteralPath 'C:\1PDF-Importer-FreeCAD'
python -m pip install --upgrade pip
python -m pip install 'PyMuPDF>=1.24,<2.0' pytest
python pdfcadcore_sync_check.py --skip-cross-repo
python -m pytest tests/ -q
python build_release.py
python scripts/smoke_release_zip.py 'FreeCAD-PDF-Importer_v*.zip'

Set-Location -LiteralPath 'C:\1PDF-Importer-LibreCAD'
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pytest
python pdfcadcore_sync_check.py --skip-cross-repo
python preflight_check.py --diagnostics
python -m pytest tests/ -q
python build_release.py
python build_windows_portable.py
python scripts/smoke_portable_zip.py 'dist/LibreCAD-PDF-Importer-Windows-Portable_v*.zip'

Set-Location -LiteralPath 'C:\1PDF-Importer-Blender'
python -m pip install --upgrade pip
python -m pip install 'PyMuPDF>=1.24,<2.0' pytest
python pdfcadcore_sync_check.py --skip-cross-repo
python -m pytest tests/ -q
python build_release.py
python scripts/smoke_release_zip.py 'dist/Blender-PDF-Importer_*.zip'
```

After push, verify the Actions logs show the smoke step completing before release creation for each importer, then confirm the GitHub release assets match the intended default downloads. Website/app/corpus should receive only the normal Q&A mirror sync for this note after the Desktop packet is accepted; no website, Steel app, or corpus code change is required for P0-C itself.

*Anonymous QA note - P0-C release gate review - 2026-06-25.*
