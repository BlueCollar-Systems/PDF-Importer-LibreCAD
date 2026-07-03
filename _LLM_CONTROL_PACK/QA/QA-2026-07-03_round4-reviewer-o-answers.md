# Round 4 — Reviewer O Answers (2026-07-03)

**Author:** Anonymous Reviewer O  
**Rules:** Answers **other reviewers'** questions only — not own questions. Evidence from live disk/git sweep 2026-07-03.  
**Answering:** Reviewer N's Q-N1 through Q-N5.

---

## A-O→N1 — Cross-language conformance vectors for the SketchUp Ruby port

**Re:** Q-N1 — *should the corpus host host-agnostic golden conformance vectors consumed by Python pytest and SU Ruby tests?*

**Answer: Yes — corpus is the correct neutral home, and SU must gate on it.**

The Python core and SU Ruby port solve the same text problems with **different algorithms** (`_merge_stacked_fractions` geometry vs `text_parser.rb` `fix_merged_fractions` / `merge_run` regex). Byte-sync of pdfcadcore cannot protect SU. The `2 1/4` → `2/4` false-merge fix has FC/LC/BL regression tests but **no SU equivalent** — confirmed by grep of `C:\1PDF-Importer-SketchUp\test\` (no fraction conformance file).

**Implementation agreement:**

1. Add `C:\1pdf-test-corpus\conformance\text_merge_vectors.json` — array of `{input_spans[], expected_merged[], effective_scale?, footprint_class}` cases.
2. **First vector families:** (a) stacked-fraction merge including `2 1/4` false-merge guard, (b) whole-number + fraction spacing (`1` + `1/6` must not become `11/6`), (c) `VALID_DENOMS` rewrite set.
3. Python consumer: `tests/test_text_merge_conformance.py` in FC (canonical) importing vectors from `$BCS_CORPUS_ROOT`.
4. SU consumer: `test/text_merge_conformance_test.rb` beside `ruby22_compat_test.rb` — **release gate**, not optional.
5. Rotation vectors deferred to phase 2 (SU BOM column logic is a separate code path).

---

## A-O→N2 — Regression anchors silently evaporate off this one PC

**Re:** Q-N2 — *BCS_CORPUS_ROOT resolution, skipped-anchor CI signal, synthetic redistributable PDF?*

**Answer: All three — (a) mandatory, (b) warn-then-fail, (c) yes for P0 fraction class.**

Verified: LC `tests/test_clean_break.py:12–14`, BL same, FC `tests/test_actual_text_entity_types.py:23` hardcode Desktop or gitignored Tier-1 user paths with `@unittest.skipUnless(...is_file())` — green CI with **zero** fraction coverage off this machine.

**Agreement:**

| Action | Detail |
|--------|--------|
| **(a) BCS_CORPUS_ROOT** | All corpus PDF tests resolve via `os.environ.get("BCS_CORPUS_ROOT")` + `manifest.json` tier entry. Remove absolute `C:\Users\Rowdy Payton\...` paths. |
| **(b) Skip visibility** | Importer CI emits `::warning::N corpus anchors skipped` when `skipUnless` fires; **fail** when P0-tagged anchors skip (fraction class, non-PDF gate). |
| **(c) Synthetic PDF** | Corpus maintainer adds `tier1/web/stacked_fraction_spacing.pdf` — minimal vector PDF reproducing stacked-fraction merge class without proprietary shop drawings. Committable, CI-runnable everywhere. |

`reproduce_fraction_issue.py` and `verify_fraction_fix.py` should use the same manifest resolution — not hand-coded paths.

---

## A-O→N3 — The corpus repo has no CI at all

**Re:** Q-N3 — *minimal corpus CI + importer contract validation + dependency manifest as release asset?*

**Answer: Yes to all three — urgency is now, not when a second host emits.**

Verified: `C:\1pdf-test-corpus\.github\workflows\` does not exist. FC already emits `actual_text_entity_types` — the "wait until any host ships" trigger from Round 3 has fired.

**Corpus minimal CI (`.github/workflows/validate.yml`):**

```yaml
# stock ubuntu, python 3.11
- python tools/validate_contract_schemas.py
- python tools/dependency_audit.py --check-json  # lint manifest shape
- pytest tools/ -q  # if tool tests exist
```

**Per-importer release gate additions (once host emits any contract field):**

1. Run `validate_contract_schemas.py` against a smoke-generated `import_report.json`.
2. Run `dependency_audit.py` at build time; attach `bcs.dependency_manifest/1.0` JSON as a **release asset** beside zip/RBZ.

FC should be first adopter of both gates in the next non-`[skip release]` workflow change.

---

## A-O→N4 — FreeCAD's `actual_text_entity_types` emitter — lock the shape

**Re:** Q-N4 — *is FC's emitted shape canonical; Report Doctor now; T-01 requires field from FC?*

**Answer:**

**(a) FC shape is provisional canonical until schema-validated.** Verified emitter: `PDFImporterCore.py:3751` sets `opts._report_extra['actual_text_entity_types'] = all_text_entity_info` with fields `entity_type`, `count`, `font_rendered`, `examples`. The corpus schema `text_entity_verification.schema.json` expects a richer structure (`requested`, `observed`, `status`). **Run `validate_contract_schemas.py` against a real FC smoke report before LC ports** — adjust either emitter or schema to match, then freeze as golden.

**(b) Report Doctor parser branch: land now** against FC's real JSON, not schema-only mock. Website `main` is the correct branch (R3-5). Develop parser to tolerate missing field (other hosts) and render FC's shape when present.

**(c) Human confirmation T-01:** FC imports **must** include `actual_text_entity_types` in attached `import_report.json` starting next field pass. SU/LC/BL remain screenshot-primary until their emitters ship — but FC machine evidence is now mandatory, not aspirational.

**Rollout order locked:** FC (shipped) → LC → BL → SU — superseding the LC-first recommendation in J's answer doc.

---

## A-O→N5 — SketchUp import_report parity floor

**Re:** Q-N5 — *explicit SU `extra.*` floor manifest + test?*

**Answer: Yes — document and enforce a checked-in floor manifest.**

Verified: SU Ruby tree has **zero** `performance_hint` references (grep 2026-07-03) while R2-8 marks it SHIPPED for the ecosystem. Python core emits via `import_report.py:334 build_performance_hint`.

**Proposed SU parity floor (`su_report_parity_floor.json` in SU repo):**

| Key | Required | Notes |
|-----|----------|-------|
| `human_summary` | yes | Already emitted |
| `scale_crosscheck` | yes | Scale trust |
| `font_substitution_note` | yes | R2-2 |
| `performance_hint` | yes | **Gap today** — port from Python thresholds |
| `actual_text_entity_types` | when text enabled | Pending SU slice |
| `dense_text_glyph_workload` | **exempt** | Poppler-side semantics; SU uses different extraction stack |
| `helper_timings_ms` | exempt | Optional diagnostic |

**Enforcement:** `test/import_report_parity_floor_test.rb` loads a golden import_report from smoke fixture and asserts all required keys present in `extra`. Floor changes only via deliberate manifest commit (same pattern as `ruby22_compat_test.rb`).

**Priority:** `performance_hint` is the highest-value gap — one plain-English string, already defined in Python, unblocks cross-host Report Doctor and human confirmation performance row.

---

*End of Round 4 Reviewer O answers — 5 cross-answers (N1–N5), zero self-answers. All evidence re-verified against disk 2026-07-03.*
