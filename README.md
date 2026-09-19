# PDF to DXF Converter for LibreCAD

**BlueCollar-Systems -- BUILT. NOT BOUGHT.**

![Version: 1.0.100](https://img.shields.io/badge/Version-1.0.100-blue.svg)

Converts PDF vector drawings to DXF format for use with LibreCAD, AutoCAD,
DraftSight, QCAD, and any DXF-compatible CAD software.

See [CHANGELOG.md](CHANGELOG.md) for release history. Version 1.0.82 preserves
native zero-ink whitespace TEXT while visible source text whose font LibreCAD
must substitute descends automatically to visually verified glyph outlines.

## Features

- Extracts lines, polylines, arcs, circles, rectangles, and closed loops
- Preserves stroke colors, line widths, and dash patterns
- Imports text with font size and rotation
- Text rendering always at maximum fidelity (no quality dials)
- **Professional import (GUI)**: Auto mode only — picks vector/raster/hybrid per page internally
- **CLI/batch modes** (BCS-ARCH-001): Auto, Vector, Raster, Hybrid for scripting
- **Text representations (GUI and CLI)**: Text, Labels, 3D Text, Glyphs, Geometry, or Raster; LibreCAD's 2D host limitation is stated in the 3D Text choice and every fallback is reported instead of silently substituted
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

See **[COMPATIBILITY.md](COMPATIBILITY.md)** for the full host version matrix (LibreCAD 2.2+, Python 3.12+, DXF consumers).

## Requirements

- Windows release installer or portable ZIP: no separate Python or pip packages.
- Source/dev install: Python 3.12+, PyMuPDF 1.28.0, ezdxf 1.4.4,
  FontTools 4.63.0, Matplotlib 3.11.1, and NumPy 2.5.1. All are free software dependencies.

Release binaries are built with exact CPython 3.12.10 AMD64 and hash-locked
wheel closures. The builder removes only pip `RECORD` rows for generated venv
launchers (which embed the checkout path and are not shipped), then verifies the
accepted artifact bytes before publication. Release-gate pytest dependencies and
all token-bearing GitHub Actions are pinned as part of the same provenance chain.

Maintainers regenerate acceptance metadata only after both release archives are
built and smoked:

```powershell
python build_release.py
python build_windows_portable.py
python scripts/smoke_portable_zip.py "dist/LibreCAD-PDF-Importer-Windows-Portable_v*.zip" --source-zip "dist/LibreCAD-PDF-Importer_v*.zip"
python scripts/verify_release_artifacts.py --accept --provenance dist/release-candidate-provenance.json
python scripts/verify_release_artifacts.py
```

Acceptance must run from the clean candidate commit with the exact retained
GitHub Actions ZIPs and canonical provenance sidecar. It requires an
authenticated GitHub CLI so the original run attempt, three-subject artifact
attestation, and retained bytes can be verified; normal schema-1.1 publication
verification repeats that authentication before release creation.

## Installation

### Windows portable release (recommended)

Download `LibreCAD-PDF-Importer-Windows-Portable_vX.Y.Z.zip` from
[Releases](https://github.com/BlueCollar-Systems/PDF-Importer-LibreCAD/releases),
extract it anywhere you can write files, then run `lcpdf-gui.exe`.

The portable ZIP bundles Python, PyMuPDF, ezdxf, FontTools, Matplotlib, NumPy, pdfcadcore, the GUI, and the
CLI launchers. No system Python, pip, or administrator rights are required.

**Offline install:** The portable ZIP and published installer work without internet after download. Source ZIP dev installs may run `preflight_check.py --install` once if `lib/` is empty (requires network for that step only).

## Upgrading / skipping versions

Extract a newer portable ZIP over your folder (or run the latest installer).
Skipping versions (for example, 1.0.40 → 1.0.80) is supported. Before shop
use, run the bundled `pdf2dxf.exe` on one of your own representative PDFs,
open the resulting DXF in LibreCAD, and review its adjacent import report.

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

The source ZIP requires **Python 3.12+** once; `preflight_check.py --install`
downloads PyMuPDF, ezdxf, FontTools, Matplotlib, and NumPy into a private `./lib` folder with no
admin rights.

### From source

```
pip install -r requirements.txt
pip install -e .
```

Source installs are intended for development. Use `python preflight_check.py`
to check dependencies, or `python preflight_check.py --install` to install
PyMuPDF, ezdxf, FontTools, Matplotlib, and NumPy into this checkout's private `lib/` folder
without admin rights.

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

Checkpoint every completed page so an interrupted long job continues instead
of starting over:
```
python pdf2dxf.py drawing.pdf output.dxf --resume --verbose
```

Resume identity includes the exact PDF bytes, every import option, importer
version, conversion-engine bytes, and the resolved LibreCAD executable and LFF
font binding (canonical path, size, and fresh SHA-256). A mismatch is rejected
rather than mixed with prior work. The GUI enables the same page-safe behavior automatically and
provides a responsive **Cancel** button; the active partial page is discarded,
while every already-certified page remains available to **Convert / Resume**.

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
  --text-mode MODE       text | labels | 3d_text | glyphs | geometry | raster
                         (default: text)
  --import-text / --no-import-text  Whether to import text at all (default: on)
  --scale 1.0            Scale factor
  --dxf-version VER      R12 | R2000 | R2004 | R2007 | R2010 | R2013 | R2018
  --gui                  Launch GUI instead of CLI
  --verbose              Print progress
  --resume               Checkpoint and resume exact certified pages
  --version              Show version
```

Per BCS-ARCH-001 Rule 5 the previous quality-tier CLI flags
(`--strict-text-fidelity`, `--hatch-mode`, `--arc-mode`,
`--cleanup-level`, `--lineweight-mode`, `--grouping-mode`,
`--raster-dpi`, `--no-raster-fallback`, `--no-text`, `--no-arcs`)
have been removed. Their consolidated values are applied universally
because every mode targets identical "indistinguishable from source"
quality. This is not a freeze on improvement: a new control is appropriate when
it represents a genuinely distinct capability, preserves the same quality
target, and has production-path verification.

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
all six distinct text representations, page range input, option checkboxes, a
determinate page progress bar, page-safe Cancel/Resume, a status log, the
complete report path, and optional auto-open in LibreCAD. The CLI exposes the
same `text`, `labels`, `3d_text`, `glyphs`, `geometry`, and `raster` requests.

## Reproducible fidelity fixtures

`scripts/generate_public_synthetic_corpus.py OUTPUT_DIRECTORY` creates a CC0,
generated-only multi-page PDF stress set (rotation, clipping, text, vectors,
raster transparency, blank page, and malformed input). It reads no customer
file and never writes PDFs into the repository unless a caller explicitly
chooses the repository as the output directory.

`scripts/compare_raster_assets.py REFERENCE.png --dxf OUTPUT.dxf` compares the
exact PNG referenced by a DXF directly with a reference raster. This avoids the
loss and antialiasing changes introduced by rendering the DXF through a third
party before scoring it.

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

The six requests remain structurally distinct. A DXF declaration is not enough
to claim success: the requested semantics and item transform must also survive
serialization. LibreCAD uses LFF stroke fonts for editable native text, so Text
and Text uses its broad Unicode LFF face while retaining source content, anchor,
height, rotation, and advance. That parent-font substitution is reported
explicitly; it is not misreported as a representation fallback. DXF has no
native Label entity, so a Labels request records that item-scoped impossibility
and then reports the closest verified editable Text fallback. Likewise,
`TEXT` thickness alone does not prove visible/editable 3D text in LibreCAD's 2D
parent.

| Option | GUI | Verified DXF representation |
|--------|-----|-----------------------------|
| **text** | ✅ Text | Native editable DXF `TEXT`, verified as the requested Text semantic with source text (or an explicitly reported Unicode compatibility normalization), placement, dimensions, rotation, source identity, parent-native LFF binding, and source-width FIT alignment. |
| **labels** | ✅ Labels | DXF exposes no native Label entity. The item-scoped Labels attempt fails loudly without creating a wrong-type alias, then the closest editable Text fallback is verified and reported. |
| **3d_text** | ✅ 3D Text | Attempts DXF `TEXT` with positive thickness and +Z extrusion first. Success additionally requires the parent to verify it as visible/editable 3D text. LibreCAD is 2D, so the exact failed item advances first to verified flat editable Text and reports that transition. |
| **glyphs** | ✅ Glyphs | One grouped DXF `INSERT` per source text span with outline entities in its owned block definition. This remains structurally distinct from raw Geometry. |
| **geometry** | ✅ Geometry | Raw modelspace `LWPOLYLINE`/`POLYLINE` glyph edges. No `TEXT`, `MTEXT`, or `INSERT` is accepted as Geometry. |
| **raster** | ✅ Raster | A source-PDF-bound PNG of only the exact text item, delivered as a verified DXF `IMAGE`; it is a direct result when requested, not a fallback. |

Plus `--import-text` / `--no-import-text` to skip text entirely.

### Text-Mode Fallback Ladder (TEXTMODE-1)

The requested representation is invariant. Alignment, rotation, width, and
height are corrected and verified inside that type. A same-type retry is not a
fallback. A different rung begins only after all safe strategies for the prior
type fail verification and clean their exact owned DXF handles.

| Requested | Ordered, representation-distinct ladder | Transition proof and verification |
|-----------|------------------------------------------|-----------------------------------|
| **text** | Text → Glyphs → Geometry → item Raster | Native `TEXT` must read back source content or its disclosed compatibility normalization, anchor, nominal height, rotation, source advance, parent-native LFF binding, FIT endpoint, and a live unique handle. Labels is not inserted as a peer alias rung. |
| **labels** | Labels → Text → Glyphs → Geometry → item Raster | The requested Label capability is evaluated for the exact source item. DXF's missing Label entity is recorded before verified editable Text is attempted; a report-only TEXT/MTEXT relabel is rejected. |
| **glyphs** | Glyphs → Geometry → Text → item Raster | Glyphs try entity-based and independent string-based outline generation before impossibility. Success requires an `INSERT`, nonempty owned outline block, matching bounds, and exact parent/child handles. |
| **geometry** | Geometry → Glyphs → Text → item Raster | Geometry uses the same two outline-generation strategies but success requires raw modelspace edges and matching bounds; an `INSERT` is not Geometry. |
| **3d_text** | 3D Text → Text → Glyphs → Geometry → item Raster | The first rung creates the item-specific DXF `TEXT`, applies and reads back thickness/+Z extrusion, then verifies parent font rendering and 3D display semantics. Flat Text is the closest fallback, and a different rung is legal only after the prior attempt is removed with recorded impossibility evidence. |
| **raster** | item Raster | PyMuPDF renders the exact source bbox. Success requires visible pixels, PNG byte verification, exact model placement/size, a live `IMAGE` handle, and an atomically written uniquely owned asset. |

`text2path_failed` means both independent same-representation outline
strategies failed verification and their owned entities were cleaned before
the next distinct rung was attempted.

`import_report.json` includes
`extra.text_representation_delivery` (`bcs.text_representation_delivery/1.0`)
with every source ID, attempted type/strategy, reason/evidence, created and
removed handle, cleanup result, final handle, and supersession. The legacy
`fallback.text` summary remains for UI compatibility. Raster is never assumed
successful.

**One unverifiable text item never costs the sheet** (owner decision
2026-09-19: "these tools are meant to help, not hinder"). Earlier versions
stopped the whole import and wrote no DXF when a single text item could not be
verified. The failure is still classified exactly as before, because a failure
not proven to come from the source may be our bug, but it now costs only that
item, which degrades down this ladder while the sheet exports:

1. the requested rungs above, as always;
2. an item Raster patch, tried whether or not the failure was proven
   (`proof_class` is `proven_impossible`, `unproven_failure`, or
   `invalid_layout`; it repeats the builder's own verdict, so a font failure
   the builder refused to call proven stays `unproven_failure` even when every
   rung ended "impossible");
3. if the patch cannot be made or proven, a **visible** native `TEXT` entity
   carrying the exact source string at the item's insertion, rotation, and
   approximate height on layer `P###_TEXT_DEGRADED`, so a dimension value is
   never silently lost;
4. if even that is impossible, the item is dropped and reported.

The degrade is loud instead of fatal. Every such item stays `verified: false`,
so `text_representation_delivery.verified`, `import_contract_ready`, and the
release smoke gates still fail for that sheet: operators get their drawing,
certification stays strict. `extra.text_items_degraded` lists each item
(`source_id`, `page`, `text`, `reason`, `reason_code`, `proof_class`,
`delivered`; at most 200, with `text_items_degraded_total` and
`text_items_degraded_truncated`), and `result.warnings` counts them together
with any clipped fills that were left out or are approximate. The rescue reason
code is `item_degraded_after_unproven_failure` (or
`item_degraded_after_proven_impossibility`). It is on each item's delivery
record (`fallback_reason_code`), on each `text_items_degraded` entry
(`reason_code`), and grouped in `fallback.text_items_degraded`; the legacy
`fallback.text` summary names one substitution and prefers the sheet's verified
fallbacks, so in the default Text mode it does not carry that code. The
one-sentence `fallback.reason` and the human summary do: the degraded rows
(`text_items_degraded: 1 x text -> raster (...)`, then `N dropped from the
drawing` when any item was dropped) are appended to whatever they already said.
A dropped item sets `fallback.used` and is not counted in
`result.text_entities`, in `pdf2dxf.py`'s `Text items` line, or in the GUI log's
`Text` line. An item whose Raster rung found that the source paints no visible
ink gets no patch; its entry carries `no_visible_ink: true` and its warning says
that nothing was drawn. A rescued text-builder crash keeps a bounded traceback
in its attempt's evidence (`traceback_tail`; the frames and the message are
bounded separately, so a very long message cannot push the raise site out). The
CLI prints one bounded, single-line warning per item on stderr (control
characters removed) for the first 20 items, then one `... and N more degraded
text item(s); see the import report.` line, and still exits 0, and the GUI shows
a warning rather than an error.
The batch CLI writes the sheet but reports it as `DEGRADED`, never `PASS`, and
exits 1 when any sheet is `DEGRADED` or `FAIL`, as it did when such a sheet
failed; a sheet that only had clipped fills left out stays `PASS` with a
warning. The QA smoke harness still fails a degraded sheet.
A resumable conversion (`--resume`, and every GUI conversion) checkpoints such a
page like any other, but announces it as `exported with N degraded text
item(s) - NOT certified`, leaves it out of `pages_certified`, and lists it in
`pages_degraded`; the resumable report carries the same `warnings` and
`text_items_degraded` fields as the page reports.
Post-write verification mismatches confined to identifiable items trigger one
re-export with all of those items forced down the ladder. Structural failures
(duplicate source IDs or handles, no stable source identity, a mismatch that
survives the re-export) still stop the import: the prior DXF is preserved and a
failure report is written whose `extra.terminal_failure` records the error
text, the exception type, whether the stop was deliberate, and a bounded
traceback.

For the import itself, `lcpdf-import` and `pdf2dxf.py` answer with the same exit
codes: `0` means a DXF was written (degraded text items and left-out clipped
fills are warnings on stderr, never a failure); `2` with `Import stopped: ...`
means the import was stopped deliberately, says why, and names the failure
report it left; `3` means any other unexpected failure, answered in one readable
line that names the failure report when the export left one (`--verbose` adds
the traceback). Exit `2` alone does not prove a deliberate stop: `pdf2dxf.py`
keeps its two older exit-`2` answers, which print no `Import stopped` and leave
no failure report, for an unparsable `--pages` value (`Invalid --pages value:
...`) and for a file that turns out not to be a readable PDF once the conversion
has started (a command line that argparse rejects exits `2` as well, with a
usage message). Other argument and open-time rejections keep their existing
codes (`1`, and `130` for an interrupted or cancelled run). If the failure
report itself cannot be written (read-only folder, full disk), the original
error and its exit code are kept and stderr says that the failure report could
not be written. The GUI error box names the failure report as well.

Auto page classification cannot replace extractable text with Raster while a
non-raster text representation is requested. Explicit Raster import mode still
does exactly what it says.

Text Raster images retain the source renderer's exact pixel origin, resolution,
and page-to-model transform. Their saved DXF axes and corners are verified against
that pixel lattice. Qualified final translucent rectangle annotations use alpha
PNG images with the original editable opaque strokes, preserving the requested
text representation below them. This bounded repair requires original source
paint and Normal-blend proof; it does not provide general PDF compositing.

## DXF Compatibility

- **R12**: Maximum compatibility. No true-color, limited linetypes.
- **R2000 - R2004**: True-color support, standard linetypes.
- **R2007 - R2018**: Full feature set including lineweights.

The default R2010 output opens in LibreCAD, AutoCAD 2010+, DraftSight, QCAD,
and virtually all modern DXF readers.

R12 does not serialize a `BLOCK_RECORD` table. Delivery evidence therefore
tracks every serialized glyph-block entity/handle but explicitly excludes that
one parser-generated support record; all R12 `INSERT`, `BLOCK`, `ENDBLK`, and
outline handles still reconcile after reopening.

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
| Transparency | LibreCAD does not generally composite DXF fill transparency. The final rectangle repair requires a proven source suffix, solid opaque strokes, Normal blending and no masks or transparency groups; other cases retain their existing display limitations. R12 does not use this repair. |
| LibreCAD preview process | The installed LibreCAD 2.2.1.5 Windows CLI can write a valid image-bearing preview and then crash during Qt shutdown. Native exit status remains a failure and is recorded separately from saved DXF and rendered-image checks. |
| Clipped/XObject-heavy PDFs | Complex clip stacks and deeply nested form XObjects can produce partial geometry |
| Native LibreCAD fonts and Labels | Editable Text uses LibreCAD's Unicode LFF face. The report records that font substitution separately from representation fallback; source content and transforms remain verified, but glyph shapes can differ from the embedded PDF font. DXF has no native Label entity, so Labels falls loudly to Text. Choose Glyphs or Geometry when exact source-font outlines matter more than editability. |
| Damaged or unusable source fonts | Exact-font structural representations are never certified without item-specific impossibility evidence. Without that evidence the item is still delivered (item Raster patch, then visible `TEXT` on `P###_TEXT_DEGRADED`, then a reported drop), but it stays `verified: false`, is listed in `extra.text_items_degraded`, and keeps the sheet out of certification |
| DXF version | R2010 is the recommended default; R12 has no serialized `BLOCK_RECORD`, which is explicitly excluded from durable support identity |
| Legacy hosts | LibreCAD/DXF consumer behavior outside the tested matrix is expected-only until verified |

## License

MIT License. Copyright (c) 2024-2026 BlueCollar-Systems.
