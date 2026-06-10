# Legacy core mirror (archived)

Frozen copies of the original `librecad_pdf_importer/core/PDF*.py`
implementations, archived when the live files were converted to thin
deprecation shims that re-export from `pdfcadcore` (D6, Q-07-d:
shim-then-delete).

- These files are **dead code**: nothing in the repo imports them. The live
  import path is `importer.py` → `core/document.py` → `pdfcadcore`.
- `build_release.py` excludes `_archived/`, so none of this ships in zips.
- The shims in `core/` keep external import paths working for one release
  cycle and will be deleted the release after (per the Q&A decision log).
- Byte-identical to the pre-shim versions at LC `b48a66a` (verified via
  `git hash-object` against `HEAD:librecad_pdf_importer/core/<name>`).

Delete this folder once the shim release has shipped and no external
consumer has reported a dependency.
