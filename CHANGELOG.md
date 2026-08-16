# Changelog

All notable release changes are recorded here.

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
