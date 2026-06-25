# QA-2026-06-24 - Outside-Box Reviewer B - FC/LC/Core

Scope reviewed:

- `C:\1PDF-Importer-FreeCAD`
- `C:\1PDF-Importer-LibreCAD`
- shared `pdfcadcore` / importer-core patterns
- desktop Q&A context in `C:\Users\Rowdy Payton\Desktop\PDFTest Files\Q&A`
- in-repo Q&A context under each repo's `_LLM_CONTROL_PACK\QA`

I did not edit source code. I did observe existing local dirty changes in both repositories, especially around `pdfcadcore/import_report.py` and `tests/test_import_report_text_mode.py`; I treated those as current working context and did not revert or overwrite them.

## Current Context

The latest Q&A context says the project has already made an important architecture correction: import mode is now `Auto`, `Vector`, `Raster`, or `Hybrid`, while text rendering is orthogonal (`Labels`, `3D Text`, `Glyphs`, `Geometry`). That is the right conceptual split. It prevents the old "quality preset" model from hiding what the user actually wants.

The desktop Q&A instruction file asks for broader accuracy, power, functionality, performance, easy installation, complete dependencies, current parent-app compatibility, old-version/hardware empathy, and cooperation across importers. The in-repo Q&A files add concrete recent context: text-mode verification, screenshot review, field fixes, and prior cross-repo concerns about layers, release assets, and validation.

One immediate process finding: running the scoped sync checks currently reports drift for `pdfcadcore/import_report.py` because the manifest expects hash `2f450af...` while the current FC/LC file hash is `073f046...`. The FC and LC working copies appear to be aligned with each other, so this looks like a stale or incomplete manifest update rather than an FC-vs-LC file mismatch. Either way, the sync gate is red today.

## Observations

The core architecture is much healthier than a narrow test-file importer. It already has normalized primitives, page data, import bounds, scale resolution, arc promotion, fill/glyph flood detection, raster fallback reasons, hatching helpers, dimension-oriented parsing, and shared report plumbing. That gives the project a real platform for broader PDF handling.

The strongest design decision is the current mode model. `Auto`, `Vector`, `Raster`, and `Hybrid` describe how the PDF is imported. Text mode describes how text is represented. Keeping those separate should remain a non-negotiable rule.

Both importers still depend heavily on a flattened PyMuPDF view of a PDF page. `page.get_drawings()` and text dictionaries are useful, but arbitrary PDFs contain nested form XObjects, clipping stacks, current transformation matrices, transparency groups, optional-content membership rules, annotations, image masks, blend modes, overprint behavior, and paint-order subtleties. The current host-neutral primitive model does not preserve enough of that structure to make arbitrary-PDF fidelity dramatically better by heuristics alone.

FreeCAD has the richer host object target. It can create Draft text, ShapeString text, Part geometry, groups, images, page containers, and reports. That is powerful, but there is still a lot of host-native logic in `PDFImporterCore.py`, including behavior that overlaps with shared core ideas. That creates a risk that future fixes land only in FreeCAD or only in LibreCAD.

LibreCAD has a practical DXF pipeline and a good command-line surface. The current package exporter emits DXF lines, circles, arcs, lightweight polylines, image references, text entities, layers, extents, lineweights, true color, and linetypes. However, there are still multiple DXF-building paths in the tree, and the older builder is still covered by tests. That keeps semantic drift alive.

Layer support is present but shallow. The importers can group by a detected OCG/layer string or by fallback page/color naming, but they do not yet model the optional-content tree, default visibility states, locked/print states, parent-child layer hierarchy, optional-content membership expressions, or layer-driven style semantics. For CAD workflows, that is a major ceiling.

Text modes are honest, but not solved. Editable labels are useful but can drift because PDF text placement, font metrics, kerning, transforms, encodings, subset fonts, and missing system fonts do not map cleanly to host text objects. FreeCAD `3D Text` is more CAD-native but depends on ShapeString behavior and font availability. Glyph/geometry modes are more visually faithful but can explode object counts and lose editability. LibreCAD's `3d_text` necessarily aliases to 2D editable text, while glyph/geometry modes depend on outline conversion.

Hybrid import is currently page-level in spirit. It can place a full-page raster background and vector overlay. That is useful, but arbitrary PDFs need region-level decisions: a scanned title block, vector dimensions, raster logo, and real text can coexist on the same page. Full-page hybrid can duplicate content, bloat output, and make selection confusing.

The validation harness is useful but still too friendly. There are generated fixtures, smoke checks, import-report tests, CLI tests, GUI structural tests, and sample PDF coverage. What is missing is a hostile corpus and a real oracle: source PDF render vs imported-result render, layer assertions, coordinate tolerances, text editability checks, DXF round-trip checks, and performance baselines.

Packaging is mostly pointed in the right direction. FreeCAD vendors PyMuPDF into the workbench release. LibreCAD builds portable and standalone artifacts with PyInstaller. But packaging still needs stronger artifact proof: exact version checks, ABI checks against host Python, runtime dependency self-tests, license/dependency manifest, and release workflows that always publish the asset users are told to install.

LibreCAD raster/image DXF output deserves special attention. DXF image entities reference external image files. If the exporter writes PNGs into a temp folder and the user moves or shares only the DXF, the import can degrade later. A CAD-friendly importer should default to a durable sibling asset folder or a ZIP bundle containing the DXF plus images.

Performance instrumentation exists, but performance governance is not yet strong enough. Heavy PDFs need object-count caps, memory tracking, page sampling rules, timeout behavior, region-level raster escape hatches, and opt-in strict benchmarks that catch regressions before users do.

## Risks And Limitations

The biggest technical limitation is not a missing knob. It is the absence of a richer intermediate representation that preserves PDF rendering semantics before lowering into FreeCAD objects or DXF entities.

The current primitive model cannot fully explain why content is visible, clipped, transformed, blended, hidden by optional-content settings, or repeated through form reuse. That makes arbitrary-PDF correctness fragile.

Layer fidelity can be misleading. A layer name in the output does not prove that the output matches the source layer tree, visibility, nested membership, or author intent.

Text fidelity will remain uneven unless the importer can decide per span whether editability or appearance is more important. One global text mode is easy to understand, but arbitrary PDFs often need mixed text strategies.

DXF semantics are inherently limited. DXF is not PDF. It cannot faithfully represent all PDF clipping, transparency, fonts, masks, and blend behavior. The importer should expose those limits clearly rather than pretending every PDF can become clean CAD geometry.

FreeCAD semantics are also not automatic. ShapeString, Draft text, Part curves, image planes, groups, and document recompute behavior each have costs. A visually accurate import can become painful if it creates tens of thousands of objects without grouping, batching, or fallback.

The sync manifest failure is a release/process risk. Even if the current file contents are correct, a red sync check means maintainers lose trust in the cross-repo guardrail.

The older and newer LibreCAD DXF paths risk different behavior for text, images, metadata, layer naming, and extents. Tests can pass while the product path and legacy path diverge.

`attach_metadata` exists in the current DXF exporter API surface, but I did not find meaningful metadata emission in the exporter path. That is a user-trust risk because the option implies provenance data that may not exist.

Current CI does not appear to prove that a released FreeCAD workbench imports correctly inside a real supported FreeCAD runtime, nor that the LibreCAD portable app can import a sample PDF and keep its image assets portable.

## Bold Ideas

Build a real shared PDF semantic IR. Instead of only normalized flattened primitives, capture display-list operations with CTM, clip stack, z-order, resource IDs, form XObject nesting, OCG membership, transparency hints, image masks, text spans, and source object provenance. Then lower that IR into FreeCAD and DXF through host-specific adapters.

Make hybrid import region-based. Segment each page into clusters such as vector CAD geometry, dense glyph art, scanned/raster regions, logos, tables, hatches, dimensions, and title blocks. Rasterize only the regions that need rasterization, then overlay editable text and clean vector geometry where confidence is high.

Create an "import preview and confidence" panel before commit. Show detected pages, scale, layers, text spans, raster regions, expected object count, likely slow pages, and why Auto chose its mode. Let users override per page or per region.

Add mixed text mode. Keep the global text mode, but allow Auto Text to choose editable labels for simple horizontal text, ShapeString where FreeCAD can support it, outlines for symbol/subset/rotated/problem fonts, and raster fallback for truly hostile text clusters.

Make layers a first-class import product. Preserve source OCG IDs, display names, hierarchy, default visibility, and membership where possible. In FreeCAD, create a layer manager/group tree. In DXF, encode stable layer names and optional source metadata so users can trace output back to the PDF.

Turn DXF output into a package, not just a file. Write `drawing.dxf`, a sibling `drawing_assets` folder, and `drawing_import_report.json`, or offer a single ZIP bundle. Use relative image paths. This would make raster/hybrid/image-heavy LibreCAD imports much less brittle.

Build a corpus oracle. For each PDF, render the source and imported output to images, compare pixels with tolerances, assert primitive counts and bounds, assert text/layer expectations, and track performance. Include synthetic PDFs for exact semantics plus public real-world PDFs for chaos.

Add a "known unsupported PDF feature" detector. If the PDF uses clipping, transparency groups, soft masks, complex shadings, Type 3 fonts, optional-content expressions, or unsupported annotations, report that before or during import with a confidence score.

Move toward one shared core package or stronger generated sync discipline. The importers should feel like two host adapters on one engine, not two projects that occasionally copy files.

Create a post-import diagnostic overlay. In FreeCAD, optionally create a non-printing/report group showing page bounds, raster regions, vector regions, skipped text, and suspected mismatches. In LibreCAD, emit a companion report and optional diagnostic DXF layers.

## Safe Immediate Improvements

Fix the current sync gate first. If the new `import_report.py` diagnostics are accepted, update the shared sync manifest atomically across the relevant repos. If they are not accepted, resolve that intentionally. Do not leave the guardrail red.

Choose one LibreCAD DXF product path. Either retire the older `dxf_builder.py` path, clearly mark it as legacy, or add tests that prove both paths emit equivalent semantics for layers, text, images, extents, and versions.

Make LibreCAD image assets durable by default. Put generated PNGs beside the DXF in a predictable asset folder and use relative paths. Add a test that moves the output bundle to a new folder and verifies references still resolve.

Add small fixtures for OCG/layer behavior. A tiny fixed PDF with two layers and a tiny generated or checked-in fixture for nested/hidden layers would immediately improve confidence. Assert FreeCAD group names and DXF layer names.

Add fixtures for clipping and transformed form XObjects. Even if the importer cannot fully support them yet, tests should identify the limitation and ensure import reports warn clearly.

Expand import reports with machine-checkable diagnostics: source layer count, detected OCG names, per-page chosen mode, text-mode effective behavior by host, raster asset paths, object counts by type, skipped feature counters, fallback reasons, and suspicious page flags.

Add opt-in strict performance tests. Use one dense vector PDF, one dense text PDF, one raster-heavy scan, and one mixed CAD sheet. Track time, memory, output object count, and output size. Keep them outside fast unit tests but run them before release.

Add release artifact self-tests. The FreeCAD release should prove PyMuPDF imports under the supported FreeCAD Python and a sample PDF imports. The LibreCAD portable app should prove CLI import, GUI launch if possible, PyMuPDF import, ezdxf import, version output, and durable image references.

Fix the LibreCAD installer version fallback. The Inno script fallback still points to an old version value; manual builds should not silently stamp obsolete metadata.

Clarify source ZIP dependency expectations. If a source ZIP requires internet access to install PyMuPDF/ezdxf, say so. If offline install is intended, include the vendored `lib` payload and test it.

Add a small "what happened" user summary to both importers, using the shared report diagnostics. Users should be able to answer: what mode was chosen, what text mode was used, what was rasterized, what was skipped, and where the output assets live.

## What Not To Do

Do not bring back old quality presets. They obscure intent and will fight the cleaner mode/text split.

Do not chase every new field PDF with one-off heuristics unless the case becomes a fixture with an oracle.

Do not promise perfect arbitrary-PDF-to-CAD conversion. PDF is a presentation format, not a CAD model. The product should be powerful and transparent about uncertainty.

Do not treat screenshot eyeballing as the release gate. Screenshots are useful triage, but they need pixel diffs, bounds checks, layer checks, text checks, and host-run validation behind them.

Do not over-vectorize scans or glyph floods. Sometimes raster is the most correct representation, especially when the alternative is thousands of useless CAD entities.

Do not let FreeCAD and LibreCAD quietly diverge in shared report schemas, text mode names, fallback reasons, or core heuristics.

Do not make the LibreCAD plugin DLL the primary install promise unless the Qt/ABI story is fully controlled. The portable CLI/GUI path is a safer default.

Do not hide external image dependencies in temp folders. DXF users move files around; image references must be durable and obvious.

Do not bury dependency packaging in ad-hoc folder copies without ABI checks, license records, and release self-tests.

## Bottom Line

Yes, these importers can become dramatically more accurate, powerful, and intuitive across arbitrary PDFs. The path is not more mode names or more field-specific heuristics. The path is a richer shared PDF semantic IR, region-based hybrid import, first-class layer and text diagnostics, durable DXF packaging, a real validation corpus, and stricter cross-repo sync discipline.

The current architecture is close enough to make that evolution realistic. The next leap is to stop treating PyMuPDF's flattened drawing output as the whole truth and start treating it as one input into a more explicit, testable import model.
