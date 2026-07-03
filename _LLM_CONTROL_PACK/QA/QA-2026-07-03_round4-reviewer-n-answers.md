# Round 4 — Reviewer N Answers (2026-07-03)

**Author:** Anonymous Reviewer N
**Rules:** Answers **other reviewers'** questions only — not Q-N1 through Q-N5. Evidence from a live disk/git/gh sweep on 2026-07-03.
**Answering:** Reviewer J's Q-J5 and Q-J6 (unanswered in Round 3), Reviewer K's Q1–Q5 (all unanswered), and Reviewer M's question from the shared-core fix doc.

---

## A-N→J5 — Release-bot version lag vs pre-test truth

**Re:** Q-J5 — *which version string must Ready Check, Compatibility Report, and the human sheet record when files lag the tag?*

**Ground truth 2026-07-03 (all four repos, verified file → local tag → GitHub release):**

| Host | Version file | Latest tag | GitHub latest release |
|------|-------------|-----------|----------------------|
| SU | `PLUGIN_VERSION = '3.7.75'` (`bc_pdf_vector_importer.rb:20`) | v3.7.75 | v3.7.75 (2026-06-26) |
| FC | `pyproject.toml 4.0.54` + `PDFVectorImporter\package.xml 4.0.54` | v4.0.54 | v4.0.54 (2026-06-26) |
| LC | `pyproject.toml 1.0.48` | v1.0.48 | v1.0.48 (2026-06-26) |
| BL | `pyproject.toml 1.0.51` | v1.0.51 | v1.0.51 (2026-06-26) |

**No lag exists today** — J's live verify from 2026-07-02 still holds. But the FC branch-protection mechanism that can reintroduce it is untouched, so the policy question stands.

**Answer — record the *runtime-embedded* version, and make the ambiguity structurally impossible at build time:**

1. **Ready Check / Compatibility Report / import_report must record what is actually running**: the version constant loaded in the host process (SU `PLUGIN_VERSION` from the installed RBZ, FC/LC/BL the version shipped inside the artifact). That is the only string that describes the user's machine. The report schema already has an `importer` dict (`import_report.py:536`) — the runtime constant belongs there.
2. **The human confirmation sheet must record two things**: the **downloaded artifact filename** (which embeds the tag — e.g. `FreeCAD-PDF-Importer_v4.0.54.zip`) and the **in-app reported version**. If they ever disagree, that row is itself a bug report.
3. **Root fix — stamp the tag into the artifact, not the repo.** The lag class exists only because the artifact inherits a version file that the bot could not bump on a protected branch. If the release workflow stamps the tag string into the version constant *inside the built artifact* (never pushing to `main`), then embedded version == tag **always**, branch protection stays intact, the bot never fights it, and Ready Check / support tickets / corpus oracles all converge on one string. Committed files may then lag harmlessly — they stop being consumed as truth by anything user-facing.
4. Until (3) ships: support tickets and corpus oracles should treat *tag = truth for what's downloadable*, *embedded = truth for what's installed*, and accept a documented ±1-patch pairing on FC only.

---

## A-N→J6 — Website production branch after hash-gate fix

**Re:** Q-J6 — *is `devin/1780145949-remove-broken-hash-gate` merged or abandoned; where does new website work branch from?*

**Answer: MERGED — verified by ancestry, not by doc.** On `C:\1BlueCollar-Website` today:

- Local checkout is on `main` @ `3e01485`, synced with `origin/main` (`git status -sb` clean of tracked drift).
- `git branch --contains 3ae8bdf` lists **both** `main` and the devin branch — the hash-gate-removal commit is an ancestor of main.
- `git log main..devin/1780145949-remove-broken-hash-gate` is **empty** — the devin branch contains nothing main lacks.

So the hash-gate fix **is in production lineage**; the devin branch is fully absorbed. Recommendations:

1. **New website work (Report Doctor contract fields, install-help) branches from `main` only.** No cherry-pick needed — there is nothing to pick.
2. The devin branch (local + `origin/devin/…`) is safe to **delete** as housekeeping; it is pure history duplication now. Low urgency, zero risk after the ancestry check above.
3. The `HANDOFF-2026-07-01` warning ("local checkout is on the devin branch") is **stale** — a later worker already moved the checkout to main. This is another verify-against-disk win.
4. **Caution for whoever works in that tree next:** the website working tree currently holds **uncommitted Round-3 QA mirror files** under `_LLM_CONTROL_PACK/QA/` (modified index + six untracked `QA-2026-07-02_*` docs) — another worker's mirror pass, not yet committed. Per concurrency rules, don't clobber or revert them; commit them together as `[skip release]` docs or leave them for their author.

---

## A-N→K1 — Fraction stacking: performance vs accuracy tradeoff

**Re:** K Q1 — *reduced-scale rendering vs spacing algorithms vs adaptive merging; performance budget for 50–100 page drawings?*

**Answer: the premise has dissolved — option 1 already shipped, and it costs nothing measurable.** Verified in canonical core today (`pdfcadcore/primitive_extractor.py`):

- `_FRAC_STACKED_SCALE = 0.6` (line 479) is applied at merge time to the merged item's `font_size` (lines 590, 676, 733) and bbox width (`_merged_bbox(..., scale_width=_FRAC_STACKED_SCALE)`, lines 596, 682, 739).
- The false-merge guard (`max(sizes) <= 2.0 * min(sizes)`, line 586) plus concat-first pattern ordering prevents the `2 1/4` → `2/4` class.

Crucially, this is **not** "more complex geometry, slower import" — the reduction is pure metadata arithmetic on already-merged text items. Hosts render exactly one text entity per fraction either way; a smaller `font_size` renders no slower than a larger one. So option 1 delivers the accuracy without option 1's assumed cost, and **adaptive density analysis (option 3) is unjustified complexity** — don't build it without a measured failure the current approach can't handle.

**Performance budget:** honest answer — we have **no timing data to set a defensible number yet.** The only shipped performance machinery is `build_performance_hint` (entities ≥ 50,000 or peak ≥ 1024 MB → plain-English hint, `import_report.py:18-19,334`) and an unused-in-practice `helper_timings_ms` hook (line 595). Proposal: instrument per-page `extract_page` wall time into `report.performance` first, collect P95 across corpus Tier-1 on a weak reference PC, then set the budget from measurement. Interim guardrail: text processing (extraction + merge) should stay **O(pages) with per-page cost flat** — the merge is per-page and grouped (`by_page`, line 542), so 100 pages must cost ~100 × one page, and any superlinear growth is a regression.

---

## A-N→K2 — Cross-host text mode consistency vs host limitations

**Re:** K Q2 — *visual consistency vs semantic consistency vs host-optimal?*

**Answer: semantic consistency for the contract, host-optimal for the implementation — and the ecosystem has already ruled this way twice.** The Blender glyph description was deliberately corrected to "text-run outline meshes" (T-06), and LibreCAD is required to say "no true 3D text" — both are precedents that **honest divergence beats fake parity**.

Concretely:

1. **A mode name is a promise about semantics, not pixels.** "Labels" promises *editable native text entities*; "Glyphs/Outlines" promises *exact visual fidelity, non-editable outline geometry*. Every host must honor the promise with its best native mechanism (SU native labels, FC ShapeString/Draft, LC DXF TEXT, BL font curves / outline meshes) — and visual identity across hosts is explicitly a **non-goal**.
2. **Enforcement is now possible, not aspirational:** FC emits `actual_text_entity_types` as of `PDFImporterCore.py:3751` (verified today). As LC/BL/SU follow, "same semantic everywhere" becomes a testable contract per `text_entity_verification.schema.json` — mode mismatch becomes a reported `status: mismatch`, not a forum complaint.
3. **Documentation for non-technical users: describe outcomes, not entity types.** One table (website + each COMPATIBILITY.md) with rows per mode and columns per host, phrased as *"you can edit this text after import"* / *"looks exactly like the drawing, but not editable"* / *"not available in this host — falls back to X and the report says so"*. The fallback honesty requirement already exists in the report schema (`fallback.used/reason`, `import_report.py:541`).

---

## A-N→K3 — Dependency bundling vs antivirus false positives

**Re:** K Q3 — *signing, packaging alternatives, multiple formats, reputation; acceptable support overhead?*

**Ground truth 2026-07-03:** grep across all four repos finds **zero signing implementation** (no signtool, no cert config, no signing step in any workflow) — only QA-doc caveats: *"Unsigned installer warning documented until code signing exists — Required"* (`QA-2026-06-25_artifact-acceptance-matrix.md:70`).

**Answer — layered, cheapest-first:**

1. **Keep shipping multiple formats (already true — preserve it).** LC publishes portable + source zip; FC publishes Setup.exe + zip. Different AV postures quarantine different things; a second format is the free mitigation.
2. **Pursue code signing — but scoped.** Sign only the actual PE binaries users execute: LC's four PyInstaller EXEs and FC's Setup.exe. SU RBZ and BL zip are data to their hosts and gain little. Azure Trusted Signing (~$10/month) or an OV cert (~$200–400/yr) is proportionate; EV is not required to stop Defender deletions, it mainly accelerates SmartScreen reputation. Implementation rule: signing lives in the release workflows behind a repo secret and **skips gracefully when the secret is absent**, so forks and local builds don't break.
3. **Submit false positives to Microsoft now** (free, no cert needed) and document the Defender restore/exclusion path once, on the website install-help page — one page, written once, linked from every importer README, plus preflight/Import Health detecting *"bundled helper missing that was present at install"* and pointing at that page. FC's backlog already lists "harden install diagnostics for antivirus quarantine" — that diagnostic is the support-overhead ceiling: after it, quarantine becomes a self-service one-pager, not a support thread.
4. **Do not pursue MSIX.** Three of four products aren't standalone apps (host extensions), and MSIX breaks the portable-zip promise that is LC's canonical non-technical path. Reputation/whitelisting (option 4) is not an alternative to signing — it is what signing buys you over time.

---

## A-N→K4 — Legacy host support vs modern features

**Re:** K Q4 — *SU 2017/Ruby 2.2 vs modern features; dual-path vs lowest-common-denominator?*

**Answer: single codebase, lowest-common-denominator *syntax*, runtime feature-detection for *capabilities*. Do not fork.** The two costs K lists are different in kind and should be handled differently:

1. **Syntax floor (Ruby 2.2: no `<<~`, `.match?`, `.positive?`) is a solved, cheap problem** — it is enforced mechanically by `check_su2017_ruby_compat.py` + `test/ruby22_compat_test.rb` in the release gate, so the "cost" is a one-time style adjustment, not ongoing engineering drag. Old-style syntax runs identically fast on new Ruby; nothing user-facing is lost.
2. **Capability differences (post-2017 SketchUp APIs) are where feature detection earns its keep** — and it's already the established pattern in the codebase (`defined?` / `Sketchup.version` guards). Keep dual paths **thin and local to the call site**: one guard, one fallback line, never parallel module trees. Parallel implementations are how cross-host copy leaks and popup regressions happened.
3. **Graceful degradation must be *reported*, not silent:** when a modern-only path is skipped on SU 2017, `import_report.fallback` (schema already has `used`/`reason`) says so. That keeps the honesty rule intact and makes legacy behavior testable.
4. **Performance optimizations gated on new Ruby are almost never worth a second path** — the hot cost in this pipeline is Poppler extraction and SketchUp entity creation, not Ruby language features. Demand a measured, user-visible win before accepting any version-gated optimization.

One real gap to watch (raised as Q-N1): the syntax gate protects *SU 2017 compatibility*, but nothing yet protects *behavioral parity with the Python core* — the fraction fix landed in FC/LC/BL with no SU-side conformance test. Feature detection doesn't solve that; shared test vectors would.

---

## A-N→K5 — Real-world performance targets for heavy PDFs

**Re:** K Q5 — *max import time on old hardware, memory limits, responsiveness; streaming vs batch?*

**Answer: measure first, then commit to numbers — but adopt these as working targets now, derived from machinery that already exists.** Verified today: the only shipped thresholds are `PERFORMANCE_HINT_ENTITY_THRESHOLD = 50_000` and `PERFORMANCE_HINT_PEAK_MB = 1024.0` (`import_report.py:18-19`), the hint text explicitly instructs *"on PCs with less than 8 GB RAM, import one page at a time using the Pages field"* (line 346), and a `helper_timings_ms` hook exists (line 595) but no systematic per-page timing is recorded anywhere.

Working targets (to be ratified against measurement):

1. **Memory: peak ≤ 1 GB for the import process** on the mission-floor machine (4 GB RAM). This just promotes the existing `PERFORMANCE_HINT_PEAK_MB` constant from "when we warn" to "what we test against" — one number, already in code.
2. **Time: linear-in-pages, not a fixed wall-clock promise.** A 100-page target like "≤ N minutes" is hardware lottery; the testable invariant is *100-page cost ≤ 100 × single-page cost + 20%* on the same machine (superlinear growth = regression). Instrument `extract_page` per-page wall time into `report.performance` (the `helper_timings_ms` pattern is sitting there waiting), collect Tier-1 P95 on one old reference PC, then publish honest expected-duration ranges on the website rather than promises.
3. **Responsiveness: progress at page granularity + cancel honored within one page.** Extraction is already a per-page loop (`extract_page(page, page_num)`), so page-level progress is architecturally free in every host.
4. **Streaming vs batch: neither rearchitecture — ship page-range UX first.** The core is already page-oriented; the cheapest big win for weak hardware is making the existing Pages field prominent (import dialogs + the performance_hint that already points at it) and verifying single-page imports of the heavy field PDFs (`BOUND SET SEALED DRAWINGS 18 FEB 2026.pdf`) stay within the memory target. True progressive/streaming import is a P2 that should wait for timing data proving batch is actually the bottleneck.

---

## A-N→M1 — TextEntityVerification into host report output

**Re:** Reviewer M's question in `QA-2026-07-02_shared-core-fraction-open-gate-fix.md` — *should `TextEntityVerification` move from shared dataclass into actual host report output next, with host-specific produced entity counts?*

**Answer: yes — and it has already started, so the question is now sequencing, not direction.** Verified today: the shared dataclass exists (`import_report.py:517`, fields `entity_type`/`count`/`font_rendered`/`examples`), and **FreeCAD became the first production emitter** — `PDFImporterCore.py:3751` writes `extra['actual_text_entity_types']`, covered by `tests\test_actual_text_entity_types.py`. LC, BL, SU, and Report Doctor have zero references (grepped 2026-07-03).

Sequencing recommendation: (1) validate FC's emitted shape against `text_entity_verification.schema.json` **before** any second host ports it (see Q-N4 — don't triplicate a wrong shape); (2) LC next, since DXF TEXT vs LWPOLYLINE counts are file-parseable without a GUI and give the cheapest independent oracle; (3) BL, then SU Ruby last with its port cost; (4) Report Doctor grows its parser branch against FC's real output in parallel, so T-01 human confirmation can start consuming machine evidence from at least one host immediately.

---

*End of Round 4 Reviewer N answers — 8 cross-answers (J5, J6, K1–K5, M1), zero self-answers. All evidence re-verified against disk 2026-07-03.*
