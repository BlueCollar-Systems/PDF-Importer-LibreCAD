# LibreCAD native text placement and strokes

## Completed desktop checks

The exact v1.0.115 r15 package at commit
`051860962dc74ac3ffe76f9176bfd36876bc052e`, built by run `38734747651`,
completed nine actual LibreCAD 2.2.1.5 desktop stages. Three ordinary packaged
GUI cases covered a small sheet in default outlines and explicit Editable text
modes, and a dense sheet in default outlines. Each completed conversion, normal
DXF2007 Save As and Close, fresh-process reopen, another Save As and normal Close.
The dense layout, cyan marks and source image remained visible.

The LEFT/baseline repair fixed the earlier oversized editable-text bounds.
However, explicit Editable mode still visibly failed: letters had fragmented
strokes and continuous table rules appeared dashed, including after redraw,
closer zoom and fresh reopen. Default outlines remained the visually usable
reference; these observations do not establish complete rendered parity.

All six native saved-file strict comparisons remain failed: four small-sheet
comparisons failed linetype retention, and two dense-sheet comparisons failed
IMAGEDEF-owner retention. Original/generated/native files and failed evidence
remain intact. No normalization, image-byte parity or native equivalence is
claimed. Earlier r14 appearance/bounds failures remain historical failures.

## Source-supported causes

LibreCAD resolves TEXT style names as native font names and ignores the font
filename in the imported STYLE table. XREF prefixes therefore require qualified
native-resolvable aliases. Native Save can also write that alias into STYLE.font;
the same family qualification must survive a later saved drawing copy.

The earlier FIT route scaled by ink width without rebasing leading spaces.
Writing a matching FIT endpoint was circular width evidence. Version 1.0.115
replaced it with LEFT/baseline TEXT whose full cursor advance is measured from
the selected installation's bound LFF asset, preserving leading/trailing spaces,
source insertion, cap height and rotation.

The v1.0.115 desktop check exposed a separate host limitation. Native LFF arcs
inside polylines scale their centers in X/Y but their radius in X only. Unequal
horizontal and vertical scaling can separate arc endpoints from adjoining
strokes. The measured native scales reproduce this defect independently.
Native letter spacing also leaves gaps between adjacent underscore glyphs,
even where the original source font's filled rules join continuously.

## Version 1.0.116 repair

Keep Unicode when its admitted glyph geometry and actual scales are safe.
Otherwise, try only the selected installation's Romans LFF, requiring drawable
coverage, baseline zero, cap height nine and an arc-free used-glyph/reference
closure. Missing or unsupported Romans follows the existing reported item
fallback. No font is installed and no host preference is changed.

Retain complete strings and source insertion, cap height, rotation and full
advance. Independently replay physical serialized fields against fresh selected
font bytes, native family and stroke-safety checks. Unicode/Romans aliases keep
all existing style properties, collision and conflicting-font guards through
page assembly and saved drawing copies. Resume identity records optional Romans
bytes and absence so earlier pages cannot silently reuse a changed font choice.
Font substitution remains explicit and never certifies the PDF's glyph shapes.

A continuous-rule fallback requires the exact bound source program/GID and actual
character placements. Only a single closed rectangle or a narrowly admitted
capsule with four monotone cubic quadrants and two horizontal sides qualifies.
The capsule proves its filled shared-midline interval, not its bounding box.
Transformed adjacent intervals must join in the same band under the source-frame
uncertainty. If native spacing breaks that proven connection, use existing exact
glyph outlines and retain the full frozen search string. Unproved punctuation,
other contours and unsupported placement do not acquire a continuity certificate.

## Validation and remaining acceptance

The relevant broader local run passed 427 tests with seven existing skips and
nine subtests, and exposed four precise fallback-evidence regressions. Restoring
the original Unicode asset/coverage gate before selection fixed those failures
without weakening their assertions or guards. The affected representation and
Editable suites plus selection/continuity checks then passed 197 tests with
seven skips. Ruff and diff checks pass; independent native-math and serialized
source reviews are clear. Earlier failed logs remain preserved.

A source-only diagnostic on the actual small sheet produced 20 visible native
TEXT spans (11 Romans, nine safe Unicode), eight exact glyph rule spans and
eight complete frozen search strings, with zero degraded items and unchanged
original input. Each rule had exact source capsule-midline continuity evidence.
That diagnostic used the predecessor before the final evidence-order/diagnostic
wording correction; its geometry and capsule proof are unchanged. It is not a
compiled-package or native-render acceptance result.

The exact v1.0.116 package still requires actual desktop import, display, Save As
and fresh reopen. Other hosts, cross-folder image transport and whole-page pixel
parity remain separate checks. Guided UI stages retain 1,800 seconds; separate
native diagnostics keep their hard 60-second deadlines. Private PDFs, their
contents and local paths are not committed.

| Local evidence identifier | SHA-256 |
| --- | --- |
| Native stroke source diagnosis | `cda8be7ba6ae6ec18c84612761e8ab1bce7925db7203275665eb65907ffd0580` |
| Final source/check bindings | `4cb8e6b44e114ece2da19bc32fde904d4992593bf9f3f540a334a08bd7b882fb` |
| Independent capsule/source review | `4714ac34f39cf1dc3398c66e1b1d883f21a5349ce42be18db71e6d5e3b49aa91` |
| Final independent serialized review | `e571643c917cc6e9b535e6061a0c394d8b21c45eb62b222e1056d095b98bac6a` |
| Source-only actual-sheet result | `592f39b313bf13572ac5931f09766add73a166ebd3193ff7457f63f4a0a26261` |
