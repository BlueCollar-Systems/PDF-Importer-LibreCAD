# QA-2026-06-24 - Round 6 App Shape Lookup Implementation

**Author:** Anonymous reviewer - Steel Logic app slice  
**Status:** Implemented and validated; ready to commit/push with Steel Logic `1.0.9+11`.  
**Related feature slate:** P0-05 `Part-mark -> shape lookup from PDF callout`

---

## What shipped

Steel Logic now has a small but real bridge from PDF/imported drawing text into the app:

- Added `ShapeLookupIntent` parser for copied PDF text and future links.
- Added a paste button inside the existing Search screen field.
- Exposed the workflow from Tools > Reference as **PDF Callout Lookup**.
- When the clipboard contains a recognizable shape callout, the app:
  - normalizes it (`W 12 x 26` -> `W12x26`, `HSS 4 x 4 x 3/8` -> `HSS4x4x3/8`);
  - runs the existing offline shape search;
  - opens the exact matching shape directly when one is found;
  - otherwise leaves the normalized search in the field and shows possible matches.
- Picker flows also benefit: if a shape picker is open and the pasted designation is an exact match, it returns that shape to the caller.

Files changed:

- `lib/shape_lookup_intent.dart`
- `lib/shape_list_screen.dart`
- `lib/tools_screen.dart`
- `lib/l10n.dart`
- `pubspec.yaml`
- `test/shape_lookup_intent_test.dart`

---

## Supported inputs

Examples covered by tests:

- `Column W 12 x 26 typ.` -> `W12x26`
- `HSS 4 x 4 x 3/8` -> `HSS4x4x3/8`
- `steellogic://shape/W14X90` -> `W14x90`
- `https://bluecollar-systems.com/shape/HSS6x6x1%2F4` -> `HSS6x6x1/4`

This does **not** claim full PDF-BOM extraction yet. It is the first safe P0 bridge: copied callout to trusted AISC lookup.

---

## Validation

Commands:

```powershell
dart format lib\shape_lookup_intent.dart lib\shape_list_screen.dart lib\tools_screen.dart lib\l10n.dart test\shape_lookup_intent_test.dart
flutter test test\shape_lookup_intent_test.dart
flutter analyze
flutter test
dart run tools\l10n_audit.dart
```

Result:

- Targeted lookup tests: pass.
- `flutter analyze`: no issues.
- Full Flutter test suite: pass, 160 tests.
- Localization key parity: OK; 5 audit hits remain pre-existing/intentionally reviewed.

## 2026-06-25 update

The implementation was expanded after peer review so the feature is not hidden inside generic Search:

- Tools screen now has a **PDF Callout Lookup** card under Reference.
- The card opens the shape search screen with a PDF-specific title.
- The same clipboard parser remains the source of truth, so typed search, pasted drawing text, picker flows, and future `steellogic://shape/...` links share normalization logic.

Validation repeated:

- `flutter analyze` — no issues.
- `flutter test test\shape_lookup_intent_test.dart` — pass.
- `flutter test` — pass, 160 tests.
- `dart run tools\l10n_audit.dart` — English/Spanish key parity OK.

---

## Cross-review resolution

- Expose the workflow from Tools for this pass; a Home quick action remains optional after human testing.
- Keep `steellogic://shape/...` parser-ready, but defer platform deep-link registration until website/app URL routing is locked.
- Recommend importer reports expose copyable normalized shape designations next.
- Do not make the mobile app parse full PDFs yet; the larger PDF-BOM/takeoff bridge should target CSV/import-report ingestion first.

---

## Recommendation

Accept this as the first shipped P0 app slice. Keep the larger PDF-BOM/takeoff bridge open, but human-test this immediately with copied callouts from 1017-class drawings and public plan PDFs.

*Posted for Round 6 QA coordination.*
