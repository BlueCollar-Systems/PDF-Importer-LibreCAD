# Round 4 Extension - Import Report Doctor

**Session:** 2026-06-24

**Status:** IMPLEMENTED in `C:\1BlueCollar-Website` as website v1.0.57

**Theme:** Turn importer telemetry into a shop-floor troubleshooting loop.

## What changed

- Added `report-doctor.html` and `report-doctor.js`.
- Added a local-only analyzer for BlueCollar `import_report.json` files.
- Added home-page and feedback-page links so real-world testers can diagnose imports before emailing or filing issues.
- Added the new route to `sitemap.xml` and website CI static checks.
- Added missing static CSS utilities already used by the install matrix plus specific Report Doctor controls.
- Removed private `BlueCollar-Systems/Steel-Shapes` from public `repo-metadata.json` generation; public steel shape assets still come from importer-hosted `steel-v*` releases.
- Added a metadata validation guard so private Steel-Shapes release URLs cannot be republished silently.
- Updated the Steel Logic privacy policy for inventory, remnant, job-clock, CSV/export, support-log, and optional sync/API-key workflows.
- Normalized Report Doctor text-mode detection so user-facing `3D Text` is interpreted the same as `3d_text` / `text3d`.

## Why this was selected

The reviewer group agreed that the importers already produce increasingly useful telemetry, but users still need a no-terminal way to understand:

- requested import mode vs resolved mode;
- requested text mode vs actual label / 3D text / glyph-outline evidence;
- fallback and raster warnings;
- high geometry/text counts that can slow older PCs;
- support-ready evidence to attach to screenshots.

This is a high-leverage bridge between field testing, Q&A, website support, and future in-host diagnostics.

## Safety decisions

- The page runs entirely in the browser.
- It does not upload PDFs or reports.
- It does not claim engineering signoff.
- It does not inspect confidential PDF content.
- It does not redistribute SketchUp Make 2017 or any third-party installer.
- It reports evidence and next actions; it does not pretend to certify perfect import accuracy.
- Private GitHub release assets are not published as public download metadata.
- Privacy copy now matches the app's current local workflow and optional sharing/sync behavior.

## Debate resolved

**Q:** Should this be an importer code feature instead of a website feature?

**A:** Both eventually. Website-first is safe, host-independent, and immediately useful for all importers.

**Q:** Should we build PDF preview/visual diff now?

**A:** Not in this pass. The doctor consumes existing report data. Visual diff remains a deeper P0/P1 path once the report fields stabilize.

**Q:** Could this scare users by showing warnings?

**A:** Better honest warnings than hidden fallbacks. Copy uses "review" language and gives practical next steps.

**Q:** Does it solve text placement bugs directly?

**A:** No. It makes text-mode mismatches easier to prove, compare, and triage during real-world testing.

## Follow-up ideas

- Add richer `actual_text_breakdown` from every host importer.
- Add per-page mode and text output summaries.
- Add a support bundle generator that redacts local paths by default.
- Add an in-host "Open Report Doctor" action once website route is live.

## Validation

- `python tools\validate_static_metadata.py` passed.
- Website CI-equivalent static checks passed for required page tokens, sitemap completeness, and dynamic release-link policy.
- `node --check report-doctor.js` passed.
- Report Doctor DOM smoke passed for sample Labels mode and explicit `3D Text` alias handling.
- `repo-metadata.json` no longer contains `BlueCollar-Systems/Steel-Shapes` or `SteelLogic` private release assets.

*Saved for the anonymous Q&A workflow.*
