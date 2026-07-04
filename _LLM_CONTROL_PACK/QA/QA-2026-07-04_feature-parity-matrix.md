# Feature Parity Matrix — Code-Level Audit (2026-07-04)

Evidence: grep + file reads on `C:\1PDF-Importer-*` repos.

---

## import_report.extra / top-level fields

| Field | SU | FC | LC | BL | Notes |
|-------|:--:|:--:|:--:|:--:|-------|
| `schema` bcs.import_report/1.1 | ✓ | ✓ | ✓ | ✓ | |
| `report_meta.build_stamp` | ✓ R6 | ✓ R6 | ✓ R6 | ✓ R6 | synced pdfcadcore |
| `extra.human_summary` | ✓ | ✓ | ✓ | ✓ | |
| `extra.scale_crosscheck` | ✓ | ✓ | ✓ | ✓ | pdfcadcore `build_scale_crosscheck` |
| `extra.font_substitution_note` | ✓ | ✓ | ✓ | ✓ | PDF font audit |
| `extra.performance_hint` | ✓ | ✓ | ✓ | ✓ | 50k entities / 1024 MB thresholds |
| `performance.phases.total_ms` | ✓ | ✓ | ✓ | ✓ | |
| `extra.actual_text_entity_types` | ✓ R6 | ✓ | ✓ | ✓ | shared builder |
| `extra.ready_check` | partial | partial | partial | partial | diagnostics only |
| `extra.source_provenance` | ✓ R6-8 | ✓ | ✓ | partial | FC/LC/BL sidecar + summary; SU summary only |
| `extra.parts_bootstrap` | ✗ | ✗ | ✗ | ✗ | R5-2 deferred |

---

## UI / operator surfaces

| Capability | SU | FC | LC | BL |
|------------|:--:|:--:|:--:|:--:|
| Import Health / support snapshot | ✓ | ✗ | ✗ | ✗ |
| Preflight copy | dialog | INSTALL | `--preflight` | `preflight_check.py` |
| Batch CLI | ✗ | harness | `lcpdf-batch` | `batch_cli` |
| Portable release artifact | RBZ | EXE installer | ZIP | add-on ZIP |
| Pre-import popup (forbidden) | **none** | N/A | N/A | N/A |

---

## Text modes (BCS-ARCH-001)

| Mode | SU | FC | LC | BL |
|------|:--:|:--:|:--:|:--:|
| labels | ✓ | ✓ | ✓ DXF TEXT | ✓ FONT |
| 3d_text | ✓ | ✓ | **N/A** | ✓ |
| glyphs/geometry | ✓ | ✓ | ✓ outlines | ✓ mesh/curve |
| `actual_text_entity_types` proof | ✓ | ✓ | ✓ | ✓ |

---

## Release gates (2026-07-04)

| Gate | SU | FC | LC | BL |
|------|:--:|:--:|:--:|:--:|
| Host unit tests | ruby test/* | pytest tests/ | pytest tests/ | pytest tests/ |
| pdfcadcore sync | N/A | manifest | manifest | manifest |
| Corpus schema CI | N/A | **wired R6** | N/A | N/A |
| corpus PDF anchors | partial | partial | partial | partial |

---

## Largest honesty gaps (not parity bugs)

1. **Visual fidelity** (color, lineweight, dimension spacing) — needs T-01 + golden rasters; `import_report` cannot prove pixels.
2. **LibreCAD 3D text** — architectural non-goal.
3. **SU heavy-page recognition skip** — geometry OK, semantics may be incomplete; now reported in `recognition_skipped_pages`.

---

*Audit snapshot — 2026-07-04*
