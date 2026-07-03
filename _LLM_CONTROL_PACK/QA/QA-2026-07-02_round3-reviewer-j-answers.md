# Round 3 — Reviewer J Answers (2026-07-02)

**Author:** Anonymous Reviewer J  
**Rules:** Answers **other reviewers'** questions only — not Q-J2 through Q-J7. Evidence from live repo sweep 2026-07-02.

---

## A-J→E1 — Preflight parity status update (Round 1, Reviewer E)

**Re:** Q-E1 — *minimum preflight surface every host must expose*

**Answer:** Round 1 correctly called for FreeCAD repo-root `preflight_check.py`. **Shipped since then.** Verified on disk:

```text
C:\1PDF-Importer-FreeCAD\preflight_check.py
```

It imports `pdfcadcore.preflight_copy.preflight_paragraph("freecad")` and probes bundled PyMuPDF under `PDFVectorImporter/src/lib` — matching LC/BL pattern. LibreCAD: `pdf2dxf.py --preflight` / portable `lcpdf-import --preflight`. Blender: `preflight_check.py --preflight`. SketchUp: **Compatibility Report** + **Import Health** (Ruby, no Python).

**Minimum foreman surface (unchanged recommendation, now implementable):**

| Host | One-action preflight |
|------|----------------------|
| SU | Extensions → Blue Collar PDF → Compatibility Report |
| FC | `python preflight_check.py` from extracted add-on or installer tree |
| LC | Portable `lcpdf-import.exe --preflight` or `pdf2dxf.py --preflight` |
| BL | `python preflight_check.py --preflight` inside add-on folder |

**P1 still open:** wire corpus `schemas/ready_check.schema.json` output into each command so IT gets JSON, not only paragraphs. Website install-help should list this table — `index.html` links Report Doctor but does not yet enumerate all four preflight paths in one place.

---

## A-J→E3 — SketchUp 2017 CI vs field proof (Round 1, Reviewer E)

**Re:** Q-E3 — *remaining SU 2017 API gaps unverified in real 2017*

**Answer:** **CI layer is strong; field layer still open (T-01).** On `C:\1PDF-Importer-SketchUp` `main` @ `c2bbabe`:

- `PLUGIN_VERSION = 3.7.75` in `bc_pdf_vector_importer.rb`
- Regression guards exist: `test/pre_import_prompt_test.rb`, `test/ruby22_compat_test.rb`, `test/text_label_placement_test.rb`, `test/text_mode_placement_test.rb`
- GitHub latest release: `v3.7.75` (matches committed version today — no tag/file lag on SU)

Round 1 answer listed `UI::HtmlDialog` fallback, Tags API, and Labels/3D Text as **field-unverified**. That remains accurate: nothing in CI substitutes for loading the RBZ inside SketchUp Make 2017.

**Recommendation (refined):**

1. **Do not block auto-release** on undiscovered post-2018 APIs until a static API audit lands — but add a grep/allowlist check for known post-2017 SketchUp API symbols in `extracted/sketchup_ext/` as P1.
2. **Do block field sign-off (T-01)** until one SU 2017 session imports `1017 - Rev 0.pdf` in Labels mode and saves `import_report.json`.
3. Mark COMPATIBILITY.md honestly: *"Ruby 2.2 CI green; SU 2017 host smoke pending human confirmation."*

---

## A-J→Coordination-pass — `actual_text_entity_types` field (2026-06-25 anonymous-active-coordination-pass)

**Re:** *Can each host report text-mode proof in import_report today, or do we need a new diagnostic field?*

**Answer:** **A new shared field is required — not present in shipping code.** Corpus schema `schemas/text_entity_verification.schema.json` already defines `actual_text_entity_types` as required. Production code search 2026-07-02:

| Location | `actual_text_entity_types` |
|----------|---------------------------|
| `pdfcadcore/import_report.py` | **Absent** — has `font_substitution_note`, `performance_hint`, `dense_text_glyph_workload` |
| SketchUp `qa_report.rb` / Ruby tree | **Absent** |
| `report-doctor.html` | **No parser branch** for text-entity verification or ready_check |

Hosts today infer text mode from user selection + `human_summary`, not host object counts. That is insufficient for pre-test acceptance.

**Implementation agreement (recommend):**

1. Add `extra.actual_text_entity_types: { requested, observed: { <host-type>: count } }` to `bcs.import_report/1.1` first (sidecar optional for large sessions).
2. **Rollout order:** LibreCAD (DXF TEXT vs LWPOLYLINE counts are file-parseable without GUI) → Blender → FreeCAD → SketchUp Ruby.
3. Add corpus golden test: given `hello_world_rotated.pdf` Labels mode, observed types must match requested mode or report `status: mismatch` per schema.
4. Report Doctor P1: render observed vs requested types before screenshots are accepted for T-01.

---

## A-J→E2 — Legacy hardware `performance_hint` shipping proof (Round 1, Reviewer E)

**Re:** Q-E2 — *page-count / entity-count guidance per host*

**Answer:** Round 1 recommended docs + runtime `import_report.extra.performance_hint`. **Runtime half is shipped** in canonical core:

```text
pdfcadcore/import_report.py — build_performance_hint(), emitted to report.extra["performance_hint"]
```

R2-8 in `Q&A_INDEX.md` marks this SHIPPED. `human_summary` integration exists via `build_human_summary()` paths that read `performance_hint`.

**Still missing (P1):**

- SU Ruby port parity — verify `qa_report.rb` emits the same key (not confirmed in this sweep).
- Website install-help does not surface RAM/page guidance in one paragraph (COMPATIBILITY.md per-repo only).
- No automatic GUI page-by-page prompt on weak hardware — correctly deferred.

**Recommendation:** Close the Round 1 gap by adding a single shared paragraph to website install-help and SU Compatibility Report output when `performance_hint` is non-empty — do not wait for GUI prompts.

---

## A-J→E5 — Steel Logic ↔ importer handoff with live app evidence (Round 1, Reviewer E)

**Re:** Q-E5 — *website capability matrix vs separate steel/CAD sections*

**Answer:** Round 1 recommendation stands and is **partially implemented.** `C:\1 Structural_Steel_Shapes_App` `main` @ `bfa77d7`:

- `pubspec.yaml`: `steel_logic 1.0.9+11`
- `README.md` explicitly states Steel Logic is **not** a PDF geometry importer; links Report Doctor and importers separately
- PDF Callout Lookup shipped in Tools (per worker log `WS-R6`, commit `8b9c114` era)
- `steellogic://shape/W12X26` deep link still **planned** (README) — matches open thread T-15

**Website:** keep CAD importers and Steel Logic in **separate nav sections** with a shared footnote: *"Import geometry in SketchUp/FreeCAD/LibreCAD/Blender; look up AISC designations in Steel Logic or paste `import_report.json` into Report Doctor."* Do **not** imply feature parity.

**Next bridge slice (supports Q-J7):** Report Doctor should export a **trimmed callout bundle** JSON (`human_summary`, steel-relevant `text_spans` / `tables`, `source_pdf.sha256`) for paste into Steel Logic — full `import_report` ingestion is T-10 and too large for mobile paste UX.

---

*End of Round 3 Reviewer J cross-answers — 5 answers to prior-round questions, zero self-answers.*
