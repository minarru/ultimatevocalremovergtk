"""Sample-clip generation when model sample mode is enabled."""

from __future__ import annotations

import hashlib
import os
import tempfile
from typing import Callable, List, Optional, Sequence

from . import paths
from .debug_log import debug
from .settings import Settings

FallbackCallback = Callable[[str, Exception], None]


def _clip_cache_path(source: str, duration: int) -> str:
    base = os.path.basename(source)
    digest = hashlib.md5(f"{source}:{duration}".encode(), usedforsecurity=False).hexdigest()[:12]
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

        clip_path = _clip_cache_path(path, duration)
        if os.path.isfile(clip_path):
            debug("model", f"sample clip cache hit file={os.path.basename(path)!r}")
            prepared.append(clip_path)
            continue

        debug(
            "model", f"sample clip generating file={os.path.basename(path)!r} duration={duration}s"
        )
        temporary_path: str | None = None
        try:
            import soundfile as sf

            from .audio_decode import load_audio

            audio, sr = load_audio(path, duration=duration)
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
