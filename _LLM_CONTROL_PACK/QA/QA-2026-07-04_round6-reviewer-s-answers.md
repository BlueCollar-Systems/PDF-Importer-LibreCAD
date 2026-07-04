# Round 6 — Reviewer S Cross-Answers (2026-07-04)

Answers to **prior reviewers' OPEN questions** (not S's own Q-S1…Q-S7).

---

## A-S→N1 (R4-1 text-merge conformance vectors)

**Answer: P1, not P0 for T-01.** Stacked-fraction vectors matter for shop fractions on drawings, but T-01's filed defects (BOM QUAN rotation, FC fill color, BL lineweights) are **host-geometry** bugs, not merge-vector gaps. Ship `conformance/text_merge_vectors.json` in the same corpus PR as SU `text_merge_conformance_test.rb`, but do **not** block Round 6 importer contract work on it. Owner: **corpus + SU** (Python consumer already exists in FC tests).

---

## A-S→N3 (R4-3 corpus CI)

**Answer: Corpus CI exists; importer adoption was the gap.** Verified `C:\1pdf-test-corpus\.github\workflows\ci.yml` runs schema + dependency audit. FC CI should clone corpus and run `validate_contract_schemas.py` on every push (implemented this session). Per-importer **dependency manifest release asset** remains P1 — useful for support, not blocking importer contract parity.

---

## A-S→N5 (R4-5 SU parity floor)

**Answer: Yes — extend the floor manifest.** `performance_hint` is **already in SU Ruby** (docs were stale). Floor should add `report_meta.build_stamp` and conditional `actual_text_entity_types`. Exempt `dense_text_glyph_workload` on SU when Poppler path differs. Floor changes = deliberate manifest commit only.

---

## A-S→P2 (R5-2 parts_bootstrap bridge)

**Answer: Defer to app slice.** Importer prerequisite is stable `import_report` with `report_meta.build_stamp` and `actual_text_entity_types` — not inline `parts_candidates[]`. FC `parts_bootstrap.json` sidecar is **R5 engineering**, not Round 6 importer gate.

---

## A-S→Q3 (R5-7 corpus tag fixtures)

**Answer: Agree with fixtures in `tier1/tags/`** but Round 6 priority is **importer contract fields** first. Tag fixtures validate app/website surfaces; wire `validate_contract_schemas.py` for `part` schema when fixtures land. Not blocking importer completeness.

---

*Reviewer S — 5 cross-answers. Compliance: ≥4 required ✓*
