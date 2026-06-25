# Anonymous QA Note - FreeCAD P0-A/P0-C Release Pipeline

Date: 2026-06-25
Scope: read-only inspection of `C:\1PDF-Importer-FreeCAD` only. No code edits or commits.

## Findings

1. **P0-A was valid against committed HEAD.** The committed `auto-release.yml` builds the default `--latest` ZIP on `ubuntu-latest`, runs `python build_release.py`, then publishes with `gh release create ... --latest`. `build_release.py` vendors `PyMuPDF>=1.24,<2.0` into `PDFVectorImporter/src/lib` with `pip install --only-binary :all:` but without `--platform`, `--abi`, or `--python-version`, and verifies import only with the same runner Python. Since `PDFVectorImporter/src/lib/` is ignored/untracked, a clean Ubuntu release runner resolves a Linux PyMuPDF payload and can still pass its own import check.

2. **An unstaged in-progress `auto-release.yml` fix is present and points the right way, but it is not shipped yet.** The worktree currently switches auto-release to `windows-latest` and adds release tests plus an extracted ZIP payload smoke before `gh release create --latest`. Treat this as pending until committed and run in Actions.

3. **P0-C is only partially addressed by that unstaged fix.** The current staged gate runs `python -m pytest tests/ -q` before `python build_release.py`, but `tests/test_preflight_check.py` expects the ignored/untracked `PDFVectorImporter/src/lib` to exist and import. A clean runner can fail the gate before vendoring unless the build happens first or that diagnostic test is changed to use an extracted release artifact. Separately, `windows-release.yml` still builds/uploads/publishes the tag installer assets without a release test, extracted-ZIP import smoke, or silent installer smoke.

## Recommended exact changes

1. Commit/rework the auto-release direction: keep `runs-on: windows-latest`, but gate publish in this order: setup Python, version bump, `python build_release.py`, `python -m pip install "PyMuPDF>=1.24,<2.0" pytest`, `python pdfcadcore_sync_check.py --skip-cross-repo`, `python -m pytest tests/ -q`, extracted-ZIP payload smoke, then and only then `gh release create ... --latest`.

2. Make the dependency payload check explicit. Either build the latest ZIP on Windows as above, or add platform-targeted vendoring in `build_release.py`:
   `python -m pip install --target PDFVectorImporter/src/lib --only-binary=:all: --platform win_amd64 --implementation cp --python-version 310 --abi cp310-abi3 "PyMuPDF>=1.24,<2.0"`.
   Then fail the build if `src/lib/pymupdf-*.dist-info/WHEEL` does not contain `Tag: cp310-abi3-win_amd64`, if no `.pyd` exists, or if any `.so`/`manylinux` payload exists.

3. Mirror the same gate in `windows-release.yml` after `python build_windows_installer.py` and before upload/publish: run tests, inspect/import the `dist/FreeCAD-PDF-Importer_v*.zip`, and run a silent install smoke for `dist/FreeCAD-PDF-Importer-Setup_v*.exe`.

## Verification commands

```powershell
git -C C:\1PDF-Importer-FreeCAD status --short --branch
git -C C:\1PDF-Importer-FreeCAD ls-files 'PDFVectorImporter/src/lib/**'
rg -n "runs-on|Run release gate tests|Build release zip|Smoke release zip|gh release|--latest|Publish GitHub Release assets" C:\1PDF-Importer-FreeCAD\.github\workflows
```

After a Windows release build:

```powershell
$zip = Get-ChildItem C:\1PDF-Importer-FreeCAD\dist -Filter 'FreeCAD-PDF-Importer_v*.zip' | Select-Object -First 1
$smoke = Join-Path $env:TEMP 'fc-release-smoke'
Remove-Item $smoke -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive -LiteralPath $zip.FullName -DestinationPath $smoke -Force
Get-Content (Get-ChildItem "$smoke\PDFVectorImporter\src\lib" -Recurse -Filter WHEEL | Select-Object -First 1).FullName
Get-ChildItem "$smoke\PDFVectorImporter\src\lib" -Recurse -Include *.pyd,*.dll,*.so
$lib = Join-Path $smoke 'PDFVectorImporter\src\lib'
python -c "import sys; sys.path.insert(0, r'$lib'); import pymupdf as fitz; print(getattr(fitz, '__version__', '') or getattr(fitz, 'VersionBind', ''))"
```

Silent installer smoke on `windows-latest`:

```powershell
New-Item -ItemType Directory -Force "$env:APPDATA\FreeCAD\v1-1\Mod" | Out-Null
$exe = Get-ChildItem C:\1PDF-Importer-FreeCAD\dist -Filter 'FreeCAD-PDF-Importer-Setup_v*.exe' | Select-Object -First 1
$p = Start-Process $exe.FullName -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=$env:TEMP\fc-setup.log" -Wait -PassThru
if ($p.ExitCode -ne 0) { Get-Content "$env:TEMP\fc-setup.log"; exit $p.ExitCode }
python C:\1PDF-Importer-FreeCAD\preflight_check.py --diagnostics
```

Anonymous QA reviewer note.
