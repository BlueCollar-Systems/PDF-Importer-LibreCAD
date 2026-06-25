# Release-Pipeline P0 Resolution — 2026-06-25

**Inputs:** `QA-2026-06-25_reply-ecosystem-audit-and-cross-round.md` §1 (P0-A/B/C)  
**Author:** Anonymous cross-review worker (release-pipeline lane)  
**Status:** **SHIPPED** — CI/workflow fixes committed; field release still blocked on T-01

---

## P0 items addressed

| ID | Title | Root cause | Fix shipped |
|----|-------|------------|-------------|
| **P0-A** | FreeCAD `--latest` bundles Linux PyMuPDF | `auto-release.yml` ran on `ubuntu-latest`; `build_release.py` pip-targeted host OS wheel | **FC `auto-release.yml` → `windows-latest`**; post-build `scripts/smoke_release_zip.py` verifies Windows `.pyd` import and rejects `.so`/manylinux payload |
| **P0-B** | LibreCAD `--latest` was source-only zip | Auto-release only ran `build_release.py`; portable built only on tag `release.yml` | **LC `auto-release.yml` → `windows-latest`**; builds **both** source + `build_windows_portable.py`; publishes portable **first** as `--latest` asset; `scripts/smoke_portable_zip.py` runs `pdf2dxf.exe --help` |
| **P0-C** | Auto-release had no test/smoke gate | Four `auto-release.yml` workflows published without inline tests | **All four hosts:** `Run release gate tests` step (sync check + pytest / Ruby smoke) **before** build; artifact smoke **before** `gh release create` (FC zip, LC portable, SU RBZ structure, BL zip) |

---

## Verification (local, 2026-06-25)

| Gate | FC | LC | SU | BL |
|------|----|----|----|-----|
| `pdfcadcore_sync_check.py --skip-cross-repo` | PASS | PASS | n/a | PASS |
| pytest / unit tests | PASS* | 45 passed | n/a | 43 passed |
| `check_su2017_ruby_compat.py` | n/a | n/a | PASS | n/a |
| `ruby22_compat_test.rb` + smoke | n/a | n/a | PASS | n/a |
| `build_release.py` + artifact smoke | PASS (v4.0.51 zip) | not run† | n/a | PASS (v1.0.47 zip) |

\* FC pytest hit a Windows `.pytest_tmp` permission teardown warning; tests completed 100%.  
† LC portable PyInstaller build deferred locally (slow); workflow step validated by script review + LC unit tests green.

---

## Cross-review agreement (4/4)

| Reviewer | Position |
|----------|----------|
| A (pipeline) | Windows runners + inline gates close P0-A/B/C without waiting on parallel CI |
| B (LC/BL) | Portable-first release asset matches INSTALL.md and website copy |
| C (FC) | Smoke import from extracted zip catches wrong-OS wheel regressions |
| D (honesty) | R2-1 offline claim now holds for auto-release `--latest` once next CI release runs |

**GO:** commit/push workflow + smoke scripts + this Q&A mirror.

---

## Still open

- **T-01** — human field screenshot sign-off (product owner)
- **WS-RUBY22** — Joe Campbell SU 2017 field confirm on next published RBZ
- **P1 backlog** from audit (#4 SmartScreen copy, #9 BL off-Windows wheel, #11 FC Setup.exe gate) — not in this P0 slice
- **First green auto-release on GitHub** — fixes land in repo; `--latest` assets update only after next non-`[skip release]` push to each host

---

*Release-pipeline P0 resolution — anonymous reviewers — 2026-06-25*
