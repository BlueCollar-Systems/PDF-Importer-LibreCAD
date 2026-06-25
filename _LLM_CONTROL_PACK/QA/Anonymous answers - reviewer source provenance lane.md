# Anonymous Answers - Source Provenance Lane

Date: 2026-06-25
Author: Anonymous reviewer
Rule: I am answering questions I did not ask. I am not answering `Anonymous question - source provenance and audit trail.md` because that was my question.

## Answer to `Unrealized question.md`

Question: Which other similar tools and apps can we learn from in order to make these tools the absolute best?

Honest answer: learn from both CAD converters and construction takeoff tools, but do not copy their limits blindly.

Useful patterns to study:

- Autodesk AutoCAD PDFIMPORT: users can choose pages and object categories such as geometry, fills, raster images, and TrueType text. Lesson: every importer should make content categories explicit and record what was actually imported. Source: https://help.autodesk.com/view/ACDLT/2021/ENU/?query=PDFIMPORT+
- Visual Integrity pdf2cad: emphasizes editable CAD entities, layers, text, page ranges, batch mode, font mapping, scale-to-original dimensions, and error/warning reports. Lesson: our importers should compete on batchability, font mapping honesty, scale trust, and warning quality, not only visual output. Source: https://marketplace.autodesk.com/apps/ae39b8f1-6556-486e-9a44-bffd4e9ac7dd
- QCAD Professional PDF import: page selection, image import choice, clipping choice, and explicit behavior for vector content outside the paper. Lesson: give users import-boundary controls and explain clipping/out-of-page decisions. Source: https://qcad.org/doc/qcad/latest/reference/en/scripts/Pro/File/OpenFilePro/doc/OpenFilePro_en.html
- Scan2CAD: batch conversion, automation API, raster/vector/OCR emphasis, offline licensing. Lesson: our long-term edge is automatable shop workflow plus honest raster/vector/OCR classification. Source: https://www.scan2cad.com/
- Bluebeam Revu: takeoff tools, Markups List, Excel export, visual search, legends, profiles, and collaboration. Lesson: the Steel Logic bridge should focus on downstream review, takeoff, repeatable summaries, and user-friendly reports, not just raw import. Source: https://www.bluebeam.com/workflows/takeoffs-and-estimation/
- PDF.js: broad parsing/rendering test discipline, legacy builds, debugger, and test PDFs. Lesson: keep a visible PDF-debug/report tool and use broad corpus-driven regression tests. Source: https://github.com/mozilla/pdf.js/

Implementation tasks:

1. Add a `competitive-lessons.md` or Q&A note that turns these product patterns into acceptance criteria.
2. Add a website/app roadmap row for: batch import, page-range previews, warning reports, source provenance, and Steel Logic takeoff export.
3. Add corpus tags that mirror these lessons: clipping, out-of-page content, font mapping, raster/vector hybrid, batch/multipage, and takeoff/export.

## Answer to `Anonymous question - semantic text verification.md`

Question: How can we prove automatically and repeatedly that each importer creates the correct parent-software entity type for every text mode?

Answer: add a cross-host `actual_text_entity_types` proof contract, then implement host-specific collectors.

Minimum contract per import:

```json
{
  "requested_text_mode": "labels",
  "actual_text_entity_types": {
    "native_label": 42,
    "native_3d_text": 0,
    "outline_curve_or_mesh": 0,
    "raw_geometry_edges": 0,
    "fallbacks": []
  }
}
```

Host proof paths:

- SketchUp: after import, count `Sketchup::Text`, groups/components containing 3D text geometry, SVG/glyph outline groups, and raw edge/curve geometry. Write summary into Import Health and log.
- FreeCAD: count Draft Text/ShapeString objects versus wires/edges/meshes in the created document group.
- LibreCAD: parse generated DXF and count `TEXT`/`MTEXT` versus `LWPOLYLINE`/`POLYLINE`/linework for text-origin entities.
- Blender: inspect object types after import: `FONT` curves for Labels/3D Text, mesh/curve outlines for Glyphs/Geometry, extrusion/depth for 3D Text.

Implementation tasks:

1. Define `actual_text_entity_types` in `import_report.json`.
2. Add one small golden PDF with four text spans and run all four text modes.
3. Make tests fail if selected mode silently produces the wrong category without a documented fallback.
4. Surface mismatches in plain English: "Requested Labels, created outline geometry for 9 rotated spans because native labels cannot preserve this transform."

## Answer to `Anonymous question - first launch installer self test.md`

Question: How can each installer or portable package run a first-launch self-test on a clean, offline, low-permission PC?

Answer: every package should ship a first-launch "Ready Check" that runs before the first real import and writes a machine-readable result.

Minimum checks:

- bundled dependency load from package path, not global system path;
- parent host/API compatibility;
- temp/cache/log directory writable;
- font discovery and fallback font availability;
- one tiny embedded PDF smoke import/conversion;
- outbound network not required;
- repair instructions for each failure.

Per host:

- SketchUp: menu item plus first-load prompt: Compatibility Report / Ready Check; verify Poppler EXEs, Ruby 2.2-safe extension load, temp path, tiny PDF import dry run if possible.
- FreeCAD: `preflight_check.py --diagnostics` plus workbench menu command; verify bundled PyMuPDF and FreeCAD Mod path.
- LibreCAD: portable launcher `--preflight <sample.pdf>` and GUI Ready Check button; verify portable EXE extraction and DXF write.
- Blender: add-on Preferences panel Ready Check; verify vendored PyMuPDF inside Blender Python and create/delete a tiny scene import.
- Website: show the exact Ready Check command next to each download.

Implementation tasks:

1. Add a shared `ready_check` result schema.
2. Bundle or generate a tiny diagnostic PDF for each package.
3. Add Ready Check result to artifact acceptance matrix.
4. Make website Report Doctor accept Ready Check JSON/log files.

## Answer to `Anonymous question - failed import recovery contract.md`

Question: What should the cross-importer recovery contract be when an import is cancelled, crashes, times out, or runs out of memory?

Answer: imports should be transactional where the host allows it, and quarantined where it does not.

Recovery contract:

1. Start every import inside a named transaction/import group.
2. Write temp output under a per-run folder with a run id.
3. Do not merge imported objects into the user's main model/drawing until a page or whole import has passed validation.
4. On cancellation/error, roll back the transaction if possible.
5. If rollback is impossible, move partial results into a clearly named quarantine group/layer such as `BCS_PARTIAL_IMPORT_<run_id>`.
6. Always preserve diagnostics: import log, report JSON, crash/timeout reason, last completed page, last completed phase, and suggested retry mode/page range.
7. Clean temp binaries/intermediate files but keep the final diagnostic package.

Host-specific notes:

- SketchUp supports model operations; use commit/abort operation carefully and quarantine only if abort is not safe.
- FreeCAD document object creation should happen under a predictable group so failed runs can be deleted or quarantined.
- LibreCAD portable output should write to a temp DXF first, then atomically move to the chosen output path only on success.
- Blender should create a collection per import and delete/quarantine it on failure.

Implementation tasks:

1. Define `import_status: success|cancelled|failed|partial_quarantined`.
2. Add `recovery_action` and `retry_suggestion` to import reports.
3. Add timeout/out-of-memory simulated tests where possible.
4. Add UI copy: "No changes were made" or "Partial results were moved to quarantine."
