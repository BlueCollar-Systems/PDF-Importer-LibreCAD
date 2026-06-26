# Release-Pipeline P0 Resolution — 2026-06-25

**Inputs:** `QA-2026-06-25_reply-ecosystem-audit-and-cross-round.md` §1 (P0-A/B/C)  
**Author:** Anonymous cross-review worker (release-pipeline lane)  
**Status:** **SHIPPED AND RELEASE-VERIFIED** — CI/workflow fixes are committed for auto-release and tag/manual release paths; latest release assets were regenerated and smoked; product field sign-off still tracks separately under T-01

**2026-06-25 follow-up:** auto-release test gates now fail before any version-bump commit in FC/LC/SU/BL. Artifact smoke still runs after build and before release upload/create.

**2026-06-25 FreeCAD clean-runner follow-up:** FreeCAD auto-release vendors the bundled PyMuPDF runtime before pytest because `src/lib` is gitignored on a fresh runner; release creation now uses `gh release create --target` so a commit that touches `.github/workflows` does not block tag/release creation through a checkout token.

**2026-06-25 final release verification:** manual auto-release dispatches passed after the fixes: FC v4.0.52, LC v1.0.47, SU v3.7.72, and BL v1.0.49. Each run completed its release gate, built the package, smoked the shipped artifact, created or updated the GitHub release, dispatched the website, and the website deployed successfully. SU/BL tag creation was also hardened to use `gh release create --target`; SU's dependency resolver gate now uses the correct bundled helper name on Linux and Windows runners.

---

## P0 items addressed

| ID | Title | Root cause | Fix shipped |
|----|-------|------------|-------------|
| **P0-A** | FreeCAD `--latest` bundles Linux PyMuPDF | `auto-release.yml` ran on `ubuntu-latest`; `build_release.py` pip-targeted host OS wheel | **FC `auto-release.yml` → `windows-latest`**; post-build `scripts/smoke_release_zip.py` verifies Windows `.pyd` import and rejects `.so`/manylinux payload |
| **P0-B** | LibreCAD `--latest` was source-only zip | Auto-release only ran `build_release.py`; portable built only on tag `release.yml` | **LC `auto-release.yml` → `windows-latest`**; builds **both** source + `build_windows_portable.py`; publishes portable **first** as `--latest` asset; `scripts/smoke_portable_zip.py` runs `pdf2dxf.exe --help` |
| **P0-C** | Release workflows had no enforced test/smoke gate | Auto-release workflows published without inline tests; tag/manual release workflows for FC/LC/BL could also publish artifacts without the same gate | **All release paths:** `Run release gate tests` step (sync/compile/preflight + pytest or Ruby smoke) before build/publish; auto-release tests now run before version-bump commits; artifact smoke runs before upload/create (FC zip, LC portable, SU RBZ structure, BL zip) |

---

## Verification (local, 2026-06-25)

| Gate | FC | LC | SU | BL |
|------|----|----|----|-----|
| `pdfcadcore_sync_check.py --skip-cross-repo` | PASS | PASS | n/a | PASS |
| pytest / unit tests | PASS* | 45 passed | n/a | 43 passed |
| `check_su2017_ruby_compat.py` | n/a | n/a | PASS | n/a |
| `ruby22_compat_test.rb` + smoke | n/a | n/a | PASS | n/a |
| `build_release.py` + artifact smoke | PASS (v4.0.52 zip) | PASS (source + portable v1.0.47 zip) | PASS (RBZ v3.7.72) | PASS (v1.0.49 zip) |
| GitHub auto-release dispatch | PASS (v4.0.52) | PASS (v1.0.47) | PASS (v3.7.72) | PASS (v1.0.49) |
| tag/manual release workflow gate inspection | PASS (`windows-release.yml`) | PASS (`release.yml`) | n/a | PASS (`release.yml`) |

\* FC pytest hit a Windows `.pytest_tmp` permission teardown warning; tests completed 100%.  

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
- **P1 backlog** from audit (#4 SmartScreen copy, #9 BL off-Windows wheel) — not in this P0 slice

## Closed by final release verification

- **First green GitHub release runs** — complete for FC/LC/SU/BL; website release metadata and Cloudflare Pages deploy completed successfully.

---

*Release-pipeline P0 resolution — anonymous reviewers — 2026-06-25*
