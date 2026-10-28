# Human Verification — PDF to DXF (LibreCAD)

Use **your own shop PDFs** for sign-off. There is no fixed public test matrix.

Test the representation the user actually requests. Do not switch modes to hide
alignment, rotation, scale, font, or extrusion problems.

## Before you start

1. Install the latest portable ZIP or plugin release from GitHub Releases.

## Checklist

For each representative shop drawing you import:

| Check | Pass |
|-------|------|
| **Text** → inspect each span's actual delivery. Exact-look requests preserve source glyph outlines; with **Editable text**, native `TEXT` is accepted only after its font, placement, full advance and source-pen checks pass, and the report discloses the LibreCAD-font substitution. Other visible spans follow the reported Glyphs fallback; source-bound zero-ink whitespace can remain native `TEXT` | ☐ |
| **Labels** → the report records DXF's missing native Label capability, then attempts the Text path above; inspect whether each span actually delivered native `TEXT` or Glyph outlines and verify every transition | ☐ |
| **3D Text** → LibreCAD is a 2D host: thickness alone is not native 3D text proof. The report records that item's failed 3D attempt, then its actual Text/Glyphs/Geometry/item-Raster fallback; verify the delivered representation against the PDF | ☐ |
| **Glyphs** → grouped outline block per source span | ☐ |
| **Geometry** → raw outline edges faithful to the PDF | ☐ |
| **Raster** → exact item pixels in a verified source-bound DXF IMAGE, with no neighboring text borrowed | ☐ |
| Requested/delivered/fallback/result shown in the complete report | ☐ |
| No degraded or dropped text: `extra.text_items_degraded_total` is 0, no `P###_TEXT_DEGRADED` layer, and no "Warning: text item ..." line (a sheet with one is delivered but never certified) | ☐ |
| Searchable text: the layer `P###_TEXT_SEARCH` exists, is frozen (nothing extra is visible or printed), and `extra.searchable_text_companions` reports `failed: 0` and `mismatch: 0`; thawing it and freezing `P###_TEXT` shows editable LFF text with the exact strings at the right place, rotation, and width (glyph shapes differ from the PDF font), and it prints only after the layer's print flag is switched on | ☐ |
| Recovered text: `extra.text_glyph_codes` reports `unproven: 0`, and every recovered span is read against the source PDF page and says the same thing - these characters were matched against a reference face installed on this machine, not read from the file | ☐ |
| Scale plausible vs the source drawing | ☐ |
| Multi-page import behaves as expected | ☐ |
| Save and reopen: text strings, placement and positive native pen survive; inspect line patterns too, because LibreCAD's native writer rewrites three fine custom dash patterns to built-in linetypes and adds its standard linetypes. Do not certify a whole-page match when the saved result differs | ☐ |

## After each import

- Save `import_report.json` when the importer writes one
- If something looks wrong: use [Report Doctor](https://bluecollar-systems.com/report-doctor) or **Send Feedback** with screenshots and your report JSON

## Sign-off

| Role | Name | Date | Result |
|------|------|------|--------|
| Shop tester | | | |
| Engineering | | | |

BUILT. NOT BOUGHT.
