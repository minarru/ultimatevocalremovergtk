"""Shared audio export helpers for separation and audio tools."""

import os
from pathlib import Path

from bundled.constants import WAV

from .settings import Settings
from .settings.coerce import enum_value


class AudioExportError(RuntimeError):
    """A requested audio artifact could not be produced."""


def resolve_wav_type_set(settings: Settings) -> str:
    """Reproduce ``MainWindow.process_check_wav_type``."""
    wav_type = enum_value(settings.process.wav_type)
    save_format_sel = settings.process.save_format
    if wav_type == "32-bit Float":
        return "FLOAT"
    if wav_type == "64-bit Float":
        return "FLOAT" if save_format_sel != WAV else "DOUBLE"
    return str(wav_type)


def flac_export_parameters(flac_bit_set: str) -> list[str]:
    """Return ffmpeg ``-sample_fmt`` parameters for FLAC export via pydub."""
    if flac_bit_set == "24-bit":
        return ["-sample_fmt", "s24"]
    return ["-sample_fmt", "s16"]


def flac_subtype(flac_bit_set: str) -> str:
    """libsndfile subtype for FLAC bit depth."""
    return "PCM_24" if flac_bit_set == "24-bit" else "PCM_16"


def replace_audio_suffix(path: str, new_suffix: str) -> str:
    """Replace a ``.wav`` suffix (any case) or append ``new_suffix`` otherwise.

    ``new_suffix`` should include the leading dot (e.g. ``.flac`` / ``.mp3``).
    """
    p = Path(path)
    if p.suffix.lower() == ".wav":
        return str(p.with_suffix(new_suffix))
    if path.lower().endswith(new_suffix.lower()):
        return path
    return f"{path}{new_suffix}"


def opus_export_parameters() -> list[str]:
    """Return ffmpeg parameters for Opus export via pydub.

    Opus cannot encode 44.1 kHz; ``-ar 48000`` makes the resample explicit.
    ``-vbr on`` is libopus's default; the pydub ``bitrate`` is a target.
    """
    return ["-application", "audio", "-vbr", "on", "-ar", "48000"]


def save_format(
    audio_path: str,
    save_format_sel: str,
    mp3_bit_set: str,
    flac_bit_set: str = "16-bit",
    opus_bit_set: str = "192k",
) -> str:
    """Torch-free port of ``separate.save_format``.

    FLAC prefers a direct libsndfile rewrite; MP3 and Opus still go through
    ``pydub`` so bitrate strings stay exact. Intermediate WAV is removed on
    success.
    """
    from bundled.constants import FLAC, MP3, OPUS

    if not os.path.isfile(audio_path):
        raise AudioExportError(f"Source audio export is missing: {audio_path}")

    if save_format_sel == WAV:
        return audio_path

    if save_format_sel not in (FLAC, MP3, OPUS):
        raise AudioExportError(f"Unsupported audio export format: {save_format_sel!r}")

    from .debug_log import debug

    if save_format_sel == FLAC and audio_path.lower().endswith(".wav"):
        try:
            import soundfile as sf

            data, samplerate = sf.read(audio_path, always_2d=False)
            flac_path = replace_audio_suffix(audio_path, ".flac")
            sf.write(
                flac_path,
                data,
                samplerate,
                format="FLAC",
                subtype=flac_subtype(flac_bit_set),
            )
            if not os.path.isfile(flac_path):
                raise AudioExportError(f"FLAC export was not created: {flac_path}")
            try:
                os.remove(audio_path)
            except OSError as exc:
                debug(
                    "audio",
                    f"export cleanup failed file={os.path.basename(audio_path)} "
                    f"error={type(exc).__name__}: {exc}",
                )
            return flac_path
        except Exception as exc:  # fall through to pydub
            debug(
                "audio",
                f"direct flac export failed file={os.path.basename(audio_path)} "
                f"error={type(exc).__name__}: {exc}; falling back to pydub",
            )

    from pydub import AudioSegment

    from .external_tools import configure_pydub_ffmpeg

    if configure_pydub_ffmpeg() is None:
        message = (
            f"Audio export failed for {os.path.basename(audio_path)!r}: "
            f"ffmpeg is required for {save_format_sel}"
        )
        debug("audio", message)
        raise AudioExportError(message)

    try:
        audio_segment = AudioSegment.from_wav(audio_path)
    except Exception as exc:  # surfaced via missing output file
        message = (
            f"Audio export failed while reading {os.path.basename(audio_path)!r}: "
            f"{type(exc).__name__}: {exc}"
        )
        debug("audio", message)
        raise AudioExportError(message) from exc

    suffixes = {FLAC: ".flac", MP3: ".mp3", OPUS: ".opus"}
    output_path = replace_audio_suffix(audio_path, suffixes[save_format_sel])
    try:
        if save_format_sel == FLAC:
            audio_segment.export(
                output_path,
                format="flac",
                parameters=flac_export_parameters(flac_bit_set),
            )
        elif save_format_sel == MP3:
            try:
                audio_segment.export(
                    output_path,
                    format="mp3",
                    bitrate=mp3_bit_set,
                    codec="libmp3lame",
                )
            except Exception:  # fall back to default codec like UVR
                audio_segment.export(output_path, format="mp3", bitrate=mp3_bit_set)
        elif save_format_sel == OPUS:
            audio_segment.export(
                output_path,
                format="opus",
                bitrate=enum_value(opus_bit_set),
                codec="libopus",
                parameters=opus_export_parameters(),
            )
    except Exception as exc:  # surfaced via missing output file
        message = (
            f"Audio export failed for {os.path.basename(audio_path)!r} as {save_format_sel}: "
            f"{type(exc).__name__}: {exc}"
        )
        debug("audio", message)
        raise AudioExportError(message) from exc

    if not os.path.isfile(output_path):
        raise AudioExportError(f"Converted audio export was not created: {output_path}")

    try:
        os.remove(audio_path)
    except OSError as exc:
        debug(
            "audio",
            f"export cleanup failed file={os.path.basename(audio_path)} error={type(exc).__name__}: {exc}",
        )
    return output_path
