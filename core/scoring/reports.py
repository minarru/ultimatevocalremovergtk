"""Finite-score aggregation, durable reports, and paired comparisons."""

from __future__ import annotations

import csv
import io
import math
import os
import statistics
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .common import metric, read_json, records, sha256, text_field, write_json


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = defaultdict(list)
    for row in rows:
        for name, value in row['metrics'].items():
            groups[(row['candidate']['id'], row['split'], row['group'], row['stem'], name)].append(
                value
            )
    result = []
    for (candidate, split, group, stem, name), values in sorted(groups.items()):
        finite = [v['value'] for v in values if v['status'] == 'finite']
        result.append(
            {
                'candidate_id': candidate,
                'split': split,
                'group': group,
                'stem': stem,
                'metric': name,
                'median': statistics.median(finite) if finite else None,
                'finite_count': len(finite),
                'status_counts': dict(Counter(v['status'] for v in values)),
            }
        )
    return result


def persist_report(output: Path, report: dict[str, Any]) -> None:
    report['summary'] = summarize(report['rows'])
    write_json(output / 'results.json', report)
    stream = io.StringIO()
    fields = (
        'candidate_id',
        'candidate_kind',
        'song_id',
        'split',
        'group',
        'stem',
        'metric',
        'value',
        'status',
    )
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in report['rows']:
        for name, value in row['metrics'].items():
            writer.writerow(
                {
                    'candidate_id': row['candidate']['id'],
                    'candidate_kind': row['candidate']['kind'],
                    'song_id': row['song_id'],
                    'split': row['split'],
                    'group': row['group'],
                    'stem': row['stem'],
                    'metric': name,
                    'value': value['value'],
                    'status': value['status'],
                }
            )
    fd, tmp = tempfile.mkstemp(prefix='.results-', dir=output)
    try:
        with os.fdopen(fd, 'w', newline='') as handle:
            handle.write(stream.getvalue())
        os.replace(tmp, output / 'results.csv')
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def compare_reports(
    a: Path, b: Path, *, a_candidate: str | None = None, b_candidate: str | None = None
) -> dict[str, Any]:
    left = read_json(a, 'uvr.score.results')
    right = read_json(b, 'uvr.score.results')
    for report in (left, right):
        validate_report(report)
    if left.get('protocol') != right.get('protocol'):
        raise ValueError('Scoring protocols differ; scores are not comparable')

    def select(
        report: dict[str, Any], chosen: str | None
    ) -> tuple[str, dict[tuple, dict[str, Any]]]:
        candidates: set[str] = {c['id'] for c in report['candidates']}
        if chosen is None:
            if len(candidates) != 1:
                raise ValueError(
                    'Select --a-candidate and --b-candidate for reports with multiple candidates'
                )
            chosen = next(iter(candidates))
        if chosen not in candidates:
            raise ValueError(f'Candidate not found: {chosen}')
        entries = {}
        for row in report['rows']:
            if row['candidate']['id'] == chosen:
                key = (row['song_id'], row['split'], row['group'], row['stem'])
                if key in entries:
                    raise ValueError(f'Duplicate score key: {key}')
                entries[key] = row
        return chosen, entries

    aid, aa = select(left, a_candidate)
    bid, bb = select(right, b_candidate)
    shared = sorted(aa.keys() & bb.keys())
    rows = []
    aggregates = defaultdict(list)
    for key in shared:
        x, y = aa[key], bb[key]
        if x['reference_identity'] != y['reference_identity'] or x['audio'] != y['audio']:
            raise ValueError(f'References or preparation mapping differ for {key}')
        deltas = {}
        if x['metrics'].keys() != y['metrics'].keys():
            raise ValueError(f'Metric inventory differs for {key}')
        for name in x['metrics']:
            av, bv = x['metrics'][name], y['metrics'][name]
            delta = (
                metric(bv['value'] - av['value'])
                if av['status'] == bv['status'] == 'finite'
                else metric(status='nonfinite_pair')
            )
            delta['a'] = {k: av[k] for k in ('value', 'status')}
            delta['b'] = {k: bv[k] for k in ('value', 'status')}
            deltas[name] = delta
            aggregates[(key[1], key[2], key[3], name)].append(delta)
        rows.append(
            {'song_id': key[0], 'split': key[1], 'group': key[2], 'stem': key[3], 'metrics': deltas}
        )
    summary = []
    for (split, group, stem, name), values in sorted(aggregates.items()):
        finite = [v['value'] for v in values if v['status'] == 'finite']
        lower = name == 'silent_target_rms_dbfs'
        wins = sum(v < -1e-9 if lower else v > 1e-9 for v in finite)
        losses = sum(v > 1e-9 if lower else v < -1e-9 for v in finite)
        summary.append(
            {
                'split': split,
                'group': group,
                'stem': stem,
                'metric': name,
                'median_delta': statistics.median(finite) if finite else None,
                'wins': wins,
                'losses': losses,
                'ties': len(finite) - wins - losses,
                'unavailable_pairs': len(values) - len(finite),
                'better': 'lower' if lower else 'higher',
            }
        )
    return {
        'schema_version': 1,
        'kind': 'uvr.score.comparison',
        'ok': True,
        'status': 'success',
        'a_candidate': aid,
        'b_candidate': bid,
        'protocol': left['protocol'],
        'rows': rows,
        'summary': summary,
        'tie_tolerance_db': 1e-9,
        'source_reports': {
            'a': {'path': str(a.resolve()), 'sha256': sha256(a)},
            'b': {'path': str(b.resolve()), 'sha256': sha256(b)},
        },
        'a_candidate_metadata': next(c for c in left['candidates'] if c['id'] == aid),
        'b_candidate_metadata': next(c for c in right['candidates'] if c['id'] == bid),
        'source_status': {'a': left.get('status'), 'b': right.get('status')},
        'pending_jobs': {
            'a': [j for j in left.get('jobs', []) if j['status'] == 'pending'],
            'b': [j for j in right.get('jobs', []) if j['status'] == 'pending'],
        },
        'coverage': {
            'matched': len(shared),
            'only_a': [list(k) for k in sorted(aa.keys() - bb.keys())],
            'only_b': [list(k) for k in sorted(bb.keys() - aa.keys())],
        },
        'source_errors': {'a': left.get('errors', []), 'b': right.get('errors', [])},
    }


def validate_report(report: dict[str, Any]) -> None:
    """Reject malformed reports before comparison rather than assuming trusted JSON."""
    if not isinstance(report.get('protocol'), dict) or not report['protocol']:
        raise ValueError('Scoring report must contain a metric protocol')
    ids = [text_field(c, 'id') for c in records(report, 'candidates')]
    if len(ids) != len(set(ids)):
        raise ValueError('Scoring report has duplicate candidate IDs')
    jobs = report.get('jobs', [])
    if not isinstance(jobs, list) or any(
        not isinstance(j, dict) or j.get('status') not in ('pending', 'success', 'failed')
        for j in jobs
    ):
        raise ValueError('Scoring report has invalid job statuses')
    rows = report.get('rows')
    if not isinstance(rows, list):
        raise ValueError('Scoring report rows must be a list')
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Scoring report row must be an object')
        for field in ('song_id', 'split', 'group', 'stem', 'reference_identity'):
            text_field(row, field)
        candidate = row.get('candidate')
        if not isinstance(candidate, dict) or candidate.get('id') not in ids:
            raise ValueError('Scoring report row has unknown candidate')
        audio, values = row.get('audio'), row.get('metrics')
        if not isinstance(audio, dict) or not all(
            isinstance(audio.get(k), int) and audio[k] > 0
            for k in ('frames', 'channels', 'sample_rate')
        ):
            raise ValueError('Scoring report row has invalid audio dimensions')
        if not isinstance(values, dict) or not values:
            raise ValueError('Scoring report row has no metrics')
        for value in values.values():
            if not isinstance(value, dict):
                raise ValueError('Metric must contain value and status')
            status = text_field(value, 'status')
            number = value.get('value')
            if status == 'finite':
                if (
                    not isinstance(number, (int, float))
                    or isinstance(number, bool)
                    or not math.isfinite(number)
                ):
                    raise ValueError('Finite metric must contain a finite number')
            elif number is not None:
                raise ValueError('Nonfinite metric must contain null')
