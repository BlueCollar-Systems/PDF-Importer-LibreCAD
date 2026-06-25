# Anonymous Answers - Pre-Test Question Round

## Answer: similar tools and apps to learn from

The strongest reference points are not one-to-one competitors; they are mature PDF/CAD workflows whose best ideas can be adapted.

- AutoCAD `PDFIMPORT`: learn from explicit import options, clear distinction between editable vector objects and raster/image-only PDFs, and user-facing explanations when no editable objects can be extracted.
- Bluebeam Revu: learn from calibration, measurement/takeoff persistence, markup lists, layer-aware review workflows, and exportable summaries.
- Adobe Acrobat Preflight: learn from profile-based checks, fixups where safe, and plain-language error reporting before a user commits work.
- Inkscape PDF import: learn from the explicit tradeoff between keeping text editable and converting text to paths/glyph outlines.

The practical takeaway is that these importers should feel less like a blind converter and more like a controlled import workstation: preflight first, explicit mode choices, post-import auditability, repeatable validation, and clear repair guidance.

References consulted:
- Autodesk PDF import support: https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/No-objects-were-imported.html
- Autodesk `PDFIMPORT` command docs: https://help.autodesk.com/view/ACDLT/2021/ENU/?query=PDFIMPORT+%28Command%29
- Bluebeam markups and measurements: https://www.bluebeam.com/product/markups-and-data/
- Bluebeam user manual measurement topics: https://support.bluebeam.com/user-manual/dashboard.html
- Adobe Acrobat Preflight: https://helpx.adobe.com/acrobat/using/analyzing-documents-preflight-tool-acrobat.html
- Adobe Preflight profiles: https://helpx.adobe.com/acrobat/using/preflight-profiles-acrobat-pro.html
- Inkscape PDF support overview: https://wiki.inkscape.org/wiki/Current_PDF_Support

## Answer: source provenance and audit trail

Each importer should preserve two levels of provenance.

Object-level provenance should be attached to each created object where the parent software supports metadata or custom properties. Required minimum fields: source PDF path/name or hash, page number, source layer/OCG when known, import mode, resolved text mode, source bbox, scale factor/confidence, fallback reason, and importer version.

Import-level provenance should be written to a stable JSON/CSV manifest next to the import log. This manifest is required even when parent-software metadata is limited. It should include per-page statistics and enough object counters to identify mismatch classes during support without reopening the original PDF.

This should be implemented incrementally and safely. First step: define a shared provenance schema and emit import-level manifests from every importer. Second step: attach parent-specific metadata where APIs support it, such as SketchUp attribute dictionaries, Blender custom properties, FreeCAD object properties, and DXF extended data/comments where LibreCAD can preserve them without corrupting the drawing.

## Answer: first-launch installer self-test

Every package should have a visible "Import Health" or "Run Self-Test" entry that works offline and under a low-permission user account. It should check:

- bundled dependency import/load, not system dependency load;
- writable temp/cache/log folder;
- parent API compatibility for the running software version;
- bundled font/render helpers where applicable;
- ability to parse a tiny embedded or generated smoke-test PDF;
- ability to create the expected parent-software entity types for the supported text modes, or report a documented limitation.

The repair path must be explicit: "dependency missing from package", "parent version unsupported", "temp path blocked", "font unavailable", or "external tool blocked by antivirus/policy". Generic "failed" messages are not enough for non-technical users.

## Answer: failed import recovery contract

The recovery contract should be consistent across importers:

- No partial import should be considered successful unless the importer explicitly marks it complete.
- If possible, create output into a temporary group/document/layer/collection first, then promote it after completion.
- On cancel, timeout, memory pressure, or exception, leave either the original document unchanged or quarantine the partial result under a clearly named failed-import container.
- Always leave diagnostics in a known location.
- Temporary files should be cleaned unless they are needed for diagnosis; retained files must be listed in the diagnostics.
- Retry should not require manual cleanup.

For SketchUp specifically, transaction/operation wrappers should be used wherever possible so a failed import can abort cleanly. For Blender, collection quarantine is the safest model. For FreeCAD, document transactions or staging groups should be used. For LibreCAD/DXF, write to a temporary output file first and replace/promote only when the full export succeeds.

## New Work Items From This Round

1. Add a cross-repo document defining semantic text verification, provenance, first-launch self-test, and recovery contracts.
2. Add or update root-level preflight/self-test docs so every repo exposes the expected user/developer command.
3. Add an import-level provenance manifest schema and minimal unit coverage where practical.
4. Re-sync the Q&A round into each repo and commit/push after validation.

## Agreement Position

I agree these are safe improvements if the first implementation step is contract/schema/test documentation plus low-risk manifest helpers. I do not recommend large parent-API behavior rewrites immediately before human testing unless a specific failing test or reproducible crash is found.
