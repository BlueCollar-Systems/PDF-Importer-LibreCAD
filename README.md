# PDF to DXF Converter for LibreCAD

**BlueCollar Systems -- BUILT. NOT BOUGHT.**

Converts PDF vector drawings to DXF format for use with LibreCAD, AutoCAD,
DraftSight, QCAD, and any DXF-compatible CAD software.

## Features

- Extracts lines, polylines, arcs, circles, rectangles, and closed loops
- Preserves stroke colors, line widths, and dash patterns
- Imports text with font size and rotation
- Text rendering always at maximum fidelity (no quality dials)
- **Professional import (GUI)**: Auto mode only — picks vector/raster/hybrid per page internally
- **CLI/batch modes** (BCS-ARCH-001): Auto, Vector, Raster, Hybrid for scripting
- **2D text (GUI)**: Labels (editable DXF TEXT) or Outlines (skip editable text). LibreCAD has no true 3D text; see [COMPATIBILITY.md](COMPATIBILITY.md)
- **Maximum fidelity by default** -- no quality tiers, no fast-mode compromises
- Organizes geometry into DXF layers (per-page and per-OCG)
- Outputs DXF versions from R12 through R2018
- CLI and GUI interfaces (including no-console Windows launcher)
- Optional native LibreCAD `Plugins` menu integration (no terminal)
- Optional auto-open in LibreCAD after conversion
- Built on pdfcadcore shared extraction engine

## Import report / scale trust

Conversions write `<output>_import_report.json` with optional `extra.resolved_scale`.

- Use `factor` only when `confidence >= 0.70` and `fallback_reason` is not `no_scale_detected`.
- Otherwise treat scale as unknown in your CAD workflow.

## Compatibility

See **[COMPATIBILITY.md](COMPATIBILITY.md)** for the full host version matrix (LibreCAD 2.2+, Python 3.10+, DXF consumers).

## Requirements

- Windows release installer or portable ZIP: no separate Python or pip packages.
- Source/dev install: Python 3.10+, PyMuPDF >=1.24,<2.0, ezdxf >=1.0.

## Installation

### Windows portable release (recommended)

Download `LibreCAD-PDF-Importer-Windows-Portable_vX.Y.Z.zip` from
[Releases](https://github.com/BlueCollar-Systems/PDF-Importer-LibreCAD/releases),
extract it anywhere you can write files, then run `lcpdf-gui.exe`.

The portable ZIP bundles Python, PyMuPDF, ezdxf, pdfcadcore, the GUI, and the
CLI launchers. No system Python, pip, or administrator rights are required.

Bundled command-line entrypoints:

```powershell
.\pdf2dxf.exe drawing.pdf output.dxf
.\lcpdf-batch.exe "C:\path\to\pdfs" "C:\path\to\out_dxf" --recursive
```

### Source ZIP fallback

Download `LibreCAD-PDF-Importer_vX.Y.Z.zip`, extract it anywhere you can write
files, then run:

```powershell
python preflight_check.py --install
python pdf2dxf.py --gui
```

The source ZIP requires **Python 3.10+** once; `preflight_check.py --install`
downloads PyMuPDF and ezdxf into a private `./lib` folder with no admin rights.

### From source

```
pip install -r requirements.txt
pip install -e .
```

Source installs are intended for development. Use `python preflight_check.py`
to check dependencies, or `python preflight_check.py --install` to install
PyMuPDF and ezdxf into this checkout's private `lib/` folder without admin
rights.

Optional: install the native LibreCAD menu plugin (Windows):
```
powershell -ExecutionPolicy Bypass -File .\plugin\build_install_lcpdf_menu.ps1
```

## CLI Usage

Basic conversion:
```
python pdf2dxf.py drawing.pdf
```

Specify output path:
```
python pdf2dxf.py drawing.pdf output.dxf
```

Convert specific pages with a mode:
```
python pdf2dxf.py drawing.pdf --pages 1,3,5 --mode vector --verbose
```

Force raster mode for scanned PDFs:
```
python pdf2dxf.py drawing.pdf --mode raster
```

Target a specific DXF version:
```
python pdf2dxf.py drawing.pdf --dxf-version R2004
```

All options:
```
python pdf2dxf.py input.pdf [output.dxf] [options]

Options:
  --pages 1,2,3          Pages to convert (default: all)
  --mode MODE            auto | vector | raster | hybrid  (default: auto)
  --text-mode MODE       labels | 3d_text | glyphs | geometry  (default: 3d_text)
  --import-text / --no-import-text  Whether to import text at all (default: on)
  --scale 1.0            Scale factor
  --dxf-version VER      R12 | R2000 | R2004 | R2007 | R2010 | R2013 | R2018
  --gui                  Launch GUI instead of CLI
  --verbose              Print progress
  --version              Show version
```

Per BCS-ARCH-001 Rule 5 the previous quality-tier CLI flags
(`--strict-text-fidelity`, `--hatch-mode`, `--arc-mode`,
`--cleanup-level`, `--lineweight-mode`, `--grouping-mode`,
`--raster-dpi`, `--no-raster-fallback`, `--no-text`, `--no-arcs`)
have been removed. Their consolidated values are applied universally
because every mode targets identical "indistinguishable from source"
quality.

## GUI Usage

Launch the graphical interface:
```
python pdf2dxf.py --gui
```

Installed entrypoint:
```
lcpdf-gui
```

Or run the GUI directly:
```
python gui.py
```

The GUI provides file pickers, **professional single-flow import** (Auto strategy per page),
text choice (**Labels** or **Outlines** — LibreCAD is 2D-only), page range input,
option checkboxes, a progress bar, a status log, and optional auto-open in LibreCAD.
Advanced users can still use CLI `--mode` and `--text-mode` (including `3d_text` / `glyphs`).

Windows no-console options:
```
launch_lcpdf_gui.pyw
```
or:
```
lcpdf-guiw
```

## LibreCAD Menu Integration

After running the plugin installer script, restart LibreCAD and use:

- `Plugins > PDF Importer (BlueCollar)...`
- `Plugins > PDF Importer Settings...`

This launches the importer GUI directly from LibreCAD without a terminal window.

## Batch Import

Convert an entire directory tree of PDFs to DXF:

```
python -m librecad_pdf_importer.batch_cli "C:\path\to\pdfs" "C:\path\to\out_dxf" --recursive --mode auto --pages all --json batch_report.json
```

Installed entrypoint:
```
lcpdf-batch "C:\path\to\pdfs" "C:\path\to\out_dxf" --recursive --mode auto --pages all
```

## QA Smoke Harness

Run a quick automated smoke-test pass on one PDF or a folder:

```
python -m librecad_pdf_importer.qa_smoke "C:\path\to\pdfs" --mode auto --pages 1 --min-entities 1 --json qa_smoke.json
```

## Import Modes (BCS-ARCH-001)

Every mode targets **indistinguishable-from-source** fidelity within DXF's
capabilities. Modes differ only in extraction *strategy*, not quality tier.

| Mode | When to Use |
|------|-------------|
| **auto** *(default)* | Picks vector/raster/hybrid per page. Reports what it chose. |
| **vector** | Clean vector PDFs (CAD exports, shop drawings). |
| **raster** | Scanned or image-only PDFs. |
| **hybrid** | Mixed content (vectors + embedded raster). |

### Text Rendering (orthogonal to mode)

LibreCAD is **2D CAD** — there is no true 3D text in DXF or LibreCAD.

| Option | GUI | Behavior in DXF export |
|--------|-----|------------------------|
| **labels** | ✅ Default | DXF `TEXT` entities (MTEXT avoided for LibreCAD) |
| **geometry** | ✅ Outlines | Skips editable TEXT (outline-only workflow) |
| **3d_text** | CLI only | Same as `labels` in this exporter |
| **glyphs** | CLI only | Same as `labels` until vector-glyph DXF path exists |

Plus `--import-text` / `--no-import-text` to skip text entirely.

## DXF Compatibility

- **R12**: Maximum compatibility. No true-color, limited linetypes.
- **R2000 - R2004**: True-color support, standard linetypes.
- **R2007 - R2018**: Full feature set including lineweights.

The default R2010 output opens in LibreCAD, AutoCAD 2010+, DraftSight, QCAD,
and virtually all modern DXF readers.

## Project Structure

```
pdf2dxf.py            CLI entry point
gui.py                Tkinter GUI
dxf_import_engine.py  Pipeline orchestrator
dxf_builder.py        Primitive -> DXF entity mapping
dxf_text_builder.py   Text -> DXF TEXT/MTEXT mapping
pdfcadcore/           Shared PDF extraction core
```

## Known Limitations

| Limitation | Details |
|-----------|---------|
| Encrypted PDFs | Password-protected PDFs must be unlocked before import |
| Compression filters | Decoding is delegated to PyMuPDF. Malformed or non-standard compressed object streams may fail to parse |
| Raster-only scans | Pure raster PDFs produce no vector geometry |
| Clipped/XObject-heavy PDFs | Complex clip stacks and deeply nested form XObjects can produce partial geometry |
| MTEXT in LibreCAD | LibreCAD has known issues with MTEXT bounding boxes; TEXT fallback is used automatically |
| Embedded subset fonts | Text using embedded subset fonts may not render correctly |
| DXF version | R2010 is the recommended default; R12 mode uses TEXT entities only |
| Legacy hosts | LibreCAD/DXF consumer behavior outside the tested matrix is expected-only until verified |

## License

MIT License. Copyright (c) 2024-2026 BlueCollar Systems.
