# Round 6 — Reviewer S Questions (2026-07-04)

**Session:** Importer completeness gate before advanced features  
**Evidence sweep:** 2026-07-04 — verified against disk on owner machine

---

## Q-S1 — R4 OPEN carry-forward: are text-merge conformance vectors (R4-1) still blocking cross-host accuracy?

Round 4 locked corpus `conformance/text_merge_vectors.json` + Python/SU consumers, but rotation vectors were deferred. SU BOM QUAN upright fix shipped in v3.7.76; fraction false-merge guards exist in Python `primitive_extractor.py` and SU `text_parser.rb` with **different algorithms**.

**Question:** Should Round 6 treat **host-agnostic stacked-fraction vectors** as P0 (blocking T-01 machine sign-off) or P1 (after `actual_text_entity_types` reaches all four hosts)? Who owns the first SU `test/text_merge_conformance_test.rb` beside `ruby22_compat_test.rb`?

---

## Q-S2 — `actual_text_entity_types` rollout honesty (R4-4 / R3-2)

Verified 2026-07-04: FC/LC/BL emit via shared `build_actual_text_entity_types()` in pdfcadcore; SU Ruby emitter was **missing** until this session. Corpus `text_entity_verification.schema.json` expects bucket counts (`native_label`, `dxf_text`, etc.) — the shared builder now maps host+mode correctly.

**Question:** Is the **FC-first → LC → BL → SU** order still authoritative now that three Python hosts emit? Should `validate_contract_schemas.py` become **blocking in FC CI** when ≥2 hosts emit (per R3-2), and should SU Import Health surface the field for T-01?

---

## Q-S3 — SU `performance_hint` + `total_ms` parity (R4-5 / R2-8)

Round 4 docs claimed SU had zero `performance_hint` references; code review 2026-07-04 shows SU **already ships** `build_performance_hint` in `qa_report.rb` and `performance.phases.total_ms`. Gap was documentation drift, not missing code.

**Question:** Should the SU parity floor test (`import_report_parity_floor_test.rb`) be extended to assert `report_meta.build_stamp` and `actual_text_entity_types` when text is enabled — making the floor manifest the single source for cross-host contract keys?

---

## Q-S4 — Corpus CI + importer contract gates (R4-3 / R5-7)

Corpus repo **now has** `.github/workflows/ci.yml` running `validate_contract_schemas.py` and `dependency_audit.py`. FC CI did **not** reference corpus tools until this session.

**Question:** Should every importer release workflow attach a `dependency_manifest.json` asset and run schema validation against a smoke `import_report.json` — or is corpus CI + FC-first adoption sufficient for Round 6?

---

## Q-S5 — Cross-host feature matrix: what still blocks “moving on”?

| Capability | SU | FC | LC | BL |
|------------|----|----|----|-----|
| Import Health UI | ✓ | ✗ (report file) | ✗ | ✗ |
| Preflight copy | messagebox | INSTALL + probe | `--preflight` | `preflight_check.py` |
| Batch CLI | ✗ | adapter | `lcpdf-batch` | `batch_cli` |
| Portable EXE/ZIP | RBZ | installer | portable ZIP | add-on ZIP |
| `actual_text_entity_types` | **this session** | ✓ | ✓ | ✓ |
| `report_meta.build_stamp` | **this session** | **this session** | synced | synced |
| CLI stderr templates (R4-03) | N/A | N/A | **this session** | **this session** |
| Blender GUI perf (redraw thrash) | N/A | N/A | N/A | **this session** |
| 3D text | ✓ | ✓ | **no** (2D host) | ✓ |
| `source_provenance` emitter | ✗ | ✗ | ✗ | ✗ |

**Question:** Which row is still P0 for “importers nailed down” vs honestly P2 (app-side barcode/part tag per R5-1)?

---

## Q-S6 — “100% accurate / complete / powerful” — honest per-host gap list

**Question:** For each host, what is the **single largest remaining accuracy gap** that machine-readable `import_report` cannot yet prove?

Proposal for peer review:
- **SU:** semantic recognition skipped on heavy pages (new `recognition_skipped_pages` signal) — geometry imports but BOM/schedule semantics may be incomplete.
- **FC:** fill color + dimension cluster spacing (T-01 field report FC-1/FC-2).
- **LC:** no true 3D text; DXF TEXT vs outline parity only.
- **BL:** lineweight/bevel on paper-space widths (T-01 BL-1); depsgraph flood on large files (BL-2).

---

## Q-S7 — Outside-the-box: should importers emit a “ready for advanced features” boolean?

R5 defers barcode/part tag to Steel Logic app. Importers already emit `ready_check`-shaped diagnostics in Python hosts.

**Question:** Should Round 6 add a **`import_contract_ready`** aggregate in `import_report.extra` — true only when `actual_text_entity_types`, `report_meta.build_stamp`, `scale_crosscheck`, and schema validation all pass — so the website Report Doctor and T-01 script can gate “start part tag work” without reading six separate fields?

---

*Reviewer S — 7 questions. No self-answers.*
