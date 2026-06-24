# Round 4 — Reviewer C: UX / Accessibility / Shop Floor

**Session:** 2026-06-24  
**Persona:** Anonymous — former welder who installs software with gloves on  
**Mandate:** If it needs a manual, the manual should be in the product.

---

## What we already have

- Website **Easy Install** section — no terminal required messaging.
- LibreCAD portable ZIP bundles Python + PyMuPDF + pdfcadcore (huge win for IT-averse shops).
- SketchUp Compatibility Report + first-run dependency notice.
- `import_report.extra.diagnostics.recommended_actions` — machine-generated coaching (Round 4).

---

## Outside-the-box ideas (≥5)

### C-1 — Preflight wizard (before file picker returns)

**Idea:** 60-second checklist: host version OK? bundled deps OK? disk space OK? pick default text mode for *this session* with plain labels (“Editable labels” vs “Exact outlines”).

**Why it matters:** Prevents the #1 support pattern — wrong text mode discovered after 10-minute import.

**Host limit:** Blender add-on prefs differ from SU dialog — shared *copy*, not shared UI widget.

---

### C-2 — Plain-English errors (no exception class names)

**Idea:** Map `fallback.reason` enums to templates: `not_a_pdf` → “This file doesn’t look like a PDF. Try opening it in a viewer first.”

**Why it matters:** Accuracy of *user action* — they fix the right thing. Accessibility: screen readers hate `PyMuPDFError`.

**Status:** Partial via open gate + human_summary; extend to CLI stderr on LC/BL.

---

### C-3 — “What will I get?” mode preview

**Idea:** Before import: table showing geometry ✓/✗, labels ✓/✗, 3D text ✓/✗ for *this host* — same matrix as website but contextual.

**Why it matters:** Sets expectations = fewer “broken” reviews. Honest host limits build trust.

**Status this session:** Website matrix **shipped** on install-help; in-host dialog deferred.

---

### C-4 — First-run tour (3 tooltips, skippable)

**Idea:** Day-one: (1) where import lives, (2) text mode picker, (3) where Import Health / report lives.

**Why it matters:** SketchUp extensions are buried. LibreCAD portable users may never find `pdf2dxf.exe --version`.

---

### C-5 — High-contrast / large-type import summary

**Idea:** Post-import summary respects OS font scaling; minimum 14px equivalent in HtmlDialog.

**Why it matters:** Shop floor lighting and aging eyes — UX is accessibility.

---

### C-6 — Offline “it worked last time” badge

**Idea:** Import Health shows green check if last 3 imports same host version had zero warnings.

**Why it matters:** Intuitive confidence without understanding JSON schema.

---

## Peer challenges

**To Reviewer A:** Import Health is perfect — add “Copy summary for email” button so users don’t photograph monitors with glare.

**To Reviewer B:** Heatmaps are engineer candy — prioritize human_summary in support docs first (done). Heatmaps next sprint only if support still asks “where did it fail?”

---

## Rank self (impact / effort)

| Idea | Impact | Effort |
|------|--------|--------|
| C-3 capability matrix | High | Low — **website done** |
| C-2 plain errors | High | Medium |
| C-1 preflight | High | Medium |
| C-4 first-run tour | Medium | Low |
| C-6 streak badge | Low | Low |
| C-5 high-contrast | Medium | Medium |

---

*Reviewer C — Round 4, 2026-06-24*
