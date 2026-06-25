# Anonymous Answers Round 2 — Cross-Review (F / G / H / I)

**Date:** 2026-06-25  
**Rule:** Each answer is from a **different** reviewer. No author answered their own question.

---

## Reviewer F answers (not Q-F1)

### A-F→G1 — Font substitution on non-English Windows

**Re:** Q-G1

**Answer:** **Partial detection today.** pdfcadcore records `font_name` per text span from PyMuPDF but does **not** yet classify embedding or locale-specific substitution. Labels / DXF TEXT / ShapeString paths **will** substitute host fonts when PDF fonts are missing or non-embedded — this is worse on non-English Windows where Arial/Times fallbacks differ from US defaults.

**Recommendation (agreed this session):** Add `build_font_embedding_hints()` in canonical `pdfcadcore/import_report.py`: scan pages with `page.get_fonts(full=True)`; when non-embedded fonts appear, set `extra.font_substitution_note` and mention Labels vs Outlines/Glyphs in `human_summary`. Ghostscript (optional on SU) helps repair but is not bundled everywhere. **Field test:** 1017-class PDF on DE/JA locale VM — compare Labels vs Outlines for part marks.

**Unknown / needs test:** CID/Type0 CJK shop sets — no corpus oracle yet.

---

### A-F→H1 — Roaming Profiles / SketchUp Plugins path

**Re:** Q-H1

**Answer:** **Document, do not automate roam.** SketchUp loads extensions from version-specific user paths under `%APPDATA%\SketchUp\SketchUp 20XX\SketchUp\Plugins` (exact folder varies by SU year). Roaming `%APPDATA%` can duplicate or shadow RBZ contents across machines with different SU builds.

**Supported guidance:**

| Scenario | Guidance |
|----------|----------|
| Domain Roaming Profile | Install RBZ **per user** on each PC after SketchUp version is confirmed; avoid roaming only the Plugins folder across mismatched SU versions |
| Shared shop PC | Per-user Windows login → per-user RBZ install |
| IT golden image | Bake RBZ into image **per SketchUp year** |

Compatibility Report already logs platform and plugin version; **P1:** append resolved `__FILE__` plugin dir line for support. **Deferred:** automated roam detection — needs field IT input.

---

### A-F→I1 — PDF JavaScript / actions

**Re:** Q-I1

**Answer:** **No importer executes PDF JavaScript.** PyMuPDF extraction (FC/LC/BL) reads static content streams; it does not run `/JS`. SketchUp Ruby parser reads vector operators — also no JS VM.

**Risk:** Interactive PDFs may **look** different in Acrobat because actions ran there; our import uses static content only. **Recommendation:** Detect `/JS`, `/JavaScript`, `/OpenAction` via PyMuPDF `doc.get_js()` / catalog keys when available; add `extra.pdf_interactive_note` in import_report (warn, not block). SU Ruby path: **unknown** for JS detection — document “not scanned” in COMPATIBILITY until implemented.

**Honest limit:** Detection is best-effort; absence of flag does not prove safety for malicious PDFs — keep fail-closed encrypted-PDF gate.

---

## Reviewer G answers (not Q-G1)

### A-G→F1 — Offline install

**Re:** Q-F1

**Answer:** **Offline-ready (no network):**

| Artifact | Offline? | Notes |
|----------|----------|-------|
| SU Windows RBZ (GitHub Release) | ✅ Yes | Poppler bundled in RBZ; Ghostscript optional download |
| FC Inno Setup EXE | ✅ Yes | Private PyMuPDF runtime bundled |
| LC portable ZIP (`lcpdf-gui.exe`) | ✅ Yes | Python + PyMuPDF + ezdxf bundled |
| BL release ZIP | ✅ Yes | cp310-abi3 PyMuPDF inside add-on |
| FC/LC **source ZIP** dev path | ⚠️ Partial | `preflight_check.py --install` may fetch wheels **if** `lib/` empty — needs internet once |

Website should state: **“Download the release ZIP/EXE/RBZ — no internet required after download.”** Source contributors need one online vendoring step unless they clone with pre-vendored `lib/`.

---

### A-G→H1 — Roaming Profiles

**Re:** Q-H1

**Answer:** Agree with F on per-user RBZ. FreeCAD 1.1 adds complexity: Mod folder is `%APPDATA%\FreeCAD\v1-1\Mod\` — roaming can break junction-based dev installs. **Production shops:** use FC installer EXE (copies files), not junction dev script. COMPATIBILITY should list `%APPDATA%` paths per host for IT ticket triage.

---

### A-G→I1 — PDF JavaScript

**Re:** Q-I1

**Answer:** Agree — **no execution**. For LC/FC/BL, PyMuPDF `doc.is_pdf` + metadata pass can flag JavaScript presence. Warn in `human_summary`: “PDF contains document scripts; import uses static geometry only.” **P2:** SU parity for JS scan — low priority vs T-01 field retest.

---

## Reviewer H answers (not Q-H1)

### A-H→F1 — Offline install

**Re:** Q-F1

**Answer:** IT checklist: (1) Pre-download release on connected PC; (2) USB to shop floor; (3) Run preflight/`Compatibility Report` offline; (4) Never rely on website live version badges during install — use packaged artifact version string. Steel Logic app is offline for shape lookup; PDF callout lookup is local parse — no network.

**Gap found:** Website install-help did not previously bold **“no internet required after download”** — ship in this session.

---

### A-H→G1 — Font substitution

**Re:** Q-G1

**Answer:** DXF TEXT carries PDF `font_name` but CAD apps substitute at open time — LibreCAD on non-English Windows may map “ArialMT” differently. **Outlines** avoids host font lookup (geometry only) at cost of editability. import_report hint should say: *“Non-embedded fonts detected — Labels may look different on this PC; retry Outlines/Glyphs for appearance.”*

---

### A-H→I1 — PDF JavaScript

**Re:** Q-I1

**Answer:** Enterprise AV sometimes quarantines PDFs with `/JS`. We should **not** execute; optional warn helps IT explain why import still works. Malware scanning is out of scope — user should scan untrusted PDFs separately.

---

## Reviewer I answers (not Q-I1)

### A-I→F1 — Offline install

**Re:** Q-F1

**Answer:** Blender add-on must not show “pip install PyMuPDF” as the only path — release ZIP bundles wheels. Verify offline by air-gap test: extract ZIP, install add-on, run `--preflight` — **CI gap:** no automated air-gap job yet.

---

### A-I→G1 — Font substitution

**Re:** Q-G1

**Answer:** `pdffonts` (Poppler) on SU can list encoding/emb — could feed SU import_report in future. Python hosts: PyMuPDF `get_fonts(full=True)` embedded flag is the P0 signal. Non-Latin glyph fidelity still depends on Outlines path — **needs test** on CJK welding chart if available in corpus.

---

### A-I→H1 — Roaming Profiles

**Re:** Q-H1

**Answer:** Log plugin path in Compatibility Report — low risk code change. Roam **Documents** (models) not **Plugins** when SU versions differ between roam source and target PC. Document in SU README “Enterprise / multi-user installs”.

---

## Follow-up spawned

### Q-F1a — Air-gap CI job?

Should CI include an “extract portable ZIP and run preflight without network” job? **Deferred P2** — manual field prep sufficient for now.

### Q-G1a — CJK corpus?

Add tier-2 CJK welding PDF to corpus manifest? **Deferred** — needs licensed sample.

---

*End of round 2 answers — see `QA-2026-06-25_round2-resolution.md` for agreements and build slate.*
