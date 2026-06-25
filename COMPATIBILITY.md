# Compatibility — PDF to DXF (LibreCAD)

**Canonical path:** `C:\1PDF-Importer-LibreCAD`  
Modes are extraction **strategy** (Auto / Vector / Raster / Hybrid), not quality tiers.

---

## Minimum host version

**LibreCAD 2.0.x** (portable ZIP canonical install). **Recommended: LibreCAD 2.1+**.

## Oldest tested

| Host | Status |
|------|--------|
| LibreCAD 2.2.x+ | ⚠️ Expected |
| LibreCAD 2.1.x / 2.0.x | ⚠️ Expected |
| LibreCAD &lt; 2.0 | ❌ Not supported |

Portable Windows ZIP smoke-tested at release; full GUI verification is manual.

## Ruby / Python ABI

| Runtime | Notes |
|---------|-------|
| **Python 3.10+** | Standalone CLI / portable bundle |
| Ruby | Not used |

Release portable ZIP bundles Python + PyMuPDF + ezdxf — no system Python required.

## Bundled dependencies

| Dependency | Portable ZIP | Source dev |
|------------|--------------|------------|
| Python runtime | ✅ Bundled | 3.10+ required |
| PyMuPDF (>=1.24, &lt;2.0) | ✅ Bundled | `preflight_check.py --install` |
| ezdxf (>=1.0) | ✅ Bundled | `preflight_check.py --install` |
| pdfcadcore | ✅ Bundled | Same |

## Legacy hardware notes

- **2D host only** — no 3D text; use Labels or Outlines in GUI.
- Large PDFs: CLI page ranges (`--pages`) on older PCs; check `import_report.extra.performance_hint`.
- DXF R2010 default; use `--dxf-version R12` for legacy DXF readers.

## Offline install

Release **portable ZIP** and installer artifacts work without internet after download. Source dev path may run `preflight_check.py --install` once if `lib/` is empty.

## Enterprise / roaming

Install portable ZIP per user profile with write access. Roaming `%APPDATA%` is untested — prefer per-machine extract paths documented in INSTALL.md.

## Preflight command

```powershell
cd C:\1PDF-Importer-LibreCAD
python preflight_check.py
python preflight_check.py --install
python pdf2dxf.py --preflight
lcpdf-import --preflight path\to\sample.pdf
```

Portable users: run `lcpdf-gui.exe` from extracted ZIP — no terminal required.

---

## LibreCAD version matrix

| LibreCAD | Python (standalone) | ezdxf | PyMuPDF | Status |
|----------|---------------------|-------|---------|--------|
| 2.2.x+ | 3.10+ | >=1.0 | >=1.24,<2.0 | ⚠️ Expected |
| 2.1.x | 3.10+ | >=1.0 | >=1.24,<2.0 | ⚠️ Expected |
| 2.0.x | 3.10+ | >=1.0 | >=1.24,<2.0 | ⚠️ Expected |
| < 2.0 | | | | ❌ Not supported |

### LibreCAD-specific behavior

- **2D only**: 3D Text and Glyphs map to DXF TEXT equivalent to Labels in GUI.
- **GUI text options**: Labels (editable TEXT) and Outlines only.

## DXF consumers (secondary)

Exported DXF (default R2010) opens in AutoCAD 2010+, DraftSight, QCAD. R12 available for maximum legacy compatibility.

## CI coverage

GitHub Actions: pytest on Python **3.10, 3.11, 3.12**; `pdfcadcore_sync_check.py`.
