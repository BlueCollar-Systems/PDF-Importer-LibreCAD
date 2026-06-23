# Round 3 — Synthesis (All Reviewers)

**Date:** 2026-06-23  
**Inputs:** Reviewer A (errors), B (improvements), C (cross-repo), D (app/website)  
**Scan machine:** Windows 10; repos at `C:\1PDF-Importer-*`, `C:\1BlueCollar-Website`, `C:\1 Structural_Steel_Shapes_App`

---

## 1. Consolidated verdict

| Area | Verdict |
|------|---------|
| **Automated test health** | **GREEN** — all executed suites passed (see §4) |
| **pdfcadcore sync** | **GREEN** — `ALL IN SYNC` on FC, LC, BL |
| **Release / version alignment** | **GREEN** — pyproject/metadata match GitHub tags for current wave |
| **Round-2 sign-off blockers** | **YELLOW** — R2-3 strict timing still not CI-proven; manual retest on dense PDF still required |
| **Uncommitted local work** | **NONE** — all six repos clean (§5) |

**Round-3 recommendation:** **CONDITIONAL GO for documentation/website fixes**; **HOLD code release claims** until R2-3 evidence (strict timing run or documented manual benchmark) is attached to this thread.

---

## 2. Top consolidated findings (by severity)

| ID | Sev | Finding | Repo / file | Reviewers |
|----|-----|---------|-------------|-----------|
| R3-1 | P1 | Strict timing benchmark opt-in only; not in CI (R2-3) | SU `test/corpus_strict_timing_test.rb`, `.github/workflows/` | A, B, C |
| R3-2 | P1 | Full corpus placement skipped without `BCS_CORPUS_ROOT` | SU `corpus-placement.yml` | B, C |
| R3-3 | P2 | SketchUp `import_report` lacks granular phase timings (R2-2 partial) | SU `qa_report.rb:70-76` | A, B |
| R3-4 | P2 | Open-gate fail-open on SU vs fail-closed Python hosts | SU `main.rb:1398-1400` | A, C |
| R3-5 | P2 | Website LC portable example still shows v1.0.33 | `index.html:204` | A, D |
| R3-6 | P2 | `repo-metadata.json` omits LC portable zip asset | `repo-metadata.json`, `sync_repo_metadata.py` | C, D |
| R3-7 | P2 | BL import_report tests thinner than LC | BL `tests/` | B |
| R3-8 | P2 | Missing git tag v3.7.53 | SU git tags | A |
| R3-9 | P2 | FC pytest Windows `.pytest_tmp` PermissionError on cleanup | FC local pytest | A |
| R3-10 | P2 | Steel app `1.0.7+8` vs GitHub Steel-Shapes `v1.0.8` | `pubspec.yaml`, metadata | D |
| R3-11 | P2 | Dead junction workspace paths | `C:\1SU-PDFimporter` etc. | B, C |
| R3-12 | P2 | Auto-release not gated on open QA (R2-9) — **user ruled: no gate** | all `auto-release.yml` | B |

**No P0 crashes** identified in automated scans.

---

## 3. Disagreements between reviewers

| Topic | Position A | Position B | Synthesis |
|-------|------------|------------|-----------|
| **LC portable zip on latest release** | Reviewer A initially flagged missing portable asset (metadata showed 120 KB zip only) | Reviewer C/D checked GitHub API | **Resolved:** both zips exist on v1.0.34; **metadata sync script** is incomplete, not the release pipeline |
| **Website `/shapes` links** | Raw filesystem check flagged "missing" `.html` paths | Reviewer D notes Cloudflare clean URLs | **Not a bug** — `_redirects` intentionally blank; production routing OK |
| **SU fail-open gate** | Reviewer A lists as error/parity gap | Reviewer C lists as documented design | **Agreement on facts**; dispute is severity — treat as **documented P2** unless team wants behavior change |

---

## 4. Test & check summary (executed this session)

| Repo | Command | Result |
|------|---------|--------|
| SketchUp | `ruby test/qa_report_test.rb` | 4 runs, 20 assertions, **0 failures** |
| SketchUp | `ruby test/corpus_harness_test.rb` | 2 runs, **0 failures** |
| SketchUp | `ruby test/corpus_strict_timing_test.rb` (default) | **Skipped** (exit 0, no `CORPUS_STRICT_TIMING`) |
| FreeCAD | `python pdfcadcore_sync_check.py` | **ALL IN SYNC** |
| FreeCAD | `pytest tests/` (ignore corpus/integration) | **60 passed**, 1 DeprecationWarning |
| FreeCAD | `pytest tests/test_qa_report_v11.py tests/test_import_report_writer.py` | **8 passed** |
| LibreCAD | `python pdfcadcore_sync_check.py` | **ALL IN SYNC** |
| LibreCAD | `pytest tests/test_import_report_*.py tests/test_dxf_import_report.py` | **5 passed** |
| LibreCAD | `pytest tests/` | **39 passed** |
| Blender | `python pdfcadcore_sync_check.py` | **ALL IN SYNC** |
| Blender | `pytest tests/test_import_report_writer.py` | **2 passed** |
| Blender | `pytest tests/` | **36 passed** |
| Website | `python tools/validate_static_metadata.py` | **Passed** (8 labels) |
| Steel app | `flutter analyze` | **No issues** |
| Steel app | `flutter test` | **153 passed** |

---

## 5. Uncommitted changes per repo (Option 3 / local work)

| Repo | `git status` | Branch | HEAD (one-line) |
|------|--------------|--------|-----------------|
| `C:\1PDF-Importer-SketchUp` | **clean** | main | `6737a4d` chore: bump version to 3.7.56 |
| `C:\1PDF-Importer-FreeCAD` | **clean** | main | `921bef0` docs: update Q&A cross-repo validation |
| `C:\1PDF-Importer-LibreCAD` | **clean** | main | `7a563f4` docs: update Q&A cross-repo validation |
| `C:\1PDF-Importer-Blender` | **clean** | main | `c2f075e` docs: update Q&A cross-repo validation |
| `C:\1BlueCollar-Website` | **clean** | main | `1374de0` docs: update Q&A cross-repo validation |
| `C:\1 Structural_Steel_Shapes_App` | **clean** | main | `c42f2f3` docs: update Q&A cross-repo validation |

**Option 3 pending work:** None detected locally — prior cross-repo improvements appear already committed on `main`.

---

## 6. Questions for team feedback

1. **R2-3:** Will sign-off require a **CI strict-timing job** or is a **logged manual run** (`CORPUS_STRICT_TIMING=1`, PDF `1017`, budget 60s) sufficient for this wave?
2. **R2-2:** Should SketchUp adopt **granular `performance.phases`** keys to match Python hosts, or is total elapsed enough for SU?
3. **Open gate:** Should SketchUp **fail-closed** on gate errors to match Python, or remain fail-open with explicit COMPATIBILITY docs?
4. **Steel Logic version:** Is `pubspec.yaml` `1.0.7+8` intentional ahead of Play `1.0.8`, or should we bump and release?
5. **Release gate (R2-9):** Adopt a hard **no auto-release while Desktop Q&A round open** rule? — **RESOLVED (2026-06-23):** **No gate.** Auto-release does **not** wait for Desktop Q&A rounds to close; ship on green CI/tests as today. See `QA-2026-06-23_round3-user-rulings.md`.

---

## 7. Proposed commit plan (AFTER team agreement — do not execute yet)

| Order | Repo | Suggested scope | Suggested message |
|-------|------|---------------|-------------------|
| 1 | `1BlueCollar-Website` | Fix `index.html` LC portable example; fix `sync_repo_metadata.py` to list portable asset | `docs(website): refresh LC portable example and release metadata` |
| 2 | `1PDF-Importer-LibreCAD` | INSTALL `--version` one-liner for portable path | `docs(install): document pdf2dxf.exe --version for portable users` |
| 3 | `1PDF-Importer-FreeCAD` | Migrate test off deprecated `PDFImportConfig` | `refactor(tests): import ImportConfig from pdfcadcore` |
| 4 | `1PDF-Importer-Blender` | Port LC import_report text-mode tests | `test: add import_report text-mode parity tests` |
| 5 | `1PDF-Importer-SketchUp` | Optional: wire strict timing CI job + Ruby phase timings | `ci: add opt-in corpus strict timing; feat: granular import_report phases` |
| 6 | All repos | Mirror Desktop Round-3 QA into `_LLM_CONTROL_PACK/QA/` | `docs(qa): add Round 3 scan reports` |

---

## 8. Blockers requiring human decision before commit

| Blocker | Decision needed |
|---------|-----------------|
| **R2-3 performance proof** | Manual benchmark attached vs CI enforcement |
| ~~**R2-9 release gating**~~ | **RESOLVED** — no Q&A gate on auto-release (user ruling 2026-06-23) |
| **SU open-gate policy** | Document only vs code alignment |
| **Steel app version** | Bump to 1.0.8+ or document divergence |
| **Junction paths R2-10** | Recreate `C:\1SU-PDFimporter` style paths or update dev docs |

---

*Round 3 synthesis — anonymous. Awaiting feedback in Q&A folder or chat.*
