# QA-2026-06-24 — Deploy artifact verification (v3.7.65 / v4.0.48 / v1.0.41 / v1.0.44)

**Date:** 2026-06-24 (verification run)  
**Verifier:** automated artifact pass (hashes, archive integrity, embedded versions, GitHub release parity)  
**Scope:** Four downloaded GitHub release assets from `Downloads`

## Executive summary

| File | Health | Version match | Deploy ready |
|------|--------|---------------|--------------|
| `SketchUp-PDF-Importer_v3.7.65.rbz` | **HEALTHY** | Yes (3.7.65) | **READY** |
| `FreeCAD-PDF-Importer-Setup_v4.0.48.exe` | **HEALTHY** | Yes (4.0.48) | **READY** |
| `LibreCAD-PDF-Importer-Windows-Portable_v1.0.41.zip` | **HEALTHY** (layout: see CAUTION note) | Yes (1.0.41) | **READY** |
| `Blender-PDF-Importer_v1.0.44.zip` | **HEALTHY** | Yes (1.0.44) | **READY** |

**Overall artifact gate:** **GO** — all four files are intact, match latest GitHub release digests, and embedded versions match filenames.

**Overall production gate:** **NO-GO** until per-host install smoke (below) and open **T-01** field screenshot retest from agreement round (`QA-2026-06-25_agreement-D-release-coordination.md`). Distribution/staging upload of these exact blobs is approved; declaring shop-floor production sign-off is not.

---

## Per-file detail

### 1. SketchUp — `SketchUp-PDF-Importer_v3.7.65.rbz`

| Check | Result |
|-------|--------|
| Exists | Yes |
| Size | 9,228,021 bytes (~8.8 MiB) |
| Last modified (local) | 2026-06-24 19:51:19 |
| SHA256 | `BC97D13720B60A2BD1AE8FAEE22467AA6F71DEB11FC258806494DACAE7BE5FA5` |
| GitHub `v3.7.65` digest | `sha256:bc97d13720b60a2bd1ae8faee22467aa6f71deb11fc258806494dacae7be5fa5` — **match** |
| ZIP/RBZ valid | Yes (77 entries) |
| Key entries | `bc_pdf_vector_importer.rb`, `bc_pdf_vector_importer/` (Poppler bin, Ruby extension) |
| Embedded version | `bc_pdf_vector_importer/metadata.rb` → `VERSION = '3.7.65'` |
| Repo HEAD | `C:\1PDF-Importer-SketchUp` @ `2a45fb0`; extracted metadata also `3.7.65` |

**Verdict:** **HEALTHY** — **READY**

---

### 2. FreeCAD — `FreeCAD-PDF-Importer-Setup_v4.0.48.exe`

| Check | Result |
|-------|--------|
| Exists | Yes |
| Size | 15,365,365 bytes (~14.7 MiB) |
| Last modified (local) | 2026-06-24 19:51:13 |
| SHA256 | `962758B4C0CF0F39B075692450E8A9B0ACF156011E836D087FBE606490554F9A` |
| GitHub `v4.0.48` digest | `sha256:962758b4c0cf0f39b075692450e8a9b0acf156011e836d087fbe606490554f9a` — **match** |
| Installer type | **Inno Setup** (string in binary); not listable as 7-Zip archive (expected) |
| PE ProductVersion | `4.0.48` |
| Repo | `C:\1PDF-Importer-FreeCAD` @ `c17d786`; `pyproject.toml` `version = "4.0.48"` |

**Verdict:** **HEALTHY** — **READY** (run installer smoke on a VM; not silently extracted here)

---

### 3. LibreCAD portable — `LibreCAD-PDF-Importer-Windows-Portable_v1.0.41.zip`

| Check | Result |
|-------|--------|
| Exists | Yes |
| Size | 186,372,286 bytes (~178 MiB) |
| Last modified (local) | 2026-06-24 19:51:42 |
| SHA256 | `E8A74566A152245CC537AD442C93B5AC193B9466868D531025146496883F7D9D` |
| GitHub `v1.0.41` digest | `sha256:e8a74566a152245cc537ad442c93b5ac193b9466868d531025146496883f7d9d` — **match** |
| ZIP valid | Yes (4 entries) |
| Top-level | `lcpdf-gui.exe`, `lcpdf-import.exe`, `lcpdf-batch.exe`, `pdf2dxf.exe` (~47 MiB each) |
| `gui.py` / loose `pdfcadcore` / `preflight_check.py` | **Not present as separate files** — expected for PyInstaller one-file portable per `INSTALL.md` (bundled inside exes) |
| Functional smoke | `pdf2dxf.exe --preflight` → **exit 0**, preflight paragraph printed |
| Repo | `C:\1PDF-Importer-LibreCAD` @ `09e5a51`; `pyproject.toml` `version = "1.0.41"` |

**CAUTION (documentation only):** Checklist items that expect a visible `pdfcadcore/` tree or `preflight_check.py` in the ZIP do not apply to this portable layout; use `--preflight` on `pdf2dxf.exe` instead.

**Verdict:** **HEALTHY** — **READY**

---

### 4. Blender — `Blender-PDF-Importer_v1.0.44.zip`

| Check | Result |
|-------|--------|
| Exists | Yes |
| Size | 18,280,632 bytes (~17.4 MiB) |
| Last modified (local) | 2026-06-24 19:51:24 |
| SHA256 | `AAACD6BE1B1D0175B5ADF7F7A834D1B022C73C3FC8FB1F6D29FFE0D8EF919942` |
| GitHub `v1.0.44` digest | `sha256:aaacd6be1b1d0175b5adf7f7a834d1b022c73c3fc8fb1f6d29ffe0d8ef919942` — **match** |
| ZIP valid | Yes (58 entries) |
| Top-level | `pdf_vector_importer/`, `README.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md` |
| Addon version | `pdf_vector_importer/__init__.py` → `bl_info["version"] = (1, 0, 44)` |
| `blender_manifest.toml` | Not present (legacy `bl_info` registration — OK for target Blender 3.x) |
| PyMuPDF | Vendored under `pdf_vector_importer/lib/pymupdf*` + `fitz/` + `pymupdf.exe` |
| `pdfcadcore` | Present under `pdf_vector_importer/pdfcadcore/` |
| Repo | `C:\1PDF-Importer-Blender` @ `1ed91c4`; `pyproject.toml` `version = "1.0.44"` |

**Verdict:** **HEALTHY** — **READY**

---

## Version consistency vs agreement / test round

| Product | This artifact | Latest GitHub tag | Local `main` | Agreement-round tested (Round 6 notes) |
|---------|---------------|-------------------|--------------|----------------------------------------|
| SketchUp | 3.7.65 | v3.7.65 (2026-06-25) | 3.7.65 @ 2a45fb0 | Corpus/oracle on **source** HEAD; not this RBZ binary |
| FreeCAD | 4.0.48 | v4.0.48 | 4.0.48 @ c17d786 | Automated tests on repo; **installer not re-run** in this pass |
| LibreCAD | 1.0.41 | v1.0.41 | 1.0.41 @ 09e5a51 | Round 6 corpus run cited importer **1.0.38** on isolated HEAD — **this portable is newer** |
| Blender | 1.0.44 | v1.0.44 | 1.0.44 @ 1ed91c4 | Pipeline tests on repo HEAD; zip not host-imported here |

**Gap:** Release binaries are **newer** than the Round 6 LibreCAD corpus snapshot (1.0.38) and were not fully exercised in-host in Round 6. Automated integrity + LC `--preflight` reduce risk; **one import per host** still required before production.

---

## Tester quick smoke (before production deploy)

1. **SketchUp:** Extension Manager → Install Extension → select RBZ → restart → import one known corpus PDF → confirm geometry + import report.
2. **FreeCAD:** Run `FreeCAD-PDF-Importer-Setup_v4.0.48.exe` → confirm add-on appears → import one PDF → check import report / scale banner.
3. **LibreCAD:** Unzip portable → run `lcpdf-gui.exe` OR `pdf2dxf.exe <sample.pdf> -o out.dxf` → open DXF in LibreCAD.
4. **Blender:** Edit → Preferences → Add-ons → Install from disk → select zip → enable → File → Import → PDF Vector → one sample PDF.

Complete **T-01** field screenshot retest per `QA-2026-06-24_human-confirmation-script.md` before calling production closed.

---

## Mirror locations

- Canonical: `C:\Users\Rowdy Payton\Desktop\PDFTest Files\Q&A\QA-2026-06-24_deploy-artifact-verification.md`
- Repo mirrors: `_LLM_CONTROL_PACK/QA/` in SketchUp, FreeCAD, LibreCAD, Blender importers
- Website: no `_LLM_CONTROL_PACK/QA` folder present — not mirrored

