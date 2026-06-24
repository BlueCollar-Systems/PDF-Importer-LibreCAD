# Human Confirmation — PDF to DXF (LibreCAD)

**Prep:** 2026-06-24 · See `Desktop/PDFTest Files/Q&A/QA-2026-06-24_human-confirmation-script.md`

## Setup

1. Importer **v1.0.39+** (portable or plugin).
2. `$env:BCS_CORPUS_ROOT = 'C:\1pdf-test-corpus'`
3. `python C:\1pdf-test-corpus\tools\list_tier1.py --host LC --resolved`

## Tier-1 (Labels + Outlines only — no 3D text)

| PDF | Labels → DXF TEXT | Outlines | Pass |
|-----|-------------------|----------|------|
| 1017 - Rev 0 | ☐ | ☐ | Geometry + readable dims |
| 1011 (1 OF 2) | ☐ | ☐ | Title block text |
| hello_world_rotated | ☐ | ☐ | Rotation handled |
| text_only_fontsNotEmbedded | ☐ | ☐ | Text entities present |

## CLI spot check

```powershell
python -m pytest tests/ -q -k "import_report or preflight" --ignore=tests/integration
```

BUILT. NOT BOUGHT.
