# Outside-The-Box Q&A Session Charter - 2026-06-24

Status: active.

## Question

Have we gone far enough beyond "make the test files work" to build the most accurate, powerful, intuitive, and useful PDF importer/tool ecosystem we can reasonably build?

## Ground Rules

- Arbitrary PDFs remain the target. Test PDFs are examples, not the product boundary.
- Accuracy comes first, then performance, then workflow speed. No shortcut is acceptable if it silently corrupts geometry, scale, layers, or text semantics.
- Bold ideas are welcome, but each must identify its evidence, risk, and shortest safe next step.
- Practical improvements should be implemented immediately when they are low-risk, testable, and do not destabilize current releases.
- Anything that requires larger redesign should be recorded as a roadmap item with a validation path.

## Review Lanes

| Reviewer | Scope | Report |
|---|---|---|
| A | SketchUp importer | `QA-2026-06-24_outside-box-reviewer-A-sketchup.md` |
| B | FreeCAD, LibreCAD, shared core | `QA-2026-06-24_outside-box-reviewer-B-fc-lc-core.md` |
| C | Blender importer | `QA-2026-06-24_outside-box-reviewer-C-blender.md` |
| D | Website, installers, Steel Shapes app | `QA-2026-06-24_outside-box-reviewer-D-website-app.md` |

## Evaluation Axes

- Fidelity: geometry, arcs, Beziers, hatches, images, clipping, layers/OCG, colors, line weights, dash patterns, fonts, Unicode, rotation, leaders, tables, dimensions, annotations.
- Semantics: editable labels versus glyph geometry, real CAD layers/tags, imported object metadata, source-page traceability, quality warnings.
- Scale and placement: page transforms, units, page arrangement, reference scaling, multi-page alignment, coordinate stability.
- Performance: heavy PDFs, dense text, component reuse, chunking, progress, cancellation, low-spec PCs, preview-before-import.
- UX: mode names, defaults, clear warnings, install friction, diagnostics, recovery actions, non-technical user path.
- Validation: corpus tests, round-trip checks, screenshot/image comparisons, known-bad PDFs, benchmark budgets.
- Product leverage: shared core, portable diagnostics bundle, support workflow, website download correctness, app cross-links.

## Required Output

1. Independent reviewer reports.
2. A synthesis note listing agreements, disagreements, and implement-now items.
3. Implemented safe improvements with tests.
4. Commit/push when validation is green.
