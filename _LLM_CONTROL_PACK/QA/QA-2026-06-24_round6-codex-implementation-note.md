# QA-2026-06-24 - Round 6 Codex Implementation Note

Status: active, not final.

## What I implemented

- Added a public PDF corpus manifest to `C:\1PDF-Importer-SketchUp\tools\public_pdf_corpus_manifest.json`.
- Added a dependency-free downloader at `C:\1PDF-Importer-SketchUp\tools\download_public_pdf_corpus.py`.
- Documented the local-only public corpus lane in `C:\1PDF-Importer-SketchUp\test\CORPUS_CI.md`.
- Acquired 14 public PDFs locally under `C:\1pdf-test-corpus\web-acquired`.
- Downloader wrote `C:\1pdf-test-corpus\web-acquired\PUBLIC_PDF_CORPUS.lock.json` with hashes and source metadata.

## Acquired public PDFs

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

## Validation performed

SketchUp headless corpus placement was run against the 14 newly acquired public PDFs.

Result:

- 14 OK
- 0 FAIL
- 0 TIMEOUT
- Large public plan sets completed:
  - Chief Architect Grandview: 19 pages, 382107 paths, 4765 text items, 4765/4765 placements.
  - Home Recovery sample plans: 39 pages, 216326 paths, 14806 text items, 14806/14806 placements.
  - Sacramento ADU Willow: 20 pages, 83176 paths, 4100 text items, 4101/4101 placements.

## Active issue found

The local `C:\1pdf-test-corpus` also contains older tiered corpus files, including an intentional encrypted PDF negative-control. Baseline generation correctly refused the encrypted PDF, but the baseline generator currently reports that expected refusal as a failed baseline run.

Recommendation:

- Keep encrypted/corrupt PDFs in Tier 2.
- Treat them as expected refusal controls only when the importer fails closed with the correct open-gate reason.
- Do not create normal placement baselines for encrypted/corrupt negative controls.

## Coordination request

Other agents should avoid regenerating or committing public-corpus baselines until the negative-control handling is settled, or they may accidentally turn expected bad-PDF refusal into a red gate.

Proposed next step:

1. Patch the SketchUp corpus gate/generator to recognize expected Tier 2 refusal PDFs.
2. Re-run the full `C:\1pdf-test-corpus` placement gate.
3. Add the app-facing PDF QA confirmation surface or at minimum wire the already-written human confirmation script into the app diagnostic/reporting workflow.
4. Commit only after the Round 6 notes agree the corpus lane is stable.
