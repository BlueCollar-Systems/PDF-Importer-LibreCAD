# PDF to DXF Converter for LibreCAD

**BlueCollar Systems -- BUILT. NOT BOUGHT.**

Converts PDF vector drawings to DXF format for use with LibreCAD, AutoCAD,
DraftSight, QCAD, and any DXF-compatible CAD software.

## Features

- Extracts lines, polylines, arcs, circles, rectangles, and closed loops
- Preserves stroke colors, line widths, and dash patterns
- Imports text with font size and rotation
- Text rendering always at maximum fidelity (no quality dials)
- **4 Import Modes** (BCS-ARCH-001): Auto (default, picks strategy per page), Vector, Raster, Hybrid
- **4 Text Rendering Options**: Labels, 3D Text, Glyphs, Geometry (orthogonal to mode; 3D Text falls back to Labels in DXF)
- **Maximum fidelity by default** -- no quality tiers, no fast-mode compromises
- Organizes geometry into DXF layers (per-page and per-OCG)
- Outputs DXF versions from R12 through R2018
- CLI and GUI interfaces (including no-console Windows launcher)
- Optional native LibreCAD `Plugins` menu integration (no terminal)
- Optional auto-open in LibreCAD after conversion
- Built on pdfcadcore shared extraction engine

## Compatibility

| LibreCAD Version | Python | ezdxf | PyMuPDF | Status |
|-----------------|--------|-------|---------|--------|
| 2.1.x+ | 3.10+ | 1.0+ | >=1.24,<2.0 | ⚠️ Expected |
| 2.0.x | 3.8+ | 1.0+ | >=1.24,<2.0 | ⚠️ Expected |

Evidence levels:
- `✅ Verified`: host-run validation evidence captured.
- `⚠️ Expected`: syntax/runtime compatible but no host-run evidence yet.
- `❌ Not supported`: outside maintained/tested compatibility scope.

## Requirements

- Python 3.10+
- PyMuPDF >=1.24,<2.0
- ezdxf >= 1.0

## Installation

```
pip install -r requirements.txt
pip install -e .
```

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

The GUI provides file pickers, mode selection (Auto / Vector / Raster / Hybrid),
text-rendering selection (Labels / 3D Text / Glyphs / Geometry), page range input,
option checkboxes, a progress bar, a status log, and optional auto-open in LibreCAD.

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

| Option | Behavior in DXF |
|--------|-----------------|
| **labels** *(default)* | MTEXT/TEXT entities, editable as text |
| **3d_text** | Falls back to `labels` (DXF has no 3D text primitive) |
| **glyphs** | Per-character vector glyphs via pdftocairo |
| **geometry** | Text converted to lines/polylines |

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
