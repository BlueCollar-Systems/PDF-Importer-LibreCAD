# Anonymous Active Coordination Pass

Date: 2026-06-25  
Scope: Current five-file Q&A folder, PDF importer repos, website, and Steel Logic app  
Author: Anonymous reviewer  
Status: Active coordination note for peer review

## What Was Read

The current Desktop Q&A folder contains five files, and all five were read before this note was created:

1. `Instructions 0607202613216.txt`
2. `Q&A_INDEX.md`
3. `QA-2026-06-24_third-party-project-briefing.md`
4. `QA-2026-06-25_anonymous-project-status-brief.md`
5. `QA-2026-06-25_anonymous-third-party-project-state-report.md`

The shared direction is consistent across the files: the objective is not to pass a narrow sample set. The objective is a family of practical, accurate, dependency-complete PDF importers and related tools that work across real user environments, including legacy host versions and older hardware, with honest host-specific limitations.

## Current Understanding

The ecosystem currently includes:

| Component | Current state |
|----------|---------------|
| SketchUp importer | Current public release `v3.7.68`; SketchUp 2017 Ruby 2.2 load blocker fixed; Ruby 2.2 gates now present |
| FreeCAD importer | Current verified release line `v4.0.48`; installer works; unsigned installer remains a trust caveat |
| LibreCAD importer | Current verified release line `v1.0.41`; portable ZIP is the supported install path |
| Blender importer | Current verified release line `v1.0.44`; headless validation passed; interactive UX still needs field confirmation |
| Website | Current metadata points to SketchUp `v3.7.68`; download metadata is clean |
| Steel Logic app | Prior validation clean; PDF callout lookup exists; full PDF-BOM/takeoff bridge remains open |
| PDF test corpus | Exists as the shared regression/stress foundation |

The repos were checked at the start of this pass and were clean/aligned with their remotes:

| Repo | Head observed |
|------|---------------|
| `C:\1PDF-Importer-SketchUp` | `ebb47bc` |
| `C:\1PDF-Importer-FreeCAD` | `893d55e` |
| `C:\1PDF-Importer-LibreCAD` | `ee5cc12` |
| `C:\1PDF-Importer-Blender` | `35632e4` |
| `C:\1BlueCollar-Website` | `4e2218a` |
| `C:\1 Structural_Steel_Shapes_App` | `77ad300` |
| `C:\1pdf-test-corpus` | `fa342fd` |

## Coordination Gap Found

`Q&A_INDEX.md` references a larger historical hub set, including `QA-2026-06-24_COORDINATION-HUB.md`, `QA-2026-06-24_open-threads.md`, and `QA-2026-06-24_worker-status-log.md`. Those files are not present in the current five-file Desktop Q&A folder.

This is not a code failure, but it is a process risk. A new reviewer who follows the index literally will look for missing files and may lose time or create duplicate work. This note should serve as the current active coordination surface until the larger hub files are restored, mirrored, or intentionally superseded.

## Four New Questions For Peer Review

### Q1 — What is the minimum supported runtime matrix for each importer?

Each product needs an explicit oldest-supported host/runtime row that is enforced by CI or release packaging, not only documented.

Proposed minimum rows:

| Importer | Oldest target that should block release if broken |
|----------|---------------------------------------------------|
| SketchUp | SketchUp Make 2017 / Ruby 2.2 |
| FreeCAD | Oldest FreeCAD version the project still claims in `COMPATIBILITY.md`; Python ABI must match bundled PyMuPDF |
| LibreCAD | Oldest Windows version and hardware class that can run the portable EXEs |
| Blender | Oldest Blender Python ABI supported by the packaged PyMuPDF payload |

Question for others: are these minimum rows already precise enough, or should they be narrowed before the next public release claim?

### Q2 — What exact artifact-level gates should be mandatory before a release is considered deployable?

Source tests are not enough. The SketchUp Ruby 2.2 incident proves that a built artifact can fail in a supported host even when modern developer checks pass.

Proposed mandatory artifact gates:

1. Build the exact release package.
2. Extract or install the exact package.
3. Verify bundled dependencies load from the package path.
4. Verify version metadata inside the package matches the release tag.
5. Run at least one import smoke test through the package path.
6. For the oldest supported host/runtime, run a parser/API compatibility gate.

Question for others: which importer still lacks one of these six gates?

### Q3 — What is the old-hardware performance acceptance bar?

The goal includes older PCs. That needs a measurable threshold. Without a threshold, a 350-second one-page import may be technically accurate but practically unacceptable for a shop workflow.

Proposed first-pass thresholds:

| Scenario | Warning threshold | Blocker threshold |
|----------|------------------|-------------------|
| One simple vector page | > 15 seconds | > 45 seconds |
| One complex shop drawing page | > 90 seconds | > 300 seconds |
| Glyph/geometry text mode | warn based on entity count before import | block only if memory/error risk is high |
| Multi-page import | require page-range workflow and estimated cost | block only if UI gives no control |

Question for others: should these thresholds be treated as release gates, user warnings, or both?

### Q4 — How do we prove selected text mode equals actual host output?

Text mode correctness is the highest-risk functional area. A pass/fail must prove entity type, not just visual presence.

Proposed proof model:

| Text mode | Proof needed |
|-----------|--------------|
| Labels | Host-native text/label entity count and placement sample |
| 3D Text | Host-native 3D text or documented host-equivalent entity count |
| Glyphs | Glyph/outline geometry count, no accidental native-label fallback |
| Geometry | Edge/curve/path geometry count, no accidental native-label fallback |

Question for others: can each host currently report this proof in `import_report.json` or host logs, or do we need a new per-host `actual_text_entity_types` diagnostic field?

## Answers To Existing Peer Prompts

### A1 — Is any P0 blocker missing from the open-thread set?

Yes, one P0 should be made explicit: **public artifact old-host launch validation**. Human field testing is already listed, but the release process should separately require that the exact website/GitHub artifact launches in the oldest supported host version, at least for SketchUp 2017 and Blender's oldest claimed Python ABI.

This is separate from import accuracy. A plugin that fails to load is a total product failure.

### A2 — Does the capability matrix still risk overpromising?

The main overpromise risk is text terminology. "3D Text" and "Glyphs" mean different concrete entities in SketchUp, FreeCAD, LibreCAD, and Blender. LibreCAD is correctly described as 2D-only, but all public-facing text should avoid implying true 3D text in LibreCAD.

Recommendation: every download/help page should show a host-specific text-mode table with "native", "outline/fallback", or "not supported" labels.

### A3 — Is the current corpus enough for sign-off?

No. It is enough for regression coverage, not final sign-off. The corpus should continue to grow around failure classes:

- old PDFs;
- malformed but recoverable PDFs;
- Type3 fonts;
- embedded subset fonts;
- rotated/skewed text;
- dense title blocks;
- multi-layer architectural drawings;
- scan/vector hybrid sheets;
- large multi-page construction sets;
- encrypted/refusal cases.

The current corpus is valuable because it is reproducible, but the stated product goal requires ongoing real-world PDF intake.

### A4 — Is the human confirmation script complete?

It is close, but it should explicitly require testing from public downloads rather than local builds, and it should record:

- cold-install behavior;
- whether dependencies were found from bundled paths;
- startup/load errors before import;
- actual host entity type per text mode;
- import time;
- whether the user understood warnings without developer explanation.

The script should also include one older or lower-spec PC if available.

## Recommended Immediate Workstreams

### WS-1 — Restore or supersede the missing coordination hub

Priority: P0 process  
Reason: the current index points to files absent from this folder.

Acceptance:

- one current active coordination file is clearly listed at the top of `Q&A_INDEX.md`;
- new reviewers know whether to use this slim folder or mirrored repo QA folders;
- no missing file is required for immediate participation.

### WS-2 — Add an artifact acceptance matrix

Priority: P0 release process  
Reason: "source passed" and "artifact works" must be separated.

Acceptance:

- each importer has an artifact-level checklist;
- each checklist includes exact commands;
- each checklist records whether oldest-host launch was tested or deferred.

### WS-3 — Add actual text entity diagnostics

Priority: P1 functionality  
Reason: the user needs confidence that labels are labels, 3D text is 3D text, glyphs are glyphs, and geometry is geometry.

Acceptance:

- import reports/logs include selected text mode and actual created entity categories;
- mismatches are warnings, not hidden behavior;
- all hosts expose equivalent diagnostics where technically possible.

### WS-4 — Add old-hardware performance policy

Priority: P1 UX/performance  
Reason: high-accuracy glyph imports can be too slow for real users.

Acceptance:

- importers estimate high-cost pages before committing;
- users can choose page ranges and lower-cost text mode;
- logs include entity counts and timing;
- warning thresholds are documented.

## Immediate Actions Taken In This Pass

1. Read all five current Desktop Q&A files.
2. Checked repo cleanliness and current heads for the seven active repos.
3. Inspected release/build gates for SketchUp, FreeCAD, LibreCAD, Blender, and website.
4. Identified the highest process risk: missing active hub files referenced by the index.
5. Added this active anonymous coordination pass to the Desktop Q&A folder.

## Current Recommendation

Do not declare final field sign-off yet. Do continue implementation hardening and human testing from the current public downloads.

The most valuable next engineering change is not another broad refactor. It is an artifact-level acceptance matrix and text-entity proof diagnostics, because those directly address the recent real-world failures:

- package loads but wrong runtime;
- text mode selected but different entity type produced;
- import technically completes but takes too long for older hardware;
- dependency exists on the developer PC but not on the user PC.

## Proposed Agreement Statement

I agree with the current direction if the following remains explicit:

1. Current artifacts are deployable for renewed testing.
2. Final field-release sign-off is still pending.
3. The project goal is broad PDF capability, not sample-file tuning.
4. Public claims must stay inside host limitations.
5. Every release must prove the packaged artifact works under the oldest supported runtime.

