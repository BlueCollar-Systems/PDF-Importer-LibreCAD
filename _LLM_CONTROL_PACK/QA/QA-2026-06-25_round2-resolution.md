# Round 2 Resolution — Agreements & GO Gate

**Date:** 2026-06-25  
**Inputs:** Round 2 questions (F/G/H/I), cross-answers, Round 1 open items (scale banner, performance_hint P1).

**Process:** Four reviewers reached **≥4 agreements** on disputed points. Items below marked **SHIP** are implemented this session before commit/push.

---

## Agreements (disputed → resolved)

| # | Topic | Agreement | Status |
|---|-------|-----------|--------|
| **R2-1** | Offline install | Release artifacts (RBZ, Inno EXE, LC portable, BL ZIP) work **without internet after download**. Source dev path may need one online `preflight_check.py --install`. State explicitly in INSTALL + website `#install-help`. | **SHIP** |
| **R2-2** | Font substitution | When PyMuPDF detects **non-embedded fonts**, set `extra.font_substitution_note` + reflect in `human_summary`. Labels risky on non-English Windows; Outlines/Glyphs for appearance. | **SHIP** |
| **R2-3** | SU version skip | When RBZ version changes, show **one-time update notice** comparing previous vs current version; point to Compatibility Report. Document skip-version path in README. | **SHIP** |
| **R2-4** | LC Outlines recovery | GUI **confirms** when user selects Outlines on BOM-heavy workflow — suggest Labels for editable part marks; allow proceed. | **SHIP** |
| **R2-5** | Scale banner (Round 1 A4) | Single sentence in `preflight_copy.SCALE_CROSSCHECK_BANNER` used when scale cross-check warns. | **SHIP** |
| **R2-6** | PDF JavaScript | **No execution** in any host. Best-effort detect on Python hosts → `extra.pdf_interactive_note`. SU scan deferred. | **SHIP** (Python); **DEFER** SU |
| **R2-7** | Roaming Profiles | Document per-user RBZ + path matrix in COMPATIBILITY/README; log plugin dir in SU Compatibility Report. | **SHIP** docs + log line |
| **R2-8** | performance_hint | Threshold-based hint in import_report when entity count or peak_mb high. | **SHIP** (report only) |

---

## Build slate — this session (SHIP)

| Priority | Task | Owner |
|----------|------|-------|
| P0 | Offline install paragraph — INSTALL (FC/LC/BL/SU README) + website | This worker |
| P0 | `font_substitution_note` + `pdf_interactive_note` in pdfcadcore → sync FC/LC/BL | This worker |
| P0 | LC `gui.py` Outlines confirmation dialog | This worker |
| P0 | SU `version_notice.rb` + Compatibility Report plugin path line | This worker |
| P0 | `SCALE_CROSSCHECK_BANNER` + `performance_hint` in import_report enrich | This worker |
| P0 | README “Upgrading / skipping versions” section (all four importers) | This worker |
| P0 | Round 2 Q&A docs Desktop + 6-repo mirror + INDEX/worker log | This worker |

---

## Deferred (with reason)

| Item | Reason |
|------|--------|
| SU JavaScript / OpenAction scan | Ruby parser lacks cheap catalog scan; Python parity sufficient for P0 |
| Air-gap CI job (Q-F1a) | Manual USB deploy acceptable before first field wave |
| CJK locale field matrix (Q-G1a) | No licensed tier-1 CJK corpus in repo |
| Roaming Profile automated detection | Needs enterprise IT partner |
| Steel Logic BOM bridge (T-10) | Out of round 2 scope |
| T-01 human screenshot sign-off | Still **product owner** — blocks release sign-off, not doc push |

---

## Version bumps (user-visible only)

| Repo | Bump | Why |
|------|------|-----|
| SketchUp | 3.7.69 → **3.7.70** | Update notice on version change |
| LibreCAD | 1.0.43 → **1.0.44** | Outlines confirmation dialog |
| FC / BL / Website | No bump | Report extras + docs only |

---

## GO decision

- **Documentation + code slice:** ✅ GO commit/push when tests green and mirrors synced.
- **Field test:** ✅ GO renewed human confirmation with offline + font + Outlines guidance documented.
- **Release sign-off:** ❌ Still blocked on **T-01** human retest.

---

*Round 2 resolution — anonymous reviewers — 2026-06-25*
