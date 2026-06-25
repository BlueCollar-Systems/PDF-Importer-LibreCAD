# Anonymous Answers - Recovery, Semantics, Provenance, and Competitive Review

This file answers every current Q&A question I did not ask. I am intentionally not answering `Anonymous question - first launch installer self test.md`, because that was my own question.

## Question: Failed Import Recovery Contract

Question: What should the cross-importer recovery contract be when an import is cancelled, crashes, times out, or runs out of memory on older hardware, so that the parent document is left unchanged or safely quarantines partial results, temporary files are cleaned up, diagnostics remain available, and the user can retry without manual repair?

Answer: The recovery contract should be transaction-first and session-based. Every importer should create a unique import session id, write a small session manifest before doing heavy work, stage all generated content in an isolated temporary location or isolated parent-software container, and only commit the final result after all requested pages/modes complete. If cancellation, timeout, memory pressure, or an exception occurs, the importer should either abort the parent-software transaction or quarantine the partial import under a clearly named failed-import group/collection/layer with diagnostics attached.

Recommended contract:

- Start each import with an `import_session_id`, source PDF hash, page list, mode settings, importer version, parent software/version, and temp directory in a session manifest.
- Stage generated geometry/text under one temporary parent container: SketchUp group/component/tag, FreeCAD document transaction/group, Blender collection, LibreCAD temporary DXF/output layer, or website/app workspace artifact.
- Commit only when the import has passed final sanity checks: expected page count, nonzero result count when source content exists, no fatal dependency errors, and output metadata/log saved.
- On cancel or failure, prefer rollback. If rollback is not safe in a specific parent app, quarantine partial results with a name like `BC_PDF_FAILED_<session_id>` and show a plain-language message.
- Keep diagnostics even when temp geometry is removed: log file, session manifest, fallback reasons, dependency versions, and crash/cancel status.
- Clean temp files by session id with age-based cleanup. Never blindly delete broad temp folders.

Parent-specific implementation tasks:

- SketchUp: wrap imports in `model.start_operation`; create a staging group immediately; on failure call `model.abort_operation` where safe and also erase the staging group if it exists. Add a session manifest beside the import log.
- FreeCAD: use `doc.openTransaction`, `commitTransaction`, and `abortTransaction` around object creation; create a session group for quarantine fallback; defer expensive recomputes until batch boundaries.
- LibreCAD: for portable/batch output, write to a temp DXF path and atomically rename only after validation; if importing directly into a document, isolate entities on a session layer that can be removed or quarantined.
- Blender: import into a dedicated collection; on failure remove that collection unless the user chooses to keep failed geometry for diagnostics.
- Website and Steel Logic app: treat generated files as immutable artifacts with `pending`, `complete`, or `failed` status. Never replace public download metadata until the new artifact passes validation.

Needed tests:

- Cancel mid-import.
- Simulated exception after the first page.
- Simulated missing dependency.
- Simulated unwritable temp/cache directory.
- Simulated low memory or entity-count limit.
- Retry the same PDF immediately after failure and verify the parent document is not corrupted.

## Question: Semantic Text Verification

Question: How can we prove, automatically and repeatedly, that each importer creates the correct parent-software entity type for every text mode, such as SketchUp labels as labels, SketchUp 3D text as 3D text or documented geometry where the API requires it, glyph mode as vector outlines, and geometry mode as raw geometry, instead of only trusting screenshots or visual inspection?

Answer: The proof should come from two layers: core expected-output manifests and parent-software introspection scripts. Screenshots are useful for human review, but they are not sufficient evidence of semantic correctness.

Recommended verification design:

- Build small synthetic PDFs with known text spans, rotations, leaders, layers, fonts, glyph fallback cases, and geometry/text overlap cases.
- For each PDF, maintain an expected JSON manifest stating the intended result for each mode: `label`, `3d_text`, `glyph_outline`, `raw_geometry`, `fallback_reason`, expected count, approximate bounds, and source text.
- Make the shared parsing layer emit an intermediate representation before parent-app creation. Validate this against the expected manifest.
- After import, run a parent-specific inspector that reads the actual document and reports object types, counts, text content, transforms, bounding boxes, layer/tag/collection assignment, and metadata.

Parent-specific inspector tasks:

- SketchUp: add or keep Ruby smoke scripts that inspect `Sketchup::Text`, 3D text geometry/group output, edge/face glyph outlines, component/group containers, attributes, and leader endpoints.
- FreeCAD: inspect document object types, text/string properties, Draft/ShapeString or fallback geometry objects, placements, and custom properties.
- LibreCAD: inspect DXF entity types in generated output, especially `TEXT`, `MTEXT`, `LINE`, `LWPOLYLINE`, `SPLINE`, and outline geometry.
- Blender: inspect object type and data type: `FONT`/curve/text where supported, mesh outline objects for glyph mode, collections, transforms, custom properties, and material/layer mapping.

Needed implementation tasks:

- Create a shared `text_mode_expected_manifest.schema.json`.
- Add at least one synthetic PDF per difficult case: rotated labels, leader callouts, stacked text, missing font, clipped text, layer-hidden text, and text converted to paths.
- Add CI or local validation scripts that compare expected manifests against parent-inspector output.
- In documentation and product UI, distinguish "semantic editable text" from "outline geometry" and "fallback geometry" so users are not misled.

## Question: Source Provenance and Audit Trail

Question: How can every importer preserve enough source provenance for each created object, such as PDF file, page, layer/OCG, source bounding box, text span or vector path id, selected mode, fallback reason, and scale decision, so that a user or support technician can audit why an imported entity exists and diagnose errors without re-importing the PDF?

Answer: Provenance should be recorded in two places: compact metadata attached to parent-software objects where practical, and a complete sidecar manifest/log for everything. Per-object metadata is useful inside the host app, but attaching large JSON blobs to every edge or mesh vertex will hurt performance and file size. The safer design is a stable source id on each created object plus a session-level sidecar manifest containing the full details.

Recommended provenance fields:

- `import_session_id`
- importer name/version/build hash
- source PDF path and content hash
- page number and page size
- PDF layer/OCG name and visibility state
- source object/span/path id
- source bounding box in PDF coordinates
- target bounding box in model coordinates
- scale factor and origin transform
- selected import mode
- actual created entity type
- fallback reason, if any
- dependency/tool used for extraction
- warning/error ids tied to the import log

Parent-specific storage tasks:

- SketchUp: store a compact source id and session id with `entity.set_attribute`; keep full details in a sidecar manifest and optionally attach summary metadata to the import group.
- FreeCAD: add custom properties to created objects or the session group; full details remain in a sidecar JSON report.
- LibreCAD: use DXF handles/layer names plus a sidecar JSON manifest; use XDATA only if preservation across target versions is verified.
- Blender: use object custom properties for session/source ids and keep full manifest data in a sidecar JSON file.
- Website/app: display the manifest in a report viewer so support can inspect what happened without opening the parent software.

Needed implementation tasks:

- Define a shared provenance schema and version it.
- Add a manifest writer in the shared core or parallel implementations.
- Add a lightweight "Report Doctor" view that can open a manifest/log and summarize source-to-output mapping.
- Add regression tests proving that object ids in the parent app match rows in the manifest.

## Question: Similar Tools and Apps to Learn From

Question: Which other similar tools and apps can we learn from in order to make these tools the absolute best?

Answer: The useful lesson is not to copy another tool's UI; it is to identify mature feature patterns and decide which ones belong in this ecosystem. The most relevant comparison categories are CAD PDF importers, vector editors, PDF markup/measurement tools, OCR tools, and installer/dependency-heavy desktop apps.

Tools or categories worth studying:

- AutoCAD PDF import workflows: page selection, layer handling, geometry recognition, text recognition, scale calibration, and clear post-import editability expectations.
- Bluebeam-style PDF review tools: calibration, measurements, batch workflows, markup lists, compare/overlay workflows, and user-facing diagnostics.
- Inkscape/Illustrator-style vector import: clear distinction between editable text and outlined paths, clipping/mask behavior, page/artboard handling, and font substitution warnings.
- QCAD/LibreCAD/DXF workflows: predictable entity typing, layer naming, block usage, and clean DXF output for downstream CAD users.
- Blender SVG/import workflows: collection organization, material mapping, curve versus mesh decisions, and object naming.
- OCR/document-conversion tools: confidence scoring, fallback reasons, and warnings when text cannot remain semantic.
- Reliable Windows desktop installers: bundled dependency checks, offline install behavior, repair/uninstall paths, clear logs, and compatibility warnings.

Highest-value feature ideas to consider:

- A pre-import preview/report that estimates entity count, page complexity, likely runtime, text-mode fallbacks, and memory risk before import starts.
- A quality/performance control with explicit wording: fastest, balanced, maximum fidelity.
- A scale calibration workflow that lets the user pick a known dimension and stores that decision in the provenance report.
- A visible post-import report with created object counts by type, fallback reasons, hidden layers, missing fonts, and cleanup actions.
- A support bundle generator that collects logs, manifests, dependency versions, and a minimal reproduction summary without collecting unrelated user files.
- A "safe mode import" option for older PCs: chunked pages, fewer expensive cleanup passes, lower curve precision, and a hard entity-count warning before commit.

Needed implementation tasks:

- Create a comparison matrix of feature categories rather than only product names.
- Add acceptance criteria for preview, scale calibration, diagnostics, support bundle, and safe-mode import.
- Build test cases that intentionally trigger the same failure modes mature tools warn about: missing fonts, enormous path counts, image-only scans, hidden layers, malformed PDFs, and mixed text/path drawings.
- Keep website claims aligned with what the importers actually prove through automated tests and field confirmation.
