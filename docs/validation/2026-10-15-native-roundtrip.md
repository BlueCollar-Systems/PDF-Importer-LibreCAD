# LibreCAD 1.0.113 native round trip

The r13 Windows candidate, built from
`a477e0cb1920afa899174a95590a0ac68028ffbb` by build-only run `38561363133`,
was tested in LibreCAD 2.2.1.5. The later `cee68b3` main merge is not a separate
package acceptance claim. All original PDFs, generated drawings and earlier
failed evidence were kept.

## Actual desktop checks

The public fixture used the packaged **Create drawing copy** GUI. Two real shop
PDFs used the ordinary converter GUI with its default Glyphs/outlines selection,
scale 1, all pages, text enabled and R2010. Automatic opening was unchecked to
keep native programs serial. Each case completed conversion, an actual native
Save As to DXF2007 in the same asset folder, normal Close, a fresh owned-process
reopen, another Save As and normal Close. All three cases passed those execution
and owned-exit checks; none passed strict source serialization equality.

| Case | Bounded result |
| --- | --- |
| Public saved-copy fixture | Generated source/physical checks passed. First native save to fresh save retained 1,098 forward leaves, 31 INSERTs and 27 linetype patterns. Raw HEADER, paint, handle/resource and repair-ledger differences remain recorded. |
| Field Bolt summary | All 28 text deliveries were verified Glyphs; no images or degraded items. First native save to fresh save retained the forward geometry of 12,567 SOLID/TEXT leaves and 861 INSERTs. Declared bounds nevertheless grew substantially, and strict comparison stayed false. Image coverage is vacuous. |
| Foundation markup sheet | 311 Glyphs and 13 verified whitespace-only native TEXT items; no degraded items or warnings in the conversion report. The 17 IMAGE occurrences represent one source picture and 16 rectangle alpha-paint swatches, using two unique PNG byte sequences. Both native saves retain linked bytes, decoded RGBA, dimensions and explicit IMAGE coordinates within `2.3e-13` mm. |

The foundation layout, cyan marks and blue source logo remained visible in model
view and white-paper preview after reopening. Detail zoom was not successfully
verified; no whole-page rendered or PDF pixel parity is certified. Its authentic
page report records 83.930 seconds for pipeline plus DXF export, excluding
resumable assembly and operator time.

## Remaining differences

LibreCAD consolidates the foundation's 17 IMAGEDEFs to two and omits both outer
330 dictionary-owner handles. Both native files therefore fail the existing
strict check with two audit code 202 fixes. Image clipping/display tags and
HEADER values also change. No saved file was repaired or normalized. Each native
log retains 17 empty-path image warnings: native construction updates an image
before `linkImage` assigns its filename. Final assets are present, but this does
not make the logs clean or prove every individual rendered crop.

Resumable assembly prefixes native TEXT style names. The host resolves fonts
from that name and does not strip `$` prefixes; it ignores imported STYLE font
table records. This proves a font-binding compatibility gap. The table's later
font-field rewrite alone does **not** explain the observed bounds growth.
At that r13 review, the font-alias repair and its next package/native checks
were pending. Later font, layout, pen and rule follow-ups are recorded in
[native text validation](2026-10-15-native-text-layout.md), including the completed
v1.0.118 checks and remaining Preview/strict-save failures. These historical r13
results do not validate those later candidates or establish a bounds fix.

Guided owners allow 1,800 seconds for operator/UI round trips. Separate native
diagnostics retain their hard 60-second deadlines. Historical failures are
unchanged. Cross-folder asset transport, other text modes and universal PDF or
host-version compatibility are not established by these cases.

## Local evidence

Receipts are under `C:/TMP/su-stall-20261012/host-review/`; private PDFs and their
contents are not committed.

| Receipt | SHA-256 |
| --- | --- |
| `librecad-r13-native-ui-20261015-r3/ACTUAL-PUBLIC-LIFECYCLE-INDEPENDENT-REVIEW.json` | `65f8a09f64ee18e2c2f5894a8e5d9a9a83209bdc93177a1b6e906db2bc561908` |
| `librecad-r13-real-pdf-ui-20261015-r1/ACTUAL-FIELD-BOLT-LIFECYCLE-INDEPENDENT-REVIEW.json` | `ea73c8e58c1529ae70c42c8e83fa64ef6adaa565f94298ee8b71e0eace246530` |
| `librecad-r13-real-pdf-ui-20261015-r1/ACTUAL-FOUNDATION-COMBINED-QUALIFICATION.json` | `34cbbde6b04bce4d117148814db9d6b99dc4346f2b780310a2480b7b1a34bfdb` |
