# Round 4 — Engineering progress + defect flag (2026-07-03)

**Author:** Anonymous Reviewer N
**Scope:** Post-answer verification sweep — checked every open item across Rounds 1–4 against disk, implemented the unclaimed agreed slices, and flagged one defect in in-flight work. Timestamp ~14:30 UTC.

---

## ⚠️ DEFECT FLAG — FC `actual_text_entity_types` emitter re-imports every page (uncommitted work)

**For the worker with the dirty FC/LC/BL trees** (shared-core fraction + emitter changes, uncommitted as of this sweep):

`PDFVectorImporter\src\PDFImporterCore.py` (report-writing phase, ~lines 3739–3754): to collect text-entity info, the new code calls

```python
_, page_text_info = import_pdf_page(pdf_path, page_num=p, opts=opts, autofit=False)
```

**inside the report phase, for every page, after the main import already ran.** `import_pdf_page` (line 2282) calls `_ensure_doc()` and `_import_pdf_page_inner(...)` — it **creates entities in the active FreeCAD document**. Net effect: every import is performed twice — double geometry in the user's document and ~2× import time. `tests\test_actual_text_entity_types.py` won't catch it because it only asserts the info dict, not document entity counts.

**Fix direction:** capture `page_text_info` from the main import loop's existing calls (thread it through to the report phase) instead of re-importing. Add a regression assert: object count in the FC document after import == single-import count. **Please do not commit/push the emitter until this is resolved.**

---

## Verified: what concurrent workers already addressed today

| Item | Status | Evidence |
|------|--------|----------|
| Q-N1 conformance vectors | **Built** (corpus `conformance-vectors/`, Python + SU Ruby consumers) | `test_conformance_vectors.py` → `python: pass`, `sketchup: pass` after repairs below |
| Q-N2a BCS_CORPUS_ROOT in tests | **Done** in FC/LC/BL test files (uncommitted) | LC/BL `test_clean_break.py:12`, FC `test_actual_text_entity_types.py:23` |
| Q-N3 corpus CI | **Built** (`.github/workflows/ci.yml`) | repaired, see below |
| Q-N5 parity floor manifest | **Drafted** (`sketchup-report-parity-floor.json`, `validate_sketchup_parity.rb`) | corpus root |
| Round 3 closure | **Done** — `QA-2026-07-03_round3-resolution.md` R3-1…R3-10 | Reviewer O |
| Human-confirmation version addendum | **Updated 2026-07-03** | SU mirror addendum |

## Repaired: broken states found during verification (all verified green after repair)

1. **`tools/reproduce_fraction_issue.py` + `tools/verify_fraction_fix.py` were syntax-broken** (IndentationError at the new `BCS_CORPUS_ROOT` lines) — both fixed, `py_compile` clean. Intent preserved exactly.
2. **Corpus `ci.yml` would have been red on its first run** — required manifest keys (`version`, `created`, `corpus_root`, `categories`) that don't exist in the real `manifest.json` (`entries`, `updated`, `default_root`, …), and required `tier1/user` + `tier2/regression` dirs that are gitignored/absent on a fresh clone. I corrected both checks to the real repo shape; the owning session has since rewritten `ci.yml` into a single-job version (plain JSON lint, no gitignored-dir requirement, dependency-manifest emission) that resolves the same blockers — that rewrite is now the live version. One thing for the owner to confirm on first CI run: `conformance-vectors/test_conformance_vectors.py` behavior when `BCS_FREECAD_REPO` / SU repo are absent on the runner (it should skip, not fail).
3. **Conformance vector `simple_fraction_concatenated` had a stale expectation** (`font_size 3.78`, unreduced) — the core applies `_FRAC_STACKED_SCALE = 0.6` in Pattern A too (`primitive_extractor.py:589–597`). Vector corrected to `2.268` / `stacked_fraction_reduced`; full vector suite now passes for **both** Python and SketchUp implementations.

## Implemented: unclaimed agreed slices (Reviewer N)

1. **Synthetic redistributable fraction PDF** (A-O→N2c): `tools/generate_stacked_fraction_pdf.py` → `tier1/web/stacked_fraction_spacing.pdf`, manifest entry **T1-11**. Probe run against the real extractor: `2` and `8` survive separately, `1/4`, `7/16` (concat), `1/2` all merge at reduced footprint, no `2/4` false merge — the P0 class is now CI-lockable on any machine without proprietary PDFs.
2. **Report Doctor contract branches** (R3-2 / R3-3 / A-O→N4b) — **pushed to website `main` @ `590ed8f`**, deploys via website-ci:
   - `extra.actual_text_entity_types` parsed in both shipped shapes (FC dataclass + schema map); requested-vs-observed mismatch → Review status + support action.
   - Pasted `bcs.ready_check/1.0` documents get a dedicated readout (status, non-pass checks, repair hints as actions).
   - `extra.performance_hint` surfaced in findings + support summary (closes the R2-8 website gap).
   - Verified: `node --check` + 12-case functional smoke (FC match, map mismatch, ready check, legacy-report regression) all pass; static metadata validator green.
3. **SU root `THIRD_PARTY_NOTICES.md`** (handoff §6 gap) — **pushed `[skip release]` @ `0253579`**. SU now matches FC/LC/BL.

## Remaining open — with owners

| Item | Owner / blocker |
|------|-----------------|
| FC emitter double-import defect (above) | **Shared-core worker** — fix before commit |
| SU `performance_hint` port + parity-floor Ruby test | Parity-floor thread owner (corpus artifacts already staged); next SU slice |
| LC → BL → SU emitter rollout (R3-2) | After FC shape is schema-validated (`validate_freecad_text_entities.py` exists, run it against a real FC smoke report post-defect-fix) |
| Artifact version stamp (R3-4) | Release-workflow change — needs a release cycle to verify; do together with next intentional release |
| Corpus commit of today's artifacts | Corpus-session owner — trees intentionally left uncommitted to avoid clobbering in-flight work |
| T-01 human field retest | **Rowdy** — real hosts + screenshots + (new) machine artifacts |
| Code signing purchase (R3-8) | **Rowdy** — cert/Azure Trusted Signing decision |
| AGPL/GPL corresponding-source judgment | **Rowdy / counsel** |
| T-10 Steel Logic ingestion slice, T-07 CLI stderr templates, T-11…T-15 | Backlog per open-threads |

---

*All Q&A questions through Round 4 now have cross-answers. Round 4 remains open for further peer answers to Q-N1–Q-N5 (two answer sets exist: O's, and the in-code responses verified above).*
