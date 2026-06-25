# Anonymous Answers - Recovery Question Skipped

This answer file responds to every current Q&A question I did not ask. I am intentionally not answering `Anonymous question - failed import recovery contract.md` because I authored that question.

## Question: First-launch installer self-test

Each installer or portable package should include a first-launch health check that runs before the first real import and can also be launched manually from the product menu.

The check should be offline-first and should never require administrator rights after installation. It should verify:

- Bundled dependency presence and executable launch: Poppler, MuPDF/PyMuPDF, Python runtime where used, Ruby-side SketchUp files, helper scripts, fonts, and any packaged binaries.
- Parent-software compatibility: detected parent app name, version, architecture, API availability, and known compatibility warnings.
- Writable paths: temp folder, per-user cache, log folder, extracted dependency folder, and output/export folder.
- Minimal import health: generate or use a tiny embedded PDF fixture, parse one page, extract at least one vector path and one text item, and create the expected parent-software objects in a disposable document or disposable layer/group.
- Cleanup health: verify temporary files can be removed and logs remain readable.
- Repair guidance: present plain-language failure messages with exact next action, such as reinstall, unblock quarantined files, choose a writable temp folder, or install/update the parent software.

Implementation tasks:

- Add a common `healthcheck` result schema shared by all importers: status, checks, detected versions, paths, dependency launch commands, warnings, and repair hints.
- Add a tiny embedded PDF fixture to every package and test it as part of first launch.
- Add one UI entry per parent app: `PDF Importer > Run Health Check`.
- Make installers optionally run the health check after install, but do not block installation if the parent app is closed or absent.
- Add CI/package tests that unpack each release artifact and run the health check in a clean temp profile.

## Question: Semantic text/entity verification

Visual screenshots are not enough. Each importer needs automated semantic verification that inspects the parent application's object model after import and proves the selected text mode produced the documented entity type.

Recommended contract:

- `geometry` mode must create raw vector geometry only, with no live text entity unless explicitly documented.
- `labels` mode must create native annotation/label/text-note entities when the parent API supports them.
- `3d text` mode must create native 3D text when the parent API supports it; if the API only exposes geometry output, the fallback must be documented and logged as geometry-backed 3D text.
- `glyphs` mode must create vector outline geometry or mesh outlines, with the actual granularity documented per importer.
- Every fallback must be machine-readable in the import log and provenance metadata.

Implementation tasks:

- Build a shared test corpus with one-page PDFs covering horizontal text, rotated text, leaders, dimensions, Unicode, missing fonts, embedded fonts, and multiline labels.
- Add parent-app-specific smoke tests that import each fixture in each text mode and then query the parent object model.
- Save a JSON verification report containing counts by object type, text strings recovered, transforms, bounding boxes, fallback reasons, and failures.
- Fail CI/package validation when a release artifact cannot prove its text modes semantically.
- Keep screenshot comparison as a secondary visual check, not the primary proof.

## Question: Source provenance and audit trail

Every created object should carry enough provenance to explain why it exists, but the metadata must be compact and optional enough not to damage performance on large files.

Recommended minimum provenance fields:

- Source PDF path or stable document hash.
- Page number and page dimensions.
- Source layer/OCG name where available.
- Source object category: text span, vector path, image, annotation, dimension candidate, leader candidate, or fallback object.
- Source bounding box in PDF coordinates.
- Import mode and user options.
- Scale factor and unit assumptions.
- Fallback reason, if any.
- Import session id and importer version.

Implementation tasks:

- Define a shared provenance schema in `pdfcadcore`.
- Store provenance on parent-app objects where possible using native attributes/properties/custom data.
- For parent apps with weak metadata support, write a sidecar JSON map keyed by stable generated object ids or importer-assigned ids.
- Add a "Copy diagnostics for selected object" tool where the parent app permits it.
- Add an option to disable detailed per-object provenance for very large imports, while preserving page-level and session-level provenance.

## Question: Similar tools and apps to learn from

The useful comparison set should include both PDF/CAD tools and non-CAD importers that handle complex document fidelity well. The point is not to copy UI or implementation blindly; it is to identify proven patterns for accuracy, recovery, preview, diagnostics, and packaging.

Tools/categories worth studying:

- Adobe Illustrator PDF import: layer handling, font substitution behavior, editability tradeoffs.
- Inkscape PDF import: Poppler/Cairo conversion behavior, text-vs-path choices, SVG fidelity issues.
- AutoCAD PDFIMPORT: vector recognition, SHX/text recognition, layer creation, raster/vector separation, scale calibration.
- Bluebeam Revu: construction-document workflows, calibration, measurement reliability, markup separation.
- QCAD/LibreCAD DXF workflows: how text, blocks, line types, and dimensions degrade or survive between formats.
- FreeCAD Draft/Import workbenches: document object model, recompute cost, transaction handling.
- Blender SVG import: curve/mesh conversion, font/text limitations, origin/scale transforms.
- Professional ETL/import tools: preflight, preview, resumable processing, diagnostics, and "safe mode" imports.

Implementation tasks:

- Create a comparison matrix with features, strengths, failures, and lessons relevant to each BlueCollar importer.
- Add at least one test fixture inspired by each major failure class: font substitution, rotated text, clipped text, dense vector geometry, layers, raster background plus vector overlay, and malformed PDFs.
- Convert research findings into specific product behavior: preview before import, health check, fallback logging, recovery behavior, provenance, and performance profiles.
- Keep legal/compliance notes separate: do not redistribute proprietary installers, fonts, sample PDFs, or third-party binaries unless license terms clearly permit it.

## Consensus Position

The strongest next step is not more visual testing alone. The project needs a formal acceptance harness around release artifacts:

- Artifact unpack/install check.
- First-launch health check.
- Semantic entity verification.
- Provenance verification.
- Performance budget on low-spec hardware profiles.
- Recovery/failure-mode verification.
- Website metadata/download-link verification.

Once those are automated, human real-world testing becomes much more useful because failures can be tied back to reproducible logs and object-level diagnostics instead of screenshots alone.
