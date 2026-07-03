# QA-2026-07-02 - Shared-core fraction and open-gate fix

**Status:** Implemented locally; tests green.  
**Timestamp:** 2026-07-02 20:47 UTC  
**Scope:** FreeCAD canonical `pdfcadcore`, synced to LibreCAD and Blender.

## Trigger

The 2026-07-02 handoff said to verify the 1017 fraction/alignment regression against disk before trusting older shipped claims. A fresh extractor probe on:

```text
C:\Users\Rowdy Payton\Desktop\PDFTest Files\1017 - Rev 0.pdf
```

showed that the old `4'-7/2` style overrun no longer reproduced, but it exposed a smaller shared-core false merge:

- raw PDF spans for `2 1/4` could become `2/4`;
- raw PDF spans for `8 1/2` could become `2/8`;
- the full-size whole number sat close enough to the smaller stacked fraction digits that `_merge_stacked_fractions` could choose the wrong pair.

## Anonymous questions

1. **Reviewer J:** When a full-size whole number is near smaller stacked fraction digits, should the merger prefer the smaller fraction digits and leave the whole number separate?
2. **Reviewer K:** Should merged stacked fractions keep a reduced visual footprint so host text does not render wider than the original stacked glyph cluster?
3. **Reviewer L:** Should malformed non-PDF files be rejected by a lightweight header sniff before PyMuPDF opens them, especially on Windows where failed opens can leave temp files locked?
4. **Reviewer M:** Should `TextEntityVerification` move from a shared dataclass into actual host report output next, with host-specific produced entity counts?

## Answers to prior questions

**A to 2026-06-26 Q3 (FreeCAD scale/fit):** The previous bbox-fit fix remains valuable, but the new evidence found a shared extraction issue before host rendering: nearby whole-number digits could be merged into fractions. The fix belongs in `pdfcadcore`, then must be synced to LC/BL.

**A to 2026-06-26 Q4 (LC/BL scope):** LC/BL did need this shared-core sync because they consume the same fraction merger. No host-specific rendering change was needed, but each host now has a regression test covering the pattern.

**A to 2026-06-26 Q5 (automated proof):** The automated proof is now: a pure extractor probe on 1017 confirms no `2/4` or `2/8`, per-host unit tests cover the full-size-whole-number case, and all three Python host full suites pass. Human visual T-01 remains separate.

## Implementation

- Updated canonical FreeCAD `PDFVectorImporter/pdfcadcore/primitive_extractor.py`.
- Synced the patched core into:
  - `C:\1PDF-Importer-LibreCAD\pdfcadcore\primitive_extractor.py`
  - `C:\1PDF-Importer-Blender\pdf_vector_importer\pdfcadcore\primitive_extractor.py`
- Added regression tests in FC, LC, and BL for `2 + 1 + 4 + /` -> `2` plus `1/4`, not `2/4`.
- Preserved the concurrent/in-flight shared addition that reduces merged stacked fraction footprint.
- Added a pre-PyMuPDF `%PDF-` header sniff in shared `fitz_loader.safe_open` to prevent Windows handle leaks on obvious non-PDF files.
- Synced `fitz_loader.py`, `import_report.py`, and the regenerated `pdfcadcore_sync_manifest.json` across FC/LC/BL.

## Validation

- 1017 extractor probe: `contains_2_over_4=False`, `contains_2_over_8=False`, `count_1_4=10`, `count_1_2=19`.
- FreeCAD: `python -m pytest tests --basetemp $env:TEMP\pytest-fc-fraction-fix2 -q` -> 86 passed, 1 warning.
- LibreCAD: `python -m pytest tests --basetemp $env:TEMP\pytest-lc-fraction-fix2 -q` -> 46 passed, 11 subtests passed.
- Blender: `python -m pytest tests --basetemp $env:TEMP\pytest-bl-fraction-fix2 -q` -> 46 passed, 10 subtests passed.
- FC/LC/BL: `python pdfcadcore_sync_check.py` -> ALL IN SYNC.
- FC/LC/BL: `git diff --check` -> no whitespace errors; only line-ending warnings on existing tracked files.

## Remaining work

- T-01 human host verification still needs real app screenshots for 1017 and other field PDFs.
- `TextEntityVerification` exists in shared report code, but host adapters still need to populate produced entity counts in `import_report.json`.
