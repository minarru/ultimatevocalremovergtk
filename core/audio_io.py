"""Shared audio export helpers for separation and audio tools."""

import os

from bundled.constants import WAV

from .settings import SettingsModel


def resolve_wav_type_set(settings: SettingsModel) -> str:
    """Reproduce ``MainWindow.process_check_wav_type``."""
    wav_type = settings.get("wav_type_set")
    save_format_sel = settings.get("save_format")
    if wav_type == "32-bit Float":
        return "FLOAT"
    if wav_type == "64-bit Float":
        return "FLOAT" if save_format_sel != WAV else "DOUBLE"
    return wav_type


def flac_export_parameters(flac_bit_set: str) -> list[str]:
    """Return ffmpeg ``-sample_fmt`` parameters for FLAC export via pydub."""
    if flac_bit_set == "24-bit":
        return ["-sample_fmt", "s24"]
    return ["-sample_fmt", "s16"]


def save_format(
    audio_path: str,
    save_format_sel: str,
    mp3_bit_set: str,
    flac_bit_set: str = "16-bit",
) -> None:
    """Torch-free port of ``separate.save_format``.

    FLAC prefers a direct libsndfile rewrite; MP3 still goes through ``pydub``
    so bitrate strings stay exact. Intermediate WAV is removed on success.
    """
    from bundled.constants import FLAC, MP3

    if save_format_sel == WAV:
        return

    from .debug_log import debug

    if save_format_sel == FLAC and audio_path.lower().endswith(".wav"):
        try:
            import soundfile as sf

            data, samplerate = sf.read(audio_path, always_2d=False)
            flac_path = audio_path[:-4] + ".flac"
            subtype = "PCM_24" if flac_bit_set == "24-bit" else "PCM_16"
            sf.write(flac_path, data, samplerate, format="FLAC", subtype=subtype)
            try:
                os.remove(audio_path)
            except OSError as exc:
                debug(
                    "audio",
                    f"export cleanup failed file={os.path.basename(audio_path)} "
                    f"error={type(exc).__name__}: {exc}",
                )
            return
        except Exception as exc:  # noqa: BLE001 - fall through to pydub
            debug(
                "audio",
                f"direct flac export failed file={os.path.basename(audio_path)} "
                f"error={type(exc).__name__}: {exc}; falling back to pydub",
            )

    from pydub import AudioSegment

    from .external_tools import configure_pydub_ffmpeg

    if configure_pydub_ffmpeg() is None:
        debug(
            "audio",
            f"export failed format={save_format_sel} file={os.path.basename(audio_path)} reason=ffmpeg_missing",
        )
        return

    try:
        audio_segment = AudioSegment.from_wav(audio_path)
    except Exception as exc:  # noqa: BLE001 - surfaced via missing output file
        debug(
            "audio",
            f"export failed format={save_format_sel} file={os.path.basename(audio_path)} "
            f"error={type(exc).__name__}: {exc}",
        )
        return

    try:
        if save_format_sel == FLAC:
            audio_segment.export(
                audio_path.replace(".wav", ".flac"),
                format="flac",
                parameters=flac_export_parameters(flac_bit_set),
            )
        elif save_format_sel == MP3:
            mp3_path = audio_path.replace(".wav", ".mp3")
            try:
                audio_segment.export(mp3_path, format="mp3", bitrate=mp3_bit_set, codec="libmp3lame")
            except Exception:  # noqa: BLE001 - fall back to default codec like UVR
                audio_segment.export(mp3_path, format="mp3", bitrate=mp3_bit_set)
    except Exception as exc:  # noqa: BLE001 - surfaced via missing output file
        debug(
            "audio",
            f"export failed format={save_format_sel} file={os.path.basename(audio_path)} "
            f"error={type(exc).__name__}: {exc}",
        )
        return

    try:
        os.remove(audio_path)
    except OSError as exc:
        debug(
            "audio",
            f"export cleanup failed file={os.path.basename(audio_path)} error={type(exc).__name__}: {exc}",
        )
