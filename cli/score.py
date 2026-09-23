"""Command parsing and presentation for offline reference scoring."""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path
from typing import Any

from .reporting import add_reporting_args, emit_document, emit_event, report_mode


def add_score_parser(sub: Any) -> None:
    parser = sub.add_parser(
        'score', help='Prepare references and score saved model or ensemble audio'
    )
    commands = parser.add_subparsers(dest='score_command', required=True)
    prepare = commands.add_parser('prepare', help='Prepare mixtures and reference stems')
    prepare.add_argument('--sources', type=Path, required=True)
    prepare.add_argument('-o', '--output', type=Path, required=True)
    prepare.add_argument('--song', action='append', help='Select a song ID (repeatable)')
    prepare.add_argument('--split', action='append', help='Select a dataset split (repeatable)')
    files = commands.add_parser('files', help='Score explicit reference/estimate pairs')
    files.add_argument('--reference', action='append', required=True, metavar='STEM=PATH')
    files.add_argument('--estimate', action='append', required=True, metavar='STEM=PATH')
    files.add_argument('--group', choices=('pair', 'four', 'custom'), default='pair')
    files.add_argument('--candidate', default='files', help='Stable candidate ID')
    files.add_argument('--label', help='Candidate display label')
    files.add_argument('--kind', choices=('model', 'ensemble'), default='model')
    files.add_argument('--provenance', help='Existing UVR run manifest')
    files.add_argument('--song-id', default='file')
    files.add_argument('-o', '--output', type=Path)
    run = commands.add_parser('run', help='Score a dataset and estimates manifest')
    run.add_argument('--dataset', type=Path, required=True)
    run.add_argument('--estimates', type=Path, required=True)
    run.add_argument('-o', '--output', type=Path, required=True)
    compare = commands.add_parser(
        'compare', help='Compare saved reports using paired B minus A scores'
    )
    compare.add_argument('a', type=Path)
    compare.add_argument('b', type=Path)
    compare.add_argument('--a-candidate')
    compare.add_argument('--b-candidate')
    compare.add_argument('-o', '--output', type=Path)
    for command in (files, run):
        command.add_argument(
            '--metrics',
            choices=('basic', 'all'),
            default='all',
            help='all includes optional BSS Eval; basic uses NumPy and SoundFile',
        )
    for command in (prepare, files, run, compare):
        add_reporting_args(command)
        command.set_defaults(func=cmd_score)


def _paths(values: list[str]) -> dict[str, Path]:
    result = {}
    for value in values:
        stem, separator, path = value.partition('=')
        if not separator or not stem or not path or stem in result:
            raise ValueError('Use unique STEM=PATH entries for references and estimates')
        result[stem] = Path(path).expanduser().resolve()
    return result


def _human(report: dict[str, Any]) -> None:
    print(f"status={report['status']}")
    for field in ('dataset', 'results_path', 'comparison_path'):
        if isinstance(report.get(field), str):
            print(f'{field}={report[field]}')
    for row in report.get('rows', []):
        scores = ' '.join(
            f"{name}={value['value']:.3f}"
            if value['value'] is not None
            else f"{name}={value['status']}"
            for name, value in row['metrics'].items()
        )
        print(
            f"{row.get('candidate', {}).get('label', 'B minus A')} | {row['split']} | {row['song_id']} | {row['group']}/{row['stem']} | {scores}"
        )
    if 'coverage' in report:
        print(f"coverage={report['coverage']}")
        for item in report['summary']:
            print(
                f"{item['split']} | {item['group']}/{item['stem']} | {item['metric']} | median_delta={item['median_delta']} wins={item['wins']} losses={item['losses']} ties={item['ties']} unavailable_pairs={item['unavailable_pairs']}"
            )
        for side, jobs in report.get('pending_jobs', {}).items():
            if jobs:
                print(f'Pending {side.upper()} jobs: {jobs}')
        for side, errors in report.get('source_errors', {}).items():
            for error in errors:
                print(f'{side.upper()} source error: {error}', file=sys.stderr)
    for error in report.get('errors', []):
        print(f'error: {error}', file=sys.stderr)


def cmd_score(args: argparse.Namespace) -> int:
    from core.debug_log import log_event
    from core.processing_phase import ProcessingPhase
    from core.scoring.common import write_json
    from core.scoring.evaluate import run_dataset, score_files
    from core.scoring.prepare import prepare_dataset
    from core.scoring.reports import compare_reports

    def progress(phase: str, values: dict[str, Any]) -> None:
        log_event('scoring', 'operation_progress', level='debug', phase=phase, **values)
        if args.quiet:
            return
        if phase == 'song_finished':
            emit_event(args, phase, **values)
            if report_mode(args) == 'human' and not args.quiet:
                print(
                    f"Completed {values['completed']}/{values['total']}: {values['song_id']}",
                    file=sys.stderr,
                )
        else:
            operation = ProcessingPhase(phase)
            emit_event(args, 'phase', phase=operation.value, **values)
            if report_mode(args) == 'human' and not args.quiet:
                print(
                    f"{operation.label}: {values.get('song_id', '')} {values.get('candidate_id', '')} {values.get('stem', '')} {values.get('metric_stage', '')}",
                    file=sys.stderr,
                )

    def stop(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        if args.score_command == 'prepare':
            report = prepare_dataset(
                args.sources, args.output, song_ids=args.song, splits=args.split, callback=progress
            )
        elif args.score_command == 'files':
            report = score_files(
                _paths(args.reference),
                _paths(args.estimate),
                group=args.group,
                metrics=args.metrics,
                candidate={
                    'id': args.candidate,
                    'label': args.label or args.candidate,
                    'kind': args.kind,
                    'provenance': args.provenance,
                },
                song_id=args.song_id,
                output=args.output,
                callback=progress,
            )
        elif args.score_command == 'run':
            report = run_dataset(
                args.dataset, args.estimates, args.output, metrics=args.metrics, callback=progress
            )
        else:
            report = compare_reports(
                args.a, args.b, a_candidate=args.a_candidate, b_candidate=args.b_candidate
            )
            if args.output:
                args.output.mkdir(parents=True, exist_ok=False)
                report['comparison_path'] = str((args.output / 'comparison.json').resolve())
                write_json(args.output / 'comparison.json', report, replace=False)
    finally:
        signal.signal(signal.SIGTERM, previous)
    if report_mode(args) == 'human':
        _human(report)
    else:
        emit_document(args, report)
    return {'success': 0, 'partial': 3, 'failed': 1, 'stopped': 130}[report['status']]
