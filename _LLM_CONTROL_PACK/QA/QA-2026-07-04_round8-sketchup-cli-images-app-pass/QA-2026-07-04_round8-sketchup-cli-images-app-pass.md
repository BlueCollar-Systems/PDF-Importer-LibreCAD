# QA 2026-07-04 Round 8 - SketchUp CLI, Images, App Pass

## Scope

User request: add SketchUp CLI support, add SketchUp individual embedded-image extraction, close remaining importer parity gaps, then apply the same QA approach to the other repos, especially the Structural Steel Shapes app.

Repos checked:

- `C:\1PDF-Importer-SketchUp`
- `C:\1PDF-Importer-FreeCAD`
- `C:\1PDF-Importer-Blender`
- `C:\1PDF-Importer-LibreCAD`
- `C:\1 Structural_Steel_Shapes_App`
- `C:\1BlueCollar-Website`
- `C:\1pdf-test-corpus`

## Questions Asked And Answered

| Question | Answer | Action |
|---|---|---|
| Does SketchUp have a real CLI path? | Yes, but smoke testing found a repo-root launch bug in direct CLI requires. | Fixed `cli.rb` to resolve its extension directory with `File.expand_path(File.dirname(__FILE__))`; direct CLI smoke now exits 0. |
| Does SketchUp preserve individual embedded images? | Yes. The importer has a dedicated `EmbeddedImageExtractor` for Image XObjects, including nested images inside Form XObjects. | Verified with extractor unit tests; pipeline keeps embedded-image assets separate before page raster fallback. |
| Do the importers have feature parity for tracked capabilities? | Yes for tracked matrix features. | Regenerated feature matrix: SU 19/19, FC 19/19, BL 20/20, LC 20/20, App 3/3. |
| Did the app have an importer-side gap? | Yes. Import-report ingestion was still too thin for Report Doctor / drawing trust workflows. | Expanded app ingestion for host/runtime metadata, diagnostics, fallback state, embedded image paths, import contract checks, source provenance, and parts bootstrap summaries. |
| Did app QA expose unrelated work? | Yes. Localization audit found hardcoded UI strings. | Localized Omni-Box, scanner, time-entry, and quantity labels; improved audit interpolation handling; audit now clean. |
| Do the non-importer ecosystem repos still pass their available QA? | Yes for the local checks available without deployment credentials. | Website static metadata validator passed; corpus schema and conformance-vector validators passed. |
| Are the importers "perfect"? | Automated QA is green for the covered paths, but perfection still needs host visual signoff in the actual CAD apps. | Remaining manual signoff is listed below; no automated tracked feature gap remains. |

## Implemented / Verified

### SketchUp Importer

- Direct CLI support verified through `extracted\sketchup_ext\bc_pdf_vector_importer\cli.rb`.
- Batch CLI support verified through `tools\su_batch_cli.rb`.
- Individual embedded-image extraction verified through `embedded_image_extractor_test.rb`.
- Direct CLI launch-path bug fixed in `cli.rb`.

### Cross-Importer Parity

- `PDFVectorImporter\compare_feature_matrix.py` now recognizes SketchUp Ruby CLI surfaces.
- Regenerated:
  - `feature_matrix.md`
  - `feature_matrix.json`

### Structural Steel Shapes App

- `lib\services\import_report_ingestion.dart` now parses the import report contract instead of a small stub subset.
- Added app-side typed summary for `bcs.parts_bootstrap/1.0`.
- Added `readyForShopUse` gate from import contract, warnings, and fallback state.
- Expanded `test\import_report_ingestion_test.dart`.
- Localized previously hardcoded Omni-Box / scanner / time-entry / quantity UI strings.
- Updated `tools\l10n_audit.dart` to ignore localized interpolation noise while still detecting real hardcoded UI strings.

## QA Results

### SketchUp

- `ruby -c extracted\sketchup_ext\bc_pdf_vector_importer\cli.rb` - pass.
- `ruby test\embedded_image_extractor_test.rb` - 3 runs, 12 assertions, pass.
- `ruby test\batch_cli_test.rb` - 4 runs, 14 assertions, pass.
- `ruby test\qa_report_test.rb` - 10 runs, 60 assertions, pass.
- `ruby test\import_dialog_defaults_test.rb` - 22 runs, 108 assertions, pass.
- `ruby test\ruby22_compat_test.rb` - 3 runs, 5 assertions, pass.
- Direct CLI smoke on `1017 - Rev 0.pdf` page 1 - exit 0; wrote `1017 - Rev 0_import_report.json` and `primitives.json`.
- Batch CLI smoke on `1017 - Rev 0.pdf` page 1 - exit 0; wrote `1017 - Rev 0_import_report.json` and `1017 - Rev 0_geometry_sidecar.json`.

### FreeCAD / Matrix

- `python -m py_compile PDFVectorImporter\compare_feature_matrix.py` - pass.
- `python PDFVectorImporter\compare_feature_matrix.py ...` - pass.
- Coverage summary:
  - SU: 19/19, 100.0%
  - FC: 19/19, 100.0%
  - BL: 20/20, 100.0%
  - LC: 20/20, 100.0%
  - App: 3/3, 100.0%

### App

- `flutter test test\import_report_ingestion_test.dart` - 4 tests, pass.
- `dart run tools\l10n_audit.dart` - EN keys 827, ES keys 827, key parity OK, no hardcoded UI findings.
- `flutter test` - 237 tests, pass.

### Website / Corpus

- `python tools\validate_static_metadata.py` in `C:\1BlueCollar-Website` - pass; 8 static metadata labels checked.
- `python tools\validate_contract_schemas.py` in `C:\1pdf-test-corpus` - pass; 4 contract schemas valid.
- `python conformance-vectors\test_conformance_vectors.py` in `C:\1pdf-test-corpus` - pass; 8 vectors, Python pass, SketchUp pass.

## Remaining Honest Signoff

No automated tracked feature gaps remain after this pass. The remaining checks are not code gaps; they are host/application signoff gates:

- Open the same stress PDFs in SketchUp, FreeCAD, Blender, and LibreCAD and visually inspect alignment, lineweight, color, and embedded-image placement.
- For very large map PDFs, measure import time per mode and decide whether to expose more aggressive UI presets for "fast preview" versus "full fidelity."
- In the app, wire the richer import report summary into the next Report Doctor / drawing trust UI surface when that feature is ready.
