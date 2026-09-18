"""Soft page budgets compare seconds, while accumulated stage timing uses ms."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / '.')]

from types import SimpleNamespace

import pytest

from pdfcadcore import streaming
from pdfcadcore.stage_timing import StageTimer


def test_page_progress_seconds_do_not_inflate_extraction_time(monkeypatch):
    clock=[0.0]
    monkeypatch.setattr(streaming.time,"perf_counter",lambda:clock[0])
    doc=SimpleNamespace(page_count=2,load_page=lambda number:number)

    def extract(page,**kwargs):
        clock[0]+=[2.5,18.0][page]
        return SimpleNamespace(primitives=[object()],text_items=[])

    monkeypatch.setattr(streaming,"extract_page",extract)
    progress=[];timer=StageTimer()
    for _ in streaming.iter_pages(doc,progress=lambda item:progress.append(item),
                                  stage_timing=timer,soft_budget_s=15):
        clock[0]+=.7  # Native object building is deliberately outside extraction.
    assert [row.elapsed_s for row in progress]==pytest.approx([2.5,18.0])
    assert [row.total_elapsed_s for row in progress]==pytest.approx([2.5,20.5])
    assert [row.over_budget for row in progress]==[False,True]
    assert timer.get('extract_ms')==pytest.approx(20500)
    assert timer.get('host_build_ms')==pytest.approx(1400)
