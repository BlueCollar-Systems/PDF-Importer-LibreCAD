# Anonymous QA Note - LibreCAD P0-B / Release Gate Follow-up

**Date:** 2026-06-25  
**Scope:** `C:\1PDF-Importer-LibreCAD` release pipeline, live latest release metadata, and website download routing.  
**Author:** Anonymous QA reviewer.

## Findings

1. **P0-B live artifact status: currently repaired, but still worth gating.**  
   The live GitHub latest release is `v1.0.45` and now includes both:
   - `LibreCAD-PDF-Importer-Windows-Portable_v1.0.45.zip` - 186,393,621 bytes
   - `LibreCAD-PDF-Importer_v1.0.45.zip` - 130,211 bytes

   Live `https://bluecollar-systems.com/repo-metadata.json` also lists both assets for LibreCAD, and `C:\1BlueCollar-Website\nav.js:49-50` ranks the Windows portable before the source ZIP. So the prior "latest is source-only" symptom is **not true for the current public latest**.

2. **The repo has an uncommitted auto-release fix draft.**  
   Relevant release-pipeline entries from `git status --short` in `C:\1PDF-Importer-LibreCAD` include:
   - `M .github/workflows/auto-release.yml`
   - `?? scripts/`

   The modified auto-release now runs on `windows-latest`, builds the portable ZIP, smokes it, and uploads explicit portable/source asset paths (`.github/workflows/auto-release.yml:117-154`). This is the right direction and directly addresses the source-only auto-release gap, but it is not committed yet.

3. **The draft auto-release gate currently calls a nonexistent preflight flag.**  
   `.github/workflows/auto-release.yml:122` runs:

   ```bash
   python preflight_check.py --diagnostics
   ```

   `preflight_check.py:22-25` only defines `--install`; `python preflight_check.py --diagnostics` fails with `error: unrecognized arguments: --diagnostics`. Use `python preflight_check.py` or add a real `--diagnostics` alias before relying on this gate.

4. **The tag/manual release workflow is still ungated.**  
   `.github/workflows/release.yml:40-58` builds `build_release.py`, builds `build_windows_portable.py`, uploads `dist/*.zip`, then publishes with `softprops/action-gh-release`. It does **not** run sync checks, preflight, pytest, or `scripts/smoke_portable_zip.py` before publishing. If this workflow remains a supported release path, it can still publish a broken or incomplete portable.

## Recommended Exact Workflow Changes

1. Commit the auto-release direction, but replace the bad preflight call:

```bash
python pdfcadcore_sync_check.py --skip-cross-repo
python preflight_check.py
python -m pytest tests/ -q
```

2. Keep and commit `scripts/smoke_portable_zip.py`, then call it from both release paths:

```bash
python scripts/smoke_portable_zip.py "dist/LibreCAD-PDF-Importer-Windows-Portable_v*.zip"
```

3. Add the same gate to `.github/workflows/release.yml` before upload/publish:

```yaml
- name: Run release gate tests
  run: |
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt pytest
    python pdfcadcore_sync_check.py --skip-cross-repo
    python preflight_check.py
    python -m pytest tests/ -q

- name: Build source release zip
  run: python build_release.py

- name: Build Windows portable app zip
  run: python build_windows_portable.py

- name: Smoke Windows portable zip
  run: python scripts/smoke_portable_zip.py "dist/LibreCAD-PDF-Importer-Windows-Portable_v*.zip"
```

4. Publish explicit expected assets, not a broad `dist/*.zip`, in both workflows:

```bash
PORTABLE="dist/LibreCAD-PDF-Importer-Windows-Portable_v${VERSION}.zip"
SOURCE="dist/LibreCAD-PDF-Importer_v${VERSION}.zip"
test -f "$PORTABLE"
test -f "$SOURCE"
gh release create "$TAG" --title "$TITLE" --generate-notes --latest "$PORTABLE" "$SOURCE"
```

For `release.yml`, either set `defaults.run.shell: bash` and use the same shell block, or implement the equivalent PowerShell `Test-Path` checks before `softprops/action-gh-release`.

5. Optional hardening: extend `scripts/smoke_portable_zip.py` beyond `pdf2dxf.exe --help` to run a tiny one-page PDF-to-DXF conversion through the portable `pdf2dxf.exe`, proving the bundled PyMuPDF/ezdxf path works from the extracted ZIP.

## Verification Commands

Live latest release assets:

```powershell
$r = Invoke-RestMethod -Uri 'https://api.github.com/repos/BlueCollar-Systems/PDF-Importer-LibreCAD/releases/latest' -Headers @{ 'User-Agent'='qa' }
$r.tag_name
$r.assets | Select-Object name,size,browser_download_url
```

Live website metadata:

```powershell
$m = Invoke-RestMethod -Uri 'https://bluecollar-systems.com/repo-metadata.json' -Headers @{ 'User-Agent'='qa' }
$m.repos.'BlueCollar-Systems/PDF-Importer-LibreCAD'.latest_release.assets | Select-Object name,size,url
```

Local release-gate checks:

```powershell
cd C:\1PDF-Importer-LibreCAD
git status --short
python pdfcadcore_sync_check.py --skip-cross-repo
python preflight_check.py
python -m pytest tests/ -q
python .\scripts\smoke_portable_zip.py "dist\LibreCAD-PDF-Importer-Windows-Portable_v*.zip"
```

Observed on this pass:
- `python -m pytest tests/ -q` -> `45 passed, 11 subtests passed`
- `python pdfcadcore_sync_check.py --skip-cross-repo` -> `ALL IN SYNC`
- `python preflight_check.py` -> diagnostics OK
- `python preflight_check.py --diagnostics` -> fails, flag not defined
- `python .\scripts\smoke_portable_zip.py "dist\LibreCAD-PDF-Importer-Windows-Portable_v*.zip"` -> passed against local `v1.0.36` portable ZIP

## Release Readiness Note

Do not keep P0-B open as "current latest is source-only" for `v1.0.45`; that is now false. Keep the release-pipeline item open until the portable build + test + executable smoke gate is committed and applied to **both** `auto-release.yml` and `release.yml`, with the invalid `--diagnostics` call removed or implemented.
