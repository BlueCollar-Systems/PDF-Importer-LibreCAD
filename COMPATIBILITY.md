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

- **2D parent** — a 3D Text request creates and reads back item-specific DXF
  `TEXT` thickness/+Z extrusion, but LibreCAD is not credited with native 3D
  delivery unless its displayed/editable 3D semantics are also verified. The
  current verified outcome is a loud nearest-representation fallback.
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

- **Text**: native editable DXF `TEXT`, with exact source-item binding and the Text semantic verified independently from Labels. Parent-font substitution and any Unicode compatibility normalization are reported and are not described as source-font exactness.
- **Labels**: DXF exposes no native Label entity. The importer records that exact item-scoped capability failure, creates no report-only TEXT/MTEXT alias, then verifies the closest editable Text fallback. The fallback and LibreCAD Unicode LFF substitution are both reported distinctly.
- **3D Text**: thickness/+Z extrusion is created and read back for the exact item, but native success additionally requires verified parent 3D display/edit semantics. LibreCAD's 2D parent therefore reports and delivers verified flat editable Text as the closest fallback.
- **Glyphs**: grouped `INSERT` entities whose owned block definitions contain the outline curves.
- **Geometry**: exploded raw modelspace outline edges, structurally distinct from Glyphs.
- **Raster**: an exact source-PDF-bound item crop is a direct result when requested, or a terminal fallback only after every structural rung is proven impossible. Visible pixels, placement, source digest/page/item, `IMAGE` handle, and owned asset bytes must verify.
- **GUI text options**: Text, Labels, 3D Text, Glyphs, Geometry, and Raster—the same choices as the CLI.
- **R12 identity**: R12 does not serialize `BLOCK_RECORD`; that single synthetic parser record is excluded from durable support IDs while every serialized glyph entity remains handle-reconciled.

## DXF consumers (secondary)

Exported DXF (default R2010) opens in AutoCAD 2010+, DraftSight, QCAD. R12 available for maximum legacy compatibility.

## CI coverage

GitHub Actions: pytest on Python **3.10, 3.11, 3.12**; `pdfcadcore_sync_check.py`.
