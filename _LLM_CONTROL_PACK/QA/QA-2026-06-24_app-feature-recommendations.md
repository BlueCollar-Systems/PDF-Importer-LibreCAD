# Steel Logic + Importer Ecosystem — Feature Recommendations (2026-06-24)

**Session:** Human confirmation prep · competitive scan (fab shops, mobile steel, QR/deep links) — **not copying**, prioritizing BlueCollar differentiators.

---

## P0 — Confirm in human session (ship next if validated)

| ID | Feature | Rationale | Hosts | Status |
|----|---------|-----------|-------|--------|
| P0-01 | **Human confirmation checklist + tier-1 corpus CLI** | Fab shops need repeatable “open these 10 PDFs, these text modes, pass/fail” without engineering jargon | All + website | **Shipped this session** (`HUMAN_CONFIRMATION.md`, `list_tier1.py`, manifest) |
| P0-02 | **Scale cross-check banner in import_report** | #1 shop-floor trust issue after import | pdfcadcore, SU, FC, LC, BL | Shipped Round 5 |
| P0-03 | **Golden oracle harness wired to named PDFs** | Regression on 1017-class drawings without full corpus CI | SU (+ FC mirror) | **Extended this session** |
| P0-04 | **Preflight plain-English copy** | Reduces “wrong text mode” support tickets | INSTALL, website `#install-help`, SU dialog | Shipped Round 5 |
| P0-05 | **Part-mark → shape lookup from PDF callout** | Tekla/SDS2 users expect W12×26 tap-to-lookup; Steel Logic already has AISC v16 | Steel Logic app | **Partial** — add “lookup from clipboard” + deep link `steellogic://shape/W12X26` |
| P0-06 | **import_report QR / file URI handoff** | Foreman scans QR on paper traveler → opens Report Doctor or Steel Logic job note | Website Report Doctor, app | **Deferred** — needs stable public URL schema |

---

## P1 — High value after P0 validation

| ID | Feature | Rationale | Hosts |
|----|---------|-----------|-------|
| P1-01 | **PDF page thumbnail preflight in SU/FC** | Pick rotated/layer-heavy page before full import | SU, FC |
| P1-02 | **OCG layer picker UI** | GWG/NIST sets fail silently when all layers import | SU, FC, BL |
| P1-03 | **BOM/table column detector** | Quantity rotation (1017-class) + CSV export | pdfcadcore, SU, FC |
| P1-04 | **CLI `--preflight` one-liner** | LC/BL headless shops | LC, BL |
| P1-05 | **span_quality aggregate in human_summary** | Plain “3 spans weak” vs raw JSON | pdfcadcore |
| P1-06 | **Steel Logic job clock tied to import_report hash** | Prove which PDF revision was on the floor | App |
| P1-07 | **Website “open importer help” deep links** | `bluecollar-systems.com/#install-help?host=sketchup` | Website |
| P1-08 | **Mobile offline shape pack sync** | Field lookup without network | App |

---

## Competitive scan (patterns, not clones)

| Product / pattern | What shops like | BlueCollar response |
|-------------------|-----------------|---------------------|
| SDS2 / Tekla PowerFab PDF markups | Mark ↔ member link | Shape lookup + import_report part inventory |
| StruCalc / CalcSteel web | Browser scale, no install | Keep desktop importers + Report Doctor |
| Bluebeam Revu | Layer toggle, measurement | OCG tag mapping (SU), scale cross-check |
| Procore / Fieldwire QR | Deep link to sheet | Report Doctor URL + future app QR |
| Generic PDF→DXF converters | One-click | Honest capability matrix + preflight copy |

---

## Moonshot (post human confirmation)

- WASM pdfcadcore in browser (Round 4 R4-27)
- NL import (“import page 2 labels only”)
- Self-learning placement hints from human confirmation outcomes

---

## Human session agenda (60–90 min)

1. Tier-1 PDFs × text modes (see `QA-2026-06-24_human-confirmation-script.md`)
2. Sign off P0-05 shape lookup UX mock
3. Reject/defer P1 items with shop priority vote
4. Capture screenshots → `PDF Importers Screenshots/`

*Recommendations for human confirmation — 2026-06-24*
