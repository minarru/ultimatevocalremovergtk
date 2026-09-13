"""Small manifest, persistence, and audio validation primitives."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

Progress = Callable[[str, dict[str, Any]], None]
GROUPS = {'pair': ('vocals', 'instrumental'), 'four': ('vocals', 'drums', 'bass', 'other')}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _invalid_constant(value: str) -> NoReturn:
    raise ValueError(f'Invalid JSON constant: {value}')


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f'Non-finite JSON number: {value}')
    return number


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def read_json(path: Path, kind: str | None = None) -> dict[str, Any]:
    try:
        data = json.loads(
            path.read_text(),
            parse_constant=_invalid_constant,
            parse_float=_finite_float,
            object_pairs_hook=_unique_object,
        )
    except (OSError, ValueError) as exc:
        raise ValueError(f'Cannot read manifest {path}: {exc}') from exc
    if not isinstance(data, dict):
        raise ValueError(f'Manifest must be an object: {path}')
    if kind is not None and (data.get('kind') != kind or data.get('schema_version') != 1):
        raise ValueError(f'Expected schema_version=1, kind={kind}: {path}')
    return data


def write_json(path: Path, data: dict[str, Any], *, replace: bool = True) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(text)
        if replace:
            os.replace(tmp, path)
        else:
            os.link(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def text_field(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{key} must be a nonempty string')
    return value


def records(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = data.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(x, dict) for x in value):
        raise ValueError(f'{key} must be a nonempty list of objects')
    return value


def resolve_path(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def metric(value: float | None = None, status: str | None = None) -> dict[str, Any]:
    if status:
        return {'value': None, 'status': status}
    if value is None or math.isnan(value):
        return {'value': None, 'status': 'undefined'}
    if math.isinf(value):
        return {'value': None, 'status': 'positive_infinity' if value > 0 else 'negative_infinity'}
    return {'value': float(value), 'status': 'finite'}


def energy_ratio(signal: float, error: float) -> dict[str, Any]:
    if signal == 0 and error == 0:
        return metric(status='undefined')
    if signal == 0:
        return metric(float('-inf'))
    if error == 0:
        return metric(float('inf'))
    return metric(10 * (math.log10(signal) - math.log10(error)))


def audio_info(path: Path) -> dict[str, Any]:
    import soundfile as sf

    try:
        info = sf.info(str(path))
    except (OSError, RuntimeError) as exc:
        raise ValueError(f'Cannot read audio {path}: {exc}') from exc
    if info.frames <= 0 or info.channels <= 0 or info.samplerate <= 0:
        raise ValueError(f'Empty or invalid audio: {path}')
    return {'frames': info.frames, 'channels': info.channels, 'sample_rate': info.samplerate}


def require_same_audio(a: dict[str, Any], b: dict[str, Any]) -> None:
    for key in ('sample_rate', 'channels', 'frames'):
        if a[key] != b[key]:
            raise ValueError(
                f'Audio {key} mismatch: {a[key]} != {b[key]}; scoring never resamples, aligns, or truncates'
            )


def progress(callback: Progress | None, phase: str, **values: Any) -> None:
    if callback:
        callback(phase, values)


def file_signature(path: Path) -> tuple[int, int, int, int, int]:
    """Detect inputs replaced or modified across multi-pass evaluation."""
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
