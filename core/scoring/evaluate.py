"""Offline candidate scoring; filenames never determine model or stem identity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .common import (
    GROUPS,
    Progress,
    audio_info,
    file_signature,
    metric,
    progress,
    read_json,
    records,
    require_same_audio,
    resolve_path,
    sha256,
    text_field,
)
from .metrics import BASIC_PROTOCOL, paired_blocks, score_pair
from .reports import persist_report, summarize


def scoring_protocol(metrics: str) -> dict[str, Any]:
    if metrics not in ('basic', 'all'):
        raise ValueError('Metrics must be basic or all')
    result = dict(BASIC_PROTOCOL)
    result['metrics'] = metrics
    if metrics == 'all':
        from .bss import protocol

        result['bss_eval'] = protocol()
    return result


def candidate_metadata(candidate: dict[str, Any], base: Path) -> dict[str, Any]:
    kind = text_field(candidate, 'kind')
    if kind not in ('model', 'ensemble'):
        raise ValueError('Candidate kind must be model or ensemble')
    result: dict[str, Any] = {
        'id': text_field(candidate, 'id'),
        'label': text_field(candidate, 'label'),
        'kind': kind,
    }
    if candidate.get('provenance'):
        path = resolve_path(base, text_field(candidate, 'provenance'))
        result['provenance'] = {
            'path': str(path),
            'sha256': sha256(path),
            'document': read_json(path),
        }
    return result


def score_group(
    song_id: str,
    split: str,
    group: str,
    references: dict[str, Path],
    estimates: dict[str, Path],
    candidate: dict[str, Any],
    *,
    metrics: str,
    mapping: dict[str, Any] | None = None,
    callback: Progress | None = None,
) -> list[dict[str, Any]]:
    if group not in (*GROUPS, 'custom'):
        raise ValueError(f'Unknown target group: {group}')
    if not references or not estimates or set(estimates) - set(references):
        raise ValueError('Every estimate needs an explicitly mapped reference')
    if group in GROUPS and (set(references) | set(estimates)) - set(GROUPS[group]):
        raise ValueError(f'Unexpected stem for group {group}')
    progress(callback, 'reading_audio', song_id=song_id, candidate_id=candidate['id'], group=group)
    signatures = {
        path: file_signature(path) for path in (*references.values(), *estimates.values())
    }
    info = audio_info(next(iter(references.values())))
    for path in (*references.values(), *estimates.values()):
        require_same_audio(info, audio_info(path))
    for stem in references.keys() - estimates.keys():
        for _block in paired_blocks(references[stem], references[stem], info['sample_rate']):
            pass
    reference_hashes = {s: sha256(p) for s, p in sorted(references.items())}
    identity = hashlib.sha256(
        json.dumps({'references': reference_hashes, 'mapping': mapping}, sort_keys=True).encode()
    ).hexdigest()
    scored = {}
    for stem in sorted(estimates):
        progress(
            callback,
            'scoring',
            song_id=song_id,
            candidate_id=candidate['id'],
            group=group,
            stem=stem,
            metric_stage='basic',
        )
        scored[stem] = score_pair(references[stem], estimates[stem])
    if any(r['reference_sha256'] != reference_hashes[stem] for stem, r in scored.items()):
        raise ValueError('Reference changed during scoring')
    bss: dict[str, Any] = {'status': 'not_requested', 'stems': {}}
    if metrics == 'all':
        from .bss import score_bss

        progress(
            callback,
            'scoring',
            song_id=song_id,
            candidate_id=candidate['id'],
            group=group,
            metric_stage='bss_eval',
        )
        bss = score_bss(references, estimates, group)
    if any(file_signature(path) != signature for path, signature in signatures.items()):
        raise ValueError('Audio changed during group scoring')
    rows = []
    for stem, result in scored.items():
        values = {name: result[name] for name in ('waveform_sdr', 'si_sdr')}
        values['silent_target_rms_dbfs'] = result['silent_target']['output_rms_dbfs']
        if metrics == 'all':
            from .bss import NAMES

            values.update(
                bss['stems'].get(stem, {name: metric(status=bss['status']) for name in NAMES})
            )
        rows.append(
            {
                'song_id': song_id,
                'split': split,
                'group': group,
                'stem': stem,
                'candidate': candidate,
                'reference_identity': identity,
                'reference_group_sha256': reference_hashes,
                'reference': str(references[stem]),
                'estimate': str(estimates[stem]),
                'reference_sha256': result['reference_sha256'],
                'estimate_sha256': result['estimate_sha256'],
                'audio': result['audio'],
                'metrics': values,
                'silent_target': result['silent_target'],
                'bss_status': bss['status'],
                'bss_reason': bss.get('reason'),
                'missing_estimates': sorted(set(GROUPS.get(group, references)) - set(estimates)),
            }
        )
    return rows


def new_report(protocol: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        'schema_version': 1,
        'kind': 'uvr.score.results',
        'protocol': protocol,
        'candidates': candidates,
        'rows': [],
        'errors': [],
        'stopped': False,
        'status': 'success',
        'ok': True,
    }


def finish(report: dict[str, Any], output: Path | None, *, complete: bool = True) -> dict[str, Any]:
    report['status'] = (
        'stopped'
        if report['stopped']
        else (
            'partial'
            if report['errors'] and report['rows']
            else ('failed' if report['errors'] else 'success')
        )
    )
    if not complete and not report['stopped']:
        report['status'] = 'running'
    report['ok'] = report['status'] == 'success'
    report['summary'] = summarize(report['rows'])
    if output:
        report['results_path'] = str((output / 'results.json').resolve())
        persist_report(output, report)
    return report


def score_files(
    references: dict[str, Path],
    estimates: dict[str, Path],
    *,
    group: str = 'pair',
    metrics: str = 'all',
    candidate: dict[str, Any] | None = None,
    song_id: str = 'file',
    output: Path | None = None,
    callback: Progress | None = None,
) -> dict[str, Any]:
    if not song_id.strip():
        raise ValueError('song_id must be a nonempty string')
    candidate = candidate_metadata(
        candidate or {'id': 'files', 'label': 'Files', 'kind': 'model'}, Path.cwd()
    )
    report = new_report(scoring_protocol(metrics), [candidate])
    if output:
        output.mkdir(parents=True, exist_ok=False)
    try:
        report['rows'] = score_group(
            song_id,
            'unspecified',
            group,
            references,
            estimates,
            candidate,
            metrics=metrics,
            callback=callback,
        )
    except KeyboardInterrupt:
        report['stopped'] = True
    except (OSError, ValueError, RuntimeError) as exc:
        report['errors'].append(
            {'song_id': song_id, 'candidate_id': candidate['id'], 'group': group, 'error': str(exc)}
        )
    return finish(report, output)


def run_dataset(
    dataset_path: Path,
    estimates_path: Path,
    output: Path,
    *,
    metrics: str = 'all',
    callback: Progress | None = None,
) -> dict[str, Any]:
    dataset = read_json(dataset_path, 'uvr.score.dataset')
    estimates = read_json(estimates_path, 'uvr.score.estimates')
    songs = {}
    for song in records(dataset, 'songs'):
        sid = text_field(song, 'id')
        if 'split' in song:
            text_field(song, 'split')
        if sid in songs:
            raise ValueError(f'Duplicate dataset song: {sid}')
        songs[sid] = song
    candidates, jobs, seen = [], [], set()
    for entry in records(estimates, 'candidates'):
        candidate = candidate_metadata(entry, estimates_path.parent)
        if candidate['id'] in seen:
            raise ValueError(f'Duplicate candidate: {candidate["id"]}')
        seen.add(candidate['id'])
        candidates.append(candidate)
        pairs = set()
        for estimate in records(entry, 'estimates'):
            sid, group = text_field(estimate, 'song_id'), text_field(estimate, 'group')
            if (sid, group) in pairs:
                raise ValueError(f'Duplicate estimate group: {sid}/{group}')
            pairs.add((sid, group))
            if sid not in songs:
                raise ValueError(f'Unknown song ID: {sid}')
            song = songs[sid]
            groups = song.get('groups')
            if (
                not isinstance(groups, dict)
                or group not in groups
                or group not in (*GROUPS, 'custom')
            ):
                raise ValueError(f'Unknown reference group: {sid}/{group}')
            raw_refs, raw_ests = groups[group], estimate.get('stems')
            if not isinstance(raw_refs, dict) or not isinstance(raw_ests, dict) or not raw_ests:
                raise ValueError('Reference and estimate stem mappings must be objects')
            refs, ests = {}, {}
            for stem, ref in raw_refs.items():
                if not isinstance(ref, dict):
                    raise ValueError('Reference entry must contain path and sha256')
                refs[stem] = resolve_path(dataset_path.parent, text_field(ref, 'path'))
                text_field(ref, 'sha256')
            for stem, path in raw_ests.items():
                if not isinstance(path, str) or not path:
                    raise ValueError('Estimate paths must be nonempty strings')
                ests[stem] = resolve_path(estimates_path.parent, path)
            if group in GROUPS and set(refs) != set(GROUPS[group]):
                raise ValueError(f'Dataset reference group is incomplete: {sid}/{group}')
            if not refs or set(ests) - set(refs):
                raise ValueError('Estimate has no corresponding reference')
            jobs.append((song, group, refs, ests, candidate))
    report = new_report(scoring_protocol(metrics), candidates)
    report['dataset'] = {
        'path': str(dataset_path.resolve()),
        'sha256': sha256(dataset_path),
        'mapping': dataset.get('mapping'),
    }
    report['estimates_manifest_sha256'] = sha256(estimates_path)
    report['jobs'] = [
        {
            'song_id': song['id'],
            'split': song.get('split', 'unspecified'),
            'candidate_id': candidate['id'],
            'group': group,
            'status': 'pending',
            'missing_estimates': sorted(set(refs) - set(ests)),
        }
        for song, group, refs, ests, candidate in jobs
    ]
    report['status'] = 'running'
    report['ok'] = False
    output.mkdir(parents=True, exist_ok=False)
    persist_report(output, report)
    try:
        for index, (song, group, refs, ests, candidate) in enumerate(jobs, 1):
            try:
                progress(
                    callback, 'reading_audio', song_id=song['id'], candidate_id=candidate['id']
                )
                for stem, ref in refs.items():
                    if sha256(ref) != song['groups'][group][stem]['sha256']:
                        raise ValueError(f'Reference hash mismatch: {song["id"]}/{stem}')

                def job_progress(
                    phase: str, values: dict[str, Any], completed: int = index - 1
                ) -> None:
                    progress(callback, phase, completed=completed, total=len(jobs), **values)

                rows = score_group(
                    song['id'],
                    song.get('split', 'unspecified'),
                    group,
                    refs,
                    ests,
                    candidate,
                    metrics=metrics,
                    mapping=dataset.get('mapping'),
                    callback=job_progress,
                )
                report['rows'].extend(rows)
                report['jobs'][index - 1]['status'] = 'success'
            except (OSError, ValueError, RuntimeError) as exc:
                report['jobs'][index - 1]['status'] = 'failed'
                report['errors'].append(
                    {
                        'song_id': song['id'],
                        'candidate_id': candidate['id'],
                        'group': group,
                        'error': str(exc),
                    }
                )
            finish(report, output, complete=False)
            progress(
                callback,
                'song_finished',
                song_id=song['id'],
                candidate_id=candidate['id'],
                group=group,
                status=report['jobs'][index - 1]['status'],
                completed=index,
                total=len(jobs),
            )
    except KeyboardInterrupt:
        report['stopped'] = True
    return finish(report, output)
