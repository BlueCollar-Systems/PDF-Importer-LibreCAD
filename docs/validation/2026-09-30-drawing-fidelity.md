# Drawing fidelity and opening view validation

Validated on Windows with LibreCAD 2.2.1.5, Python 3.12.10, PyMuPDF 1.28.2,
ezdxf 1.4.4 and fontTools 4.66.0. Focused source-font checks also passed with
the pinned PyMuPDF 1.28.0 wheel. Private drawings and native screenshots remain
outside this repository; committed regressions create synthetic source data.

## Changes covered

- Preserve the visible part of positively proved simple clipped lines while
  excluding fully clipped paint. Unknown clip/path shapes remain conservative.
- Bind text to the actual painted font program and character census, including
  distinct same-family subsets and annotation fonts. Exact installed programs
  can be attempted after a source-bound empty embedded program; unrelated font
  failures do not gain new fallback authority.
- Use exact font design units plus the original character affine when a valid
  subset lacks the outline engine's reference letters. Authenticate original
  zero-ink control glyphs before recording an explicit no-image omission.
- Remove redundant glyph contour wires only with positive fill-only source
  paint evidence. Preserve explicit stroke/unknown paint behavior and the
  requested raw Geometry representation. Preserve white annotation borders
  with the same non-inverting white encoding as their fill.
- Stack mixed page sizes without overlap, retain image display policy and
  relative assets, and persist a straight-on view containing the complete batch.

## Opening view contract

LibreCAD 2.2.1.5 reads the DXF VPORT center differently from the standard
geometric-center interpretation. Its `addVport` uses
`f = min(window_width / (view_height * aspect), window_height / view_height)`
and integer pixel offsets `window_width - 2 * center_x * f` and
`window_height - 2 * center_y * f`. Its native writer uses the inverse.

For bounds `(x0, y0, x1, y1)`, the converter preserves a valid viewport aspect
(otherwise 1.34), chooses
`h = 1.1 * max(1, y1 - y0, (x1 - x0) / aspect)`, and writes
`center = ((x0 + x1 + h * aspect) / 4, (y0 + y1 + h) / 4)`.
The minimum scale rule expands the visible range left/down when the opening
window has another aspect; it retains the upper/right extent and full drawing.
No geometry is moved to compensate for the view. Tests reproduce the actual
integer-offset importer at 600x900, 1024x658 and 1800x600, including very wide,
translated, negative-coordinate and mixed-size drawing bounds. Native checks
confirmed initial fit and saved/reopened fit for a three-page mixed batch and
initial fit for a standalone portrait drawing. Other CAD applications' viewport
conventions were not validated in this change.

## Results

- Full headless test suite: **1769 passed, 18 skipped, 28 subtests passed**.
  A short Windows temporary path avoided unrelated Git long-path limits.
  The private runner prohibited native CAD process launches during this suite.
- Ruff, shared-core synchronization and `git diff --check` passed.
- Sequential source-converter sweep: **39 unique PDFs, 106 pages**, requested
  Text mode with resume assembly; every conversion completed and every page
  was certified without degraded items. Original PDF hashes, source text IDs,
  search content and verified delivery records were checked. All assembled
  drawings remained planar, untwisted and within their persisted view bounds.
  This is converter evidence, not a claim that every page was opened natively.
- Final standalone native console export exited **0** with unchanged source and
  artifacts. A prior candidate's Qt teardown crash did not reproduce with the
  final font delivery. Native mixed-batch initial fit and save/reopen were
  visually checked. That final GUI session reached the 600-second guard while
  the operator completed tool actions; it does **not** certify graceful GUI
  exit. A prior mixed-batch GUI session did close cleanly.
- Owned native processes exited; exclusive leases were released and the user's
  LibreCAD profile was restored and verified. A separate post-cleanup check
  matched all 749 entries in the final GUI's source/artifact/input snapshot.

## Remaining native rendering limit

LibreCAD draws cosmetic edges around filled SOLID triangles. The redundant
source contour wires are removed, but this host edge behavior can still make
small glyphs appear heavier. On a 3400x2200 native page export, an exact-boundary
private convex-HATCH diagnostic had 33,095 fewer dark pixels and no additional
dark pixels relative to SOLIDs. All multi-pixel enclosed white regions survived
in the SOLID image; a single one-pixel notch was closed. The compared page's 293
glyph definitions match the final converter's geometry. This is a bounded
observation, not pixel-identical source-rendering certification.

The convex-HATCH prototype is not included in the product. It preserved exact
polygon boundary/area and showed thinner native edges, but needs broader font,
hole, transform, save/reopen and full-batch performance validation before any
representation change. The current patch does not relax geometry tolerances.
