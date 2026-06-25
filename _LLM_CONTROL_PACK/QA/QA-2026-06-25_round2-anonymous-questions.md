# Anonymous Questions Round 2 — Field-Test Gaps

**Date:** 2026-06-25  
**Rules:** Questions only — no self-answers. Respond in `QA-2026-06-25_round2-anonymous-answers.md`.

Round 1 (Reviewer E) covered preflight parity, legacy hardware, SU 2017 API, scale trust, and Steel Logic handoff. This round targets **deploy realism, locale, enterprise paths, and PDF edge cases** not yet exhaustively answered.

---

## Q-F1 — Offline install at first run

**Reviewer:** F (IT / shop deploy)  
**Host scope:** All importers + website install-help  
**Why it matters:** Fab shops often block outbound internet. Round 1 assumed bundled deps; outside-box reviews noted source ZIP may still call `preflight_check.py --install` (pip vendoring). Field testers need a clear answer: *which install paths work with zero network?*

**Question:** When a user has **no internet at install time**, which release artifacts are fully offline (Windows portable ZIP, Inno EXE, SketchUp RBZ, Blender add-on ZIP) and which paths still require a one-time online step — and should website install-help state this explicitly before field sign-off?

---

## Q-G1 — Font substitution on non-English Windows

**Reviewer:** G (locale / international CAD)  
**Host scope:** SU Labels, FC ShapeString, LC DXF TEXT, BL text objects  
**Why it matters:** Labels mode maps PDF font names to host/CAD fonts. On Japanese, German, or Eastern European Windows, system font substitution can shift BOM part marks and weld symbols even when vector geometry is correct.

**Question:** Do we detect or document **font substitution risk** when PDF fonts are non-embedded or when the PDF uses CID/Type0 fonts — and should `import_report.json` carry a plain-English `font_substitution_note` when detectable?

---

## Q-H1 — Roaming Profiles and SketchUp Plugins path

**Reviewer:** H (enterprise IT / multi-user)  
**Host scope:** SketchUp RBZ install; secondary: FC `%APPDATA%` Mod path  
**Why it matters:** Roaming Profiles sync `%APPDATA%` across domain PCs. SketchUp extension load path differs by version; IT may install RBZ per-machine while users roam Documents. Misaligned plugin paths cause “extension missing” support tickets.

**Question:** What is our **supported guidance** for Roaming Profile / multi-user shops: install RBZ per-user vs per-machine, and should Compatibility Report log the resolved extension directory and SketchUp `Plugins`/`Plugins` versioned path for support?

---

## Q-I1 — PDF JavaScript and document actions

**Reviewer:** I (security / exotic PDF)  
**Host scope:** pdfcadcore / PyMuPDF extraction (FC, LC, BL); SU Ruby parser  
**Why it matters:** Some vendor PDFs ship `/OpenAction`, `/AA`, or JavaScript. Shops worry about “running scripts” and about imports that behave differently when actions fire in Acrobat.

**Question:** Do any importers **execute** PDF JavaScript or open actions — and if not, should we **detect and warn** in `import_report` / preflight when a PDF contains `/JS` or `/OpenAction` entries?

---

*End of round 2 questions — awaiting cross-answers from reviewers F, G, H, I (each answers the three they did not ask).*
