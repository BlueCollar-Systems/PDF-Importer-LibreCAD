# Round 3 — Reviewer J Questions (2026-07-02)

**Author:** Anonymous Reviewer J  
**Rules:** Questions only — no self-answers. Respond in `QA-2026-07-02_round3-reviewer-j-answers.md` or a peer answer doc.  
**Context:** Ground-truth sweep 2026-07-02; handoffs `HANDOFF-2026-07-01` + `QA-2026-07-02_new-contributor-handoff.md`.

Round 2 (F/G/H/I) covered offline install, font substitution, roaming profiles, and PDF JavaScript. Round 1 (E) covered preflight parity, legacy hardware, SU 2017 API, scale trust, and Steel Logic handoff. This round targets **pre-test contracts, P0 core accuracy, release/version truth, human-confirmation automation, and app bridge gaps** not yet locked for implementation.

---

## Q-J2 — P0 stacked-fraction footprint contract (pdfcadcore)

**Reviewer:** J (core accuracy / cross-host)  
**Host scope:** FC, LC, BL via `pdfcadcore/primitive_extractor.py`; SU Ruby port must mirror behavior  
**Why it matters:** `1017 - Rev 0.pdf` still produces merged flat tokens (`1/8`, `7/16`) at full `font_size` after `_merge_stacked_fractions`, overrunning adjacent whole-number spans (`4'-7/2`, `13'-5/8`, `2 13/16⌀`). FC v4.0.54 bbox-fit mitigates *render* overflow but does not fix the normalized primitive footprint that LC DXF TEXT and BL text curves inherit.

**Question:** Should the merged `NormalizedText` carry a **reduced effective `font_size` and/or stacked-fraction metadata** at merge time (so all hosts share one footprint), or should each host renderer shrink independently — and what exact bbox/width assertions must the core regression test lock before any host claims the P0 closed?

---

## Q-J3 — `actual_text_entity_types` rollout order and CI gate

**Reviewer:** J (pre-test contracts / corpus)  
**Host scope:** All four importers + website Report Doctor + corpus schemas  
**Why it matters:** `PRETEST_ACCEPTANCE_CONTRACTS.md` and `schemas/text_entity_verification.schema.json` require `actual_text_entity_types`, but a 2026-07-02 code grep shows **zero production emitters** in SketchUp Ruby or `pdfcadcore/import_report.py` — only Q&A references. R2-8 shipped `performance_hint`; text-entity proof is still aspirational.

**Question:** What is the agreed **host rollout order** (which importer ships the field first), should it live in `import_report.extra` vs a separate `text_entity_verification.json` sidecar, and should corpus `validate_contract_schemas.py` become a **release-blocking gate** once any host emits the field?

---

## Q-J4 — Human confirmation sheet automation (T-01 unblock)

**Reviewer:** J (field validation / website)  
**Host scope:** `QA-2026-06-24_human-confirmation-script.md`, all hosts, Report Doctor  
**Why it matters:** T-01 remains blocked on manual screenshot retest. The human script still records stale build versions (SU 3.7.63, FC 4.0.45) and checkbox-only evidence. Ready Check and Text Entity Verification schemas exist in the corpus but are not wired into the sheet or Report Doctor (no `ready_check` / `actual_text_entity` handling in `report-doctor.html` as of 2026-07-02).

**Question:** Should the next human-confirmation pass require testers to attach **machine-readable artifacts** (Ready Check JSON, import_report with `actual_text_entity_types`, corpus `list_tier1.py --resolved` output) alongside screenshots — and who owns automating pass/fail summary generation so T-01 is not purely subjective?

---

## Q-J5 — Release-bot version lag vs pre-test truth

**Reviewer:** J (release pipeline / cross-repo)  
**Host scope:** FC protected `main`, LC/SU/BL auto-release, website `repo-metadata.json`, human confirmation  
**Why it matters:** Handoffs disagree: `HANDOFF-2026-07-01` lists committed versions matching GitHub (`FC 4.0.54`, `SU 3.7.75`); `QA-2026-07-02_new-contributor-handoff` states **GitHub Releases are truth and version files legitimately lag the tag**. Live verify 2026-07-02: `gh release view` → SU `v3.7.75`, FC/LC/BL latest match `pyproject.toml` / `PLUGIN_VERSION` on clean `main` trees — **no lag today**, but FC branch protection can reintroduce it on the next bump.

**Question:** When `package.xml` / `pyproject.toml` lag the published tag by one patch, what version string must **Ready Check, Compatibility Report, and the human confirmation sheet** record — committed file, release tag, or RBZ/ZIP embedded metadata — so support tickets and corpus oracles stay consistent?

---

## Q-J7 — Steel Logic `import_report` bridge minimum schema

**Reviewer:** J (Steel Logic app / T-10)  
**Host scope:** `C:\1 Structural_Steel_Shapes_App`, website capability matrix, importers  
**Why it matters:** PDF Callout Lookup is shipped (Tools menu, local parse). Full `import_report.json` ingestion for BOM/takeoff remains open (T-10). No Dart parser for `bcs.import_report/1.1` was found in `lib/` on 2026-07-02.

**Question:** For the **first ingestion slice** (not full BOM), which `import_report` fields are mandatory — e.g. `extra.domain_hints`, `tables[]`, `text_spans` with `generic_tags`, `human_summary` — and should Steel Logic accept **paste/upload** of the whole JSON or only a trimmed callout bundle exported by Report Doctor?

---

## Q-J6 — Website production branch after hash-gate fix

**Reviewer:** J (website / deploy)  
**Host scope:** `C:\1BlueCollar-Website`  
**Why it matters:** `HANDOFF-2026-07-01` warned the local checkout was on `devin/1780145949-remove-broken-hash-gate` while `origin/main` was separate. Ground truth 2026-07-02: local `main` is checked out at `3e01485`, synced `origin/main`; devin branch still exists at `3ae8bdf` with the hash-gate removal commit.

**Question:** Is `devin/1780145949-remove-broken-hash-gate` **merged or abandoned** for production Cloudflare Pages — and should new website work (Report Doctor contract fields, install-help) branch from `main` only, or cherry-pick the hash-gate fix if it is not yet on `main`?

---

*End of Round 3 Reviewer J questions — awaiting cross-answers from other reviewers (do not answer your own).*
