# How to Use the LibreCAD PDF Importer

This tool converts PDF drawings to DXF files that you can open in LibreCAD, AutoCAD, DraftSight, QCAD, or any DXF-compatible CAD program.

## Canonical install (field testers)

**Use the portable ZIP** (`LibreCAD-PDF-Importer-Windows-Portable_vX.Y.Z.zip`) as the single supported path for human confirmation and shop-floor testing. It bundles Python, PyMuPDF, ezdxf, FontTools, Matplotlib, NumPy, pdfcadcore, `lcpdf-gui.exe`, and CLI tools with no Qt or system-Python dependencies.

The portable ZIP also carries `librecad-plugin\bc_lcpdf_menu.dll`, which adds **Plugins > Import PDF (BlueCollar)...** to **LibreCAD 2.2.x for Windows (64-bit, Qt 5.15)**. It is built in release CI against the same Qt 5.15.2 MSVC kit LibreCAD 2.2.1.x uses. It only starts `lcpdf-gui.exe` and opens the DXF that program writes, so conversion results are identical either way. (The old locally built `pdfimporter1.dll` is not supported; delete it if you have one.)

## Quick Start

### Option 0: Portable ZIP — recommended for Windows users
1. Download `LibreCAD-PDF-Importer-Windows-Portable_vX.Y.Z.zip` from [Releases](https://github.com/BlueCollar-Systems/PDF-Importer-LibreCAD/releases).
2. Extract it anywhere you can write files.
3. Run `lcpdf-gui.exe`, or use `pdf2dxf.exe` / `lcpdf-batch.exe` for command-line and batch conversion.

The portable ZIP bundles Python, PyMuPDF, ezdxf, FontTools, Matplotlib, NumPy, pdfcadcore, the GUI, and the
CLI launchers. No system Python, pip, or administrator rights are required.

### Option 0a: Source ZIP fallback
1. Download `LibreCAD-PDF-Importer_vX.Y.Z.zip` from [Releases](https://github.com/BlueCollar-Systems/PDF-Importer-LibreCAD/releases).
2. Extract it anywhere you can write files.
3. From that folder:
   ```powershell
   python preflight_check.py --install
   python pdf2dxf.py --gui
   ```
4. `preflight_check.py --install` vendors PyMuPDF, ezdxf, FontTools, Matplotlib, and NumPy into `./lib` (no admin).

Each successful conversion also writes `<output>_import_report.json` beside the DXF
with `text_mode`, `resolved_scale`, `peak_mb`, and raster fallback telemetry.

**Offline install:** The portable ZIP works without internet after download. Source ZIP dev installs may run `preflight_check.py --install` once if `lib/` is empty.

**Scale trust:** use `extra.resolved_scale.factor` only when `confidence >= 0.70` and
`fallback_reason` is not `no_scale_detected`; otherwise set scale manually in your CAD app.

**Bad-PDF gate:** LibreCAD converter refuses encrypted/non-PDF/truncated files at open
(**fail closed**). SketchUp shows the same messages but may proceed on rare gate errors
(**fail open**).

### Option 0b: Standalone installer — when published
When `LibreCAD-PDF-Importer-Setup_vX.Y.Z.exe` appears on Releases, double-click it
(no admin required) and launch **LibreCAD PDF Importer** from the Start menu.

> Build locally: run `python build_standalone.py`, then use the exact
> versioned Inno Setup command it prints. The installer script rejects a
> missing `/DAppVersion=X.Y.Z` instead of silently minting a stale version.

### Option 1: LibreCAD Plugins menu (LibreCAD 2.2.x, Windows 64-bit)

1. Close LibreCAD.
2. Run `lcpdf-gui.exe` from the portable folder and press
   **Install LibreCAD menu entry...**. This copies `bc_lcpdf_menu.dll` into
   `Documents\LibreCAD\plugins` (no admin rights) and records where
   `lcpdf-gui.exe` lives.
3. Start LibreCAD and choose **Plugins > Import PDF (BlueCollar)...**.
4. In the importer window pick the PDF and options and press **Convert / Resume**.
   The finished DXF opens in LibreCAD automatically.

`Plugins > Import PDF into Current Drawing (BlueCollar)...` inserts the DXF into
the open drawing as a block instead. `Plugins > PDF Importer Settings (BlueCollar)...`
pins another importer; `BC_LC_IMPORTER_EXE` / `BC_LC_IMPORTER_SCRIPT` override it.
From a source checkout: `python scripts\build_librecad_plugin.py --smoke --install`
(needs the Qt 5.15.2 `msvc2019_64` kit and Visual Studio C++ build tools).
Other LibreCAD builds (Qt 6 development builds, MinGW, Linux/macOS) cannot load
the DLL; use `lcpdf-gui.exe` with "Open in LibreCAD after convert" there.

### Option 2: Command Line
```bash
python pdf2dxf.py "C:\path\to\drawing.pdf" "C:\output\drawing.dxf"
```

### Option 3: GUI Window (no terminal required)
```bash
python gui.py
```
A window opens where you can browse for a PDF, choose mode + text rendering,
export, and auto-open the DXF in LibreCAD.

### Option 3b: Double-click launcher (Windows, no terminal)
- Double-click `launch_lcpdf_gui.pyw`
- Or install entrypoint and run `lcpdf-guiw`

### Option 4: Batch Convert (multiple files)
```bash
python -m librecad_pdf_importer.batch_cli "C:\folder\with\pdfs"
```

## After Converting

1. In the GUI, keep `Open in LibreCAD after convert` enabled
2. Click `Convert`
3. LibreCAD opens automatically with the generated DXF

## GUI (professional import)

The graphical interface uses **Auto** import only (vector/raster/hybrid chosen per page).

### Before you import (text modes)

- **Text** — the native DXF `TEXT` candidate is built and checked first, but
  LibreCAD's substituted LFF font does not reproduce the source glyphs, so visible
  text is delivered as exact Glyph outlines (reported as that fallback). Only a
  whitespace-only span ends as native `TEXT`.
- **Labels** — DXF has no native Label entity; that is recorded, then the span
  follows the Text path above and is delivered as Glyph outlines.
- **3D Text** — attempts DXF `TEXT` with thickness and +Z extrusion first;
  native success also requires verified 3D display/edit semantics in the parent,
  which 2D LibreCAD cannot give, so the span is delivered as Glyph outlines.
- **Glyphs** — grouped outline block references.
- **Geometry** — raw outline edges, not editable as text.
- **Raster** — source-bound exact item pixels in a verified DXF `IMAGE`.
- **Searchable text (every mode)** — outlines are the visual truth, and the exact
  strings are hidden native `TEXT` on the frozen, non-plotting layer
  `P###_TEXT_SEARCH`. To work with editable LFF text, thaw `P###_TEXT_SEARCH` and
  freeze `P###_TEXT`; to print that text, also switch the layer's print flag on in
  the layer list (the layer is non-plotting). `--no-searchable-text` (CLI) leaves
  the layer out. A pre-R2007 (R12/R2000/R2004) file is cp1252, not UTF-8: a
  character in that code page (degree, plus-minus, diameter) is one cp1252 byte and
  any other is a `\U+XXXX` escape, so a UTF-8 text search of such a file does not
  find non-ASCII strings.
- Scale warnings appear in `import_report.json` (`extra.scale_crosscheck` / `human_summary`) when title-block scale is uncertain.

The GUI and CLI expose the same six representation choices. The selected type
is attempted and verified item by item. For Text, Labels, and 3D Text a visibly
substituted LibreCAD LFF font is never certified as delivered Text (since
1.0.81): the span descends to exact Glyph outlines and the report says so. The
hidden `P###_TEXT_SEARCH` companions keep the exact string, anchor, rotation, and
source-width FIT alignment and certify nothing. The result dialog, log, and
complete report show requested and delivered types.

## Modes (BCS-ARCH-001, CLI/batch)

Every mode targets **indistinguishable-from-source** fidelity. Modes differ
only in extraction strategy, not in quality tier.

| Mode | When to Use |
|------|-------------|
| **auto** *(default)* | Picks the right strategy per page automatically |
| **vector** | Clean vector PDFs (CAD exports, shop drawings) |
| **raster** | Scanned or image-only PDFs |
| **hybrid** | Mixed content (vectors + embedded raster) |

### Text Rendering (orthogonal)

GUI and CLI: `text`, `labels`, `3d_text`, `glyphs`, `geometry`, and `raster` as
distinct requests, plus the Import text toggle. Text builds the native `TEXT`
candidate first and 3D Text first attempts native `TEXT` with verified extrusion,
but a visibly substituted LibreCAD LFF font is never certified as delivered Text
(since 1.0.81): a visible span is delivered as exact Glyph outlines and reported
as that fallback, and only a whitespace-only span ends as native `TEXT`. DXF has
no native Label entity, so Labels records that exact item-scoped impossibility
instead of relabeling TEXT/MTEXT and then follows the same Text path to Glyph
outlines. Glyphs are grouped block references, Geometry is raw modelspace edges,
and requested Raster is an exact source-item `IMAGE`. In every mode the exact
strings are hidden native `TEXT` on the frozen layer `P###_TEXT_SEARCH`
(`--no-searchable-text` leaves it out).

## Requirements

- Standalone installer: no separate Python or pip packages.
- Source/dev checkout: Python 3.12+, PyMuPDF 1.28.0, ezdxf 1.4.4,
  FontTools 4.63.0, Matplotlib 3.11.1, and NumPy 2.5.1, either installed into
  your active environment or vendored into `./lib` with
  `tools/fetch_runtime_wheels.ps1`.

### One-click dependency check (Windows)

```powershell
python preflight_check.py
python preflight_check.py --install
python pdf2dxf.py --preflight
```

The `--install` flag downloads PyMuPDF, ezdxf, FontTools, Matplotlib, and NumPy into `./lib` with no admin rights required. `--preflight` prints pre-import text-mode and scale-trust guidance without converting a PDF.

Standalone app self-test after install:

```powershell
& "$env:LOCALAPPDATA\Programs\BlueCollar Systems\LibreCAD PDF Importer\LibreCAD-PDF-Importer.exe" --self-test
```

## Troubleshooting

**Black screen when opening DXF?** The importer auto-inverts white lines to black for visibility. If you still see a blank screen, try View > Auto Zoom in LibreCAD.

**Missing text?** Treat that as a failed delivery. Open the complete import
report, compare `text_source_spans` with `text_representation_delivery`, and
inspect the exact source-item attempt. Keep the requested representation while
correcting the source-specific failure. One text item that cannot be verified
no longer stops its sheet: it is warned about on stderr (or in the GUI), listed
in `extra.text_items_degraded`, and delivered as an unverified Raster patch, as
visible `TEXT` on layer `P###_TEXT_DEGRADED`, or dropped. Such a sheet is
never certified, so review every listed item before using the drawing.

**Garbled, shifted, rotated, or scaled text?** Do not manually switch the
request to hide it. Attach the complete report and correct placement, rotation,
width, or height inside the requested representation. If the report proves an
item-specific parent-font incompatibility, inspect the automatic fallback; do
not remove its gate or relabel parent-native rendering as source-font-exact.
Keep any same-representation font substitution or Unicode compatibility
normalization visible in the report.

**Plugin menu says launcher not found?** Install the portable ZIP or source
package, then use `Plugins > PDF Importer Settings...` to point at
`LibreCAD-PDF-Importer.exe`, `lcpdf-gui.exe`, or `launch_lcpdf_gui.pyw`. Set
`BC_LC_IMPORTER_EXE` / `BC_LC_IMPORTER_SCRIPT` for custom paths.

**Geometry looks wrong?** Check the per-page resolved strategy and exact entity
evidence in the import report. A strategy change is diagnostic only; it must not
change or weaken the requested output representation.
