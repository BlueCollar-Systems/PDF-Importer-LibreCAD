# LibreCAD native text placement

The r14 candidate at `7ec26ba0336889bae26e9ab8da547adde007033c`, built by
run `38726279355`, was checked in the actual LibreCAD 2.2.1.5 desktop. The small
summary PDF was converted through the ordinary packaged GUI in default outlines
and explicit Editable text modes. Both completed conversion, normal DXF2007
Save As, normal Close, fresh-process reopen, another Save As and normal Close.
The foundation sheet completed the same lifecycle with its whole layout, cyan
marks and source logo visible in model view and white-paper preview.

These lifecycle successes do not establish appearance or strict retention.
Editable mode visibly failed: Auto Zoom fitted enormous horizontal bounds,
leaving a tiny table and distant text rectangle. The failure persisted after
reopening. Default outlines remained visible, but their hidden native search
text still enlarged declared bounds on reopening. All original files and
failed checks are preserved. No native file was repaired or normalized.

## Proven cause and repair

All 28 native TEXT references retained `unicode#bcs-1` across generated and both
native saved files. Under the pinned host font lookup and installed font
inventory, that alias resolves Unicode. The alias repair therefore does not
explain away the separate placement defect.

The actual native save also writes that alias into `STYLE.font`. The earlier
literal-font qualification rejected it when copying the saved drawing; XREF
prefixing then broke native lookup again. Physical file-only replay reproduced
that fallback. The repair admits only an unpathed, extension-free font alias
that resolves to the same native Unicode name, retaining all style properties
and existing conflicting-font, bigfont, shape-font and extended-font guards.

One source string has 70 leading spaces followed by `Page    1`. The installed
Unicode LFF and native spacing rules give full cursor advance 533.5, while its
ink occupies X from 472.5 to 530.5. LibreCAD FIT scales the ink width without
rebasing that leading offset. For the authored advance 163.86463720533578 mm,

`24.97665697733561 + 530.5 * 163.86463720533578 / 58`

equals the observed erroneous maximum X, 1523.773036933036 mm. Independent
read-only replay of the pinned native source and actual font reproduces it.
The previous importer checked its own written FIT endpoint as width evidence;
that did not measure native layout.

Version 1.0.115 instead writes LEFT/baseline TEXT and derives its width factor
from the complete native cursor advance, including literal spaces. Full content,
insertion, height and rotation remain intact. Serialization replays actual
physical fields against freshly bound executable/LFF assets. Ink envelopes are
separate and conservative for native arc scaling; they do not certify source
font shapes or pixel parity. Unsupported visible layout uses the existing
reported fallback. Search copies preserve exact strings but cannot certify
visible output or an unproved layout.

## Scope and remaining checks

The exact 1.0.115 package's desktop import, Auto Zoom, Save As and fresh reopen
checks remain required after the source repair. R14 native saves still failed
the unchanged strict comparisons: linetype/resource/header changes and missing
IMAGEDEF owner records remain recorded. Other hosts, cross-folder image
transport and whole-page rendered parity are separate checks. Guided UI stages
retain 1,800 seconds; separate native diagnostics retain their hard 60-second
deadlines.

Private receipts under the local host-review directory contain source/file
bindings; private PDFs and their contents are not committed.

| Receipt | SHA-256 |
| --- | --- |
| `lc114-native-font-qualification-20261015-r1/FIELD-BOLT-DEFAULT-LIFECYCLE-AND-FONT-REVIEW.json` | `9cc413e1fc6d58023221f4711f56b2e4ee6f1b0e475a09ebf34dea56f6ce2833` |
| `lc114-native-font-qualification-20261015-r1/FIELD-BOLT-EDITABLE-DISPLAY-FAILURE-REVIEW.json` | `8262bd94f51798d18c46d4025504452e46fb1b4bf4f503b6f26224bd55117747` |
| `lc-native-fit-numeric-diagnosis-20261015-r3/INDEPENDENT-NATIVE-FIT-NUMERIC-DIAGNOSIS.json` | `53afae634ac68a83f81437fbdb39b380ce477de92202139a990c0acb03c02809` |
| `lc-native-saved-font-alias-diagnosis-20261015-r1/ACTUAL-NATIVE-SAVED-STYLE-COPY-DIAGNOSIS.json` | `9edf371b7fdc59fbd3639822948949191c8b4c5a117fc8cc68ed0ecb94cf6e7e` |
