"""Lazy audio decoding with explicit SoundFile and FFmpeg ownership boundaries."""

from __future__ import annotations

import contextlib
import json
import math
import os
import selectors
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, BinaryIO, Iterator, cast

from .external_tools import resolve_ffmpeg, resolve_ffprobe

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

AudioSource = str | os.PathLike[str] | BinaryIO
_METADATA_TIMEOUT = 10.0
_STDOUT_TIMEOUT = 30.0
_STDERR_LIMIT = 16 * 1024


class AudioDecodeError(RuntimeError):
    """Audio could not be decoded or its stream metadata is invalid."""


@dataclass(frozen=True)
class AudioMetadata:
    sample_rate: int
    channels: int
    frames: int | None = None
    duration_seconds: float | None = None
    format: str | None = None


@contextlib.contextmanager
def _source(source: AudioSource) -> Iterator[AudioSource]:
    if isinstance(source, (str, os.PathLike)):
        yield os.fspath(source)
        return
    position = source.tell()
    try:
        source.seek(0)
        yield source
    finally:
        source.seek(position)


@contextlib.contextmanager
def _local_path(source: AudioSource) -> Iterator[str]:
    if isinstance(source, (str, os.PathLike)):
        yield os.path.abspath(source)
        return
    # A file, rather than a pipe, lets both tools seek through arbitrary containers.
    with tempfile.TemporaryDirectory(prefix='uvr-audio-') as directory:
        path = os.path.join(directory, 'input')
        source.seek(0)
        with open(path, 'wb') as output:
            shutil.copyfileobj(source, output)
        yield path


def _capture(
    command: list[str], *, timeout: float, total_timeout: bool = False, reject_stderr: bool = False
) -> bytes:
    """Drain both pipes; keep only a bounded diagnostic tail and reap on every exit."""
    process = subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    output = bytearray()
    errors = bytearray()
    deadline = time.monotonic() + timeout
    try:
        assert process.stdout is not None and process.stderr is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, True)
            selector.register(process.stderr, selectors.EVENT_READ, False)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        'Audio tool produced no PCM before timeout'
                        if not total_timeout
                        else 'Audio metadata probe timed out'
                    )
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    elif key.data:
                        output.extend(chunk)
                        if not total_timeout:
                            deadline = time.monotonic() + timeout
                    else:
                        errors.extend(chunk)
                        del errors[:-_STDERR_LIMIT]
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
        if process.returncode:
            raise RuntimeError(
                f'Audio tool exited with status {process.returncode}: {errors.decode("utf-8", errors="replace")}'
            )
        if reject_stderr and errors.strip():
            raise RuntimeError(
                f'Audio tool reported decoding errors: {errors.decode("utf-8", errors="replace")}'
            )
        return bytes(output)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def _ffprobe(path: str) -> AudioMetadata:
    executable = resolve_ffprobe()
    if not executable:
        raise FileNotFoundError('ffprobe is required for this audio format')
    payload = _capture(
        [
            executable,
            '-v',
            'error',
            '-select_streams',
            'a:0',
            '-show_entries',
            'stream=sample_rate,channels,duration:format=format_name',
            '-of',
            'json',
            path,
        ],
        timeout=_METADATA_TIMEOUT,
        total_timeout=True,
    )
    document = json.loads(payload)
    streams = document.get('streams', [])
    if not streams:
        raise ValueError('No audio stream found')
    stream = streams[0]
    rate, channels = int(stream['sample_rate']), int(stream['channels'])
    if rate <= 0 or channels <= 0:
        raise ValueError('Invalid audio sample rate or channel count')
    duration = None
    try:
        candidate = float(stream.get('duration'))
        if math.isfinite(candidate) and candidate >= 0:
            duration = candidate
    except (ValueError, TypeError):
        pass
    return AudioMetadata(
        rate,
        channels,
        duration_seconds=duration,
        format=document.get('format', {}).get('format_name'),
    )


def read_audio_metadata(source: AudioSource) -> AudioMetadata:
    """Read headers only; duration and sample-frame count may be unknown."""
    try:
        with _source(source) as handle:
            try:
                import soundfile as sf

                info = sf.info(handle)
                if info.samplerate <= 0 or info.channels <= 0 or info.frames < 0:
                    raise ValueError('Invalid audio metadata')
                return AudioMetadata(
                    int(info.samplerate),
                    int(info.channels),
                    int(info.frames),
                    float(info.frames) / info.samplerate,
                    str(info.format),
                )
            except Exception:
                with _local_path(handle) as path:
                    return _ffprobe(path)
    except Exception as exc:
        raise AudioDecodeError(f'Cannot read audio metadata: {exc}') from exc


def _decode_ffmpeg(source: AudioSource, duration: float | None) -> tuple[NDArray[np.float32], int]:
    import numpy as np

    with _local_path(source) as path:
        info = _ffprobe(path)
        executable = resolve_ffmpeg()
        if not executable:
            raise FileNotFoundError('ffmpeg is required for this audio format')
        command = [executable, '-nostdin', '-xerror', '-v', 'error', '-i', path, '-map', '0:a:0']
        if duration is not None:
            command.extend(['-t', str(duration)])
        command.extend(
            [
                '-f',
                'f32le',
                '-acodec',
                'pcm_f32le',
                '-ar',
                str(info.sample_rate),
                '-ac',
                str(info.channels),
                'pipe:1',
            ]
        )
        # FFmpeg 6.1.1 can report decoder errors and return partial PCM with
        # status zero even under -xerror. With -v error, stderr is an error
        # channel, not ordinary progress or warnings; reject it explicitly.
        pcm = _capture(command, timeout=_STDOUT_TIMEOUT, reject_stderr=True)
    if not pcm or len(pcm) % (4 * info.channels):
        raise ValueError('Empty or incomplete audio PCM data')
    data = (
        np.frombuffer(pcm, dtype='<f4').astype(np.float32, copy=True).reshape(-1, info.channels).T
    )
    if duration is not None:
        data = data[:, : int(duration * info.sample_rate)]
    return (data[0] if info.channels == 1 else data), info.sample_rate


def load_audio(
    source: AudioSource,
    *,
    sr: int | None = None,
    duration: float | None = None,
    res_type: str = 'soxr_hq',
    force_ffmpeg: bool = False,
) -> tuple[NDArray[np.float32], int]:
    """Decode float32 native channels, then optionally resample the last axis.

    Mono is ``(samples,)`` and multichannel is ``(channels, samples)``. Caller
    streams remain open and their initial position is restored, including errors.
    """
    try:
        if sr is not None and (type(sr) is not int or sr <= 0):
            raise ValueError('Sample rate must be a positive integer')
        if duration is not None and (not math.isfinite(duration) or duration <= 0):
            raise ValueError('Duration must be finite and positive')
        with _source(source) as handle:
            if force_ffmpeg:
                data, rate = _decode_ffmpeg(handle, duration)
            else:
                try:
                    import soundfile as sf

                    with sf.SoundFile(handle) as audio:
                        rate = int(audio.samplerate)
                        frames = -1 if duration is None else int(duration * rate)
                        data = audio.read(frames=frames, dtype='float32', always_2d=False).T
                    if data.size == 0:
                        raise ValueError('Empty audio data')
                except Exception:
                    data, rate = _decode_ffmpeg(handle, duration)
            if data.size == 0:
                raise ValueError('Empty audio data')
            if sr is not None and sr != rate:
                import librosa

                data = librosa.resample(
                    data, orig_sr=rate, target_sr=sr, res_type=res_type, axis=-1
                )
                rate = sr
            return cast("NDArray[np.float32]", data), rate
    except Exception as exc:
        raise AudioDecodeError(f'Cannot decode audio: {exc}') from exc
