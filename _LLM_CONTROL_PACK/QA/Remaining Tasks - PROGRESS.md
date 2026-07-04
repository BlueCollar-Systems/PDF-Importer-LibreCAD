# Remaining Tasks — Progress (2026-07-04 session)



Append-only progress against `Remaining Tasks.txt`. Original file preserved.



## Summary



| Status | Count |

|--------|-------|

| COMPLETED | 10 |

| PARTIAL | 6 |

| BLOCKED/SKIPPED | 12+ |



---



## COMPLETION PASS DELTA — 2026-07-04 late



- [x] **R7-9 SU CLI contract merge** — `tools/su_pdf_cli.rb` is now a compatibility wrapper over the unified extension CLI; focused SU CLI/report tests pass.

- [x] **parts_bootstrap on SU/LC/BL import pipelines** — SU in-host + CLI, LC report writer, BL headless writer, and BL add-on writer now emit `parts_bootstrap.json` and `import_report.extra.parts_bootstrap` when reports are written.

- [x] **Website Report Doctor bootstrap support** — fixed duplicate `bootstrap-file` id; Report Doctor reads inline `extra.parts_bootstrap` or uploaded sidecar and includes row/sidecar evidence in support summaries.

- [x] **Steel Logic Part Tracking bootstrap loop** — `Part Tracking now loads `bcs.parts_bootstrap/1.0`, resolves piece marks and `/p/<part_id>` URLs, generates tag URLs, and still prefers source-provenance bbox hits.

- [x] **Corpus baselines generated** — `tools/generate_corpus_baselines.rb --update` wrote current baselines; one known heavy PDF stayed warn-only after the 300s guard.

- [x] **Verification sweep** — FC 135 passed / 1 skipped; LC 63 passed + 11 subtests; BL 63 passed + 10 subtests; SU focused gates passed; app `flutter analyze` clean and full `flutter test` passed; corpus schemas/conformance passed; sync check ALL IN SYNC.



Remaining non-human backlog after this pass: semantic steel solids v2/cross-host port, Scale-by-Reference parity, Import Health parity, automated visual regression tooling, public `/p/` pages/tag sheets, Omni/app expansion, and packaging/release hardening.



## COMPLETED



- [x] **R5-2 / parts_bootstrap row extraction (FC)** — `extract_bootstrap_rows()` in `pdfcadcore/parts_bootstrap.py`; wired in `PDFImporterCore.write_import_report`; per-line page tracking via `_bootstrap_text_items`. **FC v4.0.60**

- [x] **Corpus tier1/tags fixtures (R5-7)** — `schemas/parts_bootstrap.schema.json`, `schemas/part.schema.json`, `tier1/tags/sample_parts_bootstrap.json`, `tier1/tags/part_record_golden.json`; validator extended (6 schemas)

- [x] **R8-A semantic members (FC planning + host hook)** — `aisc_profiles.py`, `semantic_members.py` with `plan_semantic_members` + `create_semantic_members` (W/L cross-sections); gated by `model3d_semantic` default OFF. **FC v4.0.60**

- [x] **Report Doctor Tags tab (R5-7)** — `report-doctor.html/js`: bootstrap upload/paste, piece-mark table, copy tag URL (`/p/<uuid>`)

- [x] **App parts_bootstrap rows ingestion (R5-2)** — `import_report_ingestion.dart` accepts `rows[]` + `source_pdf`; Part Tracking + Report Doctor screen shipped

- [x] **pdfcadcore sync** — manifest regenerated; FC→LC/BL sync ALL IN SYNC; **LC v1.0.54**, **BL v1.0.59**

- [x] **SU extrude_depth dialog** — already present in `advanced_html` (`extrude_depth_mm` field + callback); verified on disk

- [x] **Phase 1 ship** — all repos committed and pushed (see Gate results)

- [x] **FC CI fix** — semantic member test skips when AISC catalog absent (`7daf0a5`)

- [x] **Cross-host corpus CI gate** — LC/BL workflows now validate corpus schemas + conformance vectors



---



## PARTIAL



- [ ] **R8-A full runtime verification** — unit tests pass; FreeCAD GUI smoke + T-01 visual not run this session

- [ ] **R8-A port to BL/SU (R8-C/R8-D)** — FC only

- [x] **parts_bootstrap on SU/LC/BL import pipelines** — closed in completion pass; all host report writers now emit sidecar + report summary

- [x] **Part Tracking sidecar/tag lookup loop (R5-1/R5-3 app slice)** — bootstrap sidecar + `/p/<part_id>` lookup closed; camera UI and reverse-highlight remain advanced UI work

- [x] **R7-9 SU CLI merge** — compatibility wrapper over unified extension CLI; focused gates pass

- [ ] **Cross-product corpus CI (P2)** — LC/BL added; SU/FC corpus token still owner-only



---



## BLOCKED / SKIPPED



- [ ] **T-01 human visual sign-off** — cannot automate (per instructions)

- [ ] **PE code signing / SmartScreen docs** — owner parked until launch

- [ ] **CORPUS_READ_TOKEN secret** — owner-only (~2 min)

- [ ] **Public /p/ pages (R5-6)** — website static JSON route not implemented

- [x] **Corpus baselines for 7 PDFs** — generated in completion pass; one known heavy PDF stayed warn-only after timeout guard

- [ ] **FC-1 dense-dimension fix** — not confirmed this session

- [x] **BL-2 large-file batching** — verified already present/tested via `batch_open_curves` multi-spline curve batching

- [ ] **Scale-by-Reference parity (SU/LC/BL)** — FC-only today

- [ ] **Import Health UI (FC/LC/BL)** — not started

- [ ] **Omni engine expansion / golden vectors** — deferred app backlog

- [ ] **Automated visual regression tooling** — research tier

- [ ] **8.6 GB Firebase dedup / git history rewrite** — owner coordinated force-push window



---



## Gate results (repos touched)



| Repo | Commit | Push | CI / Release |

|------|--------|------|--------------|

| FC | `97f97d7` (ship chain → `7daf0a5` CI fix) | pushed | **CI pass; v4.0.60 released** |

| LC | `042845f` v1.0.54 | pushed | **CI pass; v1.0.54 released** |

| BL | `c2596a3` v1.0.59 | pushed | **CI pass; v1.0.59 released** |

| Corpus | `47f4975` | pushed | schema gate OK |

| Website | `852b72c` QA mirror (`e268ec3` Tags tab) | pushed | up to date |

| App | `d53edf3` (+ `17008ba` Part Tracking | pushed | flutter analyze clean; 21 targeted tests pass |



---



*Updated: 2026-07-04 ship session (e44a8d4a follow-up).*

