from pdfcadcore.primitives import NormalizedText, PageData
from pdfcadcore.resolved_scale import resolve_page_scale


def _page(*texts: str) -> PageData:
    return PageData(
        page_number=1,
        width=1000.0,
        height=700.0,
        text_items=[
            NormalizedText(
                id=index,
                text=value,
                normalized=value.upper(),
                insertion=(900.0, 100.0),
                generic_tags=["titleblock_like", "scale_like"],
            )
            for index, value in enumerate(texts, start=1)
        ],
    )


def test_titleblock_date_time_is_never_accepted_as_drawing_scale() -> None:
    result = resolve_page_scale(_page("5/27/2016 9:10:47 AM"))

    assert result.factor == 1.0
    assert result.notation == "1:1"
    assert result.source == "default"
    assert result.fallback_reason == "no_scale_detected"


def test_clock_time_is_never_accepted_as_ratio_scale() -> None:
    for clock in ("9:10:47 AM", "9:10:47", "23:10:47"):
        result = resolve_page_scale(_page(clock))

        assert result.source == "default", clock
        assert result.fallback_reason == "no_scale_detected", clock


def test_real_architectural_and_ratio_scales_remain_valid() -> None:
    architectural = resolve_page_scale(_page('SCALE: 1/4" = 1\'-0"'))
    ratio = resolve_page_scale(_page("SCALE 1:50"))

    assert architectural.factor == 48.0
    assert architectural.source == "titleblock"
    assert ratio.factor == 50.0
    assert ratio.source == "titleblock"


def test_temporal_context_is_removed_without_discarding_a_real_scale() -> None:
    with_date = resolve_page_scale(_page("SCALE 1:50 DATE 5/27/2016"))
    with_time = resolve_page_scale(_page("SCALE 1:50 9:10:47"))

    assert with_date.factor == 50.0
    assert with_date.source == "titleblock"
    assert with_time.factor == 50.0
    assert with_time.source == "titleblock"
