"""Audio export format conversion."""
import os

import pydub
from bundled.constants import FLAC, MP3, WAV


def save_format(audio_path, save_format, mp3_bit_set, flac_bit_set="16-bit"):
    from core.debug_log import debug

    if save_format == WAV:
        return

    from core.external_tools import configure_pydub_ffmpeg

    if configure_pydub_ffmpeg() is None:
        debug(
            "audio",
            f"export failed format={save_format} file={os.path.basename(audio_path)} reason=ffmpeg_missing",
        )
        return

    try:
        musfile = pydub.AudioSegment.from_wav(audio_path)
    except Exception as exc:  # noqa: BLE001 - surfaced via missing output file
        debug(
            "audio",
            f"export failed format={save_format} file={os.path.basename(audio_path)} "
            f"error={type(exc).__name__}: {exc}",
        )
        return

    try:
        if save_format == FLAC:
            audio_path_flac = audio_path.replace(".wav", ".flac")
            from core.audio_io import flac_export_parameters

            musfile.export(
                audio_path_flac,
                format="flac",
                parameters=flac_export_parameters(flac_bit_set),
            )

        if save_format == MP3:
            audio_path_mp3 = audio_path.replace(".wav", ".mp3")
            try:
                musfile.export(audio_path_mp3, format="mp3", bitrate=mp3_bit_set, codec="libmp3lame")
            except Exception:  # noqa: BLE001 - fall back to default codec like UVR
                musfile.export(audio_path_mp3, format="mp3", bitrate=mp3_bit_set)
    except Exception as exc:  # noqa: BLE001 - surfaced via missing output file
        debug(
            "audio",
            f"export failed format={save_format} file={os.path.basename(audio_path)} "
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
