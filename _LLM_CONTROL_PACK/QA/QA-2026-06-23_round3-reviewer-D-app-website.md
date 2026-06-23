# Round 3 — Reviewer D: Steel Logic App + BlueCollar Website

**Date:** 2026-06-23  
**Scope:** `C:\1 Structural_Steel_Shapes_App`, `C:\1BlueCollar-Website`

---

## Executive summary

Steel Logic app is **clean** under `flutter analyze` and **153/153 tests passed**. Website static metadata validation **passed**. Minor **version string drift** between app `pubspec.yaml`, GitHub `Steel-Shapes` release (v1.0.8), and website footer (v1.0.54). Website LibreCAD install copy references an **outdated portable zip example** (v1.0.33).

---

## Findings (≥5)

### D-1 — Flutter analyze: no issues (positive)

| Field | Value |
|-------|-------|
| **Repo** | `C:\1 Structural_Steel_Shapes_App` |
| **Severity** | **Info** |
| **Evidence** | `flutter analyze` → `No issues found! (ran in 45.7s)` |
| **Recommend** | **No action.** |

### D-2 — Flutter test suite fully green (positive)

| Field | Value |
|-------|-------|
| **Repo** | `C:\1 Structural_Steel_Shapes_App` |
| **Severity** | **Info** |
| **Evidence** | `flutter test` → `153` tests passed (e.g. `polygon_irregular_screen_test.dart`, `universal_calculator_layout_test.dart`). |
| **Recommend** | **No action.** |

### D-3 — App version vs GitHub Steel-Shapes release mismatch

| Field | Value |
|-------|-------|
| **Repo** | Steel app vs `repo-metadata.json` |
| **File** | `pubspec.yaml` line 4: `version: 1.0.7+8`; metadata `Steel-Shapes` latest `v1.0.8` (2026-05-25) |
| **Severity** | **P2** |
| **Evidence** | Local app semver behind published Play/GitHub release tag. May indicate pending release bump or forked versioning (`1.0.7+8` build number). |
| **Recommend** | Align `pubspec.yaml` with release policy; update website Steel Logic section if user-facing version shown. **Owner confirm** intended version. |

### D-4 — Website static metadata validation passed (positive)

| Field | Value |
|-------|-------|
| **Repo** | `C:\1BlueCollar-Website` |
| **File** | `tools/validate_static_metadata.py` |
| **Severity** | **Info** |
| **Evidence** | `Static metadata fallback check passed (8 labels).` |
| **Recommend** | Run after `sync_repo_metadata.py` in release checklist. **No action.** |

### D-5 — Website footer version vs importer versions

| Field | Value |
|-------|-------|
| **Repo** | `C:\1BlueCollar-Website` |
| **File** | `index.html` line 238: `v1.0.54`; `VERSION` file = `1.0.54` |
| **Severity** | **P2** |
| **Evidence** | Website site version (1.0.54) is independent from importer tags (SU 3.7.56, FC 4.0.40, etc.) — correct pattern, but Steel Logic block does not surface app semver. |
| **Recommend** | Add `data-repo-version` for Steel-Shapes app if Play Store version should auto-display. **Defer** cosmetic. |

### D-6 — Stale LibreCAD portable ZIP example on homepage

| Field | Value |
|-------|-------|
| **Repo** | `C:\1BlueCollar-Website` |
| **File** | `index.html` line 204 |
| **Severity** | **P2** |
| **Evidence** | Example `...-Windows-Portable_v1.0.33.zip` vs current `v1.0.34` portable asset on GitHub. |
| **Recommend** | Update to v1.0.34 or templated `vX.Y.Z`. **Fix** with website commit. |

### D-7 — Shape pack metadata consistent (positive)

| Field | Value |
|-------|-------|
| **Repo** | Website + importers |
| **File** | `shapes.html` lines 58–59; `repo-metadata.json` steel-v1.0.0 entries |
| **Severity** | **Info** |
| **Evidence** | Copy states shape packs live under each importer's `steel_shapes/`; metadata lists SU/FC steel-v1.0.0 assets with SHA256SUMS. |
| **Recommend** | **No action.** |

### D-8 — Play Store / beta links present (positive)

| Field | Value |
|-------|-------|
| **Repo** | `C:\1BlueCollar-Website` |
| **File** | `index.html` Steel Logic section; `feedback.html` |
| **Severity** | **Info** |
| **Evidence** | Google Play link `com.bluecollarsystems.steellogic`; beta Google Group linked. Extensionless `/shapes`, `/feedback` routes valid via Cloudflare clean URLs (`_redirects` intentional blank). |
| **Recommend** | **No action.** |

---

## App + website test summary

| Command | Result |
|---------|--------|
| `flutter analyze` | No issues |
| `flutter test` | 153 passed |
| `python tools/validate_static_metadata.py` | 8 labels passed |

---

*Anonymous Reviewer D — Round 3 scan.*
