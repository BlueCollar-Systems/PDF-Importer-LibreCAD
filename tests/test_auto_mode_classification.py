from __future__ import annotations

from pdfcadcore.auto_mode import classify_page_content


def test_complex_pure_fill_map_is_fill_art_despite_coalesced_path_groups():
    drawings = [
        {
            "fill": (0, 0, 0),
            "color": None,
            "items": [("l", index)] * 14,
            "rect": (0, 0, 100, 100),
        }
        for index in range(2526)
    ]

    result = classify_page_content(
        drawings,
        text_blocks_count=0,
        text_words_count=0,
        page_area=20000.0,
    )

    assert result["stats"]["total_item_count"] == 35364.0
    assert result["type"] == "fill_art"


def test_complex_stroked_cad_page_remains_vector_content():
    drawings = [
        {
            "fill": None,
            "color": (0, 0, 0),
            "items": [("l", index)] * 14,
            "rect": (0, 0, 100, 100),
        }
        for index in range(2526)
    ]

    result = classify_page_content(
        drawings,
        text_blocks_count=1617,
        text_words_count=2916,
        page_area=20000.0,
    )

    assert result["type"] == "vectors"
