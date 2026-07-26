"""Sample-clip generation when model sample mode is enabled."""

from __future__ import annotations

import hashlib
import os
from typing import Callable, List, Optional, Sequence

from . import paths
from .debug_log import debug
from .settings import SettingsModel

FallbackCallback = Callable[[str, Exception], None]


def _clip_cache_path(source: str, duration: int) -> str:
    base = os.path.basename(source)
    digest = hashlib.md5(f"{source}:{duration}".encode(), usedforsecurity=False).hexdigest()[:12]
    stem, ext = os.path.splitext(base)
    return os.path.join(paths.SAMPLE_CLIP_PATH, f"{stem}_{duration}s_{digest}{ext or '.wav'}")


def prepare_input_paths(
    settings: SettingsModel,
    input_paths: Sequence[str],
    *,
    on_fallback: Optional[FallbackCallback] = None,
) -> List[str]:
    """Return paths to process, using cached sample clips when sample mode is on.

    When clip generation fails for a file, the original path is used and
    ``on_fallback`` is invoked (if provided) so callers can surface the
    fallback instead of silently turning a preview into a full-length run.
    """
    if not settings.get("model_sample_mode"):
        return list(input_paths)

    duration = max(1, int(settings.get("model_sample_mode_duration", 30) or 30))
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

        debug("model", f"sample clip generating file={os.path.basename(path)!r} duration={duration}s")
        try:
            import librosa
            import soundfile as sf

            audio, sr = librosa.load(path, mono=False, sr=None, duration=duration)
            sample_rate = int(sr)
            if audio.ndim == 1:
                sf.write(clip_path, audio, sample_rate)
            else:
                sf.write(clip_path, audio.T, sample_rate)
            prepared.append(clip_path)
        except Exception as exc:  # noqa: BLE001 - reported via on_fallback
            debug(
                "model",
                f"sample clip fallback to full file={os.path.basename(path)!r} "
                f"error={type(exc).__name__}: {exc}",
            )
            if on_fallback is not None:
                on_fallback(path, exc)
            prepared.append(path)
    return prepared
