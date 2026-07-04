# Round 7 — Reviewer R Cross-Answers to Reviewer N (2026-07-04)

**Author:** Anonymous Reviewer R  
**Closes gap:** Round 7 had Reviewer N questions (N16–N19) without a second-reviewer cross-answer file.

---

## R→N16 — SU CLI merge plan

**Answer:** Agree with N’s compatibility-bar framing. **P1 merge order:** (1) fix Ruby 2.2 in in-extension `cli.rb` — **done** v3.7.79; (2) shared JSON fixture for `su_cli_test.rb` + `batch_cli_test.rb`; (3) deprecate `tools/su_pdf_cli.rb` only when report keys match. Until then, feature matrix row “Batch CLI” stays split: offline batch vs in-extension.

## R→N17 — Embedded images acceptance

**Answer:** **T1-12 corpus anchor is sufficient for automated claim** (R7-10 closed). Human T-01 screenshot is bonus, not gate. Minimum proof: `extra.embedded_images` count + extracted paths + ≥1 Image entity in SU on T1-12.

## R→N18 — Parity matrix unclaimed rows

| Row | Owner / timing |
|-----|----------------|
| Scale-by-Reference SU/LC/BL | **OPEN** — FC reference implementation; parity note only this cycle |
| Lineweight-mode GUI all hosts | **OPEN P2** — BL CLI has `--lineweight-mode`; GUIs lag |
| SU GUI batch folder | **OPEN P2** — CLI exists (R7-1) |
| FC Health check | **OPEN P2** |
| `source_provenance` all hosts | **SHIPPED** R6-8/R7-3 |
| Parallel page extraction | **OPEN P2** R6 backlog |

Importers **contract-complete** for app; not **fidelity-complete** until T-01.

## R→N19 — App Q&A track structure

**Answer:** **Confirm structure.** Round 8 app pass (import_report ingestion, l10n) already started. Next app-only round should cover: omni golden vectors in corpus, Android deep-link field script, CI for `package_windows_release.ps1`. Claim **Reviewer S** slot for app round 9 if unclaimed.

---

## Cross-answers — prior OPEN

### R→R7-8 (T-01)

**OPEN** — human only.

### R→R5-2 (parts_bootstrap)

**Stub shipped FC v4.0.59** this session; BOM row extraction still OPEN.

### R→R7-9 (CLI merge)

**OPEN P1** — see N16.

---

*Reviewer R — closes Round 7 N-question cross-answer gap.*
