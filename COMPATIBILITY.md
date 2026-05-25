# Host Compatibility — PDF to DXF (LibreCAD)

BlueCollar PDF importers target **maximum fidelity** on every supported host version.
Modes are extraction **strategy** (Auto / Vector / Raster / Hybrid), not quality tiers.

## LibreCAD (primary host)

| LibreCAD | Python (standalone tool) | ezdxf | PyMuPDF | Status |
|----------|--------------------------|-------|---------|--------|
| 2.2.x+ | 3.10+ | >=1.0 | >=1.24,<2.0 | ⚠️ Expected |
| 2.1.x | 3.10+ | >=1.0 | >=1.24,<2.0 | ⚠️ Expected |
| 2.0.x | 3.8+ | >=1.0 | >=1.24,<2.0 | ⚠️ Expected (legacy DXF readers) |
| < 2.0 | | | | ❌ Not supported |

Evidence levels:
- **Verified**: host-run validation captured in release QA.
- **Expected**: syntax/runtime compatible; not yet host-verified in CI.
- **Not supported**: outside maintained scope.

### LibreCAD-specific behavior

- **2D only**: LibreCAD does not support true 3D text. BCS-ARCH **3D Text** and **Glyphs** map to the same DXF `TEXT` output as **Labels** in this exporter (MTEXT is avoided for LibreCAD compatibility).
- **GUI**: Single **Professional import** flow — always **Auto** mode internally. CLI/batch retain `--mode vector|raster|hybrid` for scripting.
- **GUI text options**: **Labels (editable TEXT)** and **Outlines (no editable text)** only.

## DXF consumers (secondary)

Exported DXF (default R2010) is intended to open in AutoCAD 2010+, DraftSight, QCAD, and other DXF readers. R12 is available for maximum legacy compatibility.

## CI coverage

GitHub Actions runs pytest on Python **3.10, 3.11, 3.12** (Ubuntu). Host application matrices are documented here; full LibreCAD GUI verification remains a manual release step.
