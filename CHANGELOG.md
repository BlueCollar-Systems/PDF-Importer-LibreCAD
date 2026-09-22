# Changelog

All notable release changes are recorded here.

## 1.0.103 - 2026-09-22

- Default-off for white knockout / mask layers that blinded dark CAD canvases (page_0001$0$P001_RGB_255_255_255-style fills stay available but hidden).

## 1.0.102 - 2026-09-21

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
- Text a PDF delivers as raw glyph codes is now recovered where this tool can
  prove the characters, and reported either way. The trigger is narrow and
  structural: `/Subtype /Type0` with an Identity CMap and no `/ToUnicode`, over
  a subset font program that carries no usable mapping of its own. A font with
  any real encoding, including the many that simply lack a `/ToUnicode`, is not
  touched. Substitution is all-or-nothing per span: one unproven character
  leaves the whole span byte for byte as the PDF delivered it, because a
  half-read dimension reads as a measurement. Every recovered span names the
  route that proved it (`embedded_cmap`, `post_glyph_name`, `outline_identity`
  or `blank_glyph_advance`) and is never presented as the PDF's own mapping; a
  character the engine already resolved, or a space its layout inserted, is
  counted apart under `characters_left_as_delivered`. The last two routes match
  a glyph's contours against an installed reference face of the same family,
  width and weight, with the PDF's own `/W` advance required to agree, so the
  characters come from that face rather than from the file - a reason to read
  the new checklist row. New report block `extra.text_glyph_codes`
  (`bcs.text_glyph_codes/1.0`), published by the CLI summary, the batch
  `--json` record and the resumable summary alike; `result.warnings` gains a
  term for unproven spans only, and a span this run could not examine is
  reported as a limitation of the import rather than a failure of the sheet.
  On an affected sheet the DXF also gains native `TEXT` entities on the frozen
  `P###_TEXT_SEARCH` layer that the companion previously refused, because the
  recovered strings no longer contain control characters; the counts in
  `extra.searchable_text_companions` move with them.
- One text item whose delivery cannot be verified no longer stops the export of
  its sheet (owner decision 2026-09-19: "these tools are meant to help, not
  hinder"). Before, a single such item wrote no DXF at all. The failure
  classification is unchanged and kept in the evidence (`proof_class`:
  `proven_impossible`, `unproven_failure`, or `invalid_layout`); only the
  consequence changed. The item now degrades: requested rungs, then an item
  Raster patch tried whether or not the failure was proven, then a visible
  native `TEXT` with the exact source string on layer `P###_TEXT_DEGRADED`, then
  a reported drop. This also covers an invalid positioned-fraction layout, the
  R12 positioned-colour problem, a text-builder exception, and a Raster crop
  without its pixel-lattice proof. `proven_impossible` repeats the builder's own
  verdict (it authorized the item, or proved the R12 colour); a font failure the
  builder refused to call proven is reported as `unproven_failure` even when
  every rung ended "impossible".
- Read a pre-R2007 candidate back in its own codepage. R12 to R2004 files are
  cp1252, so one degraded `TEXT` carrying a degree, plus-minus, or fraction
  character made the strict UTF-8 post-write reader raise and cost the sheet.
- Keep that degrade loud instead of fatal, because a failure not proven to come
  from the source may be our bug. The item stays `verified: false`, so
  `import_contract_ready`, certification, and the release smoke gates still fail
  for that sheet. `extra.text_items_degraded` lists every degraded or dropped
  item (at most 200, with a total and a truncated flag), `result.warnings`
  counts them together with left-out or approximate clipped fills, the CLI
  prints one bounded single-line stderr warning per item (control characters
  removed) for the first 20 items, then one `... and N more degraded text
  item(s); see the import report.` line, and exits 0, and the GUI shows a
  warning instead of an error (one completion message carries both the
  clipped-fill sentence and the degraded-text warning). The rescue reason
  code `item_degraded_after_unproven_failure` or
  `item_degraded_after_proven_impossibility` is on each item's delivery record
  (`fallback_reason_code`), on each `text_items_degraded` entry (`reason_code`),
  and grouped in the new `fallback.text_items_degraded`; `fallback.text` still
  names one substitution and prefers the sheet's verified fallbacks, so in the
  default Text mode it does not carry that code. `fallback.reason` and the human
  summary append the degraded rows (and `N dropped from the drawing`) to
  whatever they already said, so the default Text mode names a rescue or a drop
  there too. A dropped item sets `fallback.used` and is no longer counted in
  `result.text_entities`, the human summary, `pdf2dxf.py`'s `Text items` line,
  or the GUI log's `Text` line. An item whose Raster rung found that the source
  paints no visible ink gets no patch: its entry carries `no_visible_ink: true`
  and its warning says that nothing was drawn, not that a raster patch was
  delivered. A rescued text-builder crash keeps a bounded traceback in its
  attempt's evidence; frames and message are bounded separately, so a very long
  message cannot push the raise site out.
- The batch CLI reports a sheet with a degraded or dropped text item as
  `DEGRADED`, never `PASS`, writes its DXF, and exits 1 when any sheet is
  `DEGRADED` or `FAIL`: before this change such a sheet was `FAIL` with exit 1,
  and scripts that spot uncertified sheets by the exit code keep working. A
  sheet that only had clipped fills left out stays `PASS` with a warning. The
  QA smoke harness still fails a degraded sheet.
- The same exit codes for the import itself in `lcpdf-import` and `pdf2dxf.py`:
  `0` a DXF was written (degraded text items and left-out clipped fills are
  stderr warnings); `2` with `Import stopped: ...` is a deliberate stop that
  says why and names the failure report it left: no stable source identity,
  duplicate source IDs or handles, or post-write verification that is
  structural or survives its one re-export, all raised as `ImportStopped`; `3`
  any other unexpected failure, in one readable line that names the failure
  report when the export left one. Exit `2` alone does not prove a deliberate
  stop: `pdf2dxf.py` keeps its existing exit-`2` answers, with no `Import
  stopped` and no failure report, for an unparsable `--pages` value and for a
  file that turns out not to be a readable PDF once the conversion has started
  (and argparse rejects a bad command line with `2`). Every failure report now
  records what stopped the export in `extra.terminal_failure` (error text,
  exception type, deliberate or not, bounded traceback); before, it said
  `failed` and never why. If the failure report itself cannot be written
  (read-only folder, full disk), the original error and its exit code are kept
  and stderr says that the failure report could not be written. The GUI error
  box names the failure report for an unexpected failure as well.
- Keep "certified" true in resumable (`--resume`, GUI) conversions. A page with
  a degraded or dropped text item is still checkpointed and resumable, but it is
  announced as `exported with N degraded text item(s) - NOT certified`, left out
  of `pages_certified`, and listed in the new `pages_degraded`. The resumable
  report now carries `warnings`, `text_items_degraded`,
  `text_items_degraded_total`, and `text_items_degraded_truncated` like the page
  reports it points to.
- Re-export once, with those items forced down the degrade ladder, when
  post-write verification fails for identifiable text items. The verifier now
  collects every per-item mismatch (and any fault raised while checking one
  item) instead of stopping at the first, so the one re-export covers all of
  them. Structural failures (duplicate source IDs or handles, or a mismatch
  that survives the re-export) still stop the import, but end in a readable
  message, a failure report, the prior DXF preserved, and exit code 2 instead
  of a traceback.
- Accept up to 1e-4 (0.006 degrees) of dimensionless shear in positioned
  fraction character quads. Quads rebuilt by `recover_char_quad` measured
  1.8e-5 of float32 rounding, only 11% under the former 2e-5 bound. The bound
  now only chooses glyph outlines or a Raster patch for that span.
- Make LibreCAD importer output searchable (owner decision 2026-09-19). Since
  1.0.81 a visibly substituted LibreCAD LFF font is never certified as delivered
  Text, so every visible span became glyph outlines or a raster patch and its
  string was nowhere in the DXF (measured on one sheet: 427 of 427 spans, 0
  `TEXT`). That guarantee stands and outlines stay the visual truth. In
  addition, every span delivered as Glyphs, Geometry, or Raster (an item
  degraded to a Raster patch included) and every dropped item now gets ONE
  hidden native `TEXT` with the exact source string (not NFKC-normalized) at the
  item's insertion and rotation, cap height from the source font when known
  (else about 0.72 em), style `unicode`, FIT-aligned to the source advance, on
  the dedicated layer `P###_TEXT_SEARCH`, created frozen and (not in R12)
  non-plotting. Thaw `P###_TEXT_SEARCH` and freeze `P###_TEXT` to work with
  editable LFF text (to print it, also switch the layer's print flag on). A span
  already delivered as visible `TEXT` (whitespace, or the degraded `TEXT` on
  `P###_TEXT_DEGRADED`) gets none.
- The companion certifies nothing: `final_representation`, `verified`, entity
  counts, `delivered_text_entity_counts`, the TEXTMODE-1 buckets, and every
  certified handle are exactly what they are without it (the companions are
  written after every page, and each gets its paint key, so a page with images
  still exports). The resumable / GUI page assembly sizes each page without the
  hidden layer, so the visible geometry of page 2 and later is where it is
  without the companions. Each delivery record gains `search_text` (`status`,
  `handle`, `layer`, `content`) and the report gains
  `extra.searchable_text_companions` (`enabled`, `written`, `not_representable`,
  `failed`, `mismatch`, `layers`); the resumable summary carries the merged
  block. A string native `TEXT` cannot carry literally (caret or `%%` control
  sequences, a literal `\U+XXXX`, a `\P` or `\~` that LibreCAD rewrites on
  load, control characters and lone surrogates, and beyond U+FFFF in a pre-R2007
  file) is skipped as `not_representable`. A companion that cannot be written is
  `failed`, and one whose exact content, layer, type, or frozen layer is not
  confirmed after the write is `mismatch`: both are warnings (`result.warnings`,
  one stderr line, the batch, `qa_smoke` and resumable reports, the GUI log and
  completion message), never a raise, never a re-export, and never the item's
  own `verified` flag.
- New switch `--searchable-text` / `--no-searchable-text` on `lcpdf-import` and
  `pdf2dxf.py` (default on; `DxfExportOptions.searchable_text`). Switched off,
  no companion is written and no layer is created. The resume identity includes
  it. There is no GUI control yet, and the GUI's text-mode dropdown labels
  ("Text (editable native TEXT)", "Labels (closest Text fallback)", "3D Text (2D
  host: Text fallback)") are unchanged here, pending an owner decision.
- The streaming paint-order check no longer decodes a pre-R2007 (cp1252) file as
  strict UTF-8: with images on the page, one `TEXT` carrying a degree sign cost
  the sheet there. R12/R2000/R2004 files are cp1252 (a character in that code
  page is one byte, any other a `\U+XXXX` escape), so a UTF-8 text search of
  such a file does not find non-ASCII strings; R2007 and later files are UTF-8.
- Correct the README, INSTALL, COMPATIBILITY, and HUMAN_CONFIRMATION text that
  still promised "native editable DXF `TEXT`" for Text mode and an "editable
  Text fallback" for Labels and 3D Text, which has not been true since 1.0.81.

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
