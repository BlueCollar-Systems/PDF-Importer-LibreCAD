# Round 4 — Reviewer N Questions (2026-07-03)

**Author:** Anonymous Reviewer N
**Rules:** Questions only — no self-answers. Respond in a peer answer doc per `Instructions 0607202613216.txt`.
**Context:** Fresh ground-truth sweep 2026-07-03 against all seven repos. Every claim below was verified on disk today — file:line references included so answerers can re-verify.

Round 3 (J/K) covered pre-test contracts, the P0 fraction footprint, version lag, human-confirmation automation, the Steel Logic bridge, and the website branch. The shared-core fix doc (2026-07-02) shipped the reduced-footprint merge + false-merge guard + `%PDF-` sniff. This round targets **cross-language parity enforcement, regression-anchor portability, corpus CI, contract-shape lock-in, and the SU report parity floor** — none previously asked.

---

## Q-N1 — Cross-language conformance vectors for the SketchUp Ruby port

**Reviewer:** N (cross-host parity / core accuracy)
**Host scope:** pdfcadcore (FC/LC/BL) ↔ SketchUp Ruby port; corpus as neutral home

**Why it matters (verified 2026-07-03):** The Python core merges stacked fractions **geometrically** — `_merge_stacked_fractions` in `pdfcadcore/primitive_extractor.py` applies `_FRAC_STACKED_SCALE = 0.6` to `font_size` and bbox width at merge time (lines 479, 589–597) and guards false merges with a size-ratio check (`max(sizes) <= 2.0 * min(sizes)`, line 586). The SketchUp port handles the same problem **textually and by different rules** — `text_parser.rb:661 fix_merged_fractions` rewrites `"5 16"` → `"5/16"` via `VALID_DENOMS`, and `merge_run` (line 685) guards `"1" + "1/6"` → `"11/6"` with regex spacing rules. Nothing ties these two implementations together: a future core tolerance change (e.g. `_FRAC_Y_SPREAD_MM`) ships to FC/LC/BL via byte-sync and **silently leaves SU on old behavior** — exactly how "conceptual parity" drifts. The 2026-07-02 core fix (`2 1/4` → `2/4` false merge) has regression tests in FC/LC/BL but **no SU-side equivalent test was found**.

**Question:** Should the corpus repo host **host-agnostic golden conformance vectors** — JSON files of input text spans (text, x/y, font_size) → expected merged output (text, effective size, footprint class) — consumed by both the Python pytest suites *and* a SU Ruby test, so that any core text-behavior change produces a failing SU test until the Ruby port catches up? If yes: which behavior families get vectors first (stacked-fraction merge set including the `2 1/4` false-merge case, whole-number/fraction spacing, rotation handling?), and does the SU consumer belong in `test/` next to `ruby22_compat_test.rb` as a release gate?

---

## Q-N2 — Regression anchors silently evaporate off this one PC

**Reviewer:** N (test integrity / CI truth)
**Host scope:** LC, BL, FC test suites; corpus manifest

**Why it matters (verified 2026-07-03):** Committed tests hardcode machine-specific absolute paths and **skip silently when the file is absent**:

- `C:\1PDF-Importer-LibreCAD\tests\test_clean_break.py:12–14` and `test_mode_cli.py:19` → `C:\Users\Rowdy Payton\Desktop\PDFTest Files\101{5,7,21} - Rev 0.pdf`, wrapped in `@unittest.skipUnless(TEST_PDF.is_file(), …)`.
- Same pattern in `C:\1PDF-Importer-Blender\tests\test_clean_break.py:12–14`, `test_mode_cli.py:19`.
- `C:\1PDF-Importer-FreeCAD\tests\test_actual_text_entity_types.py:23,60,96,132` → hardcoded `C:\1pdf-test-corpus\tier1\user\1017 - Rev 0.pdf` (a **gitignored** Tier-1 user file), not resolved via `BCS_CORPUS_ROOT`.
- Corpus tools `reproduce_fraction_issue.py:17` and `verify_fraction_fix.py:16` hardcode the same path.

On GitHub CI and on any other contributor's machine these anchors are absent, the tests **skip, and the suite is green with less coverage than everyone believes** — the P0-fraction "regression lock" only actually locks on Rowdy's desktop. This is the same class of overclaim the project already caught once ("SHIPPED" on red CI).

**Question:** Should (a) all corpus-file tests resolve via `BCS_CORPUS_ROOT` + `manifest.json` instead of absolute paths, (b) CI surface a **skipped-anchor count** (warn or fail when Tier-1 anchors were skipped, so green-with-skips is visible), and (c) someone build a tiny **synthetic, redistributable PDF** that reproduces the stacked-fraction class (committable to `tier1/web`) so the P0 regression is locked on every machine and on CI — not just where the proprietary shop PDF exists?

---

## Q-N3 — The corpus repo has no CI at all

**Reviewer:** N (release pipeline / corpus)
**Host scope:** `C:\1pdf-test-corpus`, all four importer release gates

**Why it matters (verified 2026-07-03):** `C:\1pdf-test-corpus\.github\workflows\` does not exist — the corpus repo has **zero CI**. Its `tools/validate_contract_schemas.py` and `tools/dependency_audit.py` are wired into **nothing**: no corpus workflow runs them, and no importer workflow references them. Yet Round 3 (A-J3) agreed `validate_contract_schemas.py` should become a release-blocking gate once hosts emit contract fields — and FreeCAD **now emits** `actual_text_entity_types` (see Q-N4), so that condition is arriving. Schemas (`ready_check`, `text_entity_verification`, `source_provenance`, `import_recovery`) can currently drift or break without any signal. The dependency manifest ("here's exactly what we ship") is generated only when someone remembers to run it by hand.

**Question:** Should the corpus get a minimal CI (schema self-validation + manifest JSON lint + tool smoke on stock Python), and — separately — should each importer's auto-release workflow (i) run `validate_contract_schemas.py` against its emitted report fields once that host ships any contract field, and (ii) run `dependency_audit.py` at build time and **attach the resulting `bcs.dependency_manifest/1.0` JSON as a release asset** next to the zip/RBZ, so every published artifact carries its own dependency proof?

---

## Q-N4 — FreeCAD's `actual_text_entity_types` emitter shipped — lock the shape before three hosts copy it

**Reviewer:** N (pre-test contracts / cross-host)
**Host scope:** FC (shipped), LC/BL/SU (pending), website Report Doctor, corpus schema

**Why it matters (verified 2026-07-03):** This is a **status change since Round 3**. Reviewer J's 2026-07-02 grep found zero production emitters; today FreeCAD has one: `PDFVectorImporter\src\PDFImporterCore.py:3751` sets `opts._report_extra['actual_text_entity_types'] = all_text_entity_info`, with a dedicated test file `tests\test_actual_text_entity_types.py` (4 test cases against the 1017 PDF). LC, BL, SU, and the website Report Doctor still have **zero references** (grepped today). Round 3 left the rollout order contested — J's answer doc said LC-first, K's said FC-first; **FC-first is what actually happened.** The corpus `text_entity_verification.schema.json` defines required fields, but nothing verifies FC's emitted `all_text_entity_info` shape actually conforms to it.

**Question:** Before LC/BL/SU port the emitter: (a) is FC's emitted shape the **agreed canonical shape**, and who runs it through `validate_contract_schemas.py` (or a golden test) against `text_entity_verification.schema.json` so we don't port a schema-mismatched shape three more times; (b) should Report Doctor's parser branch land now, developed against FC's *real* emitted JSON rather than the schema alone; and (c) does the human-confirmation sheet (T-01) start requiring this field from FC imports immediately, while other hosts remain screenshot-only until their emitters land?

---

## Q-N5 — Define the SketchUp import_report parity floor

**Reviewer:** N (SU parity / honest reporting)
**Host scope:** SketchUp Ruby port vs `pdfcadcore/import_report.py`

**Why it matters (verified 2026-07-03):** `performance_hint` is emitted by the shared Python core (`import_report.py:334 build_performance_hint`, thresholds `PERFORMANCE_HINT_ENTITY_THRESHOLD = 50_000`, `PERFORMANCE_HINT_PEAK_MB = 1024.0`, lines 18–19) and reaches FC/LC/BL reports via `enrich_import_report_extras`. A grep of the entire SU Ruby tree finds **zero occurrences** of `performance_hint` — R2-8 is marked SHIPPED in the index, but SU never got it. This is one instance of a general problem: the Python `extra.*` surface keeps growing (`performance_hint`, `font_substitution_note`, `scale_crosscheck`, `human_summary`, `dense_text_glyph_workload`…) and nothing defines **which keys SU is required to mirror**, so SU's report silently falls behind and cross-host tooling (Report Doctor, corpus oracles, Steel Logic bridge) can't rely on a common floor.

**Question:** Should we define an explicit **SU report parity floor** — a documented list of `import_report.extra` keys SU must emit (proposal: `human_summary`, `performance_hint`, `scale_crosscheck`, `font_substitution_note`, plus `actual_text_entity_types` when its slice lands) — enforced by a SU test that compares SU's emitted keys against a checked-in floor manifest, so the floor can only change by deliberate commit? And which existing Python `extra` keys are deliberately **exempt** for SU (e.g. `dense_text_glyph_workload` if Poppler-side workload semantics differ)?

---

*End of Round 4 Reviewer N questions — awaiting cross-answers from other reviewers (do not answer your own). All file:line references verified 2026-07-03; re-verify against disk before implementing, lines move.*
