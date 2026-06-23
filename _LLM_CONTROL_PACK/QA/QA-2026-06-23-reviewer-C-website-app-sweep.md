# Reviewer C Website/App Readiness Sweep - 2026-06-23

## Scope

Reviewer C inspected only:

- `C:\1BlueCollar-Website`
- `C:\1 Structural_Steel_Shapes_App`

No source code, website page, app code, workflow, release artifact, commit, or push was changed. This Markdown report is the only file written.

## Repos Inspected

### BlueCollar Website

- Branch/status: `main...origin/main`, clean.
- Current local head: `1374de0 docs: update Q&A cross-repo validation [skip release]`.
- Relevant surfaces inspected:
  - `repo-metadata.json`
  - `index.html`
  - `shapes.html`
  - `README.md`
  - `nav.js`
  - `tools/validate_static_metadata.py`
  - `_LLM_CONTROL_PACK/QA`
  - `.github/workflows/website-ci.yml`

### Steel Logic App

- Branch/status: `main...origin/main`, clean.
- Current local head: `c42f2f3 docs: update Q&A cross-repo validation [skip release]`.
- Relevant surfaces inspected:
  - `pubspec.yaml`
  - `README.md`
  - `lib/database_helper.dart`
  - `tools/verify_windows_release_artifacts.ps1`
  - `dist/windows`
  - `.github/workflows/auto-release.yml`
  - `.github/workflows/notify-website-deploy.yml`
  - `_LLM_CONTROL_PACK/QA`
  - `_LLM_CONTROL_PACK/SL_LLM_INSTRUCTIONS.md`

## Commands and Checks Run

Website:

- `git status -sb`
- `git log --oneline -5`
- `git ls-files`
- `Get-Content -Raw repo-metadata.json`
- `Select-String -Path index.html,shapes.html,README.md -Pattern ...`
- `python tools\validate_static_metadata.py`
- `gh run list --limit 5 --json databaseId,workflowName,status,conclusion,headSha,displayTitle,url`
- `gh release view v1.0.54 --repo BlueCollar-Systems/BlueCollar-Website --json tagName,name,publishedAt,assets,url`
- Q&A mirror file listing and hash comparison attempt against desktop Q&A.

Steel Logic app:

- `git status -sb`
- `git log --oneline -5`
- `git ls-files`
- `Get-Content -Raw pubspec.yaml`
- `Select-String -Path README.md,lib\database_helper.dart,tools\verify_windows_release_artifacts.ps1,_LLM_CONTROL_PACK\SL_LLM_INSTRUCTIONS.md -Pattern ...`
- `powershell -ExecutionPolicy Bypass -File .\tools\verify_windows_release_artifacts.ps1 -Version 1.0.3`
- `flutter analyze`
- `flutter test`
- `gh pr list --state all --limit 10 --json number,title,state,headRefName,baseRefName,mergedAt,url`
- `gh release view v1.0.8 --repo BlueCollar-Systems/Steel-Shapes --json tagName,name,publishedAt,assets,url`
- `gh run list --limit 5 --json databaseId,workflowName,status,conclusion,headSha,displayTitle,url`
- `Get-ChildItem -LiteralPath dist\windows -File`

## Validation Results

- Website static metadata validator: passed, `8 labels`.
- Latest website CI observed through GitHub: success for `product-update` on `1374de0`.
- Website release observed: `v1.0.54`, asset `BlueCollar-Website_v1.0.54.zip`.
- Steel Logic Windows artifact verifier: passed for `v1.0.3`.
- Flutter analyzer: no issues found.
- Flutter tests: all `153` tests passed.
- Latest app Flutter CI observed through GitHub: success on `c42f2f3`.

## Findings

### Blockers

1. `APP-REL-001`: Steel Logic release version bump remains unresolved.
   - Local `pubspec.yaml` is `version: 1.0.7+8`.
   - GitHub release metadata and website `repo-metadata.json` point to latest Steel Logic release `v1.0.8`.
   - GitHub PR #8, `chore: bump version to 1.0.8`, is open and not merged: `https://github.com/BlueCollar-Systems/Steel-Shapes/pull/8`.
   - Risk: if another normal push runs auto-release before PR #8 merges, the workflow starts from `1.0.7+8` again and may target `v1.0.8` instead of advancing cleanly to the next version.
   - Classification: blocker for release-process cleanliness before the next Steel Logic release. Not a blocker for current local tests or the existing `v1.0.8` release artifact.

2. `QA-MIRROR-001`: repo Q&A mirrors are no longer a byte-for-byte mirror of the desktop Q&A folder.
   - Website and app repo mirrors match each other.
   - Desktop Q&A currently contains:
     - `Instructions 0607202613216.txt`
     - `Q&A_INDEX.md`
     - `QA-2026-06-23_repo-scan-and-commit-status.md`
   - Website/app repo mirrors contain:
     - `Q&A_INDEX.md`
     - `QA-2026-06-23_round2-resolution.md`
     - `QA-2026-06-23-cross-repo-round-application.md`
   - Risk: reviewers may be reading different Q&A state depending on whether they use the desktop folder or repo mirror.
   - Classification: blocker only if the readiness gate requires mirrors to represent the current desktop Q&A exactly. Otherwise explicitly defer as archival mirror drift.

### Non-Blockers / Proposed Improvements

1. `WEB-COPY-001`: website install wording has a stale LibreCAD example version.
   - `index.html` says `LibreCAD-PDF-Importer-Windows-Portable_v1.0.33.zip`.
   - `repo-metadata.json` and website badges indicate LibreCAD latest is `v1.0.34`.
   - Proposed fix: change the example to `LibreCAD-PDF-Importer-Windows-Portable_vX.Y.Z.zip`, or stamp it dynamically from metadata.

2. `WEB-COPY-002`: website README still says Steel Logic is "Coming soon".
   - `README.md` product table says `Coming soon`.
   - `index.html` has active Google Play beta/testing instructions, and `repo-metadata.json` tracks `Steel-Shapes` release `v1.0.8`.
   - Proposed fix: update README state to "Google Play beta" or link to the tester group / Play Store page.

3. `WEB-COPY-003`: website SEO/meta copy under-describes the current importer set.
   - `index.html` meta description and keywords emphasize SketchUp and FreeCAD.
   - The product section includes SketchUp, FreeCAD, Blender, and LibreCAD.
   - Proposed fix: include Blender and LibreCAD in the meta description/keywords or use a broader "SketchUp, FreeCAD, Blender, and LibreCAD" phrasing.

4. `APP-DOC-001`: app README release-artifact wording is stale for Android.
   - `README.md` says auto-release builds a release APK and publishes `SteelLogic_vX.Y.Z_release.apk`.
   - `.github/workflows/auto-release.yml` builds an AAB by default and only builds APK on manual `workflow_dispatch` with `build_apk=true`.
   - Latest `v1.0.8` release contains `SteelLogic_v1.0.8_release.aab` and `SHA256SUMS.txt`.
   - Proposed fix: document "AAB by default, APK optional/manual" and list both possible artifact names.

5. `APP-WIN-001`: Windows portable app artifact is verified but old relative to Android release metadata.
   - `dist/windows` contains `SteelLogic_v1.0.3_windows_x64.zip` plus `SHA256SUMS_windows_v1.0.3.txt`.
   - Verification passed for `v1.0.3`.
   - Latest app release metadata is `v1.0.8`.
   - Proposed fix: either publish/track a fresh Windows portable `v1.0.8` package, or explicitly document the Windows package as historical/local testing only.

6. `QA-MIRROR-002`: repo Q&A mirrors omit the current desktop report `QA-2026-06-23_repo-scan-and-commit-status.md`.
   - This is related to `QA-MIRROR-001`.
   - Proposed fix: decide whether repo mirrors should be current snapshots or archival evidence. If current, re-mirror after Q&A agreement.

## Agreement / Disagreement Points

### I Agree

- The website download metadata system is structurally sound: `repo-metadata.json`, `nav.js`, and static fallbacks validate cleanly.
- The shapes hub correctly points shape packs to the merged importer repos under `steel_shapes/`, not to the old standalone repos.
- The Steel Logic DB open/copy race guard is the right kind of fix: it shares one open future, resets on failure, and does not weaken schema detection.
- The Windows release verifier is useful and caught the exact class of artifact/hash drift it was meant to prevent.
- Current app validation surface is strong enough for this review pass: analyzer plus 153 tests plus artifact verification.

### I Disagree / Need Q&A Resolution

- I do not agree with calling the app release side "fully clean" while PR #8 remains open and `pubspec.yaml` is still behind the current `v1.0.8` release tag.
- I do not agree with treating Q&A mirrors as reliable current evidence unless the desktop Q&A and repo mirrors are synchronized or explicitly labeled as different scopes.
- I do not think the stale LibreCAD `v1.0.33` example should block users today, but it should be fixed before the next website polish/release cycle because it is exactly the kind of version drift the metadata system was created to avoid.

## Recommended Resolution

1. Merge or otherwise resolve Steel Logic PR #8 so `pubspec.yaml` advances to `1.0.8+9`.
2. Decide whether Q&A mirrors are current mirrors or archival snapshots. If current, synchronize website/app mirrors from the desktop Q&A after reviewers agree.
3. Fix website copy drift:
   - LibreCAD example version.
   - README Steel Logic "Coming soon" state.
   - Meta copy for Blender/LibreCAD.
4. Fix app README release wording to match AAB-by-default and APK-on-demand behavior.
5. Decide whether a new Windows portable Steel Logic package is needed for `v1.0.8` before "any PC" language is used for the app.

## Reviewer C Status

Reviewer C finds no failing local validation and no current website download metadata break. Reviewer C does find release/documentation consistency issues that should be discussed before calling website/app readiness fully resolved.
