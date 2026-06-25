# Artifact Acceptance Matrix

Date: 2026-06-25  
Status: Draft for anonymous review  
Purpose: Define what must be true before a PDF importer, website update, or app build is considered deployable.

## Principle

Source tests are necessary but not sufficient. A release candidate is not accepted until the **exact packaged artifact** is built, inspected, dependency-checked, and smoke-tested in a way that reflects the oldest supported runtime for that product.

This matrix is intended to prevent failures like:

- plugin loads on the developer machine but not in an older host runtime;
- dependency is available globally on the build machine but missing on the user PC;
- website points to stale or wrong release assets;
- a text mode is selected but a different entity type is created silently;
- a large PDF import is technically correct but unusably slow on older hardware.

## Universal Acceptance Gates

These gates apply to every product:

| Gate | Requirement |
|------|-------------|
| Version consistency | Source metadata, package name, release tag, and website metadata agree |
| Package integrity | ZIP/RBZ/EXE opens or installs without corruption |
| Dependency locality | Required dependencies load from bundled/package paths, not developer-machine globals |
| Oldest runtime | The oldest supported host/runtime is either tested or explicitly marked deferred |
| Smoke import | At least one real PDF import or conversion runs through the packaged artifact |
| Text mode proof | Selected text mode and actual output entity category are recorded or verified |
| Diagnostics | Logs/import reports explain fallbacks and warnings |
| User path | A non-technical install path exists and is documented |
| Website path | Public website/download metadata points to the accepted artifact |

## SketchUp Importer

Current accepted public release: `v3.7.68`  
Artifact: `SketchUp-PDF-Importer_v3.7.68.rbz`  
Critical oldest runtime: SketchUp Make 2017 / Ruby 2.2

| Gate | Command or verification | Status |
|------|-------------------------|--------|
| Ruby syntax | `ruby -c` over `extracted/sketchup_ext/**/*.rb` | Required |
| Ruby 2.2 API/syntax | `python tools/check_su2017_ruby_compat.py extracted/sketchup_ext` | Required |
| Ruby scanner | `ruby tools/ruby22_syntax_check.rb --include-tests` | Required |
| Unit tests | `ruby test/import_health_test.rb`; `ruby test/ruby22_compat_test.rb` | Required |
| Smoke | `ruby test/smoke_test.rb` | Required |
| Build | `python build_release.py` | Required |
| Package inspection | Extract RBZ and confirm `PLUGIN_VERSION`, `metadata.rb`, bundled Poppler helpers, and `import_health.rb` safe slice | Required |
| Oldest host launch | Install in SketchUp 2017 and confirm no Ruby Console load error | Required for field sign-off; can be deferred only with explicit note |
| Text mode proof | Import same PDF in Labels, 3D Text, Glyphs, Geometry; confirm entity category and placement | Required for field sign-off |

Minimum refusal rule: do not recommend `v3.7.65` or earlier for SketchUp 2017.

## FreeCAD Importer

Current accepted release line: `v4.0.48`  
Artifact: Windows installer EXE plus release ZIP/workbench payload  
Critical runtime: FreeCAD embedded Python compatible with bundled PyMuPDF

| Gate | Command or verification | Status |
|------|-------------------------|--------|
| Unit tests | `pytest -q` | Required |
| Dependency bundle | `python build_release.py --no-vendor-deps` after vendoring, or normal `python build_release.py` with vendoring | Required |
| PyMuPDF locality | Import PyMuPDF from `PDFVectorImporter/src/lib` or installed package path | Required |
| Installer run | Silent or normal installer completes and installs to expected FreeCAD Mod path | Required |
| Python compile | Compile installed payload with target Python where possible | Required |
| FreeCAD smoke | FreeCADCmd import/preflight smoke through installed workbench | Required where FreeCAD is available |
| Text mode proof | ShapeString/outline/3D behavior verified by import report or host inspection | Required for field sign-off |
| Trust caveat | Unsigned installer warning documented until code signing exists | Required |

Minimum refusal rule: if bundled PyMuPDF cannot import from the installed path, the artifact is not accepted.

## LibreCAD Importer

Current accepted release line: `v1.0.41`  
Artifact: `LibreCAD-PDF-Importer-Windows-Portable_v1.0.41.zip`  
Critical runtime: portable EXEs on target Windows baseline

| Gate | Command or verification | Status |
|------|-------------------------|--------|
| Unit tests | `pytest -q` | Required |
| Build portable | `python build_windows_portable.py` | Required for deployable Windows release |
| ZIP health | Archive test opens all EXEs | Required |
| CLI smoke | `pdf2dxf.exe <pdf> <out.dxf> --text-mode labels` | Required |
| Preflight smoke | `lcpdf-import.exe <pdf> --preflight` | Required |
| DXF inspection | Output DXF exists and contains expected TEXT or outline entities | Required |
| Text mode proof | Labels as DXF TEXT; glyphs/geometry as outlines where supported; 3D text documented as 2D host limitation | Required |
| Portable UX | Extract-and-run path documented clearly | Required |

Minimum refusal rule: no-argument preflight failure is not a blocker; preflight requires a PDF path by current design.

## Blender Importer

Current accepted release line: `v1.0.44`  
Artifact: `Blender-PDF-Importer_v1.0.44.zip`  
Critical runtime: Blender Python ABI compatible with vendored PyMuPDF

| Gate | Command or verification | Status |
|------|-------------------------|--------|
| Unit tests | `pytest -q` | Required |
| Python compile | Compile add-on Python files | Required |
| Vendored runtime | `python build_release.py` verifies required PyMuPDF runtime files | Required |
| ZIP health | Archive opens and add-on root layout is correct | Required |
| PyMuPDF locality | Import PyMuPDF from `pdf_vector_importer/lib` | Required |
| Headless smoke | Blender headless import script exercises all text modes where Blender is installed | Required |
| Interactive install | Preferences -> Add-ons -> Install ZIP; enable add-on; import a PDF | Required for field sign-off |
| Text mode proof | Text object vs mesh/curve/glyph output verified in scene or import report | Required |

Minimum refusal rule: if the add-on depends on global site-packages, the artifact is not accepted.

## Website

Current role: download metadata, install guidance, Report Doctor, capability matrix

| Gate | Command or verification | Status |
|------|-------------------------|--------|
| Metadata sync | `python tools/sync_repo_metadata.py` or equivalent release dispatch | Required before deploy |
| Static metadata | `python tools/validate_static_metadata.py` | Required |
| JavaScript syntax | `node --check nav.js`; `node --check report-doctor.js` | Required |
| Current release links | `repo-metadata.json` points to current accepted artifacts | Required |
| No private assets | Metadata must not expose private Steel-Shapes release assets | Required |
| Download UX | Host-specific primary download labels are clear | Required |
| Legal | Do not host SketchUp Make 2017 installer | Required |

Minimum refusal rule: if website metadata points to a superseded broken SketchUp release for SketchUp 2017 users, deploy is not accepted.

## Steel Logic App

Current role: companion structural steel shapes app and future PDF/import-report workflow bridge

| Gate | Command or verification | Status |
|------|-------------------------|--------|
| Static analysis | `flutter analyze` | Required |
| Unit/widget tests | Run available Flutter tests | Required when present |
| Windows bundle | Windows bundle verifier | Required for Windows artifact |
| Version consistency | `pubspec.yaml`, release tag, website metadata agree | Required |
| Offline behavior | Shape lookup works without network for bundled data | Required |
| PDF callout workflow | Copied-callout lookup verified with common shape callouts | Required |
| Privacy | Website/app privacy copy matches stored/exported/synced data | Required |

Minimum refusal rule: if core shape lookup requires network for local bundled data, the artifact is not accepted.

## Review Questions

1. Should "oldest host launch" be a hard blocker for every release, or can it be a documented deferred gate for non-critical patch releases?
2. Which importer is still missing the strongest package-path dependency proof?
3. Should text-mode proof be added to `import_report.json` as `actual_text_entity_types` across all hosts?
4. What old-hardware benchmark machine should define the first performance baseline?

## Proposed Decision

Adopt this matrix as the release-readiness floor. Any future claim that an importer is "ready" should specify whether it means:

1. source tests are green;
2. packaged artifact tests are green;
3. oldest-host launch is green;
4. human field confirmation is green.

Those are separate gates and should not be collapsed into one word.
