# Round 5 — Reviewer P Questions (2026-07-03)

**Author:** Anonymous Reviewer P  
**Rules:** Questions only — no self-answers. Respond in `QA-2026-07-03_round5-reviewer-p-answers.md` or a peer answer doc per `Instructions 0607202613216.txt`.  
**Theme (owner-directed):** *What haven't we thought of? What can be added or improved? How do we make this more powerful?* Owner is field-testing importers; this round targets **shop-floor capture, physical-tag ↔ digital bridges, omni-box gaps, and importer→app automation** not locked in Rounds 2–4. Reviewer N's Round 5 questions (Q-N6…Q-N11) cover lifecycle schema, URL tags, and telemetry — this doc asks **complementary** angles.

**Context sweep:** 2026-07-03 — Steel Logic has `lib/core/omni/` (calculator + intent routing to inventory/time/search), `inventory_screen.dart`, `time_clock_service.dart`, PDF Callout Lookup; importers emit `import_report.json` with `text_spans`, `generic_tags`, `tables[]`; corpus owns `source_provenance.schema.json` but no host emitter; R3-6 (Steel Logic bridge) and R3-4 (artifact version stamp) remain **OPEN**.

---

## Q-P1 — KettleTag® PLUS EZ and shop tag symbology: what must v1 actually read?

**Reviewer:** P (shop-floor / physical tracking)  
**Host scope:** Steel Logic app (camera/scanner), optional website tag-resolve page, importers (BOM export for tag assignment)  
**Why it matters:** InfoSight KettleTag® PLUS EZ and similar metal tags survive galvanizing; shops already buy them. Round 5 Q-N6 asks lifecycle breadth; this question locks **hardware compatibility and payload content** before we pick a scanner library or data model.

**Question:** For a first shipped scanner slice tied to fabricated-part tracking, what is the agreed **symbology floor** and **tag payload standard**?

| Option | Detail |
|--------|--------|
| **(a) Read-only legacy** | Support Code 128 / Code 39 only — match tags the shop already laser-etches (piece mark + job number). No BCS-printed tags in v1. |
| **(b) BCS QR standard** | Shops may use KettleTag or our printable sheets; v1 reads QR + Code 128, encodes `bcs://part/<opaque-id>` or URL per Q-N10. |
| **(c) Dual-mode assign** | Importer exports piece marks from BOM → app assigns opaque IDs → user prints BCS QR sheets *or* hand-associates existing KettleTag barcodes via one omni-box phrase: `link tag 884422 to B-14`. |

Sub-questions:
1. Minimum module size / contrast guidance for post-galv reads (document in app help, not code)?
2. Camera-less fallback: same omni-box accepts manual tag ID entry with fuzzy match on piece mark?
3. Does the scanner live on **Inventory**, **Time Clock**, and **Omni-Box** equally, or one canonical entry point?

**Agreement looks like:** Written symbology table in corpus `docs/shop_tag_standard.md`; v1 ships (b) or (c) with Code 128 + QR; manual entry fallback required; one canonical scan entry (proposal: omni-box prefix `scan` / camera icon on home).

---

## Q-P2 — Importer `tables[]` → Steel Logic parts: zero re-type BOM bootstrap

**Reviewer:** P (importer ↔ app bridge)  
**Host scope:** All four importers (`import_report.tables[]`, `text_spans` with `generic_tags`), Steel Logic inventory/parts, corpus schema home  
**Why it matters:** R3-6 (Q-J7) locked a *minimum schema* debate (Report Doctor trimmed bundle vs full JSON). Shops still **re-type every piece mark** after import. Round 5 Q-N7 proposes `bcs.part/1.0`; this question asks for the **first automation slice** from data we already extract.

**Question:** Should importers gain an optional **`parts_bootstrap.json` sidecar** (or `import_report.extra.parts_candidates[]`) emitted when BOM tables or piece-mark spans are detected — each row `{piece_mark, quantity, profile_hint, source_pdf_sha256, page, span_ids[]}` — so Steel Logic can **one-tap import** into a `parts` table without parsing full report JSON?

| Option | Tradeoff |
|--------|----------|
| **Sidecar file** | Easy paste/upload; Report Doctor can strip PII; schema lives in corpus. |
| **`extra` inline** | Single artifact; larger reports; same schema. |
| **App-only parser** | No importer change; app reads `tables[]` directly — fragile across host report shapes. |

**Agreement looks like:** Corpus schema `bcs.parts_bootstrap/1.0`; FC first emitter (already has richest report); Steel Logic accepts file drop or Report Doctor export; duplicates merge on `(project_id, piece_mark)` with user confirm; ties forward to tag assignment (Q-P1 / Q-N6).

---

## Q-P3 — Omni-box shop-floor gaps: what's still missing for gloves-on power?

**Reviewer:** P (Steel Logic app / App instructions.txt)  
**Host scope:** `lib/core/omni/`, `omni_box_screen.dart`, inventory, time clock  
**Why it matters:** `App instructions.txt` (2026-07-03) demands omni-box parity across calculators, search, inventory, and time tracking with **zero instructions** and arbitrary precision. `QA-2026-07-03_app-omni-coordination.md` documents P0 precision defects (`150mm / 2.5ft` crash, 34-digit cap). Round 5 Q-N9 asks calculator *domain packs*; this question targets **cross-module shop-floor gaps** after precision lands.

**Question:** Which omni-box capabilities are **missing or stubbed** today, and what order ships them?

1. **Compound shop queries** — e.g. `find W10x22 under 20ft in bay 3 added this week` (inventory NL + date + location fields exist?)  
2. **Scan/voice prefix routing** — `scan`, `log 2h welding B-14`, `weight W12x26 x 30ft` from one field without mode picker  
3. **Tape-linked time** — calculation tape step `@3` inserts into time entry description automatically  
4. **Offline queue visibility** — user sees pending sync count for inventory/time without opening settings  
5. **Error recovery** — failed parse proposes correction (`Did you mean 2h 15m?`) per instructions §5  

**Agreement looks like:** Ranked backlog in app repo; P0 remains Rational storage fix; P1 = intent router covers scan + time + weight without navigation; P2 = compound inventory queries; each ships with one golden omni phrase test.

---

## Q-P4 — OUTSIDE THE BOX: Reverse tag workflow — scan physical part → PDF callout context

**Reviewer:** P (outside-the-box / fabrication physics)  
**Host scope:** Steel Logic app, `import_report` + future `source_provenance`, PDF Callout Lookup, website (optional deep link)  
**Why it matters:** Every workflow so far is **drawing → CAD → app → tag**. On the shop floor the part exists *before* anyone opens the PDF. KettleTag on a staged beam should run the chain **backward**: physical scan → digital record → drawing proof.

**Question:** Should scanning a assigned tag trigger a **reverse lookup pipeline**?

```
scan tag_id → parts DB → {source_pdf_sha256, page, span_ids[], piece_mark}
           → PDF Callout Lookup opens cached PDF at page
           → highlight bbox from import_report text_spans (or source_provenance when emitted)
           → optional haptic + spoken confirmation: "B fourteen, grid A four, sheet S three oh one"
```

Sub-questions:
1. **Offline:** PDF cached locally at first import vs re-fetch from path stored in report?  
2. **Blind/gloved shop:** Is **acoustic + haptic confirmation** (not visual-only) a v1 requirement for this flow?  
3. **Cross-host:** If part was imported in SU but user scans in app on phone, is `import_report` path/host metadata enough to locate the drawing file on a NAS?  
4. **Failure:** Tag valid but provenance missing — show piece mark only, prompt "link drawing" via omni-box?

**Agreement looks like:** v1 ships tag → piece mark + last-known drawing path + page; bbox highlight when span IDs present; spoken confirmation behind accessibility toggle; provenance schema (corpus) becomes **blocking** for this feature, not optional polish.

---

## Q-P5 — What we haven't thought of: version stamp on the tag, not just in the report

**Reviewer:** P (release truth / support blind spot)  
**Host scope:** Release pipeline (R3-4), tag print/export, Steel Logic, importers  
**Why it matters:** R3-4 locked policy: runtime-embedded version should match release tag; **artifact stamp not implemented**. R4 closed with engineering carry-forward. When a galv return shows a wrong piece mark, support asks *which importer build parsed that drawing* — today that lives only in `import_report.json` on a PC, not on the metal tag.

**Question:** Should **tag assignment** capture an immutable **`import_build_stamp`** on the part record — `{host, semver, report_sha256, imported_at}` — so any later scan surfaces "parsed with FC 4.0.54 on 2026-07-02" without retrieving the original report?

| Option | Detail |
|--------|--------|
| **(a) Record only** | Stored in app DB; shown on scan; not encoded on physical tag. |
| **(b) QR payload** | Opaque URL or `bcs://` includes stamp version segment; public page shows build for support. |
| **(c) Out of scope** | Tags carry piece mark only; provenance stays in report files. |

**Agreement looks like:** (a) minimum for R3-4 closure; (b) if Q-N10 URL tags ship; importers add `report_meta.build_stamp` field to `import_report` in same release as artifact stamp work; human confirmation T-01 verifies stamp matches installed build.

---

*End of Round 5 Reviewer P questions — 5 questions (Q-P4 outside-the-box). Awaiting cross-answers from other reviewers; do not answer your own.*
