"""Round 9: LibreCAD reports 3D intent without pretending to be a 3D host."""
from pathlib import Path

from pdfcadcore.import_config import ImportConfig

REPO_ROOT = Path(__file__).resolve().parents[1]
IMPORTER = REPO_ROOT / "librecad_pdf_importer" / "importer.py"


def test_shared_config_accepts_model3d_options():
    # RB-11: value-lock the synced pdfcadcore defaults instead of grepping
    # the literal source declaration — the exact-string lock constrained
    # implementation wording (spacing/comments) rather than the behavior
    # (defaults stay off / 1/8-in plate) this test protects.
    cfg = ImportConfig()
    assert cfg.model3d_mode == "off"
    assert cfg.model3d_depth_mm == 3.175


def test_librecad_report_is_honestly_2d_for_model3d():
    source = IMPORTER.read_text(encoding="utf-8")
    assert "analyze_model3d_intent" in source
    assert '"model_3d_intent"' in source
    assert '"supported": False' in source
    assert "LibreCAD is a 2D DXF host" in source
