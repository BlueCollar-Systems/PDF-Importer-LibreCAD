# Anonymous Third-Party Project State Report

Date: 2026-06-25  
Scope: PDF importer ecosystem, Blue Collar Systems website, and companion steel-shapes app  
Audience: New independent reviewer with no prior project context  
Authorship: Anonymous technical summary for Q&A review

## Executive Summary

The project goal is to produce practical, installable PDF importers that let non-technical users bring PDF drawing content into common design/CAD/modeling tools as accurately and predictably as possible. The target is not to handle a few hand-picked test PDFs. The target is broad PDF correctness: geometry, text, layers, page transforms, scale clues, annotations, embedded fonts, glyph outlines, raster fallbacks, and real-world construction/shop drawing complexity.

The current ecosystem includes importers for SketchUp, FreeCAD, LibreCAD, and Blender, plus a Blue Collar Systems website that publishes downloads and a structural steel shapes app that supports the larger product family. The importers are intended to run on ordinary Windows PCs without depending on whatever Python, Ruby, Poppler, PyMuPDF, or other tooling happens to be installed globally on the machine.

As of this report, the repos are clean and pushed. The most recent critical issue was a SketchUp 2017 load failure caused by modern Ruby syntax incompatible with SketchUp 2017's embedded Ruby 2.2 runtime. That issue has been fixed, released, and guarded against with new compatibility checks that run during packaging and CI.

## Product Goals

The importers are being built to satisfy these goals:

1. Preserve PDF vector geometry as editable CAD/model geometry where possible.
2. Preserve PDF text according to the user's chosen text mode:
   - labels should import as host-native labels or text-like annotations where the host supports them;
   - 3D text should import as host-native 3D text where the host supports it;
   - geometry/glyph mode should import text as vector outlines or glyph geometry when exact visual fidelity matters;
   - fallback behavior should be explicit, logged, and understandable.
3. Preserve PDF layer structure where possible.
4. Handle multi-page PDFs and selected page ranges.
5. Handle rotated pages, scaled pages, transformed text, embedded fonts, Type3 fonts, missing fonts, and page coordinate conversions.
6. Detect common drawing signals such as title blocks, dimensions, repeated geometry, tables, fabrication/shop drawings, and scale clues.
7. Provide reliable logs, import reports, diagnostics, and QA evidence so failures are actionable.
8. Install easily for non-technical users.
9. Work on any reasonable Windows PC, including older machines, without relying on OS-provided developer tools.
10. Avoid shipping releases that pass on the developer machine but fail on a customer machine because of runtime-version mismatch, missing dependencies, unsigned dependency assumptions, or untested installer behavior.

## Target Repositories

Primary repos currently involved:

| Repo | Purpose | Current branch state |
|------|---------|----------------------|
| `C:\1PDF-Importer-SketchUp` | SketchUp RBZ importer | Clean, aligned with `origin/main` |
| `C:\1PDF-Importer-FreeCAD` | FreeCAD installer/importer | Clean, aligned with `origin/main` |
| `C:\1PDF-Importer-LibreCAD` | LibreCAD portable/CLI PDF-to-DXF tooling | Clean, aligned with `origin/main` |
| `C:\1PDF-Importer-Blender` | Blender add-on importer | Clean, aligned with `origin/main` |
| `C:\1BlueCollar-Website` | Public downloads and product website metadata | Clean, aligned with `origin/main` |
| `C:\1 Structural_Steel_Shapes_App` | Companion structural steel shapes app | Clean, aligned with `origin/main` |
| `C:\1pdf-test-corpus` | Shared test corpus and public/user PDF verification material | Clean, aligned with `origin/main` |

Latest confirmed heads at time of report:

| Repo | Head |
|------|------|
| SketchUp | `ebb47bc` |
| FreeCAD | `893d55e` |
| LibreCAD | `ee5cc12` |
| Blender | `35632e4` |
| Website | `4e2218a` |
| Steel shapes app | `77ad300` |
| PDF test corpus | `fa342fd` |

## Supported Importers And Current Release State

### SketchUp

Current public release: `v3.7.69`  
Download asset: `SketchUp-PDF-Importer_v3.7.69.rbz`  
Published asset SHA256: `B9C02F29AA4CC2CA26175CE490CA8CDABDBD79A7A7A1AC346FE453F22FD5D153`

Important support target: SketchUp Make 2017 and newer SketchUp versions. SketchUp 2017 embeds Ruby 2.2, which is substantially older than modern desktop Ruby. The project must treat Ruby 2.2 compatibility as a hard release gate for the SketchUp importer.

Recent incident:

- A field install failed to load in SketchUp 2017.
- Root cause: `import_health.rb` used `text[-69..]`, an endless range syntax added after Ruby 2.2.
- Secondary risk found and fixed: `.positive?` usage, also unavailable in Ruby 2.2.
- Fix shipped in the 3.7.66+ release line; current public release is 3.7.69.
- Prevention now includes compatibility scanners and tests:
  - `tools/check_su2017_ruby_compat.py`
  - `tools/ruby22_syntax_check.rb`
  - `test/ruby22_compat_test.rb`
  - `test/import_health_test.rb`
  - CI workflow updates
  - `build_release.py` now fails before packaging if Ruby 2.2-incompatible syntax/API usage is detected.

This is the correct direction: failures caused by runtime mismatch must be blocked at build time, not discovered by users after download.

### FreeCAD

Current recently verified release line: `v4.0.50`  
Artifact type: Windows installer EXE

Confirmed behavior from recent verification:

- Installer runs successfully.
- Installed payload compiles.
- Bundled PyMuPDF imports successfully.
- FreeCAD command-line smoke checks passed for text modes and import paths.
- Test suite recently reported green.

Known deployment caveat:

- The installer is functional but not code-signed. Windows may show SmartScreen or trust warnings. This is not a functional importer failure, but it matters for non-technical user confidence and should be addressed when budget/process allows.

### LibreCAD

Current recently verified release line: `v1.0.43`  
Artifact type: Windows portable ZIP

Confirmed behavior from recent verification:

- ZIP archive is healthy.
- CLI tools run.
- PDF-to-DXF smoke conversion succeeded.
- Test suite recently reported green.

Known behavior:

- `lcpdf-import --preflight` requires a PDF path argument. That is normal for the current CLI design, but reviewers should not treat no-argument preflight as a valid health check.

### Blender

Current recently verified release line: `v1.0.46`  
Artifact type: Blender add-on ZIP

Confirmed behavior from recent verification:

- ZIP archive is healthy.
- Python compile checks passed.
- Bundled PyMuPDF imports successfully.
- Blender headless smoke checks recently passed for all text modes.

Historical concern:

- The Blender importer had previously been described as not working. Later validation reported it working headlessly. Human interactive testing in Blender should still be part of the next confirmation pass because headless success does not fully prove UI workflow quality.

### Website

The website is expected to publish current download metadata and labels. It currently references the SketchUp `v3.7.69` release and the correct RBZ download URL.

Website responsibilities:

- Display current release versions.
- Link to GitHub release assets.
- Avoid stale download links.
- Provide non-technical users with a clear path to install.
- Reflect dependency/compatibility caveats where needed.

### Structural Steel Shapes App

The steel shapes app is part of the Blue Collar Systems tool ecosystem. It is not itself a PDF importer, but it shares the same quality bar: predictable Windows builds, clean app verification, and non-technical usability.

Recent verification reported:

- `flutter analyze` clean.
- Windows bundle verifier passed.

## Operating Parameters

The project should be judged against these parameters:

1. Test files are examples, not the full target.
2. Any valid PDF may include combinations of vector paths, text operators, embedded fonts, Type3 fonts, images, masks, clipping, rotations, layers, annotations, transparency, page boxes, and malformed or unusual content.
3. The importers should prefer editable geometry/text when accurate and possible.
4. When exact host-native text cannot be guaranteed, glyph/geometry fallback is acceptable if it preserves visual fidelity and logs the reason.
5. Fallbacks must not silently misrepresent content.
6. Large or complex PDFs must not become unusably slow without explanation. Performance settings and diagnostic reporting matter.
7. Installers/packages must bundle required dependencies or verify/install them reliably.
8. Local developer success is insufficient. The release must work on a clean user PC with the target host application installed.
9. SketchUp 2017 compatibility is mandatory for the SketchUp importer unless the product explicitly drops SketchUp 2017 support.
10. Releases should be built through gates that test the real packaged artifact, not only source files.

## Text Mode Expectations

Text has been the highest-risk feature area. A third-party reviewer should understand the intended behavior:

| Mode | Expected result | Risk |
|------|-----------------|------|
| Labels | Host-native labels/text annotations where available | Alignment, leader placement, rotation, host API differences |
| 3D Text | Host-native 3D text where available | Baseline, scaling, rotation, font mismatch, heavy geometry |
| Geometry/Glyphs | Vector outlines or glyph geometry | Performance, entity count, visual clutter, bounding boxes/components |
| Auto/Fallback | Best available mode based on PDF/host capability | Must log why a fallback happened |

Recent user-observed issues included text coming in as glyphs when labels or 3D text were expected, plus label/leader alignment concerns. The codebase has received fixes and test coverage, but the next real-world human confirmation pass should specifically test each text mode in each host.

## Dependency And Packaging Expectations

All importers should avoid relying on the operating system's default developer/runtime components. Expected package behavior:

- SketchUp RBZ bundles required Poppler helper binaries for Windows.
- FreeCAD installer bundles required Python package dependencies, including PyMuPDF.
- LibreCAD portable ZIP includes its executable tooling and required support binaries.
- Blender ZIP includes required Python dependency payloads or a reliable local dependency path.
- Installers should be as simple as possible for non-technical users.
- Errors should explain missing host applications or incompatible versions in plain language.

The current strongest gap is not functionality but user trust: unsigned Windows installers can trigger warnings.

## Current Validation Status

Recent validation reported the following green checks:

| Area | Validation |
|------|------------|
| SketchUp | Ruby syntax checks, Ruby 2.2 compatibility gate, Import Health test, smoke test, gated RBZ build |
| FreeCAD | Installer smoke, Python compile, bundled PyMuPDF import, FreeCAD import smoke, test suite |
| LibreCAD | ZIP health, CLI smoke, PDF-to-DXF conversion, test suite |
| Blender | ZIP health, Python compile, PyMuPDF import, Blender headless import smoke, test suite |
| Website | Metadata references current SketchUp release, repo clean |
| App | Flutter analysis and Windows bundle verification previously green |

Current repo state is clean and pushed for the tracked repos listed above.

## Known Caveats

1. FreeCAD installer is unsigned. This can create Windows trust prompts.
2. Human interactive testing is still required. Automated checks cannot prove all UI behavior, menu behavior, installer UX, or visual alignment correctness.
3. SketchUp 2017 cannot be fully proven from modern Ruby alone. The new gates catch known incompatible syntax/API usage, but a real SketchUp 2017 launch remains the strongest confirmation.
4. Heavy PDFs remain a performance risk. Glyph/geometry text modes can create many entities and may be slow on older hardware.
5. Text alignment, leaders, font substitution, and rotated/scaled text remain the areas most likely to need further field tuning.
6. PDF correctness is inherently broad. Some malformed, encrypted, damaged, or exotic PDFs may need explicit fallback or clearer user messaging rather than perfect import.

## Next Recommended Review Steps

The next third-party review should follow this order:

1. Confirm each repo is clean and aligned with its remote.
2. Download the public website assets, not local build artifacts.
3. Install each importer on a clean Windows machine or VM.
4. Confirm the host application detects the importer without startup errors.
5. For SketchUp, include SketchUp Make 2017 specifically.
6. Test the same PDF in all text modes:
   - labels;
   - 3D text;
   - glyph/geometry;
   - auto/default.
7. Compare expected entity type against actual host entities.
8. Test at least:
   - simple vector PDF;
   - construction/shop drawing;
   - multi-page PDF;
   - rotated page;
   - embedded font PDF;
   - Type3 font or unusual font PDF;
   - text-heavy sheet;
   - geometry-heavy sheet;
   - layer-containing PDF.
9. Record:
   - import duration;
   - entity counts;
   - text mode used;
   - fallback reason if any;
   - visual alignment concerns;
   - whether the import report/log matches observed behavior.
10. File any failures in Q&A with exact artifact version, host version, PDF name, page number, selected options, screenshot, log path, and expected vs actual behavior.

## Decision State

The project is not in a "nothing left to do forever" state. It is in a deployable, actively hardened state with current known critical blockers addressed. The correct next phase is controlled real-world testing using current public downloads, with strict reporting of any mismatch between selected import mode and actual output.

The SketchUp 2017 Ruby failure is the main recent example of why the release process must keep shifting from "source seems fine" to "the exact public artifact works on the real supported host." That lesson has been applied to the SketchUp build process through compatibility gates. The same mindset should continue across all importers and the app.

## Bottom Line

Current status: ready for review and real-world confirmation testing, not ready to stop improving.  
Highest-priority retest: SketchUp `v3.7.69` on SketchUp Make 2017, followed by all text modes across all hosts.  
Highest-priority process rule: no release should ship unless the packaged artifact passes host/runtime compatibility checks and dependency checks appropriate to its oldest supported environment.
