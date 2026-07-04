# Round 6 Resolution — Agreements (2026-07-04)

**Session:** Reviewer S questions; Reviewer T answers; engineering implementation same day  
**Focus:** Importer contract completeness before advanced app features

---

## Agreements

| ID | Topic | Decision | Status | Owner |
|----|-------|----------|--------|-------|
| **R6-1** | `actual_text_entity_types` all hosts | Shared pdfcadcore `build_actual_text_entity_types()` is canonical. FC/LC/BL already emitted; **SU Ruby mirror shipped** v3.7.77. Import Health surfaces type + count. | **SHIPPED** | SU, pdfcadcore |
| **R6-2** | `report_meta.build_stamp` | Top-level `report_meta` on `bcs.import_report/1.1` with `{host, semver, build_stamp, report_sha256, imported_at}`. | **SHIPPED** | pdfcadcore → FC/LC/BL; SU Ruby |
| **R6-3** | SU performance parity | `performance_hint` + `performance.phases.total_ms` — **verified present**; R2-8 SU gap closed. Docs corrected. | **SHIPPED** | SU |
| **R6-4** | CLI stderr templates (R4-03) | `pdfcadcore/cli_error_copy.py`; LC `pdf2dxf.py`, `lcpdf-import`, BL CLI wired. | **SHIPPED** | LC, BL, pdfcadcore |
| **R6-5** | Blender GUI import perf | Remove in-loop `redraw_timer`; single `view_layer.update()` at end. | **SHIPPED** | BL |
| **R6-6** | Corpus CI + FC importer gate | Corpus `ci.yml` exists; FC workflow clones corpus + runs `validate_contract_schemas.py`. | **SHIPPED** | corpus, FC |
| **R6-7** | Text-merge conformance vectors (R4-1) | Corpus `stacked-fraction-merge-vectors.json` (8 vectors incl. whole_number_fraction_spacing), `stacked-fraction-extract-golden.json`, `tier1/tags/bom_quan_upright_oracle.json`; FC `test_text_merge_conformance.py`; FC/LC/BL `test_fraction_extract_golden.py`; SU `stacked_fraction_conformance_test.rb`. | **SHIPPED** | corpus, FC, LC, BL, SU |
| **R6-8** | `source_provenance` emitter | Minimal `bcs.source_provenance/1.0` sidecar + `extra.source_provenance` summary. FC/LC/BL emit sidecar from text spans; SU Ruby mirrors summary only (no sidecar). | **SHIPPED** | FC, LC, BL, SU (partial), pdfcadcore |
| **R6-9** | T-01 human visual sign-off | Screenshots + FC/LC/BL field defects (FC-2 fill, BL-1 lineweight) still need in-host verification. | **OPEN** | human |
| **R6-10** | App advanced features (KettleTag, bootstrap, `/p/`) | R5-1…R5-7 remain **app/website** backlog; importers not blocking on barcode. | **DEFERRED** | Steel Logic, website |

---

## IMPLEMENTATION BACKLOG (ranked)

### P0 — SHIPPED this session
1. `actual_text_entity_types` SU + Import Health — **SU v3.7.77**
2. `report_meta.build_stamp` — **pdfcadcore + all hosts**
3. CLI stderr templates — **LC v1.0.50, BL v1.0.54**
4. Blender GUI perf — **BL v1.0.54**
5. FC CI corpus schema step — **FC v4.0.57**
6. Heavy-page recognition skip reporting — **SU v3.7.77** (uncommitted work committed)

### P1 — Next engineering slice
1. R4-1 text-merge vectors + SU conformance test
2. R4-2 portable regression anchors (P0 skip fail in CI)
3. FC fill color (FC-2), BL lineweight (BL-1) from T-01 field report
4. SU parity floor manifest update (`report_meta`, `actual_text_entity_types`)
5. FC release pipeline: dependency manifest asset
6. Report Doctor: `build_stamp` header (website)

### P2 — After importer contract green
1. `import_contract_ready` aggregate (Report Doctor client-side first)
2. `source_provenance` sidecar
3. `parts_bootstrap` sidecar (R5-2)
4. KettleTag / barcode (R5-1) — **app only**

---

## Feature parity matrix

See `QA-2026-07-04_feature-parity-matrix.md`.

---

## Ready for advanced features?

**Mostly yes for app planning; no for claiming “100% importer accuracy.”**

**Prerequisites left:** T-01 human sign-off on filed visual defects; R4-1 vectors (shipped); `source_provenance` reverse-tag highlight parity (emitter shipped; app lookup deferred).

---

## SHIPPED vs STILL OPEN (honest closure)

| Item | Verdict |
|------|---------|
| Cross-host `actual_text_entity_types` | **SHIPPED** all four hosts |
| `report_meta.build_stamp` | **SHIPPED** Python + SU |
| SU `performance_hint` / `total_ms` | **SHIPPED** (was already code-complete) |
| LC/BL CLI stderr | **SHIPPED** |
| Blender GUI perf | **SHIPPED** |
| Corpus CI | **SHIPPED** (existed); FC wired **SHIPPED** |
| Text-merge vectors R4-1 | **SHIPPED** |
| `source_provenance` FC emitter | **SHIPPED** FC/LC/BL sidecar + summary; **SU partial** (summary only) |
| T-01 visual defects FC-2, BL-1, BL-2, FC-1 | **OPEN** |
| LibreCAD 3D text | **N/A** (2D host by design) |
| KettleTag / barcode | **DEFERRED** (app) |

---

*Round 6 closure — 2026-07-04*
