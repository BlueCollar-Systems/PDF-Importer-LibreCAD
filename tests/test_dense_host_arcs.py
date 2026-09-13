from pathlib import Path
from types import SimpleNamespace
import importlib
import math
import pytest

def test_host_promotes_dense_circle_without_discarding_points():
    root = Path(__file__).resolve().parents[1]
    name = 'librecad_pdf_importer' if (root / 'librecad_pdf_importer').is_dir() else 'blender_pdf_vector_importer'
    document = importlib.import_module(name + '.core.document')
    points = [(10 + 5 * math.cos(i * math.tau / 200), 10 + 5 * math.sin(i * math.tau / 200)) for i in range(201)]
    primitive = SimpleNamespace(type='closed_loop', points=points, closed=True)
    document._promote_arcs(SimpleNamespace(primitives=[primitive]), .01, 5)
    assert primitive.type == 'circle'
    assert primitive.radius == pytest.approx(5)
    assert primitive.points == points
