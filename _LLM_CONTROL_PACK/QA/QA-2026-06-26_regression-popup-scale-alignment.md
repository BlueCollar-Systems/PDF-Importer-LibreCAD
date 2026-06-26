# QA 2026-06-26 - Regression Response: SketchUp Popup, Scale, Text/Leader Alignment

## Trigger

Field report on 2026-06-26:

- SketchUp importer shows a blocking pre-import popup on every standard import.
- That popup incorrectly mentions LibreCAD inside the SketchUp importer.
- Recent imports appear to have reintroduced alignment and scaling problems.
- Text/leader placement remains a primary concern across Labels and 3D Text modes.

## Initial Findings

- SketchUp `main.rb` had a hard-coded `UI.messagebox` inside `import_pdf`, before file selection.
- The popup included a LibreCAD-specific sentence even though the code path is SketchUp-only.
- Because it ran before every `UI.openpanel`, users saw it on every standard import.

## Actions Started

- Removed the blocking pre-import popup from SketchUp standard import.
- Added a SketchUp regression test that scans `import_pdf` and fails if the old blocking prompt or LibreCAD text returns.
- Resolved the Labels-mode entity disagreement in favor of the current product contract: labels must remain native labels, not silently become 3D text/mesh geometry.
- Restored rotated SketchUp label alignment without converting entity type by passing the rotated native-label direction vector and hiding leaders where the SketchUp API supports it.
- Added/updated SketchUp tests proving:
  - no blocking pre-import popup,
  - no SketchUp import dialog copy mentioning LibreCAD,
  - horizontal native labels use zero vectors for leader suppression,
  - rotated native labels stay labels and receive rotated vectors,
  - 3D Text still creates 3D text/mesh entities,
  - Labels mode only falls back to mesh text when native `add_text` fails.
- Added a conservative FreeCAD bbox-fit clamp for Draft Labels and ShapeString 3D Text. It only shrinks text when host font rendering would overflow the PDF span bbox; it does not move vector geometry or change resolved drawing scale.
- Added FreeCAD tests proving normal text size is unchanged while oversized horizontal and vertical text runs shrink to their source span bbox.
- Added FreeCAD raster background scaling parity so hybrid/raster placements use the effective import scale instead of raw page millimeters.
- Added Blender legacy adapter routing so the selected text mode reaches the object builder: Labels/3D Text remain font curves with distinct extrusion behavior, while Glyphs/Geometry convert through mesh evaluation when Blender can do it.
- Added SketchUp BOM table context so QUAN-column single digit quantities stay vertical without forcing MARK-column labels vertical.

## Active Questions

1. Did the recent scale banner/cross-check work alter actual import scale, or only reporting?
2. Are Labels and 3D Text using the same insertion baseline/rotation math as vector geometry?
3. Are any host-specific offsets being applied twice after shared `pdfcadcore` normalization?
4. Can CI prove entity type and approximate placement without requiring manual host UI testing?

## Discussion / Resolution

Anonymous reviewer A - SketchUp UX:
- The popup was a direct regression. A modal before every import is too much friction, and the LibreCAD sentence was a copy/paste leak into the SketchUp host. A show-once replacement was also rejected because the field requirement is no pre-import interruption. Resolution: remove the guidance module entirely and cover normal import plus Safe Mode with a source-level absence test.

Anonymous reviewer B - SketchUp text entity contract:
- A prior workaround routed rotated Labels-mode text into mesh text to avoid native leader behavior. That helped some alignment cases but violated the explicit contract that labels are labels. Resolution: keep Labels mode as native SketchUp labels, use zero vectors only for horizontal labels, use rotated direction vectors for rotated labels, and call `display_leader = false` / zero vectors where supported to reduce visible leader artifacts.

Anonymous reviewer C - FreeCAD text fit:
- FreeCAD ShapeString was sized directly from PDF font size. Host font metrics can render wider than the PDF span bbox, especially on dense shop drawings, which causes overlapping labels/leaders even when the extracted bbox is correct. Resolution: fit Draft Text and ShapeString uniformly down to the PDF bbox only when needed. This protects accuracy by preserving insertion point, rotation, and geometry scale.

Anonymous reviewer D - Cross-host validation:
- LibreCAD had no code changes in this pass and stayed green. Blender did receive a legacy-adapter text-mode fix so the old adapter path no longer collapses all text modes into the same curve output. Resolution: keep LibreCAD unchanged, commit the Blender adapter fix with tests, and treat human UI retest as the next gate.

## Validation

- SketchUp: `ruby test\pre_import_prompt_test.rb` - PASS, 1 run / 32 assertions.
- SketchUp: `ruby test\text_mode_placement_test.rb` - PASS, 54 assertions.
- SketchUp: `ruby test\text_label_placement_test.rb` - PASS, 127 assertions.
- SketchUp: `ruby test\text_category_placement_test.rb` - PASS, 33 assertions.
- SketchUp: `ruby test\ruby22_compat_test.rb` - PASS, 3 runs / 5 assertions.
- FreeCAD: `python -m pytest tests\test_pdf_importer_text_reconstruction.py tests\test_import_report_text_mode.py` - PASS, 16 tests.
- FreeCAD: `python -m py_compile PDFVectorImporter\src\PDFImporterCore.py` - PASS.
- FreeCAD: `python -m pytest tests --basetemp %TEMP%\pytest-fc-pdf-importer-20260626-final` - PASS, 81 tests / 1 deprecation warning.
- LibreCAD: `python -m pytest tests --basetemp %TEMP%\pytest-lc-pdf-importer-20260626` - PASS, 45 tests.
- Blender: `python -m pytest tests --basetemp %TEMP%\pytest-bl-pdf-importer-20260626-final` - PASS, 45 tests.

## Current Resolution State

Implementation and validation are complete for this round. Remaining work is commit/push/release verification and then human interactive confirmation on real PDFs inside the host applications.
