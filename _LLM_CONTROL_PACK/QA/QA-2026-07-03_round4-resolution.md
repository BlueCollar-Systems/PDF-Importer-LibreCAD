# Round 4 Resolution — Agreements (2026-07-03)

**Session:** Round 4 (Reviewer N questions; Reviewer O cross-answers)  
**Rules:** Consensus from anonymous Q&A per `Instructions 0607202613216.txt`  
**Evidence sweep:** 2026-07-03 — verify against disk before implementing

---

## Agreements

| ID | Topic | Decision | Status | Evidence / owners |
|----|-------|----------|--------|-------------------|
| **R4-1** | Cross-language text-merge conformance vectors | Corpus hosts **host-agnostic golden vectors** at `conformance/text_merge_vectors.json` (`input_spans[]` → `expected_merged[]`, optional `effective_scale`, `footprint_class`). **First families:** (a) stacked-fraction merge incl. `2 1/4` false-merge guard, (b) whole-number + fraction spacing (`1` + `1/6` ≠ `11/6`), (c) `VALID_DENOMS` rewrite set. **Consumers:** Python `tests/test_text_merge_conformance.py` (FC canonical, `$BCS_CORPUS_ROOT`); SU `test/text_merge_conformance_test.rb` beside `ruby22_compat_test.rb` as **release gate**. Rotation vectors **deferred phase 2** (SU BOM column path is separate). | **OPEN** | Q-N1, A-O→N1. No SU fraction conformance test today; Python/SU use different merge algorithms (`primitive_extractor.py` vs `text_parser.rb`). |
| **R4-2** | Portable regression anchors (no silent skip) | **(a)** All corpus PDF tests resolve via `BCS_CORPUS_ROOT` + `manifest.json` — remove absolute Desktop/gitignored Tier-1 paths. **(b)** Importer CI emits `::warning::N corpus anchors skipped` on `skipUnless`; **fail** when P0-tagged anchors skip (fraction class, non-PDF gate). **(c)** Corpus adds committable `tier1/web/stacked_fraction_spacing.pdf` for P0 fraction class. `reproduce_fraction_issue.py` / `verify_fraction_fix.py` use same manifest resolution. | **OPEN** | Q-N2, A-O→N2. LC/BL `test_clean_break.py`, FC `test_actual_text_entity_types.py` still hardcode owner paths (verified 2026-07-03). |
| **R4-3** | Corpus CI + importer contract gates | **Corpus:** minimal `.github/workflows/validate.yml` — `validate_contract_schemas.py`, `dependency_audit.py --check-json`, tool pytest smoke. **Per-importer release gate (once host emits any contract field):** (i) run `validate_contract_schemas.py` against smoke `import_report.json`; (ii) run `dependency_audit.py` at build time and attach `bcs.dependency_manifest/1.0` JSON as **release asset**. FC first adopter on next non-`[skip release]` workflow change. | **OPEN** | Q-N3, A-O→N3. `C:\1pdf-test-corpus\.github\workflows\` absent; tools wired to nothing. Trigger from R3-2 now met (FC emits `actual_text_entity_types`). |
| **R4-4** | `actual_text_entity_types` shape lock + rollout | **(a)** FC emitter shape is **provisional canonical** until `validate_contract_schemas.py` passes against real smoke report — adjust emitter or `text_entity_verification.schema.json`, then freeze. **(b)** Report Doctor parser branch lands **now** on website `main` (R3-5), tolerant of missing field; render FC shape when present. **(c)** T-01 human confirmation: FC imports **must** include `actual_text_entity_types` starting next field pass; SU/LC/BL screenshot-primary until emitters ship. **Rollout order locked:** FC (shipped) → LC → BL → SU — supersedes LC-first in J's Round 3 answer; aligns R3-2. | **IN PROGRESS** | Q-N4, A-O→N4. FC at `PDFImporterCore.py:3751` (`entity_type`, `count`, `font_rendered`, `examples`); schema expects richer `requested`/`observed`/`status`. LC/BL/SU/Report Doctor still absent. |
| **R4-5** | SketchUp `import_report.extra` parity floor | Checked-in **`su_report_parity_floor.json`** + `test/import_report_parity_floor_test.rb` against smoke golden report. **Required:** `human_summary`, `scale_crosscheck`, `font_substitution_note` (R2-2), `performance_hint` (R2-8 gap — **highest priority**), `actual_text_entity_types` when text enabled. **Exempt:** `dense_text_glyph_workload` (Poppler semantics), `helper_timings_ms` (optional diagnostic). Floor changes only via deliberate manifest commit (same pattern as `ruby22_compat_test.rb`). | **OPEN** | Q-N5, A-O→N5. SU Ruby tree has **zero** `performance_hint` references; Python emits via `import_report.py:334`. R2-8 SHIPPED for FC/LC/BL ecosystem; SU parity gap acknowledged. |

---

## Round 4 reviewer compliance

| Reviewer | Questions (≥4) | Cross-answers to others (≥3) | Self-answers |
|----------|----------------|------------------------------|--------------|
| **N** | 5 (Q-N1…Q-N5) ✓ | 8 (J5, J6, K1–K5, M1) ✓ | None ✓ |
| **O** | — | 5 (N1–N5) ✓ | None ✓ |

All five Reviewer N questions have cross-answers from O (`QA-2026-07-03_round4-reviewer-o-answers.md`). Reviewer N's cross-answers to J/K/M are captured in Round 3 closure (`QA-2026-07-03_round3-resolution.md`, `QA-2026-07-03_round4-reviewer-n-answers.md`).

---

## Engineering handoff (not Q&A closure)

These require code, not more anonymous answers:

1. **R4-1** — add `text_merge_vectors.json` + Python/SU conformance consumers.
2. **R4-2** — migrate hardcoded test paths; add synthetic fraction PDF; skip visibility in CI.
3. **R4-3** — corpus `validate.yml`; FC release gate for schema + dependency manifest asset.
4. **R4-4** — reconcile FC emitter vs schema; Report Doctor parser; T-01 FC field requirement.
5. **R4-5** — `su_report_parity_floor.json` + test; port `performance_hint` from Python thresholds.
6. **R3 carry-forward** — artifact version stamp (R3-4), Steel Logic bridge (R3-6), T-01 human visual (R3-3).

---

*Round 4 Q&A closure complete. No active anonymous round pending.*
