# Round 7 - Reviewer Q Answers (2026-07-04)

Cross-answers to **Reviewer O** (O-1 through O-7). Complements Reviewer P; adds corpus/field-test and Report Doctor lens.

---

## Q→O-1 - CLI: one contract or two?

**Answer:** Keep the **dual lane through R7** (P agrees). Reviewer Q adds: the compatibility bar is a **shared JSON fixture** checked by `su_batch_cli_test.rb` and `su_cli_test.rb`, not flag spelling alone. P1 merge deletes `su_pdf_cli.rb` only when both tools emit identical `import_report` keys for the same corpus PDF. Until then, document the matrix row in `feature-parity-matrix.md` so app teams do not assume geometry from offline batch.

## Q→O-2 - Embedded images: proof bar

**Answer:** Three-layer proof: (1) **`extra.embedded_images` count** on corpus **T1-12** (≥2 JPEG XObjects), (2) headless `EmbeddedImageExtractor` / batch CLI scan in SU CI, (3) **T-01 screenshot** before marketing parity. JSON alone closes R7-10 engineering; visual closes R7-8.

## Q→O-3 - `source_provenance` sidecar

**Answer:** SU emitter is **done** (R7-3). part tag reverse-tag is **not** done until Steel Logic loads `*_source_provenance.json` and maps object ids → viewport highlight. Summary fields in `import_report` are sufficient for Report Doctor and planning; sidecar ingest is **R7-11 deferred**, not a blocker for v1.0.10 field stub.

## Q→O-4 - `import_contract_ready` stub

**Answer:** **Advisory only** for human release gates. Report Doctor should show `import_contract_ready` prominently (like `performance_hint`) but must **not** block support triage on `ready: false` when T-01 visuals are still open. part tag P0 uses scan + shape lookup, not this flag.

## Q→O-5 - Importers "done"?

**Answer:** **Yes for downstream app scheduling** (R5 bridge, deep links, import_report stub). **No for "ship and forget"** — T-01, FC scale-by-reference, and unified corpus CI remain. Wording for stakeholders: *contract-complete, fidelity-in-progress*.

## Q→O-6 - App Round 7 scope / P0 remainder

**Answer:** v1.0.10 closes **scan intent**, **import_report parse stub**, **steellogic://** deep links. P0 before shop-floor field test: (a) Android/iOS URL intent verification on a physical device, (b) scripted flow doc (scan → W-shape → omni), (c) drop-folder path for `import_report.json` on desktop builds. Tag-sheet UI and full part tag loop stay P1.

## Q→O-7 - Cross-product corpus CI

**Answer:** **Separate repo gates first** (Q agrees with P). Intermediate step: manifest entries that reference shared oracle ids (`GO-14` embedded images) plus `feature_matrix.json` sync in Q&A mirror. Unified job that runs SU batch + app phrase lookup is **P2** — valuable, not R7-critical.

---

## Cross-answers (Round 6 carry-forward)

| Prior | Q view |
|-------|--------|
| R6-9 T-01 | Still **OPEN** — human visual is the only honest close |
| R6-10 part tag | Scan path **SHIPPED**; highlight loop **DEFERRED** |
| R4-2 corpus anchors | **T1-12** closes embedded-image anchor (R7-10) |
| Report Doctor parity | Surface `embedded_images` when `result.images` absent |

---

*Reviewer Q - Round 7 (corpus + Report Doctor cross-review)*
