# Outside-Box QA Resolution And Actions

Date: 2026-06-24
Status: GO for implemented website/support-trust work; importer-side Round 4 code was already committed and pushed.

## Reviewer Inputs Read

- `QA-2026-06-24_outside-box-reviewer-A-sketchup.md`
- `QA-2026-06-24_outside-box-reviewer-B-fc-lc-core.md`
- `QA-2026-06-24_outside-box-reviewer-C-blender.md`
- `QA-2026-06-24_outside-box-reviewer-D-website-app.md`
- Round 4 debate, backlog, and resolution notes.

## Implemented Now

- Added a public website Report Doctor page for local `import_report.json` analysis.
- Added Report Doctor navigation, homepage support entry, feedback-page intake guidance, sitemap entry, CSS, and website CI static checks.
- Added plain support-summary generation for importer bug reports without uploading PDFs or report files.
- Fixed Report Doctor text-mode normalization so `3D Text`, `3d_text`, and `text3d` are treated consistently.
- Removed private `BlueCollar-Systems/Steel-Shapes` release assets from public metadata generation.
- Added a metadata validation guard to prevent private Steel-Shapes release URLs from returning to `repo-metadata.json`.
- Refreshed `repo-metadata.json`; public importer release tags and download assets are current.
- Updated Steel Logic privacy copy for inventory, remnants, job clock, CSV/export, support logs, optional sync endpoints, and API-key behavior.

## Explicitly Deferred

- Visual PDF-vs-import heatmaps.
- Live import preview.
- Region-level hybrid import.
- Golden-vector oracle corpus.
- Per-page decision ledger and phase timings in every host.
- Shared support-pack export from inside every importer.

These are valuable, but they require importer/runtime work and should be handled as the next engineering lane rather than mixed into this website support pass.

## Validation

- `python tools\validate_static_metadata.py` passed in `C:\1BlueCollar-Website`.
- Website CI-equivalent static checks passed for required page tokens, sitemap completeness, and dynamic release-link policy.
- `node --check report-doctor.js` passed.
- `repo-metadata.json` no longer contains `BlueCollar-Systems/Steel-Shapes` or `SteelLogic` private release assets.

## Commit Scope

Website repo only:

- `C:\1BlueCollar-Website`

Importer repos were already at `HEAD == origin/main` after the Round 4 importer commits. The remaining Blender `preferences.py` status is an EOL/index warning with no content diff and should not be treated as a functional change.

