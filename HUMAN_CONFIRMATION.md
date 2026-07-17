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
| **Text** → verified editable DXF TEXT with requested Text semantics, source binding, and any Unicode compatibility normalization disclosed | ☐ |
| **Labels** → explicit no-native-DXF-Label evidence, followed by the closest verified editable Text fallback with source transform preserved; fallback and LFF substitution are reported separately | ☐ |
| **3D Text** → parent visibly/structurally verifies native 3D text, or report proves the item-specific failure and the nearest verified fallback is faithful | ☐ |
| **Glyphs** → grouped outline block per source span | ☐ |
| **Geometry** → raw outline edges faithful to the PDF | ☐ |
| **Raster** → exact item pixels in a verified source-bound DXF IMAGE, with no neighboring text borrowed | ☐ |
| Requested/delivered/fallback/result shown in the complete report | ☐ |
| LibreCAD Text and the Text fallback from Labels bind a real parent-native LFF style, preserve source-width FIT alignment after save/reopen, and report that glyph shapes can differ from the embedded PDF font | ☐ |
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
