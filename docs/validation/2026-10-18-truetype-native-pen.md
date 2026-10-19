# LibreCAD TrueType and CID-keyed CFF native pens (October 18, 2026)

Status: source candidate on branch `claude/librecad-1018-truetype-editable-text`,
third round after review. Converter probes and the unit suite ran on
Windows. No LibreCAD desktop display, Preview, Save As or reopen check was
run for this change, and no package was built or released.

The review of the first round found CAD symbol fonts (GD&T and math fonts)
becoming visible native `TEXT` with the wrong characters, slow measurement of
large fully embedded fonts, and an overstated CID-keyed CFF claim. All three
are corrected below; see [Second round](#second-round-review-fixes).

The review of the second round found two more symbol-font cases becoming
visible native `TEXT`: AutoCAD's AcadEref, and pi fonts such as MS Reference
Specialty and CommercialPi whose names were on no list. Both are corrected,
and the symbol-font claim is narrowed to what the check can see; see
[Third round](#third-round-review-fixes).

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

### Symbol fonts

A symbol font must not become Editable `TEXT`, because LibreCAD's font would
draw the character code instead of the symbol. Before any pen is measured,
the span's font is checked three ways, in this order: the PDF's font names,
the bound program's own names, and a TrueType program's own OS/2 table. A
match keeps the span's exact Glyph outlines. What the check cannot see is
listed under [Limit](#limit-what-is-not-recognized).

By name: Symbol, Wingdings, Webdings, Zapf Dingbats and the other existing
markers are unchanged. CAD symbol fonts are checked as well:

- GD&T fonts: `gdt` (AMGDT, AIGDT, GDT, SWGDT and Inventor's `_IV25`/`_IV50`
  variants);
- math, astronomy, map, weather and music fonts: `symath`, `swmath`,
  `syastro`, `swastro`, `symap`, `swmap`, `symeteo`, `swmeteo`, `symusic`,
  `swmusic`;
- Greek and other symbol fonts: `swgrek`, `greekc`, `greeks`, `mtextra`,
  `universalmath`, `marlett`;
- AutoCAD's electrical reference font: `acaderef` (third round);
- pi and icon fonts that also mark themselves in OS/2, for subsets whose OS/2
  table was stripped: `referencespecialty` (MS Reference Specialty),
  `commercialpi`, `msoutlook`, `mdl2assets` and `fluenticons` (third round).

These markers are matched on the name with spaces and punctuation removed.
`mtextra` must start the name (after any subset tag), because the Monotype
text faces Gloucester MT Extra Condensed and Gill Sans MT ExtraCondensed
contain the same letters. The PDF's font names are checked first. If none
matches, the bound program's own family, full and PostScript names are
checked, so a font the PDF renames is still caught.

The CAD fonts need a name check because nothing else reveals them. They draw
symbols at letter codes (`n` is a diameter sign; AcadEref draws contact
symbols at `N`, `O`, `W`, `m` and `x`), yet their letters have agreeing
stems. Their cmaps are ordinary Unicode tables, and of them only AIGDT marks
itself in OS/2.

By the program's OS/2 table (third round, rule
`truetype_os2_symbol_code_page_or_panose_pictorial_v1`): a TrueType (`glyf`)
program is a symbol font when bit 31 of `ulCodePageRange1` (the Symbol
character set) is set, or when its PANOSE family type is 5 (Pictorial). No
name is involved. A version 0 OS/2 table has no code page ranges, so only its
PANOSE counts. The check never relies on the cmap: the PDF's cmap repair
drops a `(3,0)` symbol cmap, and AutoCAD's text fonts (Technic,
CityBlueprint, EuroRoman and others) use `(3,0)` cmaps too, so a cmap test
would refuse them wrongly. A CFF program's OS/2 is not read. The one wrapped
from a PDF's bare CFF program is synthesized and says nothing about the
source, so CFF delivery is unchanged.

A matched span keeps exact Glyph outlines, no pen is measured for it, and
its text attempt records `source_font_symbolic`, `source_font_symbol_marker`,
`source_font_symbol_name` and `source_font_symbol_name_origin`. An OS/2 match
has the origin `font_program_os2_table` and also records
`source_font_symbol_rule` and `source_font_symbol_os2` (table version, Symbol
code page, PANOSE family type). The marker lists and the OS/2 rule are part
of the resume identity.

#### Limit: what is not recognized

A symbol font is not recognized when all of these hold: none of its names is
on a list, its program has no OS/2 table or one with neither mark, and the
letters its PDF subset carries agree on a stem. Such a span still becomes
native `TEXT` showing the character codes. The stem rule is no defence here,
because it measures only the glyphs the subset carries: the full
CommercialPi font is refused (its stems disagree), but a `BDHILT bdhmn`
subset of it is not.

This gap is real. Some PDF printers strip OS/2 from every TrueType subset.
In a survey of 400 drawing PDFs, 1279 of 1395 distinct embedded TrueType
programs carried no OS/2 table, 1192 of them written by one PDF
printer driver (Arial, Arial Narrow and RomanT notes). Refusing every
TrueType program without OS/2 would remove Editable text from most of those
drawings, so that is not done. The report note says instead that such a
symbol font is not recognized and that symbol callouts which came in as
editable text should be checked.

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

## Third round (review fixes)

The review's fixtures were rebuilt the same way: fictional notes at 10 pt in
installed fonts, PyMuPDF subsets, and a text layer that reads as plain ASCII
for the pi fonts. Each was converted by main `e4f089b`, the second round
`d91d7db` and this round, with `PYTHONHASHSEED=0`. The pens differ from the
review's because the text size differs.

| Fixture, Editable | Main `e4f089b` | Second round `d91d7db` | This round |
|---|---|---|---|
| AcadEref Type0 subset, `BD xN bd` and `ABCD NOW` (review a01) | Glyph INSERTs | visible `TEXT` `BD xN bd` and `ABCD NOW`, 0.25 mm | Glyph INSERTs, marker `acaderef` |
| AcadEref as a simple TrueType font (review b02) | Glyph INSERTs | the same two `TEXT` | Glyph INSERTs, marker `acaderef` |
| MS Reference Specialty, `BDHILT bdhmn` (review a02) | Glyph INSERT | visible `TEXT`, 0.05 mm | Glyph INSERT, marker `referencespecialty` |
| CommercialPi BT, Type0 and simple, `BDHILT bdhmn` (review a02) | Glyph INSERT | visible `TEXT`, 0.20 mm | Glyph INSERT, marker `commercialpi` |
| The same two fonts with OS/2 stripped | Glyph INSERT | visible `TEXT` | Glyph INSERT, by name |
| The same two fonts renamed "Probe Pi" in the PDF and in the program | Glyph INSERT | visible `TEXT` | Glyph INSERT, `os2_symbol_code_page` / `panose_pictorial` |
| Renamed "Probe Pi" and OS/2 stripped | Glyph INSERT | visible `TEXT` | visible `TEXT`: the [limit](#limit-what-is-not-recognized) |

Every other span kept the second round's result:

- In each probe the Arial note beside the symbol span stays native `TEXT`
  at 0.35 mm.
- MS Outlook, Wingdings, Symbol, MT Extra, Universal Math, Marlett and AIGDT
  spans (text layer `BDHILT bdhmn`) were already outlines in the second
  round, by name or for want of a stem, and still are; the report now names
  the matching font for each.
- Text fonts (Arial, Times New Roman, ISOCPEUR, RomanS, Calibri, Segoe UI,
  Technic and CityBlueprint, as Type0 or simple TrueType, with and without
  OS/2) give DXF identical to the second round.
- Base14 Helvetica, Courier and Times and embedded CFF (Nimbus Sans and
  Nimbus Roman) give DXF identical to main in Editable text, and the AMGDT
  callout page gives DXF identical to the second round.
- All 43 default Exact-look outputs of these probes are identical DXF to
  main, and so are the 18 item pictures among them.

Installed-font survey. The final check (names and OS/2) was applied to the
887 faces installed for Windows and the user. It marks 54: the GD&T, math,
Greek, astronomy, map, weather and music CAD fonts, AcadEref, AmdtSymbols,
Symbol, Wingdings 1-3, Webdings, Bookshelf Symbol, MS Reference Specialty,
MS Outlook, Marlett, MT Extra, CommercialPi, Universal Math, Segoe MDL2
Assets, Segoe Fluent Icons, Segoe UI Symbol and Revit_HEB_SHX (a Hebrew SHX
font that declares the Symbol code page). No Latin text face is marked:
Arial, Times New Roman, Calibri, ISOCPEUR, RomanS and the AutoCAD text fonts
set neither OS/2 mark. Gloucester MT Extra Condensed and Gill Sans MT
ExtraCondensed, which the second round's `mtextra` substring marked, are no
longer marked. Fusion's symbol-palette fonts (AcadEref, AIGDT, AMGDT,
AMDT_Symbols, GDT, GENISO) are marked by name, except GENISO, whose letters
have no measurable stem and so keep outlines anyway.

Seen while probing and not changed here: a PDF holding a Type0 subset of a
font with a `(3,0)` symbol cmap (Technic, CityBlueprint, Wingdings, Symbol
and others, as PyMuPDF writes them) fails the whole import with `IndexError`
in the shared `pdfcadcore` cmap repair, on main and on this branch. Those
fonts were probed as simple TrueType fonts instead.

## Tests

`tests/test_librecad_truetype_cid_native_pen.py` builds fictional fonts: an
Arial-like TrueType (also embedded as a cmap-less PDF subset), slanted,
too-thin, disagreeing and stemless variants, CID-keyed CFF programs with and
without font-dict stems, a GD&T-named variant (including one the PDF
renames), AcadEref-named and OS/2-marked pi variants, and a program with
3000 extra glyphs. Run against main, 91 of its 92 tests fail. The one that
passes pins the name-keyed CFF proof keys to main's.

The 37 tests added in the third round cover the `acaderef` and pi names, the
anchored `mtextra`, a renamed AcadEref program, the OS/2 Symbol code page
and PANOSE Pictorial marks (including a version 0 table), text-font OS/2
values that must not match, the documented no-OS/2 limit, CFF OS/2 being
ignored, the resume identity, and end-to-end pages where the symbol span
keeps Glyph outlines and the letter span beside it stays native `TEXT`
(AcadEref as a Type0 and as a simple TrueType font; OS/2-marked pi fonts,
whose report note must state the limit). 24 of them fail against the second
round. The other 13 are negative cases that pass before and after.

All 29 tests added in the second round fail against the first round: the
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

Third round, same machine: the pen test file and the 25 other suites that
touch Editable text, symbol fonts, the import report or resume identity,
with temporary files on `G:`: 805 passed, 7 skipped, 12 failed. All 12 are
the exFAT staging check above; their three files pass on an NTFS temporary
folder (80 passed). The release, provenance, build-metadata and resume
suites on NTFS: 65 passed.

## Not changed

A font the PDF does not embed has no source outlines. Its characters are bound
to MuPDF's stand-in program, not to an installed copy. The existing rule
(`exact_contours_require_original_program`) keeps installed contours out, so
those words still arrive as item images. The report now says the PDF does not
embed the font. Using an installed copy's outlines or stems would change that
rule, and is left for a separate decision.

Italic and other slanted TrueType designs have no vertical stems to measure,
so they keep exact outlines.
