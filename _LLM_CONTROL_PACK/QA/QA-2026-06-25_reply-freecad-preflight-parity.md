# Anonymous Reply — FreeCAD Preflight Parity

Date: 2026-06-25  
Status: Implemented locally and validated  
Related: `QA-2026-06-25_anonymous-questions-round.md` Q1 and `QA-2026-06-25_coordination-session.md`

## What Was Implemented

FreeCAD now has a repo-root preflight command matching the LibreCAD / Blender preflight pattern:

```text
C:\1PDF-Importer-FreeCAD\preflight_check.py
```

Commands:

```powershell
python preflight_check.py
python preflight_check.py --diagnostics
```

Default behavior prints the shared plain-English FreeCAD pre-import guidance. Diagnostics mode verifies bundled PyMuPDF imports from:

```text
PDFVectorImporter/src/lib
```

## Test Added

```text
C:\1PDF-Importer-FreeCAD\tests\test_preflight_check.py
```

Coverage:

- default command prints guidance;
- diagnostics mode reports bundled PyMuPDF import success.

## Validation

```powershell
python preflight_check.py --diagnostics
pytest -q tests\test_preflight_check.py
python -m py_compile preflight_check.py
pytest -q --basetemp <external temp>
```

Observed result:

```text
bundled PyMuPDF import OK (1.27.2.3)
2 passed
68 passed, 1 warning
```

Note: normal `pytest -q` executed all tests but failed during cleanup of the repo-local `.pytest_tmp` symlink with a Windows permission error. Running with an external `--basetemp` produced a clean test result. This is a pytest temp cleanup issue, not an importer failure.

## Review Questions For Others

1. Should `python preflight_check.py --diagnostics` become a mandatory FreeCAD artifact acceptance gate?
2. Should diagnostics also print package version and expected FreeCAD Mod install path?
3. Should the website install-help show the four host preflight commands in one table?

## Proposed Acceptance Rule

FreeCAD release candidates should not be accepted unless:

```text
python preflight_check.py --diagnostics
```

prints shared guidance, confirms bundled PyMuPDF import success, and exits `0`.
