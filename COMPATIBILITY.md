# Compatibility — PDF to DXF (LibreCAD)

Modes are extraction **strategy** (Auto / Vector / Raster / Hybrid), not quality tiers.

---

## Minimum host version

**LibreCAD 2.2+**. The standalone portable importer bundles its Python runtime;
LibreCAD remains the supported editor/viewer for the generated DXF.

## Oldest tested

| Host | Status |
|------|--------|
| LibreCAD 2.2.x+ | ✅ Supported |
| LibreCAD 2.1.x / 2.0.x | ⚠️ Unverified; upgrade recommended |
| LibreCAD &lt; 2.0 | ❌ Not supported |

Portable Windows ZIP smoke-tested at release; full GUI verification is manual.

## Ruby / Python ABI

| Runtime | Notes |
|---------|-------|
| **Python 3.12.10** | Portable bundle; source/dev requires Python 3.12+ |
| Ruby | Not used |

Release portable ZIP bundles Python + PyMuPDF + ezdxf + FontTools + Matplotlib + NumPy — no system Python required.

## Bundled dependencies

| Dependency | Portable ZIP | Source dev |
|------------|--------------|------------|
| Python runtime | ✅ 3.12.10 bundled | 3.12+ required |
| PyMuPDF 1.28.0 | ✅ Bundled | `preflight_check.py --install` |
| ezdxf 1.4.4 | ✅ Bundled | `preflight_check.py --install` |
| FontTools 4.63.0 | ✅ Bundled | `preflight_check.py --install` |
| Matplotlib 3.11.1 | ✅ Bundled | `preflight_check.py --install` |
| NumPy 2.5.1 | ✅ Bundled | `preflight_check.py --install` |
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
cd <extracted-source-folder>
python preflight_check.py
python preflight_check.py --install
python pdf2dxf.py --preflight
lcpdf-import --preflight path\to\sample.pdf
```

Portable users: run `lcpdf-gui.exe` from extracted ZIP — no terminal required.

---

## LibreCAD version matrix

| LibreCAD | Python (standalone) | ezdxf | PyMuPDF | FontTools | Status |
|----------|---------------------|-------|---------|-----------|--------|
| 2.2.x+ | 3.12+ | 1.4.4 | 1.28.0 | 4.63.0 | ✅ Supported |
| 2.1.x | 3.12+ | 1.4.4 | 1.28.0 | 4.63.0 | ⚠️ Unverified |
| 2.0.x | 3.12+ | 1.4.4 | 1.28.0 | 4.63.0 | ⚠️ Unverified |
| < 2.0 | | | | | ❌ Not supported |

### LibreCAD-specific behavior

- **Text**: the native DXF `TEXT` candidate is built with exact source-item binding and checked independently from Labels, but a visibly substituted LibreCAD LFF font is never certified as delivered Text (since 1.0.81). A visible span is delivered as exact Glyph outlines, reported as that fallback; only a whitespace-only span ends as native `TEXT`.
- **Labels**: DXF exposes no native Label entity. The importer records that exact item-scoped capability failure, creates no report-only TEXT/MTEXT alias, then follows the Text path above, so a visible span is delivered as Glyph outlines and both transitions are reported.
- **3D Text**: thickness/+Z extrusion is created and read back for the exact item, but native success additionally requires verified parent 3D display/edit semantics. LibreCAD's 2D parent cannot give them, so the item advances to the flat Text rung and, as above, is delivered as Glyph outlines.
- **Searchable text**: outlines are the visual truth; the exact source string of every span delivered as Glyphs, Geometry, or Raster (and of a dropped item) is a hidden native `TEXT` on the frozen layer `P###_TEXT_SEARCH` (non-plotting from R2000 on). It certifies nothing and changes no delivery evidence or count. To work with editable LFF text, thaw `P###_TEXT_SEARCH` and freeze `P###_TEXT`; to print that text, also switch the layer's print flag on (LibreCAD honours the non-plotting flag on a thawed layer). LibreCAD 2.2 has no find-text command: the strings are searchable in the file; thaw the layer before using another host's find command. R12/R2000/R2004 files are cp1252, so a UTF-8 text search does not find non-ASCII strings there (a character in the code page is one cp1252 byte, any other a `\U+XXXX` escape). A string LibreCAD or the DXF writer would alter (`%%` and caret codes, `\P`, `\~`, control characters) gets no companion and is reported `not_representable`. `--no-searchable-text` turns it off.
- **Glyphs**: grouped `INSERT` entities whose owned block definitions contain the outline curves.
- **Geometry**: exploded raw modelspace outline edges, structurally distinct from Glyphs.
- **Raster**: an exact source-PDF-bound item crop is a direct result when requested, and a certified (`verified: true`) terminal fallback only after every structural rung is proven impossible. Visible pixels, placement, source digest/page/item, `IMAGE` handle, and owned asset bytes must verify. An item whose failure is not proven also receives an item Raster patch instead of stopping the sheet, but that patch is recorded `verified: false` / `degraded: true`, listed in `extra.text_items_degraded`, and keeps the sheet out of certification; if the patch cannot be made or proven the item becomes visible `TEXT` on `P###_TEXT_DEGRADED`, then a reported drop.
- **GUI text options**: Text, Labels, 3D Text, Glyphs, Geometry, and Raster—the same choices as the CLI.
- **R12 identity**: R12 does not serialize `BLOCK_RECORD`; that single synthetic parser record is excluded from durable support IDs while every serialized glyph entity remains handle-reconciled.

## DXF consumers (secondary)

Exported DXF (default R2010) opens in AutoCAD 2010+, DraftSight, QCAD. R12 available for maximum legacy compatibility.

## CI coverage

GitHub Actions: pytest on Python **3.10, 3.11, 3.12**; `pdfcadcore_sync_check.py`.
