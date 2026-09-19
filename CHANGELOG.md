# Changelog

All notable release changes are recorded here.

## 1.0.101 - 2026-09-19

- Preserve qualified straight dash-dot strokes whose painted dots have zero
  centerline length, such as `[20 3 0 3]`. Modern DXF exports retain editable dash
  LINE segments and solid analytic circular HATCH dots with their original phase,
  size and position. The new case requires round caps, opaque Normal paint,
  uniform source scaling, and complete ink inside proven rectangular clips.
  Curved, partially clipped, nonuniformly transformed and unproven patterns keep
  the disclosed native linetype approximation; legacy R12 does so for dots too.
  Native LINE end caps and lineweight display remain host-dependent.
- Preserve short and zero-length literal strokes instead of discarding their
  centerlines during point cleanup. For source-proven solid round-cap strokes,
  add editable HATCH boundaries with true semicircular arcs and retain the
  original LINE. Verify both after saving, including source identity and placement.
- Preserve qualified Multiply markup appearance using local source-rendered
  display images at 600 DPI above the editable geometry. Only fully source-bound,
  vector-only footprints with proven clipping and blend groups qualify. Exact
  pixel placement, source bytes, and saved image depth are checked; no DPI reduction
  occurs when the pixel budget is exceeded. Unqualified cases are reported.
- Respect paint order around these strokes and existing opaque images, while
  allowing text grouped across a spatially separate stroke to retain its requested
  representation. Hide the SOURCE_BLEND_DISPLAY layer to edit underlying geometry;
  this display aid does not provide general PDF blend support or unlimited zoom.

## 1.0.100 - 2026-09-18

- Place text Raster images using the source renderer's exact pixel origin and
  pixel lattice, including page rotation, crop boxes, user scale and page stacking.
  Verify the saved image axes and all four corners instead of fitting the image
  into a font-metric text box.
- Preserve translucent final rectangle annotations as source-rendered alpha
  images beneath their original editable opaque strokes. This applies only when
  original PDF paint order, rectangle geometry and Normal blending are proven;
  requested text representations remain unchanged. Final-PDF text Raster crops
  retain their existing composited pixels without receiving the tint twice.
- Retain the PDF drawing order around qualified opaque images, so image
  backgrounds no longer cover later title-block text and drawing lines. Verify
  both the saved DXF entity order and its redraw table. Masked/composite images
  retain their separate display rules; this is not a general transparency compositor.
- Preserve original character origins and both font-matrix axes for staggered,
  anisotropic, and sheared source outlines, including rotated fractions and
  adjacent dimension text. Bind the matrix to the original PDF font metrics
  rather than fitting visible ink to a text box.
- Keep missing or unreadable staged font assets as runtime failures instead of
  using them to authorize a text representation fallback.
- Export proven single straight-path dash patterns as editable native line
  segments, preserving original phase through clipping, rotation, and scaling.
  Curves, multiple subpaths, zero-length dot patterns, and unproven cases retain
  the native linetype approximation and are listed in the extraction summary.
  Native line caps and supported lineweight steps remain host-dependent.

## 1.0.99 - 2026-09-17

- Match annotation images by exact decoded pixels and placement when PDF
  inventory numbers differ, retaining their source transparency masks.
- Raster crops include original source character quads beyond short font boxes while preserving source identity and page placement.

- Choose the nearest supported DXF stroke weight before saving, preventing
  invalid intermediate weights from being silently rounded up and thickening
  fine gray drawing details.

- Preserve original PDF character quads instead of reconstructing glyph frames
  from rounded font metrics, avoiding false shear in source outlines.
- Omit geometry only when renderer paint bounds prove that it lies entirely
  outside the visible PDF page; retain partially visible strokes unchanged.
- Handle positioned fractions with proven empty source font programs while
  keeping runtime, extraction, and font-staging failures out of the fallback path.
- Retain raw source paint colors, opacity, and drawing order in shared extraction
  metadata. LibreCAD's native renderer still does not composite DXF transparency.

## 1.0.98 - 2026-09-16

- Preserve covered PDF clipping masks as compound vector fills, including logo
  counters and knockout contours, instead of filling their bounding rectangles.
- Use actual polygon containment for native SOLID fills so overlapping logo
  bounding boxes cannot remove unrelated letters or create connector strokes.
- Keep source artwork edges aligned with these exact fills instead of circle
  fitting nearby polygon outlines.

## 1.0.97 - 2026-09-16

- Preserve dense drawing geometry and embedded images while avoiding repeated
  page classification, text extraction and font-cache work on large PDFs.
- Report mixed text delivery accurately when visible source text uses outlines
  and zero-ink whitespace retains native TEXT. The requested mode, item proofs
  and existing geometry remain unchanged.
- Verified conversion of a sparse-cross-reference, marked-up 48 by 36 inch
  foundation sheet through all six text modes, retaining every source text item.

## 1.0.96 - 2026-09-16

- Shared pdfcadcore: the import report's PDF audit no longer aborts a finished import
  when the file's cross-reference stream has index gaps. It probes every object number
  for JavaScript actions, and MuPDF raises an error class deriving from Exception rather
  than RuntimeError for an unallocated number, so the exception escaped every guard on
  the path and turned a completed conversion into a failure after the DXF had already
  been written. Reported on an Aspose markup export of a 48x36 in foundation sheet.
- Ordinary fraction-shaped labels ("3/8" on a dimension string) stay on the regular text
  ladder. The positioned-fraction route engaged for any span that merely looked like a
  fraction and refused the whole page as "invented aggregate placement metrics"; it now
  engages only for the merger's semantic stacked fraction.
- Terminal raster tiles build the page display list once instead of once per tile, and
  the post-write verification re-opens a reduced copy of the serialized candidate rather
  than re-reading the whole file through ezdxf. Every record the verification inspects is
  still read from the written bytes; bulk geometry it never inspects is syntax-checked in
  a streaming pass and its count reconciled. A 452k-entity submittal page converts in
  76 s where it took 121 s, byte-identical output.

## 1.0.95 - 2026-08-20

- Shared pdfcadcore: disconnected PDF subpaths are preserved rather than being joined
  into a single run. A subpath that starts away from the previous one no longer drags a
  connecting segment across the drawing.

## 1.0.94 - 2026-08-20

- Shared pdfcadcore: EOFError is now treated as a malformed embedded font rather than
  aborting a page's text extraction. fontTools raises it from a single site --
  cffLib.readSID, "Unexpected end of file while reading SID" -- when a CFF Encoding
  supplement stops mid-read, which is the same class of failure as the struct.error
  case guarded in 1.0.93. It subclassed nothing already caught, so it propagated.

## 1.0.93 - 2026-08-18

- Shared pdfcadcore: exact inventory font traces (a font's own texttrace is preferred
  over a union of SFNT family/PostScript aliases, so a sibling embedded program's
  glyph identities can no longer be merged into another font's Unicode map).
- Shared pdfcadcore: a malformed embedded font program no longer aborts a page's text
  extraction. fontTools raises struct.error (not a ValueError) for a font whose name
  table is shorter than its 6-byte header; that is now recorded as an item-scoped
  source impossibility, like the existing fontTools AssertionError case.

## 1.0.92 - 2026-08-17

- Positioned stacked fractions: exact producer character layout is preserved and
  verified through the DXF (fill-only positioned geometry, page translations and
  representable colours kept; malformed evidence refused instead of a silent raster
  fallback). No more artificial 0.6x inline scale.
- 1011 fallback transitions recorded (#35).

## 1.0.91 - 2026-08-16

- pdfcadcore sync: constant alpha (/CA, /ca) is composited against the white page once
  at extraction for strokes, fills and text, so translucent separator bars and faint
  labels look the way the PDF viewer shows them (LibreCAD has no transparency).
  Invisible render-mode-3 text (OCR layers) is left uncomposited.
- LibreCAD's white->black inversion (white ink would vanish on the default background)
  now fires only for genuinely white ink; pale tints and composited washes keep their
  colour instead of turning solid black.

## 1.0.90 - 2026-08-16

- pdfcadcore sync: both-sides weld symbols keep the second stacked fraction (the
  stacked-fraction merge selected every same-split span within 4.5 mm and the overlay
  dedupe then removed the second slash; 14 fillet-weld sizes were dropped on a real
  fabrication sheet).

## 1.0.89 - 2026-08-16

- Four visible defects found by side-by-side comparison of the LibreCAD import with the
  PDF (LibreCAD's own dxf2png render vs the PDF page): clockwise-traversed arcs were
  emitted as their complement (weld-all-around circles drawn as an open "C"); custom
  PDF_DASH linetypes rendered continuous in LibreCAD (it only recognizes its own linetype
  names) -- dashes are now mapped to the closest LibreCAD family/length variant;
  lineweights were converted pt->mm twice (2.83x too thin); raster crops of merged
  stacked-fraction items were squashed to 60% width (now square pixels, aspect
  preserved).

## 1.0.88 - 2026-08-16

- Glyph outlines now come from the exact embedded source-font program. ezdxf resolves
  fonts by file name against its system cache and silently returned its fallback face
  for the extracted asset path, so every embedded-font glyph delivery drew the fallback
  (found by the LibreCAD visual oracle on 1011: RomanT title rendered as a bold sans).
  The asset folder is registered with the engine, the exact program is re-verified at
  use, and substitution is refused (item-scoped -> raster). Evidence records
  `outline_engine_font_verified`.
- Glyph export stops recomputing known values: definition fingerprints are hashed once
  per verification pass, outline bboxes no longer copy/transform the SOLID fills, and
  plain LWPOLYLINE bboxes are taken from the vertices directly (bit-identical). On
  1011/labels the DXF export dropped 51.0/55.2 s -> 26.9/29.1 s (importer clock, same
  machine, interleaved).

## 1.0.87 - 2026-08-15

- Always emit `extra.fallback_transitions` so certified-ladder hops are visible
  to 1011 accuracy scoring.

## 1.0.86 - 2026-08-13

- circle_fit accumulation moved to math.fsum: geometry is now identical on every
  CPython version and platform (an ill-conditioned arc previously fit differently
  under 3.11 vs 3.12+ arithmetic, flipping borderline arc promotion).
- CI now enforces the fsum summation guard and the Bezier flattener contract, and
  prints which pdfcadcore copy the tests import.

## 1.0.85 - 2026-08-12

### Performance

- Gate 0 stage timers (xtract_ms / host_build_ms) plus reviewed
  circle_fit restore (lockstep with FC/BL).

## 1.0.84 - 2026-08-11

### Performance

- Refresh shared pdfcadcore sync manifest after FreeCAD circle_fit / slots
  dataclass speedups (lockstep with FC/BL).
## 1.0.83 - 2026-08-10

### Performance

- Neighbor-bin hatch angle clustering replaces O(n²) all-pairs scans without
  changing ANGLE_TOL / spacing / length acceptance (fidelity-safe).
## 1.0.82 — 2026-08-09

### Fixed

- Stop redirected/frozen `pdf2dxf.exe` stdio from crashing on non-cp1252 output
  paths after a successful conversion. Reconfigure stdout/stderr for path-safe
  encoding, wrap diagnostic prints so encoding failure cannot decide the exit
  code, and pin `--python-option X utf8=1` on portable PyInstaller builds.

## 1.0.81 — 2026-08-03

### Fixed

- Prevent visible LibreCAD LFF font substitution from terminating as verified
  Text or Labels without source-equivalent visual proof. Those items now
  descend automatically to exact glyph outlines; zero-ink whitespace remains
  native editable `TEXT`.

## 1.0.80 — 2026-08-03

### Fixed

- Preserve valid native whitespace `TEXT` spans through the serialized
  LibreCAD reopen gate. Whitespace has no font pixels to substitute, so its
  exact visual result is zero ink; visible substituted glyphs remain explicitly
  unverified for source-font pixel equivalence.

## 1.0.79 — 2026-08-03

### Fixed

- Promote bounded higher-resolution text confirmation ink to the exact mapped,
  host-safe opaque Raster delivery instead of rejecting visible source content.
- Publish an explicit valid scale crosscheck for both clean and warning outcomes,
  while malformed or missing evaluations remain fail closed in contract readiness.

## 1.0.78 — 2026-08-02

### Fixed

- Preserve selectable native LibreCAD `TEXT` for requested Text and the finite
  Labels-to-Text fallback when the bundled Unicode LFF face is required.
- Verify content, insertion, source-font cap height, rotation, FIT endpoint,
  drawable LFF glyph bodies/references, serialized reopen, and evidence
  integrity before accepting the native entity.
- Bind `unicode.lff` evidence to the exact resolved LibreCAD executable used by
  the CLI/GUI launch path, reject unrelated overrides and assets over 16 MiB,
  and fresh-read/hash the asset during serialized reopen verification.
- Preserve running LibreCAD sessions when opening a generated drawing; the
  launcher no longer force-terminates existing processes and unsaved work.
- Disclose the LFF font substitution and keep source-font pixel equivalence
  explicitly false; Glyphs and Geometry remain the exact-outline choices.

### Performance

- Avoid replacing each accepted native Text/Labels span with glyph-block
  outlines, materially reducing entity creation and file weight on text-heavy
  drawings while retaining editable text.

## 1.0.77 — 2026-08-02

### Performance

- Build the serialized modelspace handle/ownership index once per completed
  DXF instead of rebuilding the full index for every delivered text item. This
  removes an accidental quadratic verification pass while preserving the exact
  duplicate-handle, modelspace-owner, entity-type, and native-reopen checks.

## 1.0.76 — 2026-08-02

### Fixed

- Keep the report-level text-delivery contract ready when Raster correctly
  certifies a whitespace-only source item as an exact zero-ink omission. These
  items intentionally create no DXF entity; acceptance now requires their
  terminal Raster attempt to prove type, visual result, cleanup, zero ink, and
  that visible ink was not expected. Visible or otherwise unproven items still
  require a persisted entity handle and fail closed without one.

## 1.0.75 — 2026-08-01

### Fixed

- Restage missing or changed exporter-owned embedded fonts from verified source
  bytes while preserving exact asset identity checks.
- Composite premultiplied-alpha text crops onto white before ink detection and
  confirm legitimate zero-ink output across every requested text representation.
- Route incomplete inline-image inventories to deterministic, host-safe page
  fidelity surfaces without silently dropping source instances.
- Preflight cumulative page-fidelity pixel and tile usage and select one safe
  job-wide DPI before allocating assets.
- Draw opaque full-page fidelity surfaces above retained editable entities to
  prevent duplicate visual paint; editables remain available beneath the image
  layer.
- Treat certified collinear or exactly reverse-retraced PDF fills as zero-paint
  operations while retaining strict failures for nondegenerate fill loss.

### Release engineering

- Add an atomic, fail-closed `--accept` workflow for regenerating and immediately
  verifying exact release artifact metadata.
