# QA-2026-06-24 - Round 6 Public Corpus Coordination Addendum

**Author:** Anonymous reviewer - public corpus / CI lane  
**Status:** Posted for cross-review. Implementation in progress; SketchUp corpus gate green.  
**Purpose:** Coordinate with the other active Round 6 workers so the synthetic stress corpus, public corpus, importer validation, app feature slate, and human confirmation plan converge instead of splitting into separate efforts.

---

## What I reviewed

Read current Round 6 shared notes:

- `QA-2026-06-24_test-corpus-web-research.md`
- `QA-2026-06-24_app-feature-recommendations.md`
- `QA-2026-06-24_human-confirmation-script.md`
- `QA-2026-06-24_round6-corpus-and-features.md`

No conflict found. The existing Round 6 synthetic 9-PDF corpus is a targeted bug-reproduction lane. My work adds a public web-acquired real-world/edge-case lane that can be rebuilt on a clean PC from source URLs.

---

## Work performed

### SketchUp repo

Changed / added:

- `tools/public_pdf_corpus_manifest.json`
- `tools/download_public_pdf_corpus.py`
- `corpus_paths.rb`
- `test/CORPUS_CI.md`
- `test/support/corpus_harness.rb`
- `test/corpus_placement_test.rb`
- `tools/generate_corpus_baselines.rb`
- 14 new `test/fixtures/corpus_baselines/corpus_web_acquired_*.json`

Behavior:

- Public PDFs are downloaded locally under `C:\1pdf-test-corpus\web-acquired`.
- PDFs are not committed to git.
- The downloader writes a local-only lock file: `C:\1pdf-test-corpus\web-acquired\PUBLIC_PDF_CORPUS.lock.json`.
- Corpus scanning now includes `web-acquired` recursively.
- Expected refusal handling now treats encrypted negative-control PDFs as pass only when the refusal reason matches the expected password/encryption message.

### FreeCAD / LibreCAD / Blender repos

Changed:

- `corpus_paths.py`

Behavior:

- Direct corpus PDF resolution now checks `web-acquired` along with `PDFTest Files`, `pdfs`, and `New folder (2)`.
- No importer logic changed in these hosts yet; this only makes the new corpus discoverable.

---

## Public PDFs acquired locally

14 enabled public PDFs acquired:

- `construction/chief_architect_grandview.pdf`
- `construction/home_recovery_sample_floor_plans.pdf`
- `construction/sacramento_adu_willow.pdf`
- `pdfjs/22060_A1_01_Plans.pdf`
- `pdfjs/alphatrans.pdf`
- `pdfjs/annotation-border-styles.pdf`
- `pdfjs/ArabicCIDTrueType.pdf`
- `pdfjs/ContentStreamNoCycleType3insideType3.pdf`
- `pdfjs/Embedded_font.pdf`
- `pdfjs/Pages-tree-refs.pdf`
- `pdfjs/S2.pdf`
- `pdfjs/ShowText-ShadingPattern.pdf`
- `pdfjs/TrueType_without_cmap.pdf`
- `pdfjs/Type3WordSpacing.pdf`

Manual/disabled manifest candidates remain for Cal Poly PDF/VT and Ghent Output Suite because those sources have usage/download restrictions that should not be bypassed or redistributed from our repo.

---

## Validation evidence

### Acquisition

Command:

```powershell
python tools\download_public_pdf_corpus.py --root C:\1pdf-test-corpus
```

Result:

- 14 enabled entries resolved/downloaded.
- Hash/size lock written locally.
- Original Kirkland municipal sample blocked scripted download with HTTP 403, so it was replaced with accessible Home Recovery Alabama and Sacramento County plan sets.

### SketchUp headless corpus placement gate

Command:

```powershell
$env:BCS_CORPUS_ROOT='C:\1pdf-test-corpus'
ruby test\corpus_placement_test.rb
```

Result:

- 26 PDFs scanned.
- 25 OK.
- 1 expected refusal: `encryption_openpassword.pdf` with clear encrypted/password-protected message.
- 0 unexpected failures.
- 0 timeouts.
- `pdftotext` available.
- Public construction PDFs produced 100% simulated label placement where text existed:
  - Chief Architect Grandview: 19 pages, 382,107 paths, 4,765 text placements.
  - Home Recovery sample floor plans: 39 pages, 216,326 paths, 14,806 text placements.
  - Sacramento ADU Willow: 20 pages, 83,176 paths, 4,101 text placements.

### Syntax checks

Commands:

```powershell
ruby -c test\support\corpus_harness.rb
ruby -c test\corpus_placement_test.rb
ruby -c tools\generate_corpus_baselines.rb
python -m py_compile corpus_paths.py
```

Result:

- SketchUp Ruby syntax OK.
- FreeCAD / LibreCAD / Blender `corpus_paths.py` compile OK.

### Cross-host public subset smoke

LibreCAD CLI:

- `Type3WordSpacing.pdf` page 1 -> DXF + JSON + import_report written.
- `chief_architect_grandview.pdf` page 1 -> DXF + JSON + import_report written.
- Grandview page 1: 221 primitives, 120 text items, 341 DXF entities.

Blender headless CLI:

- `Type3WordSpacing.pdf` page 1 -> summary JSON + import_report written.
- `chief_architect_grandview.pdf` page 1 -> summary JSON + import_report written.
- Grandview page 1: 221 primitives, 120 text items.

FreeCAD core smoke:

- Full `PDFImporterCmd.py` requires the real FreeCAD module, so the no-FreeCAD shell cannot exercise that command path.
- `pdfcadcore.safe_open` + `extract_page` succeeded on the same public subset.
- Grandview page 1: 221 primitives, 120 text items.

---

## Points for other workers to challenge

1. **Corpus split:** Should the synthetic 9-PDF corpus and the public web-acquired corpus be unified under one root manifest, or stay as separate lanes?
2. **Baseline policy:** Current public corpus baselines are committed for SketchUp only. Should FreeCAD/LibreCAD/Blender gain comparable baseline manifests now, or should their first pass remain human-confirmation driven?
3. **Negative-control policy:** Encrypted PDFs now pass only as expected refusals. Should corrupt PDFs with zero parsed pages also be marked with an explicit expected-refusal/expected-recovery policy, or is the current OK-with-zero baseline enough?
4. **Large-plan budget:** The public construction PDFs take roughly 40-50 seconds each in SketchUp headless validation. Is that acceptable for local/human runs, or should these be tiered out of normal CI?
5. **App tie-in:** Other Round 6 notes favor PDF-BOM/takeoff bridge and shape lookup. I agree those are the highest-value app features, but I have not implemented that slice yet. We should avoid claiming the app feature is shipped until it is actually in Steel Logic and tested.

---

## Current recommendation

Proceed with both lanes:

- Use the synthetic 9-PDF corpus for fast targeted bug regression.
- Use the public web-acquired corpus for real-world breadth and arbitrary-PDF confidence.
- Keep downloaded PDFs local-only; commit only manifest/tooling/baselines.
- Human confirmation should run both a small synthetic subset and a public real-world subset before declaring the importers close to 100%.

---

## Current repo coordination note

At the time of this addendum:

- FreeCAD / LibreCAD / Blender repos had no `.git/index.lock`.
- Those three repos had only my `corpus_paths.py` discovery update dirty.
- SketchUp also has an unrelated pre-existing `round5_git_report.txt` modification; do not assume it belongs to this public-corpus change without inspecting it.

*Posted so the other active workers can challenge or incorporate the findings before final commit/push.*
