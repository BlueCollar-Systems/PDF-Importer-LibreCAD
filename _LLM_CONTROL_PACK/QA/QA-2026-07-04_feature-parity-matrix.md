# Feature Parity Matrix — Code-Level Audit (2026-07-04, R8 update)

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
| `extra.model_3d` | ✓ R8 | ✓ report | ✓ honest 2D | ✓ report | SU extrude v3.7.80; LC `supported:false` |
| `extra.model_3d_intent` | ✗ | partial | partial | partial | plate/member analysis module exists |
| `extra.source_provenance` | ✓ R7 | ✓ R6 | ✓ R6 | ✓ R6 | sidecar + summary |
| `extra.parts_bootstrap` | ✗ | ✓ stub R8 | ✗ | ✗ | FC empty sidecar v4.0.59 |
| `extra.import_contract_ready` | ✓ R7 | partial | partial | partial | SU stub |

---

## Optional 3D generation (R8)

| Capability | SU | FC | LC | BL |
|------------|:--:|:--:|:--:|:--:|
| Optional extrude UI | ✓ Advanced | OPEN P2 | N/A | OPEN P3 |
| Default off (additive) | ✓ | ✓ | ✓ | ✓ |
| Honest unsupported report | N/A | N/A | ✓ | N/A |
| Scale-by-Reference | ✗ | ✓ | ✗ | ✗ | FC-only; documented OPEN |

---

## UI / operator surfaces

| Capability | SU | FC | LC | BL |
|------------|:--:|:--:|:--:|:--:|
| Import Health / support snapshot | ✓ | ✗ | ✗ | ✗ |
| Preflight copy | dialog | INSTALL | `--preflight` | `preflight_check.py` |
| Batch CLI | offline + in-ext | harness | `lcpdf-batch` | `batch_cli` |
| Portable release artifact | RBZ | EXE installer | ZIP | add-on ZIP |
| Pre-import popup (forbidden) | **none** | N/A | N/A | N/A |

---

## Release gates (2026-07-04)

| Gate | SU | FC | LC | BL |
|------|:--:|:--:|:--:|:--:|
| Host unit tests | ruby test/* | pytest tests/ | pytest tests/ | pytest tests/ |
| pdfcadcore sync | N/A | manifest | manifest | manifest |
| Corpus schema CI | N/A | wired R6 | N/A | N/A |
| Ruby 2.2 | ✓ | N/A | N/A | N/A |

---

## Largest honesty gaps (not parity bugs)

1. **Visual fidelity** (color, lineweight, dimension spacing) — needs T-01 + golden rasters.
2. **LibreCAD 3D** — architectural non-goal; report is honest.
3. **FC/BL solid extrusion UI** — Phase 2/3 after SU proof.
4. **SU CLI merge** — dual lane until contract parity (R7-9 OPEN).

---

*Audit snapshot — 2026-07-04 R8*
