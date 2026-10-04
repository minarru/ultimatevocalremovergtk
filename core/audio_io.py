"""Shared audio export helpers for separation and audio tools."""

import os
import subprocess
import tempfile
from pathlib import Path

from bundled.constants import WAV

from .external_tools import resolve_ffmpeg
from .settings import Settings
from .settings.coerce import enum_value

# Frames per block when re-encoding a WAV to FLAC; float64 stereo is 1 MB.
_EXPORT_BLOCK_FRAMES = 1 << 16
_STDERR_TAIL_LINES = 3


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
    """Return ffmpeg ``-sample_fmt`` parameters for FLAC export via ffmpeg."""
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
    """Return ffmpeg parameters for Opus export.

    Opus cannot encode 44.1 kHz; ``-ar 48000`` makes the resample explicit.
    ``-vbr on`` is libopus's default; the ``-b:a`` bitrate is a target.
    """
    return ["-application", "audio", "-vbr", "on", "-ar", "48000"]


def _temporary_sibling(path: str) -> str:
    """A unique temporary path next to ``path``, renamed into place on success."""
    directory, name = os.path.split(path)
    handle, temporary = tempfile.mkstemp(
        dir=directory or ".", prefix=f".{name}.", suffix=Path(path).suffix
    )
    os.close(handle)
    return temporary


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _stream_flac(audio_path: str, flac_bit_set: str) -> str:
    """Re-encode a WAV as FLAC block by block instead of loading it whole.

    Blocks are float64, exactly what the previous whole-file ``sf.read`` used,
    so libsndfile's PCM conversion (and the output) is unchanged.
    """
    import soundfile as sf

    flac_path = replace_audio_suffix(audio_path, ".flac")
    temporary = _temporary_sibling(flac_path)
    try:
        with sf.SoundFile(audio_path) as source:
            with sf.SoundFile(
                temporary,
                "w",
                samplerate=source.samplerate,
                channels=source.channels,
                format="FLAC",
                subtype=flac_subtype(flac_bit_set),
            ) as destination:
                for block in source.blocks(blocksize=_EXPORT_BLOCK_FRAMES, dtype="float64"):
                    destination.write(block)
        os.replace(temporary, flac_path)
    except BaseException:
        _remove_quietly(temporary)
        raise
    return flac_path


def _ffmpeg_encode(
    executable: str, audio_path: str, output_path: str, container: str, arguments: list[str]
) -> None:
    """Encode the WAV straight to ``output_path``.

    Arguments keep the order of the pydub export this replaces, which loaded
    the whole WAV into memory and wrote it to a second temporary WAV before
    running the same ffmpeg command.
    """
    temporary = _temporary_sibling(output_path)
    command = [executable, "-nostdin", "-y", "-v", "error", "-f", "wav", "-i", audio_path]
    command += [*arguments, "-f", container, temporary]
    try:
        completed = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True)
        if completed.returncode:
            lines = completed.stderr.decode("utf-8", errors="replace").strip().splitlines()
            detail = "\n".join(lines[-_STDERR_TAIL_LINES:])
            raise AudioExportError(
                f"ffmpeg exited with status {completed.returncode} while writing "
                f"{os.path.basename(output_path)!r}: {detail}"
            )
        os.replace(temporary, output_path)
    except BaseException:
        _remove_quietly(temporary)
        raise


def save_format(
    audio_path: str,
    save_format_sel: str,
    mp3_bit_set: str,
    flac_bit_set: str = "16-bit",
    opus_bit_set: str = "192k",
) -> str:
    """Convert an exported WAV to the configured format and remove the WAV.

    FLAC is re-encoded block by block with libsndfile; MP3, Opus and the FLAC
    fallback run ffmpeg directly on the WAV. Outputs are written to a temporary
    sibling and renamed, so a failed export never leaves a partial file, and
    the WAV is removed only on success.
    """
    from bundled.constants import FLAC, MP3, OPUS

    if not os.path.isfile(audio_path):
        raise AudioExportError(f"Source audio export is missing: {audio_path}")

    if save_format_sel == WAV:
        return audio_path

    if save_format_sel not in (FLAC, MP3, OPUS):
        raise AudioExportError(f"Unsupported audio export format: {save_format_sel!r}")

    from .debug_log import debug

    output_path: str | None = None
    if save_format_sel == FLAC and audio_path.lower().endswith(".wav"):
        try:
            output_path = _stream_flac(audio_path, flac_bit_set)
        except Exception as exc:  # fall through to ffmpeg
            debug(
                "audio",
                f"direct flac export failed file={os.path.basename(audio_path)} "
                f"error={type(exc).__name__}: {exc}; falling back to ffmpeg",
            )

    if output_path is None:
        executable = resolve_ffmpeg()
        if not executable:
            message = (
                f"Audio export failed for {os.path.basename(audio_path)!r}: "
                f"ffmpeg is required for {save_format_sel}"
            )
            debug("audio", message)
            raise AudioExportError(message)

        if save_format_sel == FLAC:
            container, attempts = "flac", [flac_export_parameters(flac_bit_set)]
        elif save_format_sel == MP3:
            # Fall back to ffmpeg's default MP3 encoder like UVR.
            container = "mp3"
            attempts = [
                ["-acodec", "libmp3lame", "-b:a", mp3_bit_set],
                ["-b:a", mp3_bit_set],
            ]
        else:
            container = "opus"
            attempts = [
                ["-acodec", "libopus", "-b:a", str(enum_value(opus_bit_set))]
                + opus_export_parameters()
            ]
        suffixes = {FLAC: ".flac", MP3: ".mp3", OPUS: ".opus"}
        output_path = replace_audio_suffix(audio_path, suffixes[save_format_sel])
        for index, arguments in enumerate(attempts):
            try:
                _ffmpeg_encode(executable, audio_path, output_path, container, arguments)
                break
            except (AudioExportError, OSError) as exc:
                message = (
                    f"Audio export failed for {os.path.basename(audio_path)!r} as "
                    f"{save_format_sel}: {exc}"
                )
                debug("audio", message)
                if index == len(attempts) - 1:
                    raise AudioExportError(message) from exc

    if not os.path.isfile(output_path):
        raise AudioExportError(f"Converted audio export was not created: {output_path}")

    if save_format_sel != FLAC:
        # Lossy files decode slowly; read the waveform from the WAV while it still exists.
        from .waveform import compute_peaks, offer_peaks

        offer_peaks(output_path, lambda: compute_peaks(audio_path))

    try:
        os.remove(audio_path)
    except OSError as exc:
        debug(
            "audio",
            f"export cleanup failed file={os.path.basename(audio_path)} error={type(exc).__name__}: {exc}",
        )
    return output_path
