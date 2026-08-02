# Changelog

All notable release changes are recorded here.

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
