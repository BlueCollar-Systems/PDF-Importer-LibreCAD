# Changelog

All notable release changes are recorded here.

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
