# Remaining Tasks — Progress (2026-07-04 session)

Append-only progress against `Remaining Tasks.txt`. Original file preserved.

## Summary

| Status | Count |
|--------|-------|
| COMPLETED | 10 |
| PARTIAL | 6 |
| BLOCKED/SKIPPED | 12+ |

---

## COMPLETED

- [x] **R5-2 / parts_bootstrap row extraction (FC)** — `extract_bootstrap_rows()` in `pdfcadcore/parts_bootstrap.py`; wired in `PDFImporterCore.write_import_report`; per-line page tracking via `_bootstrap_text_items`. **FC v4.0.60**
- [x] **Corpus tier1/tags fixtures (R5-7)** — `schemas/parts_bootstrap.schema.json`, `schemas/part.schema.json`, `tier1/tags/sample_parts_bootstrap.json`, `tier1/tags/part_record_golden.json`; validator extended (6 schemas)
- [x] **R8-A semantic members (FC planning + host hook)** — `aisc_profiles.py`, `semantic_members.py` with `plan_semantic_members` + `create_semantic_members` (W/L cross-sections); gated by `model3d_semantic` default OFF. **FC v4.0.60**
- [x] **Report Doctor Tags tab (R5-7)** — `report-doctor.html/js`: bootstrap upload/paste, piece-mark table, copy tag URL (`/p/<uuid>`)
- [x] **App parts_bootstrap rows ingestion (R5-2)** — `import_report_ingestion.dart` accepts `rows[]` + `source_pdf`; part tag + Report Doctor screen shipped
- [x] **pdfcadcore sync** — manifest regenerated; FC→LC/BL sync ALL IN SYNC; **LC v1.0.54**, **BL v1.0.59**
- [x] **SU extrude_depth dialog** — already present in `advanced_html` (`extrude_depth_mm` field + callback); verified on disk
- [x] **Phase 1 ship** — all repos committed and pushed (see Gate results)
- [x] **FC CI fix** — semantic member test skips when AISC catalog absent (`7daf0a5`)
- [x] **Cross-host corpus CI gate** — LC/BL workflows now validate corpus schemas + conformance vectors

---

## PARTIAL

- [ ] **R8-A full runtime verification** — unit tests pass; FreeCAD GUI smoke + T-01 visual not run this session
- [ ] **R8-A port to BL/SU (R8-C/R8-D)** — FC only
- [ ] **parts_bootstrap on SU/LC/BL import pipelines** — pdfcadcore modules synced; host emitters not wired in LC/BL/SU import paths
- [ ] **part-tag full loop (R5-1/R5-3)** — part tag + Report Doctor shipped; scan→lookup reverse-highlight UI not built
- [ ] **R7-9 SU CLI merge** — analysis complete; shared contract test + BatchPipeline unification not merged
- [ ] **Cross-product corpus CI (P2)** — LC/BL added; SU/FC corpus token still owner-only

---

## BLOCKED / SKIPPED

- [ ] **T-01 human visual sign-off** — cannot automate (per instructions)
- [ ] **PE code signing / SmartScreen docs** — owner parked until launch
- [ ] **CORPUS_READ_TOKEN secret** — owner-only (~2 min)
- [ ] **Public /p/ pages (R5-6)** — website static JSON route not implemented
- [ ] **Corpus baselines for 7 PDFs** — `generate_corpus_baselines.rb --update` not run (time/host dependent)
- [ ] **FC-1 dense-dimension fix** — not confirmed this session
- [ ] **BL-2 large-file batching** — not started
- [ ] **Scale-by-Reference parity (SU/LC/BL)** — FC-only today
- [ ] **Import Health UI (FC/LC/BL)** — not started
- [ ] **Omni engine expansion / golden vectors** — deferred app backlog
- [ ] **Automated visual regression tooling** — research tier
- [ ] **8.6 GB Firebase dedup / git history rewrite** — owner coordinated force-push window

---

## Gate results (repos touched)

| Repo | Commit | Push | CI / Release |
|------|--------|------|--------------|
| FC | `7daf0a5` (v4.0.60 chain: a3ff10c→9939c3f→e816b65→7daf0a5) | pushed | CI pending; auto-release pending v4.0.60 |
| LC | `708946a` v1.0.54 | pushed | CI pending; auto-release pending v1.0.54 |
| BL | `66455d1` v1.0.59 | pushed | CI pending; auto-release pending v1.0.59 |
| Corpus | `20660f6` | pushed | schema gate OK locally |
| Website | `e268ec3` Tags tab | pushed | up to date |
| App | `0d634c4` (+ `17008ba` part tag | pushed | flutter analyze clean; 21 targeted tests pass |

---

*Updated: 2026-07-04 ship session (e44a8d4a follow-up).*
