# Feature Parity Matrix — Code-Level Audit (2026-07-04, R9 update)

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
| `extra.model_3d` | ✓ GUI+CLI report | ✓ Part solids | ✓ honest 2D | ✓ mesh solids | LC `supported:false`; SU headless CLI report-only |
| `extra.model_3d_intent` | ✓ | ✓ | ✓ | ✓ | plate/member evidence scan; advisory eligibility gate |
| `extra.source_provenance` | ✓ R7 | ✓ R6 | ✓ R6 | ✓ R6 | sidecar + summary |
| `extra.parts_bootstrap` | ✗ | ✓ stub R8 | ✗ | ✗ | FC empty sidecar v4.0.59 |
| `extra.import_contract_ready` | ✓ R7 | ✓ R9 | ✓ R9 | ✓ R9 | shared readiness aggregate; app/Report Doctor advisory |

---

## Optional 3D generation (R8)

| Capability | SU | FC | LC | BL |
|------------|:--:|:--:|:--:|:--:|
| Optional extrude UI | ✓ Advanced | ✓ Workbench | N/A | ✓ Operator |
| 3D solids generated | ✓ SketchUp pushpull | ✓ Part extrude | N/A | ✓ mesh prism |
| Default off (additive) | ✓ | ✓ | ✓ | ✓ |
| Honest unsupported report | N/A | N/A | ✓ | N/A |
| `model_3d_intent` report | ✓ | ✓ | ✓ | ✓ |
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
2. **Semantic steel solids** — exact AISC profile/member modeling by BOM mark/length remains the next advanced feature; current v1 is closed-region extrusion plus intent evidence.
3. **LibreCAD 3D** — architectural non-goal; report is honest.
4. **SU headless geometry** — CLI can analyze/report, but SketchUp host is required to create geometry.
5. **SU CLI merge** — dual lane until contract parity (R7-9 OPEN).

---

*Audit snapshot — 2026-07-04 R9*
