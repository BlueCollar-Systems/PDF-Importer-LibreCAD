# Current-Version Human Confirmation Addendum

Date: 2026-06-25  
Status: Active field-test addendum  
Author: Anonymous reviewer  
Purpose: Prevent stale-version field tests and align human confirmation with the current public website downloads.

---

## Why This Addendum Exists

Some mirrored human-confirmation documents still list older version numbers. Those older numbers are useful history, but they are not the correct target for the next real-world test pass.

Field testers should use the current public releases from the website or GitHub Releases, not stale local downloads.

---

## Current Test Targets

| Host / product | Use this version for current field testing | Artifact type |
|----------------|--------------------------------------------|---------------|
| SketchUp PDF Vector Importer | v3.7.68 or later | `.rbz` |
| FreeCAD PDF Vector Importer | v4.0.48 or later | Windows installer |
| LibreCAD PDF Importer | v1.0.41 or later | Windows portable ZIP |
| Blender PDF Importer | v1.0.44 or later | Blender add-on ZIP |
| Blue Collar Systems website | live metadata serving current releases | website |
| Steel Logic app | current pushed app build | app package / local build |
| PDF test corpus | current `C:\1pdf-test-corpus` | local corpus repo |

SketchUp 2017 warning:

- Do not test SketchUp 2017 with SketchUp importer v3.7.65.
- Use v3.7.68 or later.
- The specific failure being retested is whether the extension loads without Ruby syntax errors in SketchUp 2017.

---

## Preflight Commands

Set corpus root:

```powershell
$env:BCS_CORPUS_ROOT = 'C:\1pdf-test-corpus'
```

List resolved Tier-1 files:

```powershell
python C:\1pdf-test-corpus\tools\list_tier1.py --host SU --resolved
python C:\1pdf-test-corpus\tools\list_tier1.py --host FC --resolved
python C:\1pdf-test-corpus\tools\list_tier1.py --host LC --resolved
python C:\1pdf-test-corpus\tools\list_tier1.py --host BL --resolved
```

Confirm website metadata:

```powershell
Invoke-WebRequest -UseBasicParsing https://bluecollar-systems.com/repo-metadata.json
```

Expected SketchUp metadata:

```text
tag: v3.7.68
asset: SketchUp-PDF-Importer_v3.7.68.rbz
```

---

## Required Field Confirmation Matrix

| Test | SketchUp | FreeCAD | LibreCAD | Blender | Notes |
|------|----------|---------|----------|---------|-------|
| Host detects importer on startup | ☐ | ☐ | ☐ | ☐ | SketchUp 2017 is mandatory if available |
| Simple vector PDF imports geometry | ☐ | ☐ | ☐ | ☐ | Verify editable geometry where supported |
| Labels mode creates labels/text | ☐ | ☐ | ☐ | ☐ | Verify actual entity type |
| 3D Text mode creates expected 3D/text output | ☐ | ☐ | n/a | ☐ | LibreCAD is 2D; n/a is honest |
| Glyph/Geometry mode creates outlines | ☐ | ☐ | ☐ | ☐ | Watch performance/entity counts |
| Rotated text remains aligned/readable | ☐ | ☐ | ☐ | ☐ | Use rotated text fixture |
| Multi-page page selection works | ☐ | ☐ | ☐ | ☐ | Verify correct sheet imported |
| Layered PDF preserves layers/tags where supported | ☐ | ☐ | ☐ | ☐ | Record host limitations |
| Heavy PDF warns or remains usable | ☐ | ☐ | ☐ | ☐ | Especially old hardware |
| Import report/log matches observed behavior | ☐ | ☐ | ☐ | ☐ | Save report for any issue |

---

## SketchUp 2017 Specific Retest

1. Install `SketchUp-PDF-Importer_v3.7.68.rbz`.
2. Start SketchUp 2017.
3. Confirm no Ruby Console load error.
4. Open PDF Vector Importer menu.
5. Import one small PDF in Labels mode.
6. Open Import Health.
7. Confirm long paths display with `...` prefix and no error.

Pass condition:

```text
SketchUp 2017 loads the extension and completes a small import without Ruby syntax/load errors.
```

Fail condition:

```text
Any Ruby Console load error, missing menu, failed extension registration, or import-health exception.
```

---

## Reporting Template For Failures

Create a new anonymous Q&A file with this information:

```text
Host:
Host version:
Importer version:
Operating system:
Hardware notes:
PDF path/name:
Page(s):
Import mode:
Text mode:
Expected result:
Actual result:
Screenshot path:
import_report.json path:
Log path:
Was fallback reported:
Severity: P0 / P1 / P2
```

---

## Current Decision

The current public releases are ready for renewed real-world testing. They should not be represented as final field-signed-off until this addendum or equivalent human confirmation is completed and all P0 failures are resolved.
