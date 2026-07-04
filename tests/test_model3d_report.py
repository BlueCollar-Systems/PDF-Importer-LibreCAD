"""Round 9: LibreCAD reports 3D intent without pretending to be a 3D host."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
IMPORTER = REPO_ROOT / "librecad_pdf_importer" / "importer.py"
CONFIG = REPO_ROOT / "pdfcadcore" / "import_config.py"


def test_shared_config_accepts_model3d_options():
    source = CONFIG.read_text(encoding="utf-8")
    assert 'model3d_mode: str = "off"' in source
    assert "model3d_depth_mm: float = 3.175" in source


def test_librecad_report_is_honestly_2d_for_model3d():
    source = IMPORTER.read_text(encoding="utf-8")
    assert "analyze_model3d_intent" in source
    assert '"model_3d_intent"' in source
    assert '"supported": False' in source
    assert "LibreCAD is a 2D DXF host" in source
