# LibreCAD TrueType and CID-keyed CFF native pens (October 18, 2026)

Status: source candidate on branch `claude/librecad-1018-truetype-editable-text`,
second round after review. Converter probes and the unit suite ran on
Windows. No LibreCAD desktop display, Preview, Save As or reopen check was
run for this change, and no package was built or released.

The review of the first round found CAD symbol fonts (GD&T and math fonts)
becoming visible native `TEXT` with the wrong characters, slow measurement of
large fully embedded fonts, and an overstated CID-keyed CFF claim. All three
are corrected below; see [Second round](#second-round-review-fixes).

## Defect

Since 1.0.117, a visible native Editable `TEXT` needs a positive pen bound to
the source font program. Only name-keyed CFF `StdVW`/`StdHW` hints qualified.
TrueType has no stem hints, so every embedded Arial-style note fell back:
0 of 6 native `TEXT` on a fictional six-note probe, against 6 of 6 in 1.0.108.
CID-keyed CFF was refused outright. Restoring LibreCAD's default pen is not an
option: the earlier native validation recorded about 0.006 pt strokes with it.

## Rule

- **Name-keyed CFF:** unchanged. Rule `cff_private_dominant_stem_max_observed_frame_v1`.
- **CID-keyed CFF:** `StdVW`/`StdHW` from the Private dict of each font dict the
  span's glyphs select. Every selected dict must carry finite positive stems,
  its FontMatrix (combined with the top dict's) must match the font units,
  and all selected dicts must agree. Rule
  `cff_cid_fdarray_private_dominant_stem_max_observed_frame_v1`.
  A font dict's FontMatrix is combined with the top dict's when the top
  states one, and otherwise replaces the default (as in FreeType).
  **No PDF reaches this rule today.** The shared `pdfcadcore` font catalog
  rejects CID-keyed CFF before the pen rule runs: a raw `CIDFontType0C`
  program is refused as unsupported, and both OpenType-wrapped `CIDFontType0`
  probes (one CID-keyed with 18 font dicts, one name-keyed) were left out of
  the font inventory (`source_character_font_program_not_in_pdf_inventory`)
  on main and on this branch. An installed font cannot bind a source pen
  either. Such text keeps its fallback, which was item images in those probes.
  Only the unit tests reach the rule. It takes effect only if the catalog,
  whose master copy lives in the FreeCAD repository, starts admitting these
  programs.
- **TrueType (`glyf`):** the dominant vertical stem is measured from the
  program's own outlines. Reference letters: `lI1HLTEFPBDRKihmnubdpq`.
  - Seventeen scanlines cross each glyph from 10% to 90% of its ink height,
    under the nonzero rule.
  - A stem is an interval whose edges hold within 0.002 em on at least four
    consecutive scanlines. Its straight run must be at least as tall as it is
    wide, and its width must lie between 0.015 and 0.30 em. Each glyph keeps
    its narrowest stem.
  - At least two glyphs must have a stem. At least two thirds of them, and
    never fewer than two, must lie within 25% of the median. The dominant
    stem is the median of the agreeing glyphs.
  - The pen therefore depends on which reference letters the PDF's subset
    carries. The same 10 pt Arial gives 194/2048 em (0.334 mm, pen 0.35 mm)
    from capitals alone and a median of 180/2048 em (0.310 mm, pen 0.30 mm)
    once lowercase letters are present. The rendered cap stem is 0.334 mm and
    the rendered lowercase `l` 0.310 mm, so both pens stay within the font's
    own stems.
  - The program is opened lazily, so only the reference glyphs are
    decompiled. A malformed reference glyph refuses the pen with its reason.
  - Rule `truetype_outline_dominant_vertical_stem_max_observed_frame_v1`,
    reported as "pen from TrueType outline stem".

In every case the vertical stem is scaled by each character's bound x axis.
The CFF rules also scale the horizontal stem by the y axis and keep the larger
value. The result is quantized to the nearest supported DXF lineweight. The approximation and quantization error are
reported. Ink parity is never claimed. The serialized pen is rechecked against
fresh font bytes as before. Fonts outside these rules keep their reported
fallback, and no pen is invented.

### CAD symbol fonts

A symbol font never becomes Editable `TEXT`, because LibreCAD's font would
draw the character code instead of the symbol. Before any pen is measured,
the span's font is checked by name. Symbol, Wingdings, Webdings, Zapf
Dingbats and the other existing markers are unchanged. CAD symbol fonts are
now checked as well:

- GD&T fonts: `gdt` (AMGDT, AIGDT, GDT, SWGDT and Inventor's `_IV25`/`_IV50`
  variants);
- math, astronomy, map, weather and music fonts: `symath`, `swmath`,
  `syastro`, `swastro`, `symap`, `swmap`, `symeteo`, `swmeteo`, `symusic`,
  `swmusic`;
- Greek and other symbol fonts: `swgrek`, `greekc`, `greeks`, `mtextra`,
  `universalmath`, `marlett`.

These markers are matched on the name with spaces and punctuation removed.
The PDF's font names are checked first. If none matches, the bound program's
own family, full and PostScript names are checked, so a font the PDF renames
is still caught. Only a font that is renamed in the PDF and also carries no
matching name table of its own is not recognized.

These fonts need a name check because nothing else reveals them. They draw
symbols at letter codes (`n` is a diameter sign), yet their capitals are
ordinary letters with agreeing stems. Their cmaps are ordinary Unicode
tables with standard glyph names. A matched span keeps exact Glyph outlines,
no pen is measured for it, and its text attempt records
`source_font_symbolic`, `source_font_symbol_marker`, `source_font_symbol_name`
and `source_font_symbol_name_origin`.

## Installed-font survey (measured with the shipped rule)

Dominant stem in em, with the CFF `StdVW` of MuPDF's metric-equivalent Base14
program for comparison:

| Face | Outline stem | Agreeing glyphs | CFF StdVW of equivalent |
|---|---|---|---|
| Arial | 0.0914 | 22/22 | Nimbus Sans 0.093 |
| Arial Bold | 0.1373 | 19/19 | Nimbus Sans Bold 0.139 |
| Times New Roman | 0.0875 | 22/22 | Nimbus Roman 0.083 |
| Times New Roman Bold | 0.1396 | 20/20 | Nimbus Roman Bold 0.138 |
| Courier New | 0.0410 | 22/22 | Nimbus Mono 0.051 (different design) |
| Arial Black / Impact | 0.1993 / 0.2003 | 11/11, 20/20 | n/a |
| Arial Italic | refused: no vertical stems | n/a | n/a |

Calibri, Calibri Light, Verdana, Tahoma, Segoe UI, Segoe UI Light, Consolas,
Georgia and Trebuchet were also measured. Every glyph agreed in each face.

## Probe results (fictional six-note page, 10 pt)

These first-round notes are set in capitals, so the Arial subset carries
only capital reference letters; a mixed-case subset gives 0.30 mm (see
the TrueType rule above).

Seven fictional PDFs were converted by main `e4f089b` and by this branch, once
in the default Exact look and once with Editable text. Both runs used
`PYTHONHASHSEED=0`, so ezdxf writes its CLASSES section in the same order.

| Fixture, Editable | Main e4f089b | This branch |
|---|---|---|
| Embedded Arial TrueType subset | 6 Glyph INSERTs, 0 native TEXT | 6 native TEXT, 0.35 mm pen from TrueType outline stem |
| Embedded Arial Bold subset | 6 Glyph INSERTs | 6 native TEXT, 0.50 mm pen |
| Embedded Times New Roman subset | 6 Glyph INSERTs | 6 native TEXT, 0.35 mm pen |
| Embedded Arial Italic subset | 6 Glyph INSERTs | identical DXF; the reason lists the glyphs without a vertical stem |
| Embedded CFF (Nimbus Sans) | 6 native TEXT, 0.35 mm | identical DXF |
| Base14 Helvetica | 6 native TEXT, 0.35 mm | identical DXF |
| Non-embedded Arial | 6 item images | identical DXF; the reason says the PDF does not embed the font |

All seven default Exact-look outputs are identical DXF as well. "Identical
DXF" means equal text once the volatile header times and GUIDs, ezdxf's
timestamp stamp and the per-run picture folder name are masked. The per-item
pen evidence and the item pictures are identical too.

The pen against the PDF. The outline stem is what the rule measured; the
rendered stem is the `L` and `T` stem width of the PDF rendered at 2400 dpi.

| Face | Outline stem | Pen (quantization error) | Rendered `L` / `T` |
|---|---|---|---|
| Arial | 194/2048 em = 0.334 mm | 0.35 mm (+0.016) | 0.328 / 0.339 mm |
| Arial Bold | 296/2048 em = 0.510 mm | 0.50 mm (-0.010) | 0.508 / 0.508 mm |
| Times New Roman | 192.1/2048 em = 0.331 mm | 0.35 mm (+0.019) | 0.328 / 0.333 mm |
| Nimbus Sans CFF (unchanged rule) | `StdVW` 93/1000 em = 0.328 mm | 0.35 mm (+0.022) | 0.328 / 0.328 mm |

Version 1.0.108 wrote the same six Arial notes as native `TEXT` with no
lineweight of their own (layer default), which is the faint-pen case. This
branch never writes a visible native `TEXT` without a source-bound pen.

## Second round (review fixes)

The review measured fictional PDFs holding embedded subsets of AMGDT, GDT and
SWGDT. Each page has two GD&T callouts (`n0.50 THRU` and `HOLE n0.75 TYP`,
where `n` draws a diameter sign) and one Arial note (`BEAM HPL NOTE`). With
Editable text:

| Run | GD&T callouts | Arial note |
|---|---|---|
| Main `e4f089b` | Glyph INSERTs (the TrueType pen refusal blocked them by accident) | Glyph INSERT |
| First round `ad3e80d` | visible native `TEXT` showing `n`, pens 0.09 mm (SWGDT 0.15 mm), counted as editable, no fallback | native `TEXT`, 0.50 mm |
| This round | Glyph INSERTs, reason recorded, `source_font_symbol_marker` `gdt` | native `TEXT`, 0.50 mm |

In all three fonts the callout entities of this round match main's exactly.
The only entity difference from main is the Arial note (native `TEXT`
instead of a Glyph INSERT and its search copy). Default Exact-look output is
identical to main and to the first round. The named Symbol and Wingdings
simple TrueType probes are identical to main and to the first round in both
modes.

The 48-fixture Editable probe set (24 installed TrueType faces at two sizes,
plus rotated, scaled, CID, Type 3, non-embedded and symbol cases)
gives entity signatures identical to the first round for the 46 fixtures both
runs converted. The other two did not convert in the first round's run and
match main here.

The six-note page is identical DXF to the first round, and its CFF, Base14,
non-embedded and default-look outputs are still identical DXF to main.

Measurement time. The first round opened the program with every table fully
loaded, which decompiled every glyph. Times below were taken on a loaded
machine, with identical stems both ways:

| Installed font | Size | This round | Fully loaded |
|---|---|---|---|
| SimSun-ExtB | 21 MB | 1.05 s | 25.0 s |
| Arial Unicode MS | 22 MB | 0.97 s | 15.4 s |
| Malgun Gothic | 13 MB | 0.38 s | 11.0 s |
| Arial | 1 MB | 0.11 s | 0.39 s |

## Tests

`tests/test_librecad_truetype_cid_native_pen.py` builds fictional fonts: an
Arial-like TrueType (also embedded as a cmap-less PDF subset), slanted,
too-thin, disagreeing and stemless variants, CID-keyed CFF programs with and
without font-dict stems, a GD&T-named variant (including one the PDF
renames), and a program with 3000 extra glyphs. Run against main, 54 of its
55 tests fail. The one that passes pins the name-keyed CFF proof keys to
main's. All 29 tests added in this round fail against the first round: the
symbol-font check did not exist, the GD&T words became native `TEXT`, and
3009 glyphs were decompiled where this round decompiles fewer than 40. The old
`test_unproved_truetype_stems_descend_to_exact_glyphs_without_inventing_a_pen`
became `test_truetype_without_measurable_stems_descends_to_exact_glyphs_without_inventing_a_pen`:
its box-glyph font still has no stem, keeps exact glyphs and now says why.

Full suite on Windows, Python 3.12, temporary files on the shared `G:` test
drive, second round: 2592 passed, 25 skipped, 93 failed. The same 93 tests
failed in the first round's run there, and they fail with main `e4f089b`'s
code too. `G:` is exFAT: it has no stable file IDs, which the private
drawing-copy staging check compares (`st_dev`/`st_ino`), and `git` refuses
the temporary repositories that the release-provenance tests create on it.
None of those tests touch this change.

## Not changed

A font the PDF does not embed has no source outlines. Its characters are bound
to MuPDF's stand-in program, not to an installed copy. The existing rule
(`exact_contours_require_original_program`) keeps installed contours out, so
those words still arrive as item images. The report now says the PDF does not
embed the font. Using an installed copy's outlines or stems would change that
rule, and is left for a separate decision.

Italic and other slanted TrueType designs have no vertical stems to measure,
so they keep exact outlines.
