# Round 4 — Reviewer D: Steel Logic App + Ecosystem

**Session:** 2026-06-24  
**Persona:** Anonymous — product strategist who sees PDF → fab → inventory as one story  
**Mandate:** Cross-product magic without fantasy integration.

---

## What we already have

- **Steel Logic** (Structural_Steel_Shapes_App): AISC v16 reference, SVG blueprints, inventory — mobile-first.
- Shape packs merged into SU (`steel_shapes/family_packs/`) and FC (`steel_shapes/dxf|dwg/`).
- Website `/shapes` hub + README cross-links (Round 3).
- Generic classifier in SU pipeline (`fabrication` profile) — under-marketed.

---

## Outside-the-box ideas (≥5)

### D-1 — PDF → steel workflow story (one diagram, honest steps)

**Idea:** Document the real flow: Import PDF → detect W-shape callouts → insert from family pack OR verify in Steel Logic → inventory tag.

**Why it matters:** Users buy importers and app separately; ecosystem value is invisible.

**Status:** README ecosystem paragraph recommended this session; website matrix links importers to shape hub.

---

### D-2 — Shape library intelligence (designation parser)

**Idea:** When PDF text spans match `W\d+×\d+`, offer batch “Create placeholders” using nearest AISC designation from Steel Logic API/local DB.

**Why it matters:** Accuracy for BOM-style sheets; excitement for engineers — structured steel without manual hunt.

**Host limit:** SU components yes; LC DXF blocks yes; BL collections yes — shared parser in pdfcadcore `generic_recognizer` extension.

---

### D-3 — Cross-product deep link (`steellogic://shape/W10x22`)

**Idea:** From import report `extra.domain_hints`, open Steel Logic to that shape’s blueprint page.

**Why it matters:** Mobile reference + desktop CAD = complementary, not competing.

**Effort:** Moonshot — needs app URL scheme + importer UI affordance.

---

### D-4 — Release train alignment (`steel-v*` tags)

**Idea:** Single changelog slice when shape packs bump — website shows compatible importer min versions.

**Why it matters:** Version skew breaks trust (“your W12 pack doesn’t match importer 3.7.40”).

---

### D-5 — Fabricator inventory export from import metadata

**Idea:** Optional CSV from import report: layer names, text callouts matching shape regex, quantities if detected.

**Why it matters:** Shop floor wants parts list, not just lines. Steel Logic inventory could ingest CSV later.

---

### D-6 — Website “ecosystem map” hero strip

**Idea:** One visual: PDF Importers ↔ Shape Packs ↔ Steel Logic — three boxes, two arrows, no vaporware connectors.

**Why it matters:** Marketing fluff fails; honest map excites engineers who hate lock-in.

---

## Peer challenges

**To Reviewer A:** Component repeat detection is great — tie it to shape pack insertion for repeated W-section symbols on fab drawings.

**To Reviewer C:** Preflight should mention Steel Logic only when classifier confidence > threshold — don’t nag architects importing floor plans.

---

## Rank self (impact / effort)

| Idea | Impact | Effort |
|------|--------|--------|
| D-1 ecosystem docs | Medium | Low |
| D-2 designation parser | High | High |
| D-4 release alignment | Medium | Medium |
| D-6 website map | Medium | Low |
| D-5 CSV export | Medium | Medium |
| D-3 deep link | Low (niche) | High |

---

*Reviewer D — Round 4, 2026-06-24*
