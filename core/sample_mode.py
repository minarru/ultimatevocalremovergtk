"""Sample-clip generation when model sample mode is enabled."""

from __future__ import annotations

import hashlib
import os
import tempfile
from typing import Callable, Iterable, List, Mapping, Optional, Sequence

from . import paths
from .debug_log import debug
from .settings import Settings

FallbackCallback = Callable[[str, Exception], None]


def sample_start(starts: Mapping[str, float], path: str) -> float:
    """Seconds into ``path`` where its sample starts; 0.0 when none was chosen."""
    return max(0.0, float(starts.get(os.path.abspath(path), 0.0)))


def has_custom_start(starts: Mapping[str, float], paths: Iterable[str]) -> bool:
    return any(sample_start(starts, path) > 0 for path in paths)


def prune_sample_starts(starts: Mapping[str, float], paths: Iterable[str]) -> dict[str, float]:
    """Only the starts of ``paths``; files no longer in the input list are dropped."""
    keep = {os.path.abspath(path) for path in paths}
    return {path: start for path, start in starts.items() if path in keep}


def _clip_cache_path(source: str, duration: int, start: float = 0.0) -> str:
    base = os.path.basename(source)
    # A start of 0 keeps the key every earlier clip was cached under.
    key = f"{source}:{duration}" if start == 0 else f"{source}:{duration}:{start:.3f}"
    digest = hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()[:12]
    stem, _ext = os.path.splitext(base)
    return os.path.join(paths.SAMPLE_CLIP_PATH, f"{stem}_{duration}s_v2_{digest}.wav")


def prepare_input_paths(
    settings: Settings,
    input_paths: Sequence[str],
    *,
    on_fallback: Optional[FallbackCallback] = None,
) -> List[str]:
    """Return paths to process, using cached sample clips when sample mode is on.

    When clip generation fails for a file, the original path is used and
    ``on_fallback`` is invoked (if provided) so callers can surface the
    fallback instead of silently turning a preview into a full-length run.
    """
    if not settings.process.sample_mode:
        return list(input_paths)

    duration = max(1, int(settings.process.sample_mode_duration or 30))
    os.makedirs(paths.SAMPLE_CLIP_PATH, exist_ok=True)

    prepared: List[str] = []
    for path in input_paths:
        if not os.path.isfile(path):
            prepared.append(path)
            continue

        start = sample_start(settings.process.sample_starts, path)
        if start > 0:
            from .audio_probe import audio_duration_seconds

            # Pull the start back so the whole sample fits before the end of the file.
            total = audio_duration_seconds(path)
            if total is not None:
                start = max(0.0, min(start, total - duration))

        clip_path = _clip_cache_path(path, duration, start)
        if os.path.isfile(clip_path):
            debug(
                "model",
                f"sample clip cache hit file={os.path.basename(path)!r} start={start:.3f}s",
            )
            prepared.append(clip_path)
            continue

        debug(
            "model",
            f"sample clip generating file={os.path.basename(path)!r} "
            f"duration={duration}s start={start:.3f}s",
        )
        temporary_path: str | None = None
        try:
            import soundfile as sf

            from .audio_decode import load_audio

            audio, sr = load_audio(path, duration=duration, offset=start)
            with tempfile.NamedTemporaryFile(
                dir=paths.SAMPLE_CLIP_PATH, prefix=".sample-", suffix=".wav", delete=False
            ) as temporary:
                temporary_path = temporary.name
            sf.write(temporary_path, audio.T, int(sr), format="WAV", subtype="FLOAT")
            os.replace(temporary_path, clip_path)
            temporary_path = None
            prepared.append(clip_path)
        except Exception as exc:  # reported via on_fallback
            debug(
                "model",
                f"sample clip fallback to full file={os.path.basename(path)!r} "
                f"error={type(exc).__name__}: {exc}",
            )
            if on_fallback is not None:
                on_fallback(path, exc)
            prepared.append(path)
        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass
    return prepared
