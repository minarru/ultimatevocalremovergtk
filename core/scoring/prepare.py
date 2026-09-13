"""Prepare reproducible float references from explicit source manifests."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .common import (
    Progress,
    audio_info,
    file_signature,
    progress,
    read_json,
    records,
    require_same_audio,
    resolve_path,
    sha256,
    text_field,
    write_json,
)

MAPPING = {
    'id': 'moises-uvr-v1',
    'vocals': ['vocals'],
    'bass': ['bass'],
    'drums': ['drums', 'percussion'],
    'other': 'all remaining source categories',
    'instrumental': 'all non-vocal sources',
}


def load_sources(path: Path) -> list[dict[str, Any]]:
    data = read_json(path)
    if data.get('kind') == 'uvr.score.sources':
        if data.get('schema_version') != 1:
            raise ValueError('Unsupported source manifest version')
        songs = records(data, 'songs')
    elif 'verified_tracks' in data and 'archive_sha256' in data:
        # Import the explicitly mapped FLAC conversion manifest; data.json still names WAVs.
        tracks = records(data, 'tracks')
        songs = []
        known = set()
        for song in records(data, 'songs'):
            sid = text_field(song, 'id')
            known.add(sid)
            sources = [
                {
                    'stem': text_field(t, 'stem'),
                    'path': text_field(t, 'path'),
                    'track_id': t.get('track_id'),
                    'track_type': t.get('track_type'),
                }
                for t in tracks
                if t.get('song_id') == sid
            ]
            songs.append(
                {
                    'id': sid,
                    'title': song.get('song', sid),
                    'artist': song.get('artist', ''),
                    'split': song.get('group', 'unspecified'),
                    'sources': sources,
                }
            )
        if any(t.get('song_id') not in known for t in tracks):
            raise ValueError('Converted source manifest contains orphan tracks')
    else:
        raise ValueError('Expected uvr.score.sources v1 or a converted MoisesDB manifest')
    seen = set()
    result = []
    for song in songs:
        sid = text_field(song, 'id')
        if sid in seen:
            raise ValueError(f'Duplicate song ID: {sid}')
        seen.add(sid)
        if 'split' in song:
            text_field(song, 'split')
        sources = []
        paths = set()
        for source in records(song, 'sources'):
            resolved = resolve_path(path.parent, text_field(source, 'path'))
            if resolved in paths:
                raise ValueError(f'Source assigned more than once in {sid}: {resolved}')
            paths.add(resolved)
            sources.append({**source, 'stem': text_field(source, 'stem'), 'path': str(resolved)})
        result.append({**song, 'split': song.get('split', 'unspecified'), 'sources': sources})
    return result


def _prepare_song(song: dict[str, Any], folder: Path, callback: Progress | None) -> dict[str, Any]:
    import numpy as np
    import soundfile as sf

    progress(callback, 'reading_audio', song_id=song['id'])
    sources = song['sources']
    info = audio_info(Path(sources[0]['path']))
    if info['channels'] != 2:
        raise ValueError('Dataset preparation requires stereo sources')
    for source in sources:
        require_same_audio(info, audio_info(Path(source['path'])))
    n, ch, rate = info['frames'], info['channels'], info['sample_rate']
    # One song at a time; never stack all individual sources in memory.
    buses = {
        stem: np.zeros((n, ch), dtype=np.float64) for stem in ('vocals', 'bass', 'drums', 'other')
    }
    source_records = []
    progress(callback, 'combining', song_id=song['id'])
    for source in sources:
        stem = source['stem']
        target = (
            stem
            if stem in ('vocals', 'bass', 'drums')
            else ('drums' if stem == 'percussion' else 'other')
        )
        path = Path(source['path'])
        signature = file_signature(path)
        source_records.append({**source, 'sha256': sha256(path), 'target': target})
        cursor = 0
        with sf.SoundFile(str(path)) as handle:
            for block in handle.blocks(blocksize=65536, dtype='float64', always_2d=True):
                if not np.isfinite(block).all():
                    raise ValueError(f'Non-finite source: {path}')
                buses[target][cursor : cursor + len(block)] += block
                cursor += len(block)
        if cursor != n or file_signature(path) != signature:
            raise ValueError(f'Source changed while preparing: {path}')
    instrumental = buses['bass'] + buses['drums'] + buses['other']
    mixture = buses['vocals'] + instrumental
    all_audio = {**buses, 'instrumental': instrumental, 'mixture': mixture}
    peak = max(float(np.max(np.abs(x))) for x in all_audio.values())
    if not np.isfinite(peak):
        raise ValueError('Source sum overflowed')
    # Keep the exported float32 peak below 0.99 despite conversion rounding.
    ceiling = float(np.nextafter(np.float32(0.99), np.float32(0)))
    needs_attenuation = peak > 0.99 or float(np.float32(peak)) > 0.99
    gain = min(1.0, ceiling / peak) if needs_attenuation else 1.0
    written = {}
    progress(callback, 'saving', song_id=song['id'])
    for stem, audio in all_audio.items():
        audio *= gain
        path = folder / f'{stem}.wav'
        sf.write(str(path), audio, rate, subtype='FLOAT')
        written[stem] = {
            'path': path.name,
            'sha256': sha256(path),
            'silent': not bool(np.any(audio)),
            **info,
        }
    # Verify the actual exported float32 samples, not only the pre-export sum.
    from contextlib import ExitStack

    with ExitStack() as stack:
        handles = {
            s: stack.enter_context(sf.SoundFile(str(folder / f'{s}.wav'))) for s in all_audio
        }
        while True:
            blocks = {s: h.read(65536, dtype='float64', always_2d=True) for s, h in handles.items()}
            if not blocks['mixture'].size:
                break
            for stems in (('vocals', 'instrumental'), ('vocals', 'bass', 'drums', 'other')):
                residual = sum(blocks[s] for s in stems) - blocks['mixture']
                if float(np.max(np.abs(residual))) > 5e-7:
                    raise ValueError('Exported references do not reconstruct the mixture')
    return {
        'id': song['id'],
        'title': song.get('title', song['id']),
        'artist': song.get('artist', ''),
        'split': song['split'],
        'gain': gain,
        'sources': source_records,
        'mixture': written['mixture'],
        'groups': {
            'pair': {s: written[s] for s in ('vocals', 'instrumental')},
            'four': {s: written[s] for s in ('vocals', 'drums', 'bass', 'other')},
        },
    }


def prepare_dataset(
    source_manifest: Path,
    output: Path,
    *,
    song_ids: list[str] | None = None,
    splits: list[str] | None = None,
    callback: Progress | None = None,
) -> dict[str, Any]:
    songs = load_sources(source_manifest)
    if song_ids and set(song_ids) - {s['id'] for s in songs}:
        raise ValueError('Requested song ID is absent from the source manifest')
    songs = [
        s
        for s in songs
        if (not song_ids or s['id'] in song_ids) and (not splits or s['split'] in splits)
    ]
    if not songs:
        raise ValueError('No songs selected')
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        'schema_version': 1,
        'kind': 'uvr.score.dataset',
        'mapping': MAPPING,
        'preparation': {
            'sample_format': 'FLOAT',
            'sum_precision': 'float64',
            'shared_gain': True,
            'peak_ceiling': 0.99,
            'reconstruction_atol': 5e-7,
        },
        'source_manifest': str(source_manifest.resolve()),
        'source_manifest_sha256': sha256(source_manifest),
        'selected_song_ids': [s['id'] for s in songs],
        'songs': [],
        'errors': [],
        'stopped': False,
    }
    destination = output / 'dataset.json'
    write_json(destination, manifest)
    try:
        for index, song in enumerate(songs, 1):
            stage = Path(tempfile.mkdtemp(prefix='.prepare-', dir=output))
            try:
                entry = _prepare_song(song, stage, callback)
                name = f'song-{index:04d}'
                os.rename(stage, output / name)
                for ref in [
                    entry['mixture'],
                    *entry['groups']['pair'].values(),
                    *entry['groups']['four'].values(),
                ]:
                    # vocals is shared by both groups; derive the basename each time.
                    ref['path'] = f'{name}/{Path(ref["path"]).name}'
                manifest['songs'].append(entry)
            except (OSError, ValueError, RuntimeError) as exc:
                manifest['errors'].append({'song_id': song['id'], 'error': str(exc)})
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
            write_json(destination, manifest)
            progress(
                callback, 'song_finished', song_id=song['id'], completed=index, total=len(songs)
            )
    except KeyboardInterrupt:
        manifest['stopped'] = True
        write_json(destination, manifest)
    status = (
        'stopped'
        if manifest['stopped']
        else (
            'partial'
            if manifest['errors'] and manifest['songs']
            else ('failed' if manifest['errors'] else 'success')
        )
    )
    return {
        'status': status,
        'ok': status == 'success',
        'stopped': manifest['stopped'],
        'dataset': str(destination.resolve()),
        'songs': len(manifest['songs']),
        'errors': manifest['errors'],
    }
