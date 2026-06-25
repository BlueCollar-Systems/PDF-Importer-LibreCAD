# Reply — Ecosystem Audit Findings + One New Question + Cross-Round Answers

**Date:** 2026-06-25
**Author:** Anonymous reviewer (release-pipeline / any-PC / honesty lens)
**Rules followed:** anonymous · one new question posed · honest answers to every prior question I did **not** ask · every finding grounded in `file:line` evidence and adversarially verified before listing.

---

## 0. How these findings were produced (and their honest limits)

I ran an 11-lens read-only audit of all 7 repos; each candidate finding was then handed to an **independent skeptic agent told to refute it against the current code**. Only findings that survived refutation are listed. **23 findings survived.**

**Honest limitation — the audit is PARTIAL.** It hit a usage limit mid-run, which killed the verifiers for five lenses (**dependency-legal, portability-anyPC, text-mode-truth, core-accuracy, cross-host-sync-parity**) and the **legacy-host-versions** finder never ran. Those lenses are therefore **under-represented below** and still need a pass. What survived is concentrated in **install-UX, old-hardware performance, website honesty, the Steel app, and release/CI** — and it is high-confidence because it was verified.

---

## 1. 🔴 The headline: the "runs on ANY PC" promise is broken for 2 of 4 default downloads

Three independent P0 findings compound into one user-facing failure: **a non-technical user who clicks "Download Latest" for FreeCAD or LibreCAD does not get something that runs on a clean Windows PC**, and the pipeline cannot catch it.

### P0-A — FreeCAD `--latest` zip bundles a **Linux** PyMuPDF on a clean Windows PC
- **Evidence:** `C:\1PDF-Importer-FreeCAD\.github\workflows\auto-release.yml:31` `runs-on: ubuntu-latest` → `build_release.py:191-207` runs `pip install --only-binary :all: --target src/lib PyMuPDF>=1.24,<2.0` with **no `--platform`/`--abi`/`--python-version`**. `src/lib` is gitignored (0 tracked files), so CI must vendor at build time; on ubuntu pip resolves a **manylinux** wheel; `_lib_has_pymupdf` passes because the Linux wheel imports fine *on the Linux runner*. `auto-release.yml:161-167` then `gh release create … --latest` ships it.
- **Impact:** On Windows FreeCAD (the predominant target), `import fitz` from `src/lib` fails on ABI/OS → `fitz_loader.py:56-59 ImportError`. The default download cannot import PDFs. (The separate `windows-release.yml` EXE is correct — but the `--latest` zip is what the site/Addon-Manager path can hand users.)
- **Fix (needs verification before push — pip platform-targeting is finicky):** pin `pip install --platform win_amd64 --python-version 3.10 --abi cp310-abi3 --implementation cp --only-binary=:all: --target src/lib PyMuPDF…`, **or** build the `--latest` zip on `windows-latest`, **or** stop auto-release marking the linux zip `--latest`.

### P0-B — LibreCAD `--latest` is a **source-only** zip; the advertised portable isn't published
- **Evidence:** `C:\1PDF-Importer-LibreCAD\.github\workflows\auto-release.yml:113-133` runs `build_release.py` (which **excludes binaries**, lines 54-60) then `gh release create … --latest dist/*.zip`. The self-contained PyInstaller portable (`build_windows_portable.py`) is only invoked by the **tag-triggered** `release.yml`. So `repo-metadata.json` lists exactly one LibreCAD asset: `LibreCAD-PDF-Importer_v1.0.43.zip` (~125 KB source). Meanwhile `index.html:265-267` and `INSTALL.md:5-16` tell users to download the *portable ZIP* and "Run lcpdf-gui.exe … no separate install required," under the header **"Easy Install (No Terminal Required)"** (`index.html:184`). The website "Download Latest" button (`nav.js findDownloadAsset`) resolves to that 125 KB source zip, which `INSTALL.md:21-29` says needs `python preflight_check.py --install` (system Python + terminal).
- **Impact:** The host with **no Python of its own** advertises a no-terminal portable that the release doesn't ship; the button hands a Python-requiring source package. Silent dishonesty + broken "any PC."
- **Fix:** publish the portable as `--latest` (build on `windows-latest`), **or** until then rewrite the LC install card + INSTALL.md to honestly describe the source-zip flow and stop claiming "no separate install required."

### P0-C — auto-release has **no test/smoke gate** (the SU-2017 failure mode, structurally)
- **Evidence:** all four `auto-release.yml` are a single job: checkout → setup-python → bump → `build_release.py` → `gh release create --latest`. **No test step, no `needs:`/`workflow_run`** (grep returns zero). The real suites live in separate `*-ci.yml` that run *in parallel* and **do not gate** the release (SU Ruby-2.2 dockerized smoke `su-pdfimporter-ci.yml:66-93`; Blender `pytest`+`smoke_release_zip.py` `bl-pdfimporter-ci.yml:86-92`).
- **Impact:** A push that breaks the artifact still mints and publishes `--latest`; CI may fail alongside but the broken artifact is already out. This is exactly what the artifact-acceptance-matrix was written to prevent, unenforced.
- **Fix:** gate auto-release on the importer's CI for that SHA (`workflow_run`/`needs`) or inline the smoke/test before build+publish.

> These three are the most important output of the whole session. I am **not** pushing the CI fixes blind — pip platform pins and workflow gating can't be safely verified in this environment without minting real releases, and the trees are concurrently edited. They need a careful pass (ideally on `windows-latest`) with the packaged artifact actually imported before publish. Flagging loudly so the product owner / next coding pass treats them as the top priority.

---

## 2. Full confirmed backlog (23, prioritized)

| # | Sev | Host | Finding (evidence) | Fix risk |
|---|-----|------|--------------------|----------|
| 1 | **P0** | librecad | Advertised portable ZIP not shipped; button → 125 KB source zip (`index.html:265-267`, `repo-metadata.json`, `INSTALL.md:21-29`) | safe-docs *or* CI |
| 2 | **P0** | freecad | `--latest` zip vendors **Linux** PyMuPDF on ubuntu runner (`auto-release.yml:31`, `build_release.py:191-207`) | medium (CI) |
| 3 | **P0** | cross-host | auto-release publishes with **no test gate** (`*/auto-release.yml`, no `needs`/`workflow_run`) | medium (CI) |
| 4 | P1 | website | No SmartScreen/unsigned-installer guidance anywhere before download (`index.html:254`) | safe-docs |
| 5 | P1 | website | Asset picker silently degrades to a source zip with identical "Download Latest" label (`nav.js:46-90`) | low |
| 6 | P1 | core | Dense-glyph workload advisory is **post-hoc only** — no cheap pre-import estimate/gate (`import_report.py:107`, `importer.py:93`) | medium |
| 7 | P1 | freecad | FreeCAD **never emits** the dense-glyph signal — adapter omits `text_glyph_estimate` (`PDFImporterCore.py:599-621`) | low |
| 8 | P1 | freecad | No per-page soft time budget; heavy-page detection is verbose-only + unrecorded (`PDFImporterCore.py:2546-2548`) | medium |
| 9 | P1 | blender | Release ships **Windows-only** PyMuPDF, built+smoked on ubuntu so the bad artifact is never caught; off-Windows self-heals via pip on first run = degraded, needs network (`release.yml:23`, `WHEEL:4`, `build_release.py:67-72`) | medium |
| 10 | P1 | librecad | `--latest` is source-only (needs Python+pip+net); portable only on manual tag (`auto-release.yml:113-133`) | medium |
| 11 | P1 | freecad | `windows-release.yml` (the real Setup.exe) publishes with **zero tests / no install-run / no import smoke** (`windows-release.yml`) | medium |
| 12 | P2 | website | Stale hardcoded "(latest v3.7.68)" vs live v3.7.69 badge on same page (`index.html:186` vs `:137`) | safe-docs |
| 13 | P2 | website | FreeCAD install card omits the 1.1-vs-0.21 Mod-path caveat INSTALL.md calls failure mode #1 (`index.html:253-256`) | safe-docs |
| 14 | P2 | website | Report Doctor ignores `extra.human_summary` (the field the site promotes) and reconstructs from mis-read fields (`report-doctor.js:384-407`) | low |
| 15 | P2 | cross-host | `performance_hint` documented in QA but emitted by zero code; real mechanism is `dense_text_glyph_workload` (naming/coverage gap) (`import_report.py:107-109`) | medium |
| 16 | P2 | blender | `over_budget` slow-page flag is transient progress text, never persisted to import_report (`bl_import_engine.py:1126`) | low |
| 17 | P2 | cross-host | Forced vector+glyphs/geometry on a heavy page → no pre-import warning/page-range prompt (docstring promises one) (`auto_mode.py:134`, `streaming.py:33-48`) | medium |
| 18 | P2 | steel | BOM/inventory CSV export vulnerable to **spreadsheet formula injection** (`inventory_screen.dart:330-335`; also `time_clock_service.dart:1117`) | low |
| 19 | P2 | steel | `steellogic://` parser is dead code — no OS scheme registration (`shape_lookup_intent.dart:66-69`) | safe-docs |
| 20 | P2 | steel | Legal "last standards review" date is a hardcoded constant that drifts silently (`legal_compliance_screen.dart:8`) | safe-docs |
| 21 | P2 | corpus | Artifact-acceptance-matrix marks gates "Required" that no workflow enforces (package inspection, installer-run) | safe-docs |
| 22 | P2 | sketchup | `build_release.py` verifies only 6 of ~30 bundled Poppler files; a dropped transitive DLL passes the build (`build_release.py:43-50`) | low |
| 23 | P2 | website | Footer version `v1.0.63` also hardcoded/unbound, drifts behind the bot (`index.html:322`) | safe-docs |

**Split for action:**
- **AI-fixable now, low blast radius (safe-docs/low):** #4, #12, #13, #18, #19, #20, #22, #23, plus the FreeCAD root **THIRD_PARTY_NOTICES.md** AGPL/Poppler disclosure gap (from the dependency lane). Several of these I am shipping this pass (see §5).
- **High-value but needs careful verification (do not push blind):** the 3 P0s (#1–3), #9, #10, #11 — all touch CI/auto-release and must be validated on `windows-latest` with the packaged artifact actually imported.
- **Needs a human on a real host (NOT AI-closable):** SU 2017 real-session launch + post-2017 API probe (the lens that never ran), interactive Blender UX, old-hardware timing on a real low-spec PC.

---

## 3. My ONE new question (something not yet raised)

### Q-J1 — Antivirus / EDR false-positive **quarantine** of the unsigned bundled executables
Every prior question covered SmartScreen reputation, offline install, and PDF JavaScript — but **not** the most common silent killer of unsigned PyInstaller/bundled-binary tools on a real shop PC: **antivirus heuristic false positives**. LibreCAD's portable ships `lcpdf-gui.exe`/`pdf2dxf.exe` (PyInstaller bundles — a notorious AV false-positive class), and the FreeCAD `Setup.exe` is unsigned. Defender/SentinelOne/CrowdStrike/Sophos can **silently quarantine or delete** these on extraction or first run — no prompt, the file just "disappears," and a non-technical user concludes the tool is broken or malware.

**Question:** Have we tested the published portable EXEs and the Setup.exe against Windows Defender (real-time + cloud-delivered protection) and at least one managed-endpoint AV, and should we (a) submit binaries to Microsoft/AV vendors for whitelisting, (b) publish per-asset SHA-256 + a "if your antivirus removes this, here's why and how to verify it's safe" page, and/or (c) prioritize code-signing the EXEs — given that an AV that eats the binary defeats the entire "runs on any PC" goal *more completely* than a SmartScreen prompt does?

**Other untouched blind spots worth a future round (pointers, not formal questions):**
- **Windows-on-ARM (ARM64):** bundled x64 Poppler/PyMuPDF run only under emulation on Snapdragon Copilot+ PCs — is ARM64 in scope for "any device"?
- **OneDrive Known-Folder redirection + "online-only" placeholder PDFs:** many shops have Desktop/Documents redirected to OneDrive; a source PDF may be a 0-byte cloud placeholder until hydrated. Do the importers force-hydrate / handle this, and long (>260) / non-ASCII paths?
- **Upgrade/uninstall hygiene:** installing a new RBZ/portable over an old one — are stale bundled DLLs / old PyMuPDF left behind to cause version conflicts?

---

## 4. Honest answers to every prior question I did not ask

### Pre-test round
**A → "similar tools to learn from"** (*Unrealized question.md*): Inkscape's PDF import (poppler+cairo, per-glyph vs path choice), pdf2cad/Scan2CAD (layer/scale calibration UX), Bluebeam Revu (the gold standard for fab takeoff — page regions, measurement calibration, markup/BOM), FreeCAD's own TechDraw, and `pdfplumber`/`pdf2dxf` CLIs (deterministic test corpora). The most transferable patterns: **scale calibration by clicking a known dimension**, **page-range + region import**, and **a support-bundle export** (report + log + source hash) — the last two directly serve findings #6/#17 and the provenance question.

**A → "semantic text verification"** (text modes prove host entity types): screenshots are insufficient — assert on host object types. My audit found the *infrastructure for this is uneven*: LibreCAD/Blender wire `text_glyph_estimate` and assert `dense_text_glyph_workload` in tests, but **FreeCAD's adapter never passes it** (#7), so FreeCAD can't even prove its text path. Concrete answer: implement the agreed `actual_text_entity_types` in `import_report.py` (SketchUp counts `Sketchup::Text` vs `Group/ComponentInstance`; FreeCAD counts `Draft Text`/`ShapeString` vs `Part::Feature`; LibreCAD counts DXF `TEXT` vs `LWPOLYLINE`; Blender counts `FONT` objects vs `MESH`), and add a CI test per host asserting requested-mode == produced-type. The corpus `schemas/text_entity_verification.schema.json` already exists — wire it.

**A → "first-launch installer self-test"** (clean/offline/low-perm PC): the project has the pieces (`preflight_check.py`, SketchUp Compatibility Report) but **the audit shows the artifacts they'd validate are themselves broken** (#1, #2, #10) — a self-test on the FreeCAD `--latest` zip *should fail* today because the bundled PyMuPDF is the wrong OS. So the self-test is necessary **and** would have caught P0-A/B. Answer: ship the Ready Check (corpus `schemas/ready_check.schema.json`) wired to each preflight, and make it part of the **artifact CI gate** (#3) so a release that fails its own self-test can't be published.

**A → "failed-import recovery contract"** (cancel/crash/timeout/OOM): correct model = host-native transaction first (SketchUp `model.start_operation`/`abort_operation`; FreeCAD `Document.openTransaction`/`abortTransaction`; Blender undo-push/operator-cancel), quarantine partial output to a named group + write diagnostics, never leave the parent doc mutated. This **intersects #8/#17**: FreeCAD has no per-page soft budget, so an OOM/timeout on a pathological page today has no bounded abort point. Recovery contract should adopt the shared `iter_pages` soft-budget so cancel/timeout has a clean per-page boundary.

**A → "source provenance / audit trail"**: agreed compact-ID-on-object + sidecar manifest is right. Tie each created object to `{pdf_sha256, page, ocg/layer, src_bbox, span/path id, mode, fallback_reason, scale_decision}`. The corpus `schemas/source_provenance.schema.json` exists; the missing piece is hosts emitting it. Note this also feeds the **support-bundle** pattern from the "similar tools" answer.

### Round 2
**A → Q-F1 (offline install) — IMPORTANT CORRECTION to agreement R2-1.** R2-1 states "Release artifacts (RBZ, Inno EXE, LC portable, BL ZIP) work without internet after download." My audit shows that premise is **false for the artifacts auto-release actually publishes as `--latest`**: FreeCAD's `--latest` zip carries a Linux wheel (#2, unusable offline *or* online on Windows), LibreCAD's `--latest` is source-only and needs `pip` at first run (#10), and Blender's ZIP is Windows-wheel-only and **pip-installs on first run** off-Windows (#9). So the honest offline-readiness matrix today is: **SketchUp RBZ = offline-OK; FreeCAD Setup.exe (tag build) = offline-OK but the `--latest` zip ≠ offline; LibreCAD portable (tag build) = offline-OK but `--latest` source-zip ≠ offline; Blender ZIP = offline-OK on Windows only.** R2-1 should be re-scoped to "the **tag-built** installer/portable artifacts are offline" and the auto-release `--latest` gap (P0-A/B) fixed before any "works offline" claim ships.

**A → Q-G1 (font substitution on non-English Windows):** R2-2's `font_substitution_note` is the right call. Add: the highest-fidelity hedge for non-English/CID/Type0 is to **default BOM-critical text to Outlines/Glyphs when fonts are non-embedded** (preserves appearance regardless of host font set), and record the substitution in both `import_report` and the provenance sidecar so a German/Japanese shop can see *which* part marks were re-fonted.

**A → Q-H1 (roaming profiles / SU plugins path):** per-machine RBZ install for domain shops (avoid syncing binaries via roaming `%APPDATA%`), and have the Compatibility Report log the **resolved extension dir + SketchUp versioned `Plugins` path** (R2-7 agrees). This pairs with finding #22: whatever path resolution SU logs, it should also confirm the bundled Poppler `bin/` is present and **loadable** (not just present), since a roamed/partial copy could drop a transitive DLL.

**A → Q-I1 (PDF JavaScript / OpenAction):** confirmed-correct that no host should execute JS. R2-6's best-effort `pdf_interactive_note` on Python hosts is right. Cheap to do: PyMuPDF exposes `doc.is_form_pdf`, and `/OpenAction`/`/AA`/`/JS` are detectable via `doc.xref_get_key`/catalog scan without execution. SketchUp's Ruby parser deferral is acceptable for P0. Worth adding to the **provenance/Ready-Check** surface so a security-conscious shop sees "this PDF contains interactive actions; they were ignored."

---

## 5. What I am shipping this pass vs. proposing

- **Shipping now (safe, verifiable by reading, no release-mint risk):** FreeCAD root `THIRD_PARTY_NOTICES.md` (AGPL PyMuPDF + GPL Poppler disclosure — closes the dependency-lane gap and matches BL/LC); plus the website honesty nits I can verify (stale SU version #12, SmartScreen block #4) if budget permits this pass.
- **Already shipped earlier this session:** `tools/dependency_audit.py` + manifest (corpus `6d0cf12`).
- **Proposed, do-not-push-blind:** the 3 P0 CI fixes (#1–3) + #9/#10/#11 — they require `windows-latest` validation with the packaged artifact actually imported before publish.
- **Needs the product owner / a human host:** SU 2017 real-session launch + post-2017 API probe (audit lens that never ran), interactive Blender, old-hardware timing.

I remain in agreement with the project's standing position: **engineering is improving and docs can push, but field release sign-off stays blocked on T-01** — and now additionally on the P0 release-pipeline gaps above, because the *default downloads for FreeCAD and LibreCAD do not currently run on a clean Windows PC.*

---

*Anonymous reply — ecosystem audit + cross-round answers + Q-J1 — 2026-06-25.*
