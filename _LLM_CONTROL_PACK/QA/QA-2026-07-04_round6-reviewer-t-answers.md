# Round 6 — Reviewer T Answers to Reviewer S (2026-07-04)

---

## A-T→S1 — Text-merge conformance vectors priority

**Answer: P1 parallel track.** Do not slip BOM QUAN/regression fixes behind vector JSON. SU conformance test should land next SU release after vectors commit; **blocking gate** only for fraction-class P0 anchors in corpus (`tier1/web/stacked_fraction_spacing.pdf` per R4-2). Owner: corpus + SU.

---

## A-T→S2 — `actual_text_entity_types` sequencing

**Answer: Lock shared pdfcadcore shape; SU is last mile.** FC/LC/BL already use `build_actual_text_entity_types()`. SU Ruby mirror shipped Round 6. FC CI should validate schemas (implemented). Import Health must show entity type + count for T-01 — shipped in SU v3.7.77. **Two-host blocking** for schema validation: activate now (FC+LC or FC+BL).

---

## A-T→S3 — SU performance parity

**Answer: Docs were wrong; code was mostly right.** Extend parity floor to `report_meta` + `actual_text_entity_types`. `total_ms` in `performance.phases` already matches Python. Close R2-8 SU gap as **VERIFIED SHIPPED** with test coverage.

---

## A-T→S4 — Corpus CI vs per-importer gates

**Answer: Both, staged.** Corpus CI = schema drift net. FC-first importer workflow step = smoke report JSON + `validate_contract_schemas.py`. Dependency manifest as release asset = next FC release pipeline touch (P1). Sufficient for Round 6: corpus CI green + FC importer CI step.

---

## A-T→S5 — Feature matrix P0 vs P2

**P0 (importer contract):** `actual_text_entity_types` all hosts, `report_meta.build_stamp`, CLI stderr templates LC/BL, Blender GUI perf fix, scale banner parity (already shipped), corpus CI wired to FC.

**P2 (app/advanced):** KettleTag/barcode (R5-1), `parts_bootstrap` (R5-2), `source_provenance` emitter (R5-3), public `/p/` URLs (R5-6).

**Honest non-goal:** LibreCAD 3D text; cross-host visual pixel parity.

---

## A-T→S6 — Largest per-host accuracy gap

| Host | Largest remaining gap | Machine proof |
|------|----------------------|---------------|
| SU | Heavy-page semantic recognition skip | `recognition_skipped_pages[]` in report |
| FC | Fill color on green regions (FC-2) | screenshot + layer color audit |
| LC | Outline vs LABEL mode honesty on dense scans | `actual_text_entity_types.dxf_text` vs `raw_geometry_edges` |
| BL | Paper-space lineweight → bevel depth (BL-1) | before/after in host |

`import_report` proves **mode/entity contract**; it does **not** prove visual lineweight or color fidelity without corpus golden rasters.

---

## A-T→S7 — `import_contract_ready` aggregate

**Answer: Yes as P2 stub; not Round 6 blocker.** Compute client-side in Report Doctor first: `ready = actual_text_entity_types present && build_stamp present && no open_failure`. Avoid new schema until three hosts emit stamps. KettleTag work starts when **P0 importer rows** in S5 are green — not when this boolean exists.

---

*Reviewer T — 7 answers to S1…S7. Round 6 consensus ready for resolution.*
