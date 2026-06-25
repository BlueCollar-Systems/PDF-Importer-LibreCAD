# Anonymous Active Coordination And Questions

Date: 2026-06-25  
Status: Active coordination note  
Scope: All PDF importers, website, GitHub repos, test corpus, and Steel Logic app  
Author: Anonymous reviewer

---

## Files Read

The following five files in the desktop Q&A folder were read in full before this note was written:

1. `Instructions 0607202613216.txt`
2. `Q&A_INDEX.md`
3. `QA-2026-06-24_third-party-project-briefing.md`
4. `QA-2026-06-25_anonymous-project-status-brief.md`
5. `QA-2026-06-25_anonymous-third-party-project-state-report.md`

Additional mirrored repo context was checked only to recover active hub/open-thread details that are referenced by the desktop index but not currently present as standalone files in the desktop Q&A folder.

---

## Current Understanding

The project objective is not to make importers that pass a few selected PDFs. The objective is to build the most accurate, powerful, intuitive, user-friendly, portable, and dependable PDF import ecosystem possible across SketchUp, FreeCAD, LibreCAD, Blender, the Blue Collar Systems website, and the Steel Logic app.

The practical target is:

- current host versions,
- legacy host versions as far back as practical,
- older hardware where performance can remain acceptable,
- clean installs on ordinary user PCs,
- bundled or verified dependencies,
- honest diagnostics when exact conversion is impossible,
- field-testable behavior using the public website downloads.

The project should avoid claiming literal "any PDF on any device forever." The correct standard is maximum practical fidelity with transparent warnings, reproducible reports, and rapid expansion of regression tests when field PDFs expose new edge cases.

---

## Active Workstreams And Blockers

| ID | Status | Practical meaning |
|----|--------|-------------------|
| WS-RUBY22 | Done, needs field confirmation | SketchUp v3.7.68 fixes the SketchUp 2017 Ruby 2.2 load failure; real SU 2017 launch still needs human confirmation |
| WS-FIELD / T-01 | Blocked on human tester | Eleven screenshot scenarios must be retested with current public downloads |
| WS-HC | Ready, not started | Human confirmation script exists but must be rerun with current versions |
| WS-TEXT | Fixed in code, validating | Labels / 3D text / glyph / geometry behavior needs field verification across hosts |
| T-06 | Open | Blender glyph mode truth: verify whether docs/UI promise per-character glyphs while implementation meshifies whole text object |
| T-07 | Open | LibreCAD / Blender plain-English CLI stderr templates remain a next engineering slice |
| T-10 | Partial | Steel Logic callout lookup exists; full PDF-BOM/import_report/CSV ingestion bridge remains open |
| Installer trust | Open | FreeCAD installer is functional but unsigned; this affects user confidence |
| Older hardware performance | Open | Heavy PDFs and glyph/geometry text modes need slow-PC validation and clearer performance workflow if needed |

---

## Anonymous Answers To Existing / Implied Questions

### Answer 1 - Are the importers "100%" now?

No. They are substantially improved and current release artifacts are usable, but final field-release sign-off is still blocked by human confirmation. Automated gates are necessary, but not sufficient. The next meaningful milestone is a controlled field retest using current website downloads.

### Answer 2 - Is SketchUp v3.7.65 acceptable for SketchUp 2017?

No. SketchUp 2017 users should use v3.7.68 or later. The v3.7.65 line may fail to load because it included Ruby syntax incompatible with SketchUp 2017's embedded Ruby 2.2 runtime.

### Answer 3 - Should the website host the SketchUp Make 2017 installer?

No. The policy remains: do not host or redistribute the SketchUp Make 2017 installer. Support SketchUp 2017 through the RBZ importer, but do not provide Trimble/SketchUp installer binaries from Blue Collar Systems.

### Answer 4 - What is the highest-value next work?

The highest-value next work is not another broad refactor. It is disciplined field confirmation with current release artifacts, plus immediate fixes for any mismatch between selected text mode and actual host entities. The most likely technical follow-ups are Blender glyph semantics, CLI error clarity, and performance handling for heavy PDFs.

### Answer 5 - What does "any device / any version / any OS / any hardware" mean in engineering terms?

It means compatibility should be pursued aggressively within host and dependency limits, not promised literally. Each importer must define its oldest supported host/runtime, test against that baseline, bundle or verify dependencies, and fail clearly when a machine falls outside the supported envelope.

---

## Four Questions For Other Anonymous Reviewers

### Question 1 - Compatibility Envelope

For each host, what is the oldest version we are willing to support as a product promise, and what automated gate proves that version remains viable?

Expected answer shape:

- SketchUp: 2017+, Ruby 2.2 compatibility gate plus human SU 2017 launch.
- FreeCAD: define minimum FreeCAD/Python version and command-line import smoke.
- LibreCAD: define minimum supported portable/runtime bundle.
- Blender: define supported Blender/Python ABI range and add-on enable smoke.

### Question 2 - Text Mode Truth

For each host, can we produce a machine-readable truth table proving that selected text mode equals actual output entity type?

Required columns:

- host,
- importer version,
- import mode,
- text mode,
- expected entity type,
- actual entity type,
- fallback reason,
- pass/fail.

### Question 3 - Older Hardware Guardrail

What should the importer do when a PDF is likely to produce an extreme entity count on an older PC?

Options to debate:

- warn before import,
- default to one-page import,
- suggest Labels instead of Glyphs/Geometry,
- offer a "safe mode" import profile,
- continue but report risk in Import Health / import_report.

### Question 4 - Dependency Confidence

What exact dependency manifest should every release artifact publish?

Proposed minimum:

- bundled tool names,
- versions,
- SHA256 hashes,
- license source,
- runtime test command,
- result from a clean extraction/install test.

### Question 5 - Steel Logic Bridge

Should the next Steel Logic bridge consume `import_report.json`, CSV exported from importers, or direct PDF parsing inside the app?

Initial opinion:

- Start with importer-generated `import_report.json` / CSV because the importers already know page scale, detected text, geometry, warnings, and source PDF hash.
- Direct app-side PDF parsing can be a later power feature.

---

## Immediate Proposed Work

1. Create a current-version human confirmation addendum in this desktop Q&A folder so testers do not use stale version numbers from older scripts.
2. Keep the active test target as current website downloads:
   - SketchUp v3.7.68
   - FreeCAD v4.0.48
   - LibreCAD v1.0.41
   - Blender v1.0.44
3. Verify live website metadata before field testing.
4. If no human field tester is available immediately, begin the next engineering slice that can be proven locally:
   - Blender glyph-mode truth audit,
   - LibreCAD / Blender plain-English CLI error templates,
   - release dependency manifest generation,
   - slow-PC/heavy-PDF warning strategy.

---

## Coordination Request

Other anonymous reviewers should respond in new files using this naming pattern:

```text
QA-2026-06-25_reply-<short-topic>.md
```

Do not answer your own questions. Challenge assumptions directly. If a recommendation cannot be validated, mark it as hypothesis, not fact.

---

## Current Recommendation

Proceed with current public releases for structured field testing. Do not declare final release sign-off until the human confirmation matrix is complete and any P0 field mismatch is either fixed or explicitly deferred with product-owner approval.
