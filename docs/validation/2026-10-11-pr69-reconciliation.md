# Original font and character-frame reconciliation

Final closure: [v1.0.106 converter and release acceptance](2026-10-11-v106-final-acceptance.md)
records the completed full suite, cold converters, attested exact-byte acceptance
and publication. Earlier incomplete validation and release statements below
remain historical; native LibreCAD GUI acceptance is still pending.

The closed draft #69 contained useful installed-family/style normalization,
original per-character metric frames and a resume-rule identity. Those changes
are reconciled against main at c914046 while retaining its editable-text
disclosures, R12 proof gates, source colors and checkpoint assembly.

Matching family/style, Unicode cmap, numeric glyph IDs and advances does not
prove matching visible contours. Two actual fonts with identical names, cmap,
IDs and widths but triangle versus rectangle outlines reproduce that gap.
Advance telemetry is explicitly spacing-only. Exact installed-font outlines
now require each character's verified original source-program digest to match
the freshly read candidate file, and preserve the original character frames.
The bound original triangle font delivers actual Glyphs and Geometry; the
different rectangle is rejected. Positive deliveries are saved/reopened as DXF
and audited. A file changed after resolution, unbound source characters and
missing frames cannot authorize an exact contour certificate.

An absent original program can still use the disclosed editable-text path
when requested, or reach an item raster fallback with its reported limits.
The old draft's advance-only exact-outline positive assertions are not retained
as a valid fidelity contract. Its original branch/history remains preserved.
Metric regression fixtures now extract real embedded-font PDFs rather than
inventing unbound spans. Their original cap-height assertions remain.

Release publication requires explicit workflow dispatch. Ordinary push and PR
CI remains enabled; no production version bump or release is part of this
reconciliation.

Validation before the final frozen build:

- Full source run: 2,073 passed, 18 skipped, 28 subtests; two old cap-metric
  fixtures required the original-program proof described above.
- After those fixture repairs, the affected metric, adversarial font, embedded
  font, Bezier and alpha suites passed: 56 tests, 6 fixture skips.
- Whole Ruff, diff checks, shared-core manifest and dependency preflight passed.
- A final full run and cold packaged converter checks are recorded separately
  with the exact committed build identity.

These checks use actual PDF extraction, font programs and DXF persistence.
They do not claim native LibreCAD UI acceptance or universal PDF fidelity.
Historical local test archives and native evidence remain bound to their
original source snapshots.
