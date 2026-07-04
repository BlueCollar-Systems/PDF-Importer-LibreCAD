# Round 7 Resolution — Agreements (2026-07-04)

**Session:** Reviewer O questions; Reviewer P answers; engineering SU v3.7.79 + Steel Logic v1.0.10

---

## Agreements

| ID | Topic | Decision | Status | Owner |
|----|-------|----------|--------|-------|
| **R7-1** | SU batch CLI | `tools/su_batch_cli.rb` offline pipeline: preflight, parse, `import_report.json`, optional geometry sidecar. `tools/sketchup_batch_import.rb` documents full geometry via `-RubyStartup`. In-extension `cli.rb` remains Ruby-2.2-safe (dig removed). | **SHIPPED** | SU v3.7.79 |
| **R7-2** | SU embedded images | `ImageExtractor.extract_and_place` in host pipeline; `EmbeddedImageExtractor` for offline asset scan; report fields `extra.embedded_images` + paths. | **SHIPPED** | SU v3.7.79 |
| **R7-3** | SU `source_provenance` sidecar | `source_provenance.rb` writes `*_source_provenance.json`; summary includes `sidecar_path`. | **SHIPPED** | SU v3.7.79 |
| **R7-4** | `import_contract_ready` stub | Diagnostics aggregate in `extra.import_contract_ready` (advisory; Report Doctor may recompute). | **SHIPPED** | SU v3.7.79 |
| **R7-5** | App barcode / QR (R5-1) | Omni-Box scan button + `mobile_scanner` on Android/iOS; desktop shows guidance. | **SHIPPED** | Steel Logic v1.0.10 |
| **R7-6** | App `import_report` stub (R5-2) | `ImportReportIngestion` parses `bcs.import_report/1.1`; parts_bootstrap optional read. | **SHIPPED** | Steel Logic v1.0.10 |
| **R7-7** | App deep links (R5-6) | `app_links` + `DeepLinkHandler`; `steellogic://shape/W10x22` opens shape search. | **SHIPPED** | Steel Logic v1.0.10 |
| **R7-8** | T-01 human visual | FC-2 fill, BL-1 lineweight, BL-2, FC-1 still need in-host verification. | **OPEN** | human |
| **R7-9** | CLI merge (O-1) | Consolidate `su_pdf_cli.rb` + `cli.rb` flags in P1; contract test is compatibility bar. | **OPEN** | SU |
| **R7-10** | Embedded image corpus proof | **T1-12** `tier1/web/embedded_images_regression.pdf` (≥2 embedded JPEGs, CC0 generated). | **SHIPPED** | corpus |
| **R7-11** | part-tag full loop | Scan → sidecar lookup → highlight in host — needs app + importer field test. | **DEFERRED** | app |

---

## SHIPPED vs STILL OPEN (honest)

| Item | Verdict |
|------|---------|
| SU offline batch CLI + SketchUp batch doc | **SHIPPED** v3.7.79 |
| SU embedded Image XObject import | **SHIPPED** v3.7.79 |
| SU `source_provenance` sidecar file | **SHIPPED** v3.7.79 |
| `import_contract_ready` stub | **SHIPPED** SU |
| App scan / import_report stub / deep links | **SHIPPED** v1.0.10 |
| T-01 visual defects | **OPEN** |
| `parts_bootstrap` sidecar (all hosts) | **DEFERRED** |
| CLI single contract merge | **OPEN** P1 |
| Cross-product corpus CI | **OPEN** P2 |

---

## Importer phase "done"?

**For app planning: yes.** Contract fields, CLI offline analysis, embedded images, and provenance sidecar are shippable.

**For claiming perfect fidelity: no.** T-01 visual sign-off still open (R7-10 corpus anchor closed via T1-12).

---

*Round 7 closure — 2026-07-04*
---

## Round 7 cross-answer matrix

| Reviewer | Role |
|----------|------|
| O | Questions O-1..O-7 (importer + app kickoff) |
| P | Answers O-1..O-7 + prior OPEN table |
| Q | Cross-answers O-1..O-7 (corpus, field test, Report Doctor) |

**Matrix complete for Round 7.**


