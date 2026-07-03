# NEW CONTRIBUTOR HANDOFF — BlueCollar Systems (BCS) PDF Importer Ecosystem

**Audience:** a fresh contributor (human or agent) joining cold.
**Goal of this doc:** you should be able to read this once and start building, fixing, and shipping across *every* repo — not just the importers — without asking anyone anything.
**Written:** 2026-07-02. **Content snapshot:** distilled from the working session that ended ~2026-06-26.

> ⚠️ **Read this first, before you trust a single specific fact below.**
> This ecosystem is edited by **multiple anonymous workers in parallel** plus an **auto-release bot**. Docs — including this one — go stale within *hours*, and some historically *overclaimed*. Every concrete detail here (version numbers, commit hashes, file line numbers, "DONE/SHIPPED" claims) is a **hypothesis to verify against the live repo**, not gospel. The single most important cultural rule in this project is: **ground yourself against disk and `git` before acting.** When this doc and the disk disagree, the disk wins.

---

## 0. Your first 30 minutes (do this in order)

1. Read this whole handoff.
2. Open the Q&A folder (`…\Desktop\PDFTest Files\Q&A`) and read, in this order:
   - `Q&A_INDEX.md` — the live index of what's in flight.
   - the worker status log (`QA-2026-06-24_worker-status-log.md`) — **append-only**; read the tail to see who did what most recently.
   - the most recent `QA-*_reply-*.md` / question docs, especially `QA-2026-06-26_user-report-popup-and-alignment-regression.md`.
3. Verify ground truth on disk **before** editing anything:
   - list the repo roots; run `git -C <repo> status` and `git -C <repo> log --oneline -5` on each.
   - `git remote -v` on each repo to confirm the exact GitHub remote.
4. Only then pick work. Prefer work that doesn't collide with another worker's uncommitted changes (a dirty tree with a canonical-core edit propagated to embedded copies almost always means another session is mid-implementation — **leave it alone**).

---

## 1. The mission (north-star — Rowdy's own words)

> "…the most powerful, intuitive, user-friendly, versatile, etc., tools of their kind. Able to work on any device with any version of the parent software and os and hardware capable of using the code."

Translate that into priorities you weigh on every decision:

- **Portability / "it just works on a clean machine" is priority #1.** A default download must run on a fresh Windows PC with no terminal, no manual dependency install, no internet. If a change makes any host less likely to run out-of-the-box, that's a regression regardless of how nice the feature is.
- **Any version of the parent software** — SketchUp back to **2017**, and comparable floors for FreeCAD / LibreCAD / Blender. The oldest supported host is a hard constraint, not a nice-to-have (see the SU-2017 / Ruby-2.2 gate in §5).
- **Intuitive & user-friendly** — no gratuitous modals, no cross-host copy leaks, honest labels.
- **Versatile** — handle real-world drawing PDFs (dimensions, stacked fractions, BOM tables, rotated text, glyph-outline vs editable-text modes).

---

## 2. The repos (7)

Confirm exact on-disk paths and remotes yourself — the tree was reorganized once already (the old `C:\1pdfcadcore\…` layout is **dead**; `pdfcadcore` now lives *inside* FreeCAD).

| # | Repo (role) | Lang | Ships as | Key bundled deps | On-disk (verify) |
|---|---|---|---|---|---|
| 1 | **SketchUp importer** | Ruby extension | `.rbz` | **Poppler** stack (GPL) | `C:\1PDF-Importer-SketchUp` |
| 2 | **FreeCAD importer** | Python addon | zip + `Setup.exe` | **PyMuPDF** (AGPL); **canonical `pdfcadcore` lives here** | `C:\1PDF-Importer-FreeCAD` |
| 3 | **LibreCAD importer** | Python | source zip + **portable** (PyInstaller EXEs) | PyMuPDF, bundled **at build time** | `C:\1PDF-Importer-LibreCAD` |
| 4 | **Blender importer** | Python addon | zip | **PyMuPDF** (AGPL) | `C:\1PDF-Importer-Blender` |
| 5 | **Website** | web | deployed site | — | confirm path/remote on disk |
| 6 | **Steel Logic app** | (confirm) | (confirm) | — | confirm path/remote on disk |
| 7 | **Test corpus + shared tooling** | Python (stdlib) | n/a | — | `C:\1pdf-test-corpus` |

Notes:
- **The corpus repo is the neutral home for cross-host tooling** (`tools/`). Put ecosystem-wide utilities there, not inside one importer.
- The **Website** and **Steel Logic** repos are in scope — you are expected to build/improve them too, not just the importers. Their exact stack and current priorities aren't fully captured in the last session's notes; resolve that the project way: read each repo's `README` / `_LLM_CONTROL_PACK/` and its recent git history, don't wait on anyone.

---

## 3. Architecture (how the importers actually fit together)

- **`pdfcadcore`** is the shared **Python** extraction/config core. The **canonical copy is embedded in FreeCAD**, and it is **byte-synced** into the LibreCAD and Blender embedded copies. There is a **sync manifest** — when you touch the core, propagate to the embedded copies and **regenerate the manifest** (a core edit that appears in FC + FC-embedded-LC + FC-embedded-BL + a regenerated manifest is the fingerprint of legitimate in-flight core work).
- **SketchUp is a *separate Ruby port*** of the same conceptual logic, built on **Poppler** (not PyMuPDF). So a core behavior change usually needs a **parallel Ruby change in SketchUp**, not a byte copy. Don't assume "fixed in core" means "fixed in SketchUp."
- **Extraction pipeline (Python side):** PDF → `pdfcadcore/primitive_extractor.py` (text spans, stacked-fraction merging, rotation, bbox/positioning; entry point `extract_page(page, page_num)` → `PageData`) → `pdfcadcore/dimension_parser.py` (**purely semantic** — turns dimension strings into values for the report; it is *not* where placement/overlap bugs live) → host renderer.
- **Import modes:** editable text vs **Outlines/Glyphs** (non-editable outline geometry). The outline mode being non-editable is **by design** — see the honesty rule in §4. Don't "fix" it into claiming per-character editable glyphs; that exact overclaim was already corrected once.

---

## 4. Non-negotiable operating rules

1. **Never hand-bump versions.** An **auto-release bot owns version numbers**. **GitHub Releases are the source of truth; version files legitimately lag the tag** (often by one patch). Editing a version by hand fights the bot.
2. **Every code push mints a release** — *unless* it's docs-only / CI-only, in which case use **`[skip release]`** in the commit message and/or rely on the workflow's paths-ignore. **Know before you push whether you intend to ship.**
3. **Do NOT manually fire a production release** (`gh workflow run …`, dispatching `auto-release.yml`, etc.) without Rowdy's explicit go-ahead. Routine **commit/push is authorized**; minting public artifacts on demand is a separate, gated action. (There is even a safety layer that will refuse an unprompted release dispatch — respect it, don't route around it.)
4. **Keep `pdfcadcore` byte-synced** across the embedded copies; regenerate the sync manifest; keep the **SketchUp Ruby port in conceptual parity**.
5. **Honesty over polish.** No overclaiming in UI text, dialogs, READMEs, or release notes. Precedent: glyph description was corrected from "per-character vector glyphs" → **"non-editable outline geometry."** If something is lossy, non-editable, build-time-only, or unverified — **say so plainly.**
6. **Do NOT blind-fix visual/layout bugs.** Alignment, scaling, placement, and rotation must be verified **rendered in the actual host** with **before/after screenshots**. Blind heuristic-tuning is *precisely how the current regressions were reintroduced*. Workflow: **lock a core regression test → fix → verify in-host.**
7. **Concurrency discipline** (you are not alone in these trees):
   - re-read a file immediately before editing it; if it changed under you, re-read again.
   - `git fetch` + rebase before every push; **never force-push**.
   - stage **explicit paths**, not `git add .`.
   - never clobber another worker's uncommitted work.
   - mirror your Q&A reply docs into each repo's **`_LLM_CONTROL_PACK/QA/`**.

---

## 5. Release pipeline — how it actually works *now* (verify against the workflow files)

- **FreeCAD & LibreCAD build on `windows-latest`**, with `defaults: { run: { shell: bash } }` so the bash steps (heredocs, `set -e`, `$RUNNER_TEMP`) run under Git Bash on the Windows runner.
- **SketchUp & Blender build on `ubuntu-latest`** (bash is the default shell there; no shell override needed).
- **Every host gates before publish:**
  - **SketchUp:** SU-2017 **Ruby-2.2 compat check** (`check_su2017_ruby_compat.py`) + compat test + smoke → build `.rbz` → smoke the RBZ structure.
  - **Blender:** pytest gate → build → smoke the zip.
  - **FreeCAD / LibreCAD:** requirements check + **core-sync check** + preflight + pytest → build → **artifact smoke**.
- **Artifact smoke (the thing that guarantees "runs on a clean Windows PC"):**
  - **FreeCAD** `smoke_release_zip.py` **rejects any Linux `.so`** in the vendored lib, **requires the Windows `.pyd`** runtime, and imports PyMuPDF on `win32`.
  - **LibreCAD** portable smoke checks all **4 EXEs** and runs `pdf2dxf.exe --help`.
- **Two FreeCAD gotchas that already bit us (both fixed — confirm they stayed fixed):**
  - **Vendor PyMuPDF *before* the gate.** A diagnostics test imports the bundled PyMuPDF from `src/lib`, which is **gitignored/empty on a fresh checkout**; vendoring happens later in `build_release.py`. If the gate runs first, the test fails on CI but passes locally (because your `src/lib` is already populated). Vendor-then-gate.
  - **Create the tag/release with the built-in `GITHUB_TOKEN`** via `gh release create --target` / the gh API — **not a PAT**.
- **FreeCAD `main` is a protected branch (5 required status checks)**, so the bot **cannot push a version-bump commit** to it. FC is therefore effectively **tag-driven**, with a guard that **exits cleanly if the bump push is refused** (version files lag the tag — which matches the canonical "Releases are truth, files lag" model). **LibreCAD's `main` is not protected**, which is why LC sailed through when FC didn't.
- **Token hygiene:** the old **`RELEASE_BUMP_TOKEN`** PAT is **invalid and its repo secret was deleted**; CI now uses `github.token`. **Do not reintroduce that PAT.** (Rowdy: the raw token string was exposed in chat history — confirm it's revoked at the account level, not just removed as a secret.)
- **When you need to confirm a release actually shipped:** pull `gh run list` / `gh run view --log` — do **not** trust a doc that says "SHIPPED." We caught "SHIPPED" claims that were actually red CI runs.

---

## 6. Dependencies & licensing (this is a portability *and* a legal issue)

- **PyMuPDF 1.27.2.3** — license literally **"Dual Licensed — GNU AFFERO GPL 3.0 or Artifex Commercial License"** — vendored in **FreeCAD** (`…/src/lib/`) and **Blender** (`…/lib/`); **built into LibreCAD's portable at build time** (so LC's shipped bytes aren't auditable from committed source the way FC/BL are).
- **SketchUp bundles a full Poppler stack (GPL):** `poppler.dll` + `pdftocairo.exe` / `pdftotext.exe` / `pdffonts.exe` + `cairo` / `freetype` / `openjpeg` / `libcrypto` / `libcurl` / `libssh2` — ~**29 files, ~25 MB** — under `…/bc_pdf_vector_importer/bin/`, with a `licenses/` dir + `THIRD_PARTY_NOTICES.txt` **inside `bin/`**.
- **Third-party notice status:** Blender ✅ (`THIRD_PARTY_NOTICES.md`), LibreCAD ✅ (`THIRD_PARTY_LICENSES.md`), FreeCAD ✅ (`THIRD_PARTY_NOTICES.md`, added recently), **SketchUp root-level notice — still needed** (it only has one inside `bin/`).
- **Open compliance items (route AGPL judgment calls to Rowdy / counsel — you're not the lawyer):** these are **copyleft** deps bundled into freely distributed tools; the AGPL corresponding-source obligation on distribution is a real question. Consider adding a `corresponding_source_url` field where appropriate.
- **Manifest tool of record:** `tools/dependency_audit.py` in the **corpus repo** — **pure stdlib** (runs on any stock Python, no installs), emits `bcs.dependency_manifest/1.0` = **path · version · license · SHA-256** for every shipped binary, reading version/license from each package's own dist-info. Keep it green and extend it; it's how we prove "here's exactly what we ship."

---

## 7. Current priorities (in order — start at the top)

### P0 — Alignment / scaling regression (user-reported)
Full spec + reproduction: **`QA-2026-06-26_user-report-popup-and-alignment-regression.md`**.

- **Fraction overlap (FreeCAD; affects FC/LC/BL via the shared core).** Stacked fractions *do* merge, but into a **flat, full-size** token that occupies far more width than the original stacked fraction — so it **overruns adjacent text** (real examples from `1017 - Rev 0.pdf`: `4'-7/2`, `1'-0¾`, `13'-5/8`, `2 13/16⌀`). Drawing dimensions also split the whole-number from the fraction (`1'-3` and `1/8` as separate items). **Root cause:** `pdfcadcore/primitive_extractor.py::_merge_stacked_fractions` (≈ line 503; tolerances like `_FRAC_Y_SPREAD_MM = 4.5` — **line numbers will have moved, re-grep**). **Reproduces in pure Python** against `1017 - Rev 0.pdf` (no host needed) — run the extractor's `extract_page` and inspect the returned text items. **Fix direction:** render the merged fraction at reduced/stacked scale so its footprint matches the original. **Do it the right way:** lock a core regression test on the repro PDF *first*, then fix, then verify rendered in FC/LC/BL with before/after screenshots.
- **Rotated BOM "QUAN" digits (SketchUp; P1).** The shared core extracts BOM quantities at **rotation = 0 correctly**, so this is **not** the core — it's in the **SketchUp Ruby port's placement**, a regression of the old vertical-BOM fix. Fix in Ruby; verify rendered in SketchUp. (Genuinely rotated field dimensions at rot=90 are correct — don't "fix" those.)
- **Outlined "BILL OF MATERIAL" title.** Most likely just **Outlines/Glyphs mode** (non-editable by design) — **confirm** before treating it as a bug.

### P1 — UX
- The every-import modal was **removed entirely** (it also had a **cross-host copy leak** — a "LibreCAD users: this is SketchUp…" line inside the SketchUp dialog). **Relocate the genuinely-useful mode hint into the import dialog itself** — do **not** reintroduce a blocking popup, and never let one host's copy leak into another.

### P1 / P2 — Portability hardening (this *is* the north-star)
- **Antivirus/EDR false-positive quarantine of the unsigned bundled EXEs** (open question **Q-J1**). Defender/managed AV can silently delete LibreCAD's PyInstaller `lcpdf-gui.exe` or the unsigned FreeCAD `Setup.exe` with no prompt — SmartScreen guidance does **not** fix this. Evaluate **code signing**.
- **Windows-on-ARM** support.
- **OneDrive online-only placeholder PDFs** (files that aren't actually on disk) — handle gracefully.
- **Upgrade/uninstall DLL hygiene.**
- **Prune SketchUp's unused `OpenSSL` / `libcurl` / `libssh2`** (~8 MB it likely never uses) — bloat **and** CVE surface.
- **SketchUp root third-party notice** (see §6).

### Housekeeping
- **Re-run the ecosystem audit lenses** that were cut off by a usage limit: dependency-legal, portability, text-mode-truth, core-accuracy, cross-host-sync, and the legacy-SU-2017 lens. (23 findings across ~6 lenses were adversarially confirmed; the rest need a re-run.)

---

## 8. Environment, access, and build/test

- **Access model — "built-in, no questions asked":** the work machine already has all 7 repos cloned and `gh` authenticated; CI uses the built-in `GITHUB_TOKEN`. You operate inside that environment — you don't need any secret pasted to you, and **secrets must never be written into docs/commits.** If a repo won't build for lack of a credential, that's a repo/CI-settings issue, not something to paste into the Q&A folder.
- **Toolchain (verify with `--version`):** Python 3.12, Ruby 3.4, Node, Git, `gh` CLI. **Use PowerShell** (Windows Terminal defaults to it), **not** Command Prompt — the pipeline commands assume it.
- **Cross-target a Windows wheel from any host** (useful for reproducing/patching bundling): `pip download pymupdf --platform win_amd64 --python-version 3.10 --abi abi3 --implementation cp --only-binary=:all:` — this reliably fetches the correct `…-cp310-abi3-win_amd64.whl` even off a non-Windows host.
- **Reproduce the P0 fraction bug locally:** run `pdfcadcore`'s `extract_page` on `1017 - Rev 0.pdf` (in the corpus test files) and inspect the text items. A repro script existed last session; if it's gone, recreate a tiny one — it's ~20 lines.
- **Build & smoke per repo:** FreeCAD via `build_release.py` + `smoke_release_zip.py`; LibreCAD via its portable build + portable smoke; SketchUp `.rbz`; Blender zip. **Confirm the exact script names/paths on disk** before running.
- **Cross-host tooling** goes in the corpus repo's `tools/`.

---

## 9. Coordination protocol (the Q&A folder)

- **Location:** `…\Desktop\PDFTest Files\Q&A`. Everything is coordinated here **anonymously** — workers are known only by tags (e.g. Codex, "Cursor ecosystem worker", WS-RPIPE, "Anonymous reviewer").
- **`Q&A_INDEX.md`** = the live index — **edited concurrently**, so re-read right before editing and add rows surgically without overwriting others' additions.
- **Worker status log** = **append-only**; add **one** entry per session summarizing what you verified/changed.
- **Question/reply docs** = `QA-YYYY-MM-DD_<topic>.md`. **Mirror your reply docs into each repo's `_LLM_CONTROL_PACK/QA/`.**
- **Round etiquette** (from prior rounds): ask a **genuinely new** question; **answer the questions you did *not* ask**; drive to agreement; **then** implement + commit/push. If your evidence contradicts an existing "agreement," **say so and show the evidence** — that's expected, not rude.

---

## 10. Traps we already hit (so you don't)

- A doc said **"verified / SHIPPED"** but CI was actually **red** → always confirm with `gh run` logs.
- The **index, workflows, and worker log change mid-edit** → re-read, don't clobber, rebase before push.
- FreeCAD **HTTP 401** in release = the **invalid PAT**; a **~33s-fast** FC failure = the **gate**, not the build; a failure at **"push version bump"** = **branch protection** on FC `main`.
- **`src/lib` is empty on a fresh checkout** → any test importing bundled PyMuPDF fails unless you **vendor first**.
- The **`C:\1pdfcadcore\…` path is dead** → the canonical core is **FC-embedded**.
- **`pip install` with no platform pin on a Linux runner** grabs a **Linux** wheel and the import check passes *on Linux* — masking a broken Windows artifact. Pin the platform (see §8).

---

## 11. Authority & escalation

- Rowdy **delegated full latitude** to hash out fixes through the Q&A process — brainstorm, implement, test, commit, push — while he's away (as of the last session, back **Sunday/Monday evening**).
- **Two things are *not* delegated:** (a) firing a **production release** on demand — needs his OK; (b) **legal/licensing judgment calls** (AGPL/GPL) — route to him/counsel.
- Everything else: **build, improve, correct, perfect.** Start with the P0 alignment/scaling regression — it decides whether "runs on any PC and renders correctly" is actually true today.

---

*Welcome aboard. Verify against disk, keep the Q&A folder honest, don't fight the release bot, and screenshot your renders.*
