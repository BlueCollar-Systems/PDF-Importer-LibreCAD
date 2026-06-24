# Round 4 — Resolution

**Session:** 2026-06-24  
**Status:** **GO for the initial build slate** — three shippable wins implemented, tested, ready to commit/push. The broader outside-box QA session remains **ACTIVE** while reviewers and follow-up work continue.
**Mood:** Inspiring but honest. We did not pretend host parity.

---

## Group agreement — build NOW (this session)

### 1. Import report `extra.human_summary`

- **What:** One paragraph plain-English summary of each import, attached automatically to `import_report.json`.
- **Where:** `pdfcadcore/import_report.py` (`build_human_summary`) — FC canonical, synced LC/BL.
- **SketchUp:** Ruby mirror in `qa_report.rb` (internal Ruby engine path).
- **Why now:** Zero UI dependency; support, CLI, and future preflight can consume immediately.
- **Tests:** `tests/test_import_report_human_summary.py` (FC); `test/qa_report_test.rb` (SU).

### 2. SketchUp Import Health menu

- **What:** Extensions → PDF Vector Importer → **Import Health…** — last run path, text_mode, resolved_scale, timing, human_summary, log + report paths.
- **Version:** v3.7.61
- **Why now:** Highest impact/effort ratio on A’s list; uses existing stats + report.

### 3. Website “What you'll get” matrix

- **What:** Honest host × capability table on `#install-help` — geometry, layers, four text surfaces, import_report.
- **Version:** Website v1.0.56
- **Why now:** Stops wrong-host downloads; documents LC 2D limits without apology theater.

---

## Group agreement — defer (with reason)

| Item | Defer to | Reason |
|------|----------|--------|
| Live import preview | Moonshot | Needs second pass + oracle safety |
| Confidence heatmaps | P1 backlog | Engineers yes, users need summary first |
| Preflight wizard | P0 next sprint | Shared copy first; per-host UI heavy |
| Scale cross-check banner | P0 next sprint | High value; needs UX mock |
| Golden vectors | P0 next sprint | R2-4 closure |
| Steel designation parser | Moonshot | Cross-host builder work |
| steellogic:// deep link | Moonshot | App contract |
| In-host capability dialog | P1 | Website matrix covers pre-install |

---

## Explicit non-goals (Round 4)

- No claim of per-span OCG on geometry text (Round 3 ruling stands).
- No SketchUp 2017 installer hosting (Round 4 screenshot policy stands).
- No version bumps for pdfcadcore-only sync without user-visible host change (FC/LC/BL patch bumps applied for report field).

---

## Verification checklist

| Check | Expected |
|-------|----------|
| `pdfcadcore_sync_check.py` | ALL IN SYNC |
| FC `test_import_report_human_summary.py` | pass |
| SU `qa_report_test.rb` | pass |
| Website `validate_static_metadata.py` | pass (if run in CI) |

---

## Commit plan (six repos)

| Repo | Changes |
|------|---------|
| PDF-Importer-FreeCAD | pdfcadcore human_summary, test, package 4.0.42, manifest |
| PDF-Importer-LibreCAD | pdfcadcore sync, pyproject 1.0.37, manifest |
| PDF-Importer-Blender | pdfcadcore sync, addon 1.0.39, manifest |
| PDF-Importer-SketchUp | qa_report, import_health, main menu, v3.7.61 |
| 1BlueCollar-Website | install-help matrix, v1.0.56 |
| Structural_Steel_Shapes_App | QA mirror only (no code change required) |

---

**Round 4 initial build slate: SHIPPED with GO.**

**Status correction:** This note does not close the overall Round 4 / outside-box QA session. It closes only the first agreed implementation bundle. The full session remains open until all active reviewer work, disagreements, validation, commits, and pushes are complete.

*Resolution — 2026-06-24*
