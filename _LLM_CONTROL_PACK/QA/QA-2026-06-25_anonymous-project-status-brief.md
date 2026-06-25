# Anonymous Project Status Brief - PDF Importer Ecosystem

Date: 2026-06-25  
Audience: New third-party reviewer with no prior project context  
Author: Anonymous reviewer  
Scope: SketchUp, FreeCAD, LibreCAD, Blender PDF importers, shared PDF tooling/corpus, Blue Collar Systems website, and Structural Steel Shapes app

---

## Executive Summary

The goal is to build a family of PDF importers that can process real-world PDF files as accurately as possible across multiple host applications, not just pass a narrow set of sample PDFs. The test PDFs are examples used to expose failures; they are not the target. The target is broad PDF capability: geometry, text, layers, scale, rotations, page placement, annotations where practical, and install/runtime reliability on ordinary PCs.

The ecosystem currently has working release artifacts for:

| Product | Current public release | Current status |
|---------|------------------------|----------------|
| SketchUp PDF Vector Importer | v3.7.68 | Released; SketchUp 2017 Ruby 2.2 load failure fixed; website points to v3.7.68 |
| FreeCAD PDF Vector Importer | v4.0.48 | Release artifact verified; installer works; unsigned installer warning remains expected |
| LibreCAD PDF Importer | v1.0.41 | Portable Windows ZIP verified; portable path is the supported install path |
| Blender PDF Importer | v1.0.44 | ZIP verified; bundled PyMuPDF path/import smoke passed |
| Blue Collar Systems Website | current main | Live metadata serves SketchUp v3.7.68 and current importer downloads |
| Structural Steel Shapes app | current main | Validated in prior pass; PDF callout lookup/shape lookup work is present |
| PDF test corpus | current main | Public and synthetic corpus exists for regression/stress validation |

The code and release process are materially stronger than at the start of the Q&A cycle. The project is not at final field-release sign-off yet. The remaining gate is human retesting on real machines, especially legacy SketchUp 2017 and the field screenshot scenarios. The newest SketchUp incident proved that automated release checks must cover old host runtimes, not only modern development runtimes.

---

## Primary Goal

Build importers that accurately convert arbitrary PDF content into useful native entities in each host program:

- Geometry should import as editable geometry when vector data exists.
- Text modes should behave according to their label:
  - Geometry: text-like paths/edges as editable geometry where applicable.
  - Glyphs: visual glyph outlines for highest visual fidelity.
  - Labels: native host label/annotation-style text where supported.
  - 3D Text: native 3D/text geometry where supported.
- PDF layers/optional content groups should become host layers/tags where practical.
- Page size, rotation, scale, coordinate placement, title blocks, dimensions, and repeated drawing patterns should be preserved or reported clearly.
- Raster fallback should be explicit and visible, not silently substituted for editable geometry.
- The importers should work on real construction, fabrication, shop, architectural, scanned, hybrid, and difficult PDF files, not only known test samples.

The desired end state is not "works on one machine with one PDF." The desired end state is "a non-technical user can install the right package on a supported PC, import a real PDF, and understand what was imported, what fidelity level was achieved, and what warnings matter."

---

## Operating Parameters

1. Compatibility target:
   - Support the current stable version of each host application.
   - Support older host versions as far back as practical without creating separate products.
   - Explicit legacy target: SketchUp Make 2017, which uses Ruby 2.2.

2. Hardware target:
   - The importers should remain practical on older PCs and outdated hardware.
   - Large or complex PDFs must not become unusably slow without clear warning, fallback, or page-by-page workflow.

3. Dependency target:
   - Release packages should bundle required dependencies whenever legally and technically possible.
   - Users should not need system Python, Ruby gems, manually installed command-line tools, or random OS defaults.
   - Free third-party tools may be bundled or used if license-compatible.
   - Dependency health must be reported in user-facing diagnostics.

4. Install target:
   - Installation must be understandable for non-technical users.
   - The website should direct users to the correct asset, not force them to choose among source ZIPs and host-specific packages.
   - Portable packages are acceptable when they are the most reliable path.

5. Legal/policy target:
   - Do not host or redistribute the SketchUp Make 2017 installer.
   - It may be used internally for QA if already possessed, but it must not be committed, uploaded to the website, or attached to releases.

6. QA target:
   - Q&A is anonymous to reduce bias.
   - Reviewers ask and answer questions through the QA folder.
   - Disagreements should be resolved or explicitly deferred before declaring a gate closed.
   - Test files are evidence, not the whole requirement.

---

## Important Paths

Primary anonymous Q&A drop zone:

```text
C:\Users\Rowdy Payton\Desktop\PDFTest Files\Q&A
```

Mirrored in-repo QA folders:

```text
C:\1PDF-Importer-SketchUp\_LLM_CONTROL_PACK\QA
C:\1PDF-Importer-FreeCAD\_LLM_CONTROL_PACK\QA
C:\1PDF-Importer-LibreCAD\_LLM_CONTROL_PACK\QA
C:\1PDF-Importer-Blender\_LLM_CONTROL_PACK\QA
C:\1BlueCollar-Website\_LLM_CONTROL_PACK\QA
C:\1 Structural_Steel_Shapes_App\_LLM_CONTROL_PACK\QA
```

Active repositories:

```text
C:\1PDF-Importer-SketchUp
C:\1PDF-Importer-FreeCAD
C:\1PDF-Importer-LibreCAD
C:\1PDF-Importer-Blender
C:\1BlueCollar-Website
C:\1 Structural_Steel_Shapes_App
C:\1pdf-test-corpus
C:\Users\Rowdy Payton\Documents\PDF Importers
```

---

## Current Release State

### SketchUp

Current release: v3.7.68  
Current repo head: `ebb47bc`  
GitHub release asset: `SketchUp-PDF-Importer_v3.7.68.rbz`  
Release asset SHA256:

```text
C110972B655831EAA05B2715E82C71A025C83204D0561ABB57FA3FFCE126E396
```

Critical incident resolved:

- A shipped file used Ruby endless range syntax: `text[-69..]`.
- SketchUp 2017 uses Ruby 2.2, which cannot parse that syntax.
- Result: extension failed to load before registering.
- Fix: replace with Ruby 2.2-safe two-argument slice: `text[-69, 69]`.
- Secondary fix: replace `.positive?` usage in shipped code with `> 0` comparisons.
- Prevention: build-time and CI compatibility gates now scan for Ruby 2.2-incompatible syntax and APIs.

Important reviewer note:

- v3.7.65 should not be used for SketchUp 2017 field testing.
- Field testers should install v3.7.68 or later.

### FreeCAD

Current release: v4.0.48  
Current repo head: `893d55e`

Verified facts from prior deploy check:

- Installer runs successfully.
- Package version is 4.0.48.
- Python files compile.
- Bundled PyMuPDF import works.
- Caveat: installer is not code-signed, so Windows trust warnings may appear.

### LibreCAD

Current release: v1.0.41  
Current repo head: `ee5cc12`

Verified facts from prior deploy check:

- Portable ZIP archive is healthy.
- `pdf2dxf` runs and converts a PDF to DXF in smoke testing.
- `lcpdf-import --preflight` works when given a PDF argument.
- Supported install route is the portable Windows ZIP, not a native plugin DLL path.

### Blender

Current release: v1.0.44  
Current repo head: `35632e4`

Verified facts from prior deploy check:

- ZIP archive is healthy.
- Python syntax compile passed.
- Bundled PyMuPDF import works.
- Headless import checks previously passed for all text modes.

### Website

Current repo head: `4e2218a`  
Live metadata status:

- `https://bluecollar-systems.com/repo-metadata.json` serves SketchUp `v3.7.68`.
- Website direct download metadata points to `SketchUp-PDF-Importer_v3.7.68.rbz`.
- Static metadata validation passes.
- `nav.js` syntax check passes.

### Structural Steel Shapes App

Current repo head: `77ad300`

Prior validation:

- `flutter analyze` was clean.
- Windows bundle verifier passed.
- Recent app work includes copied-callout shape lookup / PDF callout lookup support.

### PDF Test Corpus

Current repo head: `fa342fd`

Purpose:

- Provide reproducible public and synthetic PDFs for regression testing.
- Avoid bundling questionable copyrighted or redistribution-restricted PDFs.
- Stress geometry, layers, Type3/text behavior, construction plans, rotations, scale, and difficult rendering cases.

---

## What Has Been Improved

1. Text mode behavior has been repeatedly repaired and tested:
   - SketchUp label and 3D text alignment issues were addressed.
   - Rotated text and leader behavior were adjusted.
   - Vertical BOM quantity handling was improved.
   - Mode routing is tested so labels, 3D text, glyphs, and geometry do not silently collapse into the wrong output type.

2. Diagnostics have improved:
   - Import reports include human-readable summaries.
   - SketchUp gained Import Health reporting.
   - Compatibility reports and preflight style checks were added or improved.
   - Website Report Doctor can inspect local import reports.

3. Packaging has improved:
   - SketchUp release builds now fail if bundled Poppler helpers are missing.
   - SketchUp release builds now fail on Ruby 2.2-incompatible shipped syntax.
   - Python-host importers bundle or verify required dependencies.
   - Website metadata selects correct primary download assets.

4. Testing has improved:
   - Public and synthetic PDF corpus exists.
   - Headless validation covers text modes and placement.
   - Ruby 2.2 compatibility is now a release gate for SketchUp.
   - Website static metadata validation guards against stale/broken download metadata.

5. Release coordination has improved:
   - QA files now distinguish between "commit/push ready" and "final field-release sign-off."
   - Current release links and version metadata are clearer.
   - Broken or risky deployment paths are documented instead of hidden.

---

## Validation Evidence

Recent SketchUp validation commands passed:

```text
python tools/check_su2017_ruby_compat.py extracted/sketchup_ext
ruby tools/ruby22_syntax_check.rb --include-tests
ruby test/ruby22_compat_test.rb
ruby test/import_health_test.rb
ruby test/smoke_test.rb
ruby test/qa_report_test.rb
ruby test/text_mode_placement_test.rb
ruby test/text_label_placement_test.rb
python build_release.py
```

Release asset verification for SketchUp v3.7.68:

- GitHub release exists.
- Direct asset URL returns HTTP 200.
- Archive test passes.
- Extracted `import_health.rb` contains `text[-69, 69]`.
- Extracted release payload passes SketchUp 2017 Ruby compatibility scanner.
- Local Downloads copy was replaced with the exact GitHub release asset.

Website validation:

```text
python tools/validate_static_metadata.py
node --check nav.js
```

Both passed.

Repository status at last sweep:

| Repo | Status |
|------|--------|
| SketchUp | clean, aligned with `origin/main` |
| FreeCAD | clean, aligned with `origin/main` |
| LibreCAD | clean, aligned with `origin/main` |
| Blender | clean, aligned with `origin/main` |
| Website | clean, aligned with `origin/main` |
| Structural Steel Shapes app | clean, aligned with `origin/main` |
| PDF test corpus | clean, aligned with `origin/main` |

---

## Remaining Open Gates

The project should not be represented as fully field-signed-off until these are done:

1. SketchUp 2017 field retest:
   - Install `SketchUp-PDF-Importer_v3.7.68.rbz`.
   - Confirm extension loads without Ruby Console syntax error.
   - Import a PDF.
   - Open Import Health and confirm long paths truncate cleanly.

2. Field screenshot retest:
   - Re-run the previously reported SketchUp, FreeCAD, LibreCAD, and Blender scenarios.
   - Confirm labels, 3D text, glyphs, and geometry output as expected.
   - Confirm Blender importer works in the real user install path.

3. Older hardware/performance retest:
   - Test large and complex PDFs on slower PCs.
   - Confirm page-by-page workflows, warnings, or fallback behavior keep the app usable.

4. Installer trust:
   - FreeCAD installer works but is unsigned.
   - Windows SmartScreen/trust warnings should be expected until code signing is implemented.

5. Broader "any PDF" claim:
   - No PDF importer can honestly guarantee perfect handling of every possible PDF.
   - The correct product claim is maximum practical fidelity, transparent diagnostics, and continuous regression expansion as new PDFs expose edge cases.

---

## Current Truth Statement

The importers are substantially improved, current downloadable artifacts are healthy, and the latest SketchUp release fixes the SketchUp 2017 load blocker. The website now points users to the fixed SketchUp release. The project is ready for renewed real-world testing, but not yet final field-release sign-off.

The next reviewer should focus on confirming behavior on actual host installations and older PCs, not on re-arguing whether the test files define the goal. The test files are examples. The goal is broad, accurate, dependable PDF import across real user environments.

---

## Recommended Next Human Test Sequence

1. Download current packages from the website, not stale local files.
2. Install each importer on a clean or representative PC.
3. For SketchUp 2017, specifically use v3.7.68 or later.
4. Import a small known-good PDF in each text mode.
5. Import one complex construction/fabrication PDF page-by-page.
6. Verify:
   - geometry is geometry,
   - labels are labels,
   - 3D text is 3D text,
   - glyphs are glyph outlines,
   - PDF layers become host layers/tags where supported,
   - warnings and import reports honestly describe fallbacks or limitations.
7. Save screenshots and import reports for any mismatch.
8. Add each mismatch to Q&A as a new anonymous finding with:
   - host app and version,
   - importer version,
   - PDF name/page,
   - import mode,
   - text mode,
   - expected result,
   - actual result,
   - screenshot/report/log path.

---

## Bottom Line For A New Reviewer

This is a multi-host PDF import ecosystem aimed at professional, non-technical users who need accurate drawing data in CAD/modeling tools. The work is not about one PDF or one machine. The work is about making the importers robust across arbitrary PDFs, legacy hosts, old hardware, bundled dependencies, clear installs, and honest diagnostics.

At this point, implementation and release automation have caught up to the latest known blocker. The correct next move is controlled human field testing using the current website downloads, with any failures fed back into Q&A as concrete reproducible cases.
