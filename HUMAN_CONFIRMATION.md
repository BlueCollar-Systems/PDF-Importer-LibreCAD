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
| **Text** → visible text is drawn as exact Glyph outlines (a substituted LFF font is never certified as Text) and the report says requested Text, delivered Glyphs; only whitespace spans are native TEXT | ☐ |
| **Labels** → explicit no-native-DXF-Label evidence, then the same Text path: delivered as Glyph outlines with both transitions reported | ☐ |
| **3D Text** → parent visibly/structurally verifies native 3D text, or report proves the item-specific failure and the nearest verified fallback is faithful | ☐ |
| **Glyphs** → grouped outline block per source span | ☐ |
| **Geometry** → raw outline edges faithful to the PDF | ☐ |
| **Raster** → exact item pixels in a verified source-bound DXF IMAGE, with no neighboring text borrowed | ☐ |
| Requested/delivered/fallback/result shown in the complete report | ☐ |
| No degraded or dropped text: `extra.text_items_degraded_total` is 0, no `P###_TEXT_DEGRADED` layer, and no "Warning: text item ..." line (a sheet with one is delivered but never certified) | ☐ |
| Searchable text: the layer `P###_TEXT_SEARCH` exists, is frozen (nothing extra is visible or printed), and `extra.searchable_text_companions` reports `failed: 0` and `mismatch: 0`; thawing it and freezing `P###_TEXT` shows editable LFF text with the exact strings at the right place, rotation, and width (glyph shapes differ from the PDF font), and it prints only after the layer's print flag is switched on | ☐ |
| Scale plausible vs the source drawing | ☐ |
| Multi-page import behaves as expected | ☐ |

## After each import

- Save `import_report.json` when the importer writes one
- If something looks wrong: use [Report Doctor](https://bluecollarsystems.com/report-doctor) or **Send Feedback** with screenshots and your report JSON

## Sign-off

| Role | Name | Date | Result |
|------|------|------|--------|
| Shop tester | | | |
| Engineering | | | |

BUILT. NOT BOUGHT.
