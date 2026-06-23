# Cross-Repo Round Application - 2026-06-23

## Scope

Applied the SketchUp round-2 logic to the other active repos:

- `C:\1PDF-Importer-SketchUp`
- `C:\1PDF-Importer-FreeCAD`
- `C:\1PDF-Importer-LibreCAD`
- `C:\1PDF-Importer-Blender`
- `C:\1BlueCollar-Website`
- `C:\1 Structural_Steel_Shapes_App`

## Resolution

Safe to commit and push. The importer changes are diagnostics, documentation,
install UX, CLI report surfacing, and Q&A mirroring. They do not change vector
extraction geometry, DXF entity construction, Blender object construction, or
FreeCAD placement math. The app change is a database open/copy race guard plus
Windows artifact verification.

## Changes Made

- Added optional `performance.phases` to the shared `bcs.import_report/1.1` builder in FreeCAD, LibreCAD, and Blender embedded `pdfcadcore` copies.
- Added optional `performance.helpers_ms`, `extra.text_source_spans`, and `extra.text_glyph_estimate` hooks for future text/performance triage.
- Synced additive `QAReport.phase_timings` across FreeCAD, LibreCAD, and Blender shared `pdfcadcore` copies and refreshed `pdfcadcore_sync_manifest.json`.
- SketchUp reports now include `performance.phases.total_ms`, the About menu resolves the metadata version when available, and the corpus harness has a documented stress opt-out soft cap.
- SketchUp gained opt-in strict timing coverage for a named corpus PDF via `test/corpus_strict_timing_test.rb` (`CORPUS_STRICT_TIMING=1`).
- FreeCAD now records coarse import timings and ShapeString fallback skip counts in `import_report.json`.
- LibreCAD GUI/package path, CLI path, and tests now write import reports with run/export timing phases.
- Blender UI and headless CLI paths now write import reports with run/setup/open/classify/cleanup/recognition/geometry/text/image/finalize timing where available.
- LibreCAD install docs now put the Windows portable ZIP first and remove outdated "portable when published" wording.
- Website install help now tells portable ZIP users to run `lcpdf-gui.exe` and states LibreCAD/DXF 2D text limits.
- Website shapes hub states the former standalone shape repos were merged under importer repo `steel_shapes/` folders.
- Steel Logic app now guards concurrent first database opens with a shared `_openFuture`, preventing double copy/open contention on first launch.
- Steel Logic app now has `tools/verify_windows_release_artifacts.ps1` and README instructions for checking Windows portable releases.
- The new app verifier found the tracked v1.0.3 extracted Windows folder did not match the checksum; the ZIP was correct, so the extracted folder was replaced from the verified ZIP and then passed verification.
- Git-tracked Q&A mirrors were added in the touched repos so the Desktop Q&A decision trail is not only local.

## Validation

- FreeCAD focused telemetry/report suite: `python -m pytest tests/test_import_report_text_mode.py tests/test_import_report_writer.py tests/test_qa_report_v11.py` -> 14 passed.
- LibreCAD focused telemetry/CLI suite: `python -m pytest tests/test_import_report_text_mode.py tests/test_import_report_writer.py tests/test_dxf_import_report.py tests/test_mode_cli.py` -> 7 passed.
- Blender focused telemetry/CLI/core suite: `python -m pytest tests/test_import_report_writer.py tests/test_mode_cli.py tests/test_text_mode_builder.py tests/test_core_pipeline.py` -> 19 passed.
- SketchUp: `ruby -c` on touched Ruby files -> syntax OK; `ruby test/corpus_strict_timing_test.rb` -> default opt-in skip OK; `ruby test/qa_report_test.rb` -> 4 runs / 20 assertions; `ruby test/corpus_harness_test.rb` -> 2 runs / 3 assertions; `ruby test/corpus_paths_test.rb` -> 3 runs / 6 assertions; `ruby test/smoke_test.rb` -> 59 checks passed.
- Website: `python tools\validate_static_metadata.py` -> passed, 8 labels.
- Shared core: `python pdfcadcore_sync_check.py` -> ALL IN SYNC.
- Steel Logic Windows artifact verifier: `powershell -ExecutionPolicy Bypass -File .\tools\verify_windows_release_artifacts.ps1 -Version 1.0.3` -> OK after replacing stale extracted folder from verified ZIP.
- Steel Logic app: `flutter test` -> 153 passed.

## Residual Risk

- These changes improve observability and install clarity; they do not replace real-world host testing on older PCs.
- Per-phase timing is now available for future slow-import reports. SketchUp has an opt-in hard timing budget, but it is not enabled in default CI in this pass.
- LibreCAD remains 2D by host format limits; there is still no true 3D text parity with FreeCAD/SketchUp.
- The app verifier validates existing Windows artifacts; it does not rebuild or publish a new app release.
