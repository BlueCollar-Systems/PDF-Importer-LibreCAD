from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def _load_shared():
    for parent in (Path("PDFVectorImporter"), Path("pdf_vector_importer"), Path(".")):
        if (parent / "pdfcadcore" / "streaming.py").is_file():
            sys.path.insert(0, str(parent.resolve()))
            break
    else:
        raise AssertionError("pdfcadcore/streaming.py not found")
    streaming = importlib.import_module("pdfcadcore.streaming")
    timing = importlib.import_module("pdfcadcore.stage_timing")
    return streaming, timing.StageTimer


streaming, StageTimer = _load_shared()


class Clock:
    def __init__(self, values):
        self.values = iter(values)

    def __call__(self):
        return next(self.values)


class PageData:
    primitives = (object(),)
    text_items = (object(), object())


class Document:
    page_count = 2

    def __init__(self):
        self.closed = False
        self.loaded = []

    def load_page(self, index):
        self.loaded.append(index)
        return object()

    def close(self):
        self.closed = True


def _install(monkeypatch, values, *, owned=True, extract_error=False, progress=None):
    timer = StageTimer(clock=Clock(values))
    doc = Document()
    monkeypatch.setattr(streaming, "_open_source", lambda _source: (doc, owned))

    def extract(_page, **_kwargs):
        if extract_error:
            raise RuntimeError("extract failed")
        return PageData()

    monkeypatch.setattr(streaming, "extract_page", extract)
    iterator = streaming.iter_pages("owned.pdf", stage_timing=timer, progress=progress)
    return doc, timer, iterator


def _lifecycle(timer):
    payload = timer.as_dict()
    return {
        "extract_ms": payload.get("extract_ms", 0.0),
        "host_build_ms": payload.get("host_build_ms", 0.0),
        "attempted": payload["attempted"],
        "yielded": payload["yielded"],
        "completed": payload["completed"],
        "pages": payload["pages"],
        "stage_counts": payload.get("stage_counts", {}),
    }


def test_complete_two_pages_uses_pre_yield_timestamp(monkeypatch):
    doc, timer, iterator = _install(
        monkeypatch, (0.000, 0.010, 0.010, 0.030, 0.030, 0.045, 0.045, 0.050)
    )
    assert [number for number, _ in iterator] == [1, 2]
    assert _lifecycle(timer) == {
        "extract_ms": 25.0,
        "host_build_ms": 25.0,
        "attempted": 2,
        "yielded": 2,
        "completed": 2,
        "pages": 2,
        "stage_counts": {"extract_ms": 2, "host_build_ms": 2},
    }
    assert doc.closed is True


@pytest.mark.parametrize("mode", ("break", "consumer_exception", "generator_exit"))
def test_early_close_flushes_once_but_does_not_complete(monkeypatch, mode):
    doc, timer, iterator = _install(monkeypatch, (0.000, 0.010, 0.010, 0.040))
    try:
        assert next(iterator)[0] == 1
        if mode == "consumer_exception":
            raise LookupError("consumer failed")
        if mode == "break":
            pass
    except LookupError:
        pass
    finally:
        iterator.close()
    assert _lifecycle(timer) == {
        "extract_ms": 10.0,
        "host_build_ms": 30.0,
        "attempted": 1,
        "yielded": 1,
        "completed": 0,
        "pages": 0,
        "stage_counts": {"extract_ms": 1, "host_build_ms": 1},
    }
    assert doc.closed is True


def test_progress_cancel_stops_before_next_extract_and_closes_owned_doc(monkeypatch):
    calls = []
    doc, timer, iterator = _install(
        monkeypatch,
        (0.000, 0.010, 0.010, 0.020),
        progress=lambda value: calls.append(value.page_number) or False,
    )
    assert [number for number, _ in iterator] == [1]
    assert doc.loaded == [0]
    assert calls == [1]
    assert _lifecycle(timer) == {
        "extract_ms": 10.0,
        "host_build_ms": 10.0,
        "attempted": 1,
        "yielded": 1,
        "completed": 1,
        "pages": 1,
        "stage_counts": {"extract_ms": 1, "host_build_ms": 1},
    }
    assert doc.closed is True


def test_extract_exception_counts_attempt_only_and_closes(monkeypatch):
    doc, timer, iterator = _install(
        monkeypatch, (0.000, 0.007), extract_error=True
    )
    with pytest.raises(RuntimeError, match="extract failed"):
        list(iterator)
    assert _lifecycle(timer) == {
        "extract_ms": 7.0,
        "host_build_ms": 0.0,
        "attempted": 1,
        "yielded": 0,
        "completed": 0,
        "pages": 0,
        "stage_counts": {"extract_ms": 1},
    }
    assert doc.closed is True


def test_caller_owned_document_stays_open(monkeypatch):
    doc, timer, iterator = _install(
        monkeypatch, (0.000, 0.010, 0.010, 0.020), owned=False,
        progress=lambda _value: False,
    )
    list(iterator)
    assert timer.as_dict()["completed"] == 1
    assert doc.closed is False
