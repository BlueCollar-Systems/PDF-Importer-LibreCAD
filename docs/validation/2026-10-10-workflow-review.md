# Workflow and font fidelity review - 2026-10-10

Local source fixes cover installation, conversion settings, safe cancellation,
and font binding. No publication or installed portable release was changed.

## Implemented changes

- Installed wheels now include `pdf_open_guard.py` and `runtime_requirements.py`.
  Installed dependency requirements come from the wheel's own metadata when the
  checkout's requirements file is absent. An isolated built-wheel test opens
  and converts a synthetic PDF from outside the source directory.
- Both CLI entry points default to the documented R2010 output. Invalid scale,
  incomplete reference-length pairs, non-finite dimensions, and overflowing or
  underflowing reference ratios stop before extraction or output writes.
- Closing the GUI during work requests its existing page-safe cancellation and
  waits for the worker checkpoint before destroying the window.
- Shared font extraction now separates same-name programs using the actual
  source-character font-program SHA and exact Unicode/origin trace occurrences.
  Same-family subsets with different glyph IDs no longer invalidate one another.
  Character glyph IDs retain their occurrence-bound trace identity. Source
  absence, incomplete occurrence evidence and ambiguity remain explicit failures.
  The three shared modules and their manifests were synchronized with Blender and
  FreeCAD; their regression tests include distinct programs painting the same
  Unicode character in a normal page and inside a Form.
- Native inferred spaces retain their original layout without inventing a
  painted glyph ID. This requires native synthetic-space flags, no matching
  painted occurrence, an exact original font binding, and an empty original
  U+0020 glyph. Positive and negative tests cover original SFNT and raw CFF
  programs, visible spaces, missing encoding, and incomplete occurrence evidence.

## Validation

- Full suite before the shared font-map change: **1,798 passed, 18 skipped,
  28 subtests passed** in 930.52 seconds.
- Installation/build/runtime/settings checks: **35 passed**.
- GUI, scale, CLI and PDF-open checks: **52 passed**.
- Shared font/source-quad/glyph-recovery checks after the font change:
  **78 passed, 6 skipped**.
- Wider text representation, fractions, control-glyph and font environment
  checks: **382 passed, 7 skipped, 9 subtests passed**.
- Final source binding, native source quads, zero-ink control glyphs and
  positioned-fraction delivery: **202 passed** after the synthetic-space and
  original CFF proof refinements, including rejection of a competing painted
  space even when its trace count matches the inferred occurrence. Additional
  final font/fallback/environment
  checks: **223 passed, 6 skipped**.
- Ruff, whitespace checks, runtime self-test and shared-core synchronization passed.

## Real-input findings and boundaries

The source corpus has 5,897 top-level PDFs. This review sampled it; it did not
convert all files or certify their native appearance. One 179,562,772-byte,
259-page drawing set's first page completed in 170.45 seconds with unchanged
source bytes before the font repair. That run truthfully marked the page
degraded: 289 text items used raster patches because same-name Helvetica
programs collided. After the repair, source extraction bound **340 of 340 text
spans** to their actual font programs with zero font failures. Complete repaired
DXF delivery initially completed in **368.74 seconds**. The settled export after
partial-census, original CFF, and competing-paint proof refinements completed in **195.72
seconds**: page 1 certified, **339 spans
delivered as editable Glyphs and one as native Text**, zero degraded or
unverified text items, and unchanged source SHA-256. Timing varies with system
load and this repair makes no speedup claim. Real vector delivery costs more
than raster patches on this sample. This is converter/reopen evidence,
not a complete native LibreCAD/PDF visual comparison. The final DXF reopened
with 12,867 modelspace entities including searchable companions; its audit had
zero errors and zero repairs. A sanitized snapshot is in
[`2026-10-10-large-page-probe.json`](2026-10-10-large-page-probe.json).

A different 103,902-byte sheet exceeded a 300-second conversion bound. A bounded
stack probe located outline construction and geometry-bound checks; file size
alone does not predict cost. An 1,153-byte transparency fixture converted in
2.55 seconds with its input unchanged. These observations do not establish
performance on old hardware or pixel equality with a PDF viewer.

These source fixes can be tried with `launch_lcpdf_gui.pyw` on the configured
development machine. Existing portable executables still contain their released
source. Older LibreCAD versions, complete device/host coverage, and universal
visual parity remain outside the verified results.
