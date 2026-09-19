"""One clipped fill that cannot be delivered costs that fill, never the document.

Synthetic pages only. Every page carries one black stroke ("the rest of the
page") next to the clipped fill under test.
"""
import json
import sys
from pathlib import Path

import ezdxf
import pymupdf
import pytest

import dxf_import_engine
import pdf2dxf
from conversion_control import ActivePageCancelled
from librecad_pdf_importer import batch_cli, cli
from librecad_pdf_importer.core import document
from librecad_pdf_importer.core.document import (
    CLIP_FILL_REPORT_ISSUE_CAP,
    DocumentExtraction,
    ExtractedPage,
    clip_fill_warning_line,
    host_clip_fill_issue,
    merge_clip_fill_deliveries,
)
from librecad_pdf_importer.exporters import dxf_exporter
from librecad_pdf_importer.exporters.dxf_exporter import DxfExportOptions, export_to_dxf
from librecad_pdf_importer.importer import run_import, write_import_report
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.primitives import PageData


STROKE = b' 0 G 5 5 m 95 5 l S'
# Two different triangles clip one flood fill: their intersection is not computed.
UNRESOLVABLE = b'q 10 10 m 90 10 l 50 90 l h W n 10 90 m 90 90 l 50 10 l h W n 0 0 1 rg 0 0 100 100 re f Q'
# A clip made only of rectangles, half covered: the resolver cuts it into (x, y) pairs.
HALF_COVERED_RECTANGLES = b'q 10 10 80 80 re 30 30 40 40 re W* n 0 g 0 0 50 100 re f Q'
# Two separate squares in one clip: two regions for the DXF builder to triangulate.
TWO_REGIONS = b'q 10 10 30 30 re 60 60 30 30 re W* n 0 g 0 0 100 100 re f Q'
# A triangle half covered: cut exactly, an info-level record and nothing to warn about.
EXACT_CUT = b'q 10 10 m 90 10 l 50 90 l h W n 0 0 1 rg 0 0 100 50 re f Q'
# A curved clip half covered: delivered, but with flattened curves.
FLATTENED = b'q 50 10 m 90 10 90 90 50 90 c 10 90 10 10 50 10 c h W n 1 0 0 rg 0 0 100 50 re f Q'

MM2_PER_PT2 = (25.4 / 72) ** 2


def make_pdf(path, *streams):
    pdf = pymupdf.open()
    for stream in streams:
        page = pdf.new_page(width=100, height=100)
        page.draw_rect(page.rect)
        pdf.update_stream(page.get_contents()[0], stream + STROKE)
    pdf.save(path)
    pdf.close()
    return str(path)


def export(run, path):
    export_to_dxf(run.extraction, str(path), DxfExportOptions(
        include_text=False, include_images=False, provenance_opts=run.config))
    reopened = ezdxf.readfile(path)
    assert not reopened.audit().errors
    return reopened.modelspace()


def solid_area(msp):
    total = 0.0
    for solid in msp.query('SOLID'):
        a, b, c = solid.dxf.vtx0, solid.dxf.vtx1, solid.dxf.vtx2
        total += abs((b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)) / 2
    return total


def strokes(msp):
    return len(msp.query('LINE LWPOLYLINE'))


# (a) an unresolvable clipped fill: everything else imports, the drop is reported

@pytest.mark.parametrize('mode', ['auto', 'vector'])
def test_unresolvable_clipped_fill_is_left_out_and_the_rest_of_the_document_imports(tmp_path, mode):
    source = make_pdf(tmp_path / 'D042.pdf', UNRESOLVABLE, EXACT_CUT)
    with run_import(source, mode=mode, overrides={'import_text': False}) as run:
        msp = export(run, tmp_path / 'D042.dxf')
        assert strokes(msp) == 2                       # both pages' strokes
        assert solid_area(msp) == pytest.approx(        # page 2's fill; page 1's is absent,
            (80 * 80 / 2 - 40 * 40 / 2) * MM2_PER_PT2)  # never its unclipped rectangle
        block = run.extraction.clip_fill_delivery()
        assert (block['dropped'], block['approximated'], block['resolved_exactly']) == (1, 0, 1)
        assert block['by_action'] == {'dropped-unsupported': 1, 'polygon-rect': 1}
        [issue] = block['issues']                       # the info-level record is only counted
        assert (issue['page'], issue['seqno'], issue['reason']) == (1, 0, 'nested')
        assert run.extraction.clip_fill_warning().startswith('WARNING: page(s) 1: 1 clipped fill(s) could not')


def test_page_delivered_as_a_raster_does_not_warn_about_its_vector_fills(tmp_path):
    source = make_pdf(tmp_path / 'D042.pdf', UNRESOLVABLE)
    with run_import(source, mode='raster', overrides={'import_text': False}) as run:
        [page] = run.extraction.pages
        assert page.resolved_mode == 'raster' and len(page.clip_fill_issues) == 1
        assert run.extraction.clip_fill_delivery()['dropped'] == 0
        assert run.extraction.clip_fill_warning() == ''
    # The same page with image delivery off falls back to its vectors, and they count again.
    with run_import(source, mode='raster', overrides={'import_text': False, 'ignore_images': True}) as run:
        assert run.extraction.pages[0].resolved_mode == 'vector'
        assert run.extraction.clip_fill_delivery()['dropped'] == 1


def test_compound_fill_cut_from_a_rectangle_only_clip_reaches_the_dxf_exactly(tmp_path):
    # The resolver writes this fill's segments as (x, y) pairs; extract_page reads
    # points only through .x/.y and used to stop the document with a TypeError.
    source = make_pdf(tmp_path / 'D100.pdf', HALF_COVERED_RECTANGLES)
    with run_import(source, mode='vector', overrides={'import_text': False}) as run:
        msp = export(run, tmp_path / 'D100.dxf')
        assert strokes(msp) == 1
        assert solid_area(msp) == pytest.approx((40 * 80 - 20 * 40) * MM2_PER_PT2)
        block = run.extraction.clip_fill_delivery()
        assert (block['resolved_exactly'], block['dropped'], block['issues']) == (1, 0, [])
        assert run.extraction.clip_fill_warning() == ''


def test_clipped_fills_the_extractor_cannot_read_cost_the_fills_not_the_page(tmp_path, monkeypatch):
    real = document.extract_page

    def extractor_that_chokes_on_compound_fills(page, number, *, drawings, **options):
        if any(row.get('bcs_compound_clip_fill') for row in drawings):
            raise TypeError('synthetic unreadable compound fill')
        return real(page, number, drawings=drawings, **options)

    monkeypatch.setattr(document, 'extract_page', extractor_that_chokes_on_compound_fills)
    source = make_pdf(tmp_path / 'D042.pdf', EXACT_CUT)
    with run_import(source, mode='auto', overrides={'import_text': False}) as run:
        msp = export(run, tmp_path / 'D042.dxf')
        assert strokes(msp) == 1 and not msp.query('SOLID HATCH')
        block = run.extraction.clip_fill_delivery()
        assert (block['resolved_exactly'], block['dropped']) == (0, 1)  # resolved by the core, lost here
        [issue] = block['issues']
        assert (issue['stage'], issue['page'], issue['seqno']) == ('host-build', 1, 0)
        assert issue['detail'] == 'TypeError: synthetic unreadable compound fill'

    def extractor_that_always_fails(*_args, **_options):
        raise TypeError('synthetic failure that is not about a fill')

    monkeypatch.setattr(document, 'extract_page', extractor_that_always_fails)
    with pytest.raises(TypeError, match='not about a fill'):
        run_import(source, mode='auto', overrides={'import_text': False})


# (b) a compound fill the DXF builder cannot build: dropped whole, reported, document continues

def test_fill_that_fails_halfway_through_its_build_leaves_nothing_behind(tmp_path, monkeypatch):
    real = dxf_exporter.mapbox_earcut_2d
    calls = []

    def earcut_that_fails_on_the_second_region(exterior, holes):
        calls.append(1)
        if len(calls) == 2:
            raise ValueError('synthetic tessellator failure')
        return real(exterior, holes)

    monkeypatch.setattr(dxf_exporter, 'mapbox_earcut_2d', earcut_that_fails_on_the_second_region)
    source = make_pdf(tmp_path / 'D042.pdf', TWO_REGIONS, EXACT_CUT)
    with run_import(source, mode='vector', overrides={'import_text': False}) as run:
        msp = export(run, tmp_path / 'D042.dxf')
        assert len(calls) == 3                          # page 1: two regions, page 2: one
        assert strokes(msp) == 2
        assert solid_area(msp) == pytest.approx((80 * 80 / 2 - 40 * 40 / 2) * MM2_PER_PT2)  # page 2 only
        [drop] = run.extraction.pages[0].clip_fill_build_drops
        assert (drop['stage'], drop['page'], drop['detail']) == (
            'host-build', 1, 'ValueError: synthetic tessellator failure')
        assert run.extraction.pages[1].clip_fill_build_drops == []

        # A second export reports its own drops, not the first export's again.
        monkeypatch.setattr(dxf_exporter, 'mapbox_earcut_2d', real)
        msp = export(run, tmp_path / 'D042-again.dxf')
        assert run.extraction.clip_fill_delivery()['dropped'] == 0
        assert solid_area(msp) == pytest.approx(
            (2 * 30 * 30 + 80 * 80 / 2 - 40 * 40 / 2) * MM2_PER_PT2)


# (c) the report block, the warnings count and the one operator line

def test_import_report_carries_the_block_and_counts_the_warnings(tmp_path, monkeypatch):
    def builder_that_refuses(*_args, **_options):
        raise RuntimeError('synthetic builder refusal')

    source = make_pdf(tmp_path / 'D042.pdf', UNRESOLVABLE, FLATTENED, TWO_REGIONS)
    with run_import(source, mode='vector', overrides={'import_text': False}) as run:
        pages = run.extraction.pages
        assert [len(page.clip_fill_issues) for page in pages] == [1, 1, 0]
        monkeypatch.setattr(dxf_exporter, '_add_compound_filled_paths', builder_that_refuses)
        export(run, tmp_path / 'D042.dxf')
        report_path = tmp_path / 'D042_import_report.json'
        write_import_report(run, str(report_path))
        report = json.loads(report_path.read_text(encoding='utf-8'))
        block = report['extra']['clip_fill_delivery']
        # Page 1: unresolvable. Page 2: flattened by the resolver, then refused by
        # the builder - one lost fill, not two findings. Page 3: refused by the builder.
        assert (block['dropped'], block['approximated'], block['resolved_exactly']) == (3, 0, 0)
        assert block['by_action'] == {'dropped-unsupported': 3}
        assert [(i['page'], i.get('stage')) for i in block['issues']] == [
            (1, None), (2, 'host-build'), (3, 'host-build')]
        assert block['issues_truncated'] is False
        assert report['result']['warnings'] == 3
        assert run.extraction.summary()['clip_fill_delivery'] == block
        line = run.extraction.clip_fill_warning()
        assert line.startswith('WARNING: page(s) 1, 2, 3: 3 clipped fill(s) could not be resolved')
        assert '\n' not in line

    # The same document through a builder that works: the flattened fill is delivered and said so.
    monkeypatch.undo()
    with run_import(source, mode='vector', overrides={'import_text': False}) as run:
        export(run, tmp_path / 'D042-built.dxf')
        write_import_report(run, str(report_path))
        report = json.loads(report_path.read_text(encoding='utf-8'))
        block = report['extra']['clip_fill_delivery']
        assert (block['dropped'], block['approximated'], report['result']['warnings']) == (1, 1, 2)
        assert '1 clipped fill(s) are approximate (flattened curves or crossing contours)' in run.extraction.clip_fill_warning()


def test_thousands_of_info_records_are_counted_and_never_listed_or_warned_about():
    def page(number, mode, issues, drops=()):
        return ExtractedPage(
            page_data=PageData(page_number=number, width=100.0, height=100.0),
            profile=None, resolved_mode=mode, clip_fill_issues=list(issues),
            clip_fill_build_drops=list(drops))

    info = [{'seqno': n, 'action': 'rect-intersection', 'severity': 'info', 'dropped': False, 'page': 1}
            for n in range(3000)]
    invisible = [{'seqno': n, 'action': 'dropped-invisible', 'severity': 'info', 'dropped': True, 'page': 1}
                 for n in range(40)]
    quiet = DocumentExtraction(pdf_path='SAMPLE.pdf', pages=[page(1, 'vector', info + invisible)])
    block = quiet.clip_fill_delivery()
    assert (block['resolved_exactly'], block['dropped_invisible'], block['dropped']) == (3000, 40, 0)
    assert block['issues'] == [] and quiet.clip_fill_warning() == ''

    lost = [host_clip_fill_issue(2, {'seqno': n}, RuntimeError('SAMPLE')) for n in range(CLIP_FILL_REPORT_ISSUE_CAP + 50)]
    loud = DocumentExtraction(pdf_path='SAMPLE.pdf', pages=[
        page(1, 'raster', lost[:7]),                     # vectors discarded: not a loss
        page(2, 'hybrid', lost),
        page(3, 'raster', [], drops=[host_clip_fill_issue(3, None, RuntimeError('SAMPLE'), seqno=9)]),
    ])                                                   # ...but this one was being built
    block = loud.clip_fill_delivery()
    assert block['dropped'] == CLIP_FILL_REPORT_ISSUE_CAP + 51
    assert len(block['issues']) == CLIP_FILL_REPORT_ISSUE_CAP and block['issues_truncated'] is True
    assert loud.clip_fill_warning().count('WARNING') == 1
    json.dumps(block, allow_nan=False)


def test_the_engine_hands_back_one_line_per_conversion_and_only_when_a_visible_fill_was_lost(tmp_path):
    messages = []
    stats = dxf_import_engine.convert(
        make_pdf(tmp_path / 'D042.pdf', UNRESOLVABLE, UNRESOLVABLE), str(tmp_path / 'D042.dxf'),
        progress_callback=messages.append)
    assert stats['clip_fill_warning'].startswith('WARNING: page(s) 1, 2: 2 clipped fill(s) could not be resolved')
    assert '\n' not in stats['clip_fill_warning'] and stats['clip_fill_delivery']['dropped'] == 2
    # The caller shows it once, at completion; the progress narrative does not say it again.
    assert not [message for message in messages if 'clipped fill' in message]

    stats = dxf_import_engine.convert(
        make_pdf(tmp_path / 'D100.pdf', EXACT_CUT), str(tmp_path / 'D100.dxf'),
        progress_callback=messages.append)
    assert stats['clip_fill_warning'] == ''
    assert not [message for message in messages if 'WARNING' in message or 'clipped fill' in message]


def test_page_by_page_conversion_says_it_once_for_all_pages_even_when_every_page_is_resumed(tmp_path):
    # What the GUI always runs. The second run converts nothing: every page was certified
    # by the first, and the fills those pages lost still have to reach the operator.
    source = make_pdf(tmp_path / 'D042.pdf', UNRESOLVABLE, EXACT_CUT, FLATTENED)
    config = ImportConfig.auto()
    config.import_text = False
    runs = []
    for _ in range(2):
        messages = []
        runs.append(dxf_import_engine.convert(
            source, str(tmp_path / 'D042.dxf'), config=config, resumable=True,
            progress_callback=messages.append))
        assert not [message for message in messages if 'clipped fill' in message]
    first, resumed = runs
    assert (first['converted_pages'], resumed['converted_pages'], resumed['resumed_pages']) == (3, 0, 3)
    line = resumed['clip_fill_warning']
    assert line == first['clip_fill_warning'] and '\n' not in line
    assert line.startswith(
        'WARNING: page(s) 1, 3: 1 clipped fill(s) could not be resolved and were left out; '
        '1 clipped fill(s) are approximate (flattened curves or crossing contours)')
    # The report that line points at carries the block itself, not only the page reports.
    report = json.loads(Path(resumed['import_report_path']).read_text(encoding='utf-8'))
    block = report['clip_fill_delivery']
    assert (block['dropped'], block['approximated'], block['resolved_exactly']) == (1, 1, 1)
    assert [issue['page'] for issue in block['issues']] == [1, 3]
    assert report['warnings'] == 2 and len(report['page_reports']) == 3


def test_line_over_page_blocks_names_every_page_and_counts_fills_past_the_report_cap():
    def block(number, issues):
        return DocumentExtraction(pdf_path='SAMPLE.pdf', pages=[ExtractedPage(
            page_data=PageData(page_number=number, width=100.0, height=100.0),
            profile=None, resolved_mode='vector', clip_fill_issues=list(issues))]).clip_fill_delivery()

    over_cap = CLIP_FILL_REPORT_ISSUE_CAP + 50
    blocks = [
        block(1, [{'seqno': 4, 'action': 'polygon-rect', 'severity': 'info', 'dropped': False, 'page': 1}]),
        block(2, [host_clip_fill_issue(2, {'seqno': n}, RuntimeError('SAMPLE')) for n in range(over_cap)]),
        block(5, [host_clip_fill_issue(5, {'seqno': 9}, RuntimeError('SAMPLE'))]),
    ]
    assert clip_fill_warning_line(blocks[:1]) == ''
    line = clip_fill_warning_line(blocks)
    assert line.startswith(f'WARNING: page(s) 2, 5: {over_cap + 1} clipped fill(s) could not be resolved')
    assert 'drawing order 0, 1, 2, 3, 4, 5, 6, 7 and' in line and line.count('WARNING') == 1
    merged = merge_clip_fill_deliveries(blocks)
    assert (merged['resolved_exactly'], merged['dropped'], merged['approximated']) == (1, over_cap + 1, 0)
    assert merged['by_action'] == {'polygon-rect': 1, 'dropped-unsupported': over_cap + 1}
    assert len(merged['issues']) == CLIP_FILL_REPORT_ISSUE_CAP and merged['issues_truncated'] is True
    assert merge_clip_fill_deliveries([{}, blocks[0]])['issues_truncated'] is False


def test_lcpdf_batch_says_which_pdf_lost_a_visible_fill_and_counts_it(tmp_path, monkeypatch, capsys):
    inputs = tmp_path / 'in'
    inputs.mkdir()
    make_pdf(inputs / 'D042.pdf', UNRESOLVABLE)
    make_pdf(inputs / 'D100.pdf', EXACT_CUT)
    report_path = tmp_path / 'batch.json'
    monkeypatch.setattr(sys, 'argv', [
        'lcpdf-batch', str(inputs), str(tmp_path / 'out'), '--json', str(report_path)])
    assert batch_cli.main() == 0                       # a left-out fill is a warning, not a failure
    captured = capsys.readouterr()
    [line] = [line for line in captured.err.splitlines() if 'clipped fill' in line]
    assert line.startswith('D042.pdf: WARNING: page(s) 1: 1 clipped fill(s) could not be resolved')
    assert line.endswith('See clip_fill_delivery in the batch report.')
    assert '"warnings": 1' in captured.out             # the printed summary
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert (report['passed'], report['failed'], report['warnings']) == (2, 0, 1)
    d042, d100 = report['results']
    assert (d042['status'], d042['warnings'], d042['clip_fill_delivery']['dropped']) == ('PASS', 1, 1)
    assert [(issue['page'], issue['seqno']) for issue in d042['clip_fill_delivery']['issues']] == [(1, 0)]
    assert (d100['warnings'], d100['clip_fill_delivery']['resolved_exactly']) == (0, 1)


@pytest.mark.parametrize('switches', [['--verbose'], ['--resume']])
def test_pdf2dxf_prints_the_line_once_whatever_the_switches(tmp_path, capsys, switches):
    source = make_pdf(tmp_path / 'D042.pdf', UNRESOLVABLE, FLATTENED)
    assert pdf2dxf.main([source, str(tmp_path / 'D042.dxf'), '--no-import-text', *switches]) == 0
    captured = capsys.readouterr()
    [line] = [line for line in captured.err.splitlines() if 'clipped fill' in line]
    assert line.startswith('WARNING: page(s) 1, 2: 1 clipped fill(s) could not be resolved')
    assert 'clipped fill' not in captured.out


# (d) cancellation is not a fill that could not be built

@pytest.mark.parametrize('signal', [ActivePageCancelled('Cancel requested at SAMPLE.'), KeyboardInterrupt()])
def test_cancellation_inside_a_clipped_fill_build_still_propagates(tmp_path, monkeypatch, signal):
    def cancelled(*_args, **_options):
        raise signal

    monkeypatch.setattr(dxf_exporter, '_add_compound_filled_paths', cancelled)
    source = make_pdf(tmp_path / 'D042.pdf', TWO_REGIONS)
    with run_import(source, mode='vector', overrides={'import_text': False}) as run:
        with pytest.raises(type(signal)):
            export_to_dxf(run.extraction, str(tmp_path / 'D042.dxf'),
                          DxfExportOptions(include_text=False, include_images=False))
        assert not (tmp_path / 'D042.dxf').exists()
        assert run.extraction.pages[0].clip_fill_build_drops == []


# A console entry point answers a failed import with one line, not a traceback.

def test_pdf2dxf_reports_an_unexpected_failure_in_one_line(tmp_path, monkeypatch, capsys):
    def convert(**_options):
        raise RuntimeError('synthetic import failure')

    monkeypatch.setattr(dxf_import_engine, 'convert', convert)
    source = make_pdf(tmp_path / 'D042.pdf', EXACT_CUT)
    assert pdf2dxf.main([source, str(tmp_path / 'D042.dxf')]) == 3
    err = capsys.readouterr().err
    assert 'import failed' in err and 'RuntimeError: synthetic import failure' in err
    assert 'Traceback' not in err and len(err.strip().splitlines()) == 1
    assert pdf2dxf.main([source, str(tmp_path / 'D042.dxf'), '--verbose']) == 3
    assert 'Traceback' in capsys.readouterr().err


def test_lcpdf_import_reports_an_unexpected_failure_in_one_line(tmp_path, monkeypatch, capsys):
    def run_import_that_fails(*_args, **_options):
        raise RuntimeError('synthetic import failure')

    monkeypatch.setattr(cli, 'run_import', run_import_that_fails)
    source = make_pdf(tmp_path / 'D042.pdf', EXACT_CUT)
    monkeypatch.setattr(sys, 'argv', ['lcpdf-import', source, '--out', str(tmp_path / 'D042.dxf')])
    assert cli.main() == 3
    err = capsys.readouterr().err
    assert 'RuntimeError: synthetic import failure' in err
    assert 'Traceback' not in err and len(err.strip().splitlines()) == 1
    monkeypatch.setattr(sys, 'argv', sys.argv + ['--verbose'])
    assert cli.main() == 3
    assert 'Traceback' in capsys.readouterr().err
