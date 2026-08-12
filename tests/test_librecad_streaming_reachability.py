import ast
from pathlib import Path


def test_librecad_streaming_reachability():
    tree = ast.parse(
        Path("librecad_pdf_importer/core/document.py").read_text(encoding="utf-8")
    )
    target = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_extract_document_impl"
    )
    called = {
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for node in ast.walk(target)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
    }
    assert "extract_page" in called
    assert "iter_pages" not in called
    assert "StageTimer" not in called
    print(
        "LIBRECAD_STREAMING_REACHABILITY_OK "
        "extraction=production timer=compatibility_only"
    )
