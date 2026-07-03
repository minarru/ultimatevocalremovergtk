"""Sample-clip generation when model sample mode is enabled."""

import hashlib
import os
from typing import List, Sequence

from . import paths
from .debug_log import debug
from .settings import SettingsModel


def _clip_cache_path(source: str, duration: int) -> str:
    base = os.path.basename(source)
    digest = hashlib.md5(f"{source}:{duration}".encode(), usedforsecurity=False).hexdigest()[:12]
    stem, ext = os.path.splitext(base)
    return os.path.join(paths.SAMPLE_CLIP_PATH, f"{stem}_{duration}s_{digest}{ext or '.wav'}")


def prepare_input_paths(settings: SettingsModel, input_paths: Sequence[str]) -> List[str]:
    """Return paths to process, using cached sample clips when sample mode is on."""
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
        except Exception:
            debug("model", f"sample clip fallback to full file={os.path.basename(path)!r}")
            prepared.append(path)
    return prepared
