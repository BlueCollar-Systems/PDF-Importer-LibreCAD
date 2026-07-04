# Round 5 — Reviewer P Answers (2026-07-03)

**Author:** Anonymous Reviewer P  
**Rules:** Answers **other reviewers'** questions only — not own questions. Evidence from live disk sweep 2026-07-03.  
**Answering:** Reviewer N's Q-N6, Q-N7, Q-N8 (Round 5); Reviewer J's Q-J7; Reviewer L's non-PDF gate question (`QA-2026-07-02_shared-core-fraction-open-gate-fix.md`); anonymous semantic text verification question.

---

## A-P→N6 — Barcode/QR part tracking: scan-to-lookup first, or full lifecycle?

**Re:** Q-N6 — *scan-to-lookup vs full lifecycle; symbologies; data model; offline; scanner library?*

**Answer: Scan-to-lookup first; lifecycle statuses are phase 2. Symbology floor = Code 128 + QR. Data model = new `parts` table keyed by opaque ID, linked to inventory for stock items.**

Verified on disk: `C:\1 Structural_Steel_Shapes_App\lib\omni_box_screen.dart` routes omni intents to inventory and time clock; `database_helper.dart` backs inventory SQLite; no camera/scanner dependency in `pubspec.yaml` today. Importers already expose piece marks via `text_spans` / BOM tables — physical tag is the missing key.

**Agreement:**

| Topic | Decision |
|-------|----------|
| **v1 scope** | **(a) scan-to-lookup** — scan opens/creates part record (piece mark, project, optional heat #). Status history (fit-up → galv) deferred until Q-P4 reverse lookup proves the data model. |
| **Symbologies** | **Code 128 + QR** in v1. DataMatrix phase 2. Standardize **BCS-printed** QR on `https://bluecollar-systems.com/p/<id>` (aligns Q-N10) while **reading** legacy part tag Code 128 without re-printing. |
| **Data model** | **`parts` table** (fabricated assemblies) separate from **`inventory`** (stock/remnants). Foreign-key optional when a part consumes stock. Tag ID = opaque UUID, not piece mark (marks repeat across jobs). |
| **Offline** | **Required** — mirror `inventory_sync.dart` / `time_clock_sync.dart` pattern: scan queue locally, sync when online. |
| **Scanner lib** | **`mobile_scanner`** (ML Kit) for Flutter — bundled, works offline after first model cache; fallback = omni-box manual entry `tag 884422` on same screen. |
| **Entry point** | **Omni-box + home camera icon** — one canonical path; do not hide scanner three menus deep. |

---

## A-P→N7 — The digital thread: piece marks from PDF → app parts → tag scans → reports

**Re:** Q-N7 — *shared `bcs.part/1.0` schema; importer export; time auto-link?*

**Answer: Yes — corpus owns `bcs.part/1.0`; minimum slice aligns with Q-P2 `parts_bootstrap`; time linker is regex on existing omni time parser.**

**Minimum viable `bcs.part/1.0` record:**

```json
{
  "schema": "bcs.part/1.0",
  "part_id": "<opaque-uuid>",
  "piece_mark": "B-14",
  "project_id": "<string>",
  "drawing_ref": {
    "source_pdf_sha256": "<hex>",
    "page": 3,
    "span_ids": ["span-0042"]
  },
  "tag_id": null,
  "import_build_stamp": { "host": "freecad", "semver": "4.0.54" },
  "status": "detailed",
  "status_history": []
}
```

**Ownership:** Corpus `schemas/part.schema.json` (new), validated by `validate_contract_schemas.py`. Importers emit **`parts_candidates[]`** (see Q-P2); Steel Logic is system-of-record for `tag_id` assignment and `status_history`. Time auto-link: when `OmniIntentKind.timeLog` parses `welding B-14`, match `piece_mark` against open parts for active project — **warn on ambiguity**, never silently pick.

**Agreement:** Schema in corpus; FC first bootstrap emitter; app assigns tags; scans update `status` only in v1 (full history in v2).

---

## A-P→N8 — What haven't we thought of: capture at the point of work

**Re:** Q-N8 — *voice, MTR OCR, photo-as-record, count-by-camera — rank by value/effort?*

**Answer: Rank (1) photo-as-record, (2) voice time logging, (3) MTR OCR, (4) count-by-camera. Host on omni-box; MTR OCR and count-by-camera are P2/P3.**

| Rank | Channel | Value | Effort | Host screen |
|------|---------|-------|--------|-------------|
| **1** | **Photo-as-record** | Fit-up/weld evidence, local hash | Low — attach URI to part/time row | Part detail + time entry |
| **2** | **Voice → omni-box** | Gloves-on time logging | Medium — offline STT or push-to-talk → text into existing parser | Omni-box |
| **3** | **MTR OCR** | Heat # traceability | High — OCR + grade validation | Inventory receive flow |
| **4** | **Count-by-camera** | Bundle tally | High / unreliable | Out of scope v1 |

**Out of scope v1:** Count-by-camera (lighting/angle variance in fab shops). **In scope v1:** Photo attach with SHA-256 stored locally; voice as **text injection** into omni-box (no separate voice UI).

---

## A-P→J7 — Steel Logic `import_report` bridge minimum schema

**Re:** Q-J7 — *mandatory fields; paste whole JSON vs trimmed callout bundle?* (R3-6 **OPEN**)

**Answer: First slice = trimmed bundle via Report Doctor; full JSON paste power-user optional. Mandatory fields narrower than full BOM.**

Verified: No `bcs.import_report/1.1` Dart parser in `lib/` (grep 2026-07-03). PDF Callout Lookup ships standalone. Report Doctor on website `main` (`590ed8f`) now renders `actual_text_entity_types`, `performance_hint`, `ready_check`.

**First-ingestion bundle (`bcs.callout_bundle/1.0`):**

| Field | Required | Why |
|-------|----------|-----|
| `source_pdf` (path or sha256) | ✓ | Reverse lookup (Q-P4) |
| `text_spans[]` with `generic_tags`, bbox | ✓ | Callout search |
| `human_summary` | ✓ | Shop-readable |
| `extra.scale_crosscheck` | ✓ | Trust gate |
| `tables[]` | optional | Feeds Q-P2 bootstrap |
| Full geometry | ✗ | Mobile UX / size |

Steel Logic: **Report Doctor export button** → paste or file drop; full JSON import hidden under Advanced. Supersedes K vs J debate (R3-6): **trimmed default, full optional**.

---

## A-P→L — Non-PDF header sniff before PyMuPDF (Windows handle leak)

**Re:** Reviewer L question in `QA-2026-07-02_shared-core-fraction-open-gate-fix.md`

**Answer: Yes — shipped in shared core; extend to SU Ruby `PdfOpenGate` parity test and corpus non-PDF fixture.**

Verified: `fitz_loader.safe_open` applies `%PDF-` sniff (shared-core fix doc, 2026-07-02). SU has separate `PdfOpenGate.inspect_path` (improvement-report-01). Round 4 R4-2 tags non-PDF gate as **P0 skip-fail class** in CI.

**Agreement:**

1. Python hosts: sniff remains in `safe_open` — **no regression**.  
2. SU: `PdfOpenGate` is release gate (already documented); add corpus **`tier1/web/not_a_pdf.pdf`** (text file renamed) for cross-host CI.  
3. `import_report.fallback_reason = not_a_pdf` when rejected — support bundle pattern.  
4. Do **not** re-open L's question for debate; close as **SHIPPED** with SU fixture gap tracked under R4-2.

---

## A-P→semantic-text — Automatic proof of correct parent-software entity types

**Re:** `Anonymous question - semantic text verification.md`

**Answer: FC-first `actual_text_entity_types` is the right contract; shape must be reconciled with schema before SU/LC/BL port (R4-4). Add golden four-mode PDF in corpus.**

Round 4 locked FC emitter at `PDFImporterCore.py:3751` with fields `{entity_type, count, font_rendered, examples}`. Schema expects richer `{requested, observed, status}`. **Do not port** until `validate_contract_schemas.py` passes on smoke report.

**Proof path per host:**

| Host | Collector |
|------|-----------|
| FC | Count Draft Text / ShapeString vs wires (emitter live) |
| LC | DXF post-parse: TEXT/MTEXT vs polyline counts |
| BL | Object type inspection after import |
| SU | `Sketchup::Text` vs mesh groups — **parity floor** Q-N5 |

Corpus: one **`tier1/web/four_mode_text_proof.pdf`** (4 spans, one per mode). CI fails if `requested_text_mode` ≠ dominant `entity_type` without documented `fallback`.

---

## Round 5 cross-answer tally (Reviewer P)

| Target | Count |
|--------|-------|
| N6, N7, N8 | 3 |
| J7, L, semantic-text | 3 |
| **Total** | **6** (≥3 required) |

Zero self-answers.

---

*End of Round 5 Reviewer P answers — 6 cross-answers, zero self-answers. Re-verify against disk before implementing.*

---

## Implementation note (2026-07-03)

Omni-Box engine, inventory NL, and time NL now exist in Steel Logic (`lib/core/omni/`, Tools→Omni-Box). Barcode/part tag scan (Q-P1) should route through the same intent router as the next slice.
