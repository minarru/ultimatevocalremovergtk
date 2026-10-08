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
from typing import TYPE_CHECKING, BinaryIO, Callable, Iterator, cast

from .debug_log import log_event
from .external_tools import resolve_ffmpeg, resolve_ffprobe

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

AudioSource = str | os.PathLike[str] | BinaryIO
_METADATA_TIMEOUT = 10.0
_STDOUT_TIMEOUT = 30.0
_STDERR_LIMIT = 16 * 1024
# A damaged file is accepted when FFmpeg loses at most this share of its audio;
# the unreadable parts are replaced with silence so timing is preserved.
_MAX_REPAIRED_FRACTION = 0.005
# aresample pads timestamp gaps left by dropped packets (and is bit-exact on
# intact streams); first_pts=0 is what enables that compensation.
_FILL_GAPS_FILTER = 'aresample=min_hard_comp=0.001:first_pts=0'


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


class _OutputLimitExceeded(Exception):
    """PCM grew past the caller's byte cap; the tool was killed.

    The PCM itself is not retained. Holding it on this exception would pin the
    buffer in the traceback for as long as the error is chained.
    """

    def __init__(self, errors: bytes) -> None:
        super().__init__('audio tool output exceeded its byte cap')
        self.errors = errors


def _repair_output_limit(decoded_bytes: int, channels: int) -> int:
    """Largest padded PCM size the damage budget can still accept.

    One extra frame of slack covers the float boundary of the budget check.
    A file past the budget is stopped here instead of being buffered first.
    """
    frame_bytes = 4 * channels
    if channels <= 0 or decoded_bytes <= 0:
        return 0
    decoded_frames = decoded_bytes // frame_bytes
    if decoded_frames <= 0:
        return 0
    max_frames = int(decoded_frames / (1.0 - _MAX_REPAIRED_FRACTION)) + 1
    return max_frames * frame_bytes


def _run_tool(
    command: list[str],
    *,
    timeout: float,
    total_timeout: bool = False,
    keep_output: bool = True,
    max_output_bytes: int | None = None,
) -> tuple[bytearray, int, bytes]:
    """Drain both pipes; keep only a bounded diagnostic tail and reap on every exit.

    Returns ``(stdout, stdout_bytes, stderr_tail)``. The stdout buffer itself is
    returned: decoded PCM for a long track is hundreds of megabytes, and callers
    wrap it in place rather than copying it. ``keep_output=False`` only counts
    the bytes. A non-zero exit raises ``RuntimeError``. ``max_output_bytes``
    kills the tool once stdout passes that size and raises
    :class:`_OutputLimitExceeded` without keeping the PCM.
    """
    process = subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    output = bytearray()
    output_bytes = 0
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
                        output_bytes += len(chunk)
                        if max_output_bytes is not None and output_bytes > max_output_bytes:
                            # Drop the prefix before raising so the traceback
                            # cannot keep a buffer the caller is about to reject.
                            output = bytearray()
                            raise _OutputLimitExceeded(bytes(errors))
                        if keep_output:
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
        return output, output_bytes, bytes(errors)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def _capture(
    command: list[str], *, timeout: float, total_timeout: bool = False, reject_stderr: bool = False
) -> bytearray:
    """Run an audio tool and return its stdout buffer (see :func:`_run_tool`)."""
    output, _count, errors = _run_tool(command, timeout=timeout, total_timeout=total_timeout)
    if reject_stderr and errors.strip():
        raise RuntimeError(
            f'Audio tool reported decoding errors: {errors.decode("utf-8", errors="replace")}'
        )
    return output


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


def _pcm_command(
    executable: str,
    path: str,
    info: AudioMetadata,
    duration: float | None,
    *,
    strict: bool,
    fill_gaps: bool = False,
    offset: float = 0.0,
) -> list[str]:
    command = [executable, '-nostdin']
    if strict:
        command.append('-xerror')
    command.extend(['-v', 'error'])
    if offset > 0:
        # Before -i: an input seek, which is sample-accurate for audio.
        # Fixed-point: FFmpeg's time parser rejects exponents such as 1e-05.
        command.extend(['-ss', f'{offset:.6f}'])
    command.extend(['-i', path, '-map', '0:a:0'])
    if duration is not None:
        command.extend(['-t', str(duration)])
    if fill_gaps:
        command.extend(['-af', _FILL_GAPS_FILTER])
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
    return command


def _format_seconds(seconds: float) -> str:
    return f'{seconds * 1000:.0f} ms' if seconds < 1 else f'{seconds:.1f} s'


def _last_lines(text: bytes, count: int = 3) -> str:
    # The stderr tail is byte-bounded, so its first line may be cut mid-way.
    lines = [line for line in text.decode('utf-8', errors='replace').splitlines() if line.strip()]
    return '\n'.join(lines[-count:])


def _decode_damaged(
    executable: str,
    path: str,
    info: AudioMetadata,
    duration: float | None,
    on_warning: Callable[[str], None] | None,
    offset: float = 0.0,
) -> bytearray:
    """Decode past corrupt packets, padding what FFmpeg drops with silence.

    Two tolerant passes measure the loss exactly: one counts the samples FFmpeg
    could decode, the other fills the timestamp gaps. The fill pass is capped at
    the damage budget, so a few corrupt timestamps cannot expand into an
    unbounded silence buffer. Only damaged files, whose strict decode already
    failed, pay for either pass.
    """
    _unused, decoded_bytes, _errors = _run_tool(
        _pcm_command(executable, path, info, duration, strict=False, offset=offset),
        timeout=_STDOUT_TIMEOUT,
        keep_output=False,
    )
    try:
        pcm, _count, errors = _run_tool(
            _pcm_command(
                executable, path, info, duration, strict=False, fill_gaps=True, offset=offset
            ),
            timeout=_STDOUT_TIMEOUT,
            max_output_bytes=_repair_output_limit(decoded_bytes, info.channels),
        )
    except _OutputLimitExceeded as exc:
        diagnostic = _last_lines(exc.errors)
        raise ValueError(
            'Audio is too damaged to decode reliably: gap filling exceeded the '
            f'{_MAX_REPAIRED_FRACTION:.1%} silence budget before the file ended.\n{diagnostic}'
        ) from exc
    frame_bytes = 4 * info.channels
    total_frames = len(pcm) // frame_bytes
    lost_frames = max(0, total_frames - decoded_bytes // frame_bytes)
    lost_seconds = lost_frames / info.sample_rate
    total_seconds = total_frames / info.sample_rate
    diagnostic = _last_lines(errors)
    if not total_frames or lost_frames > total_frames * _MAX_REPAIRED_FRACTION:
        raise ValueError(
            f'Audio is too damaged to decode reliably: {_format_seconds(lost_seconds)} of '
            f'{_format_seconds(total_seconds)} could not be read.\n{diagnostic}'
        )
    log_event(
        'audio',
        'decode_repaired',
        level='warning',
        lost_seconds=round(lost_seconds, 3),
        duration_seconds=round(total_seconds, 3),
        diagnostic=diagnostic,
    )
    if on_warning is not None:
        name = os.path.basename(path)
        if lost_frames:
            on_warning(
                f'Warning: {name} contains damaged audio; {_format_seconds(lost_seconds)} that FFmpeg '
                'could not read was replaced with silence to keep the timing intact.\n'
            )
        else:
            on_warning(
                f'Warning: FFmpeg reported decoding errors in {name}; the decoder concealed '
                'them, but the output may contain short glitches.\n'
            )
    return pcm


def _decode_ffmpeg(
    source: AudioSource,
    duration: float | None,
    on_warning: Callable[[str], None] | None = None,
    offset: float = 0.0,
) -> tuple[NDArray[np.float32], int]:
    import numpy as np

    with _local_path(source) as path:
        info = _ffprobe(path)
        executable = resolve_ffmpeg()
        if not executable:
            raise FileNotFoundError('ffmpeg is required for this audio format')
        try:
            # FFmpeg 6.1.1 can report decoder errors and return partial PCM with
            # status zero even under -xerror. With -v error, stderr is an error
            # channel, not ordinary progress or warnings; reject it explicitly.
            pcm = _capture(
                _pcm_command(executable, path, info, duration, strict=True, offset=offset),
                timeout=_STDOUT_TIMEOUT,
                reject_stderr=True,
            )
        except RuntimeError:
            # Decoder errors only (timeouts are OSError): retry tolerantly.
            pcm = _decode_damaged(executable, path, info, duration, on_warning, offset)
    if not pcm or len(pcm) % (4 * info.channels):
        raise ValueError('Empty or incomplete audio PCM data')
    # A view over the mutable capture buffer is already writable, so the samples
    # are never copied; astype only copies on a big-endian host.
    data = np.frombuffer(pcm, dtype='<f4').astype(np.float32, copy=False)
    data = data.reshape(-1, info.channels).T
    if duration is not None:
        data = data[:, : int(duration * info.sample_rate)]
    return (data[0] if info.channels == 1 else data), info.sample_rate


def _seed_peaks(path: str, data: NDArray[np.float32], rate: int) -> None:
    """Offer the native-rate envelope of a whole decoded file to the waveform view."""
    from .waveform import offer_peaks, peaks_from_array

    offer_peaks(path, lambda: peaks_from_array(data, rate))


def load_audio(
    source: AudioSource,
    *,
    sr: int | None = None,
    duration: float | None = None,
    offset: float = 0.0,
    res_type: str = 'soxr_hq',
    force_ffmpeg: bool = False,
    on_warning: Callable[[str], None] | None = None,
) -> tuple[NDArray[np.float32], int]:
    """Decode float32 native channels, then optionally resample the last axis.

    Mono is ``(samples,)`` and multichannel is ``(channels, samples)``. Caller
    streams remain open and their initial position is restored, including errors.
    ``on_warning`` receives a console-ready notice when a slightly damaged file
    was decoded with its unreadable parts replaced by silence. ``offset`` skips
    that many seconds from the start before reading.
    """
    try:
        if sr is not None and (type(sr) is not int or sr <= 0):
            raise ValueError('Sample rate must be a positive integer')
        if duration is not None and (not math.isfinite(duration) or duration <= 0):
            raise ValueError('Duration must be finite and positive')
        if not math.isfinite(offset) or offset < 0:
            raise ValueError('Offset must be finite and non-negative')
        with _source(source) as handle:
            if force_ffmpeg:
                data, rate = _decode_ffmpeg(handle, duration, on_warning, offset)
            else:
                try:
                    import soundfile as sf

                    with sf.SoundFile(handle) as audio:
                        rate = int(audio.samplerate)
                        if offset > 0:
                            audio.seek(int(offset * rate))
                        frames = -1 if duration is None else int(duration * rate)
                        data = audio.read(frames=frames, dtype='float32', always_2d=False).T
                    if data.size == 0:
                        raise ValueError('Empty audio data')
                except Exception:
                    data, rate = _decode_ffmpeg(handle, duration, on_warning, offset)
            if data.size == 0:
                raise ValueError('Empty audio data')
            if duration is None and offset == 0 and isinstance(handle, str):
                # dtype='float32' is honoured, as for the return below.
                _seed_peaks(handle, cast("NDArray[np.float32]", data), rate)
            if sr is not None and sr != rate:
                import librosa

                data = librosa.resample(
                    data, orig_sr=rate, target_sr=sr, res_type=res_type, axis=-1
                )
                rate = sr
            return cast("NDArray[np.float32]", data), rate
    except Exception as exc:
        raise AudioDecodeError(f'Cannot decode audio: {exc}') from exc
