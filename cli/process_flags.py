"""Process flags shared by ``separate`` and ``ensemble``.

Every named flag compiles to a ``(settings path, value)`` pair rather than a
``build_settings`` keyword argument, so named flags and ``--set`` share one
validation path (``core.settings.access.apply_settings_overrides``) and
``build_settings`` keeps a small signature.
"""

from __future__ import annotations

import argparse
from typing import Any, Optional, Sequence

from core.settings.coerce import enum_value
from core.settings.access import parse_setting_assignment
from core.types import FlacBitDepth, Mp3Bitrate, SaveFormat, WavType

# dest -> (settings path, value written when the flag is present)
_BOOL_FLAG_PATHS: dict[str, tuple[str, Any]] = {
    "cpu": ("process.use_gpu", False),
    "gpu": ("process.use_gpu", True),
    "autocast": ("process.autocast", True),
    "no_autocast": ("process.autocast", False),
    "normalize": ("process.normalization", True),
    "match_mix": ("process.match_mix_level", True),
    "sample": ("process.sample_mode", True),
    "save_split_inst": ("process.save_inst_vocal_splitter", True),
    "no_vocal_split": ("process.vocal_splitter_enabled", False),
}

# dest -> settings path, for flags whose value is written straight through
_VALUE_FLAG_PATHS: dict[str, str] = {
    "format": "process.save_format",
    "wav_type": "process.wav_type",
    "mp3_bitrate": "process.mp3_bitrate",
    "flac_depth": "process.flac_bit_depth",
    "device": "process.device",
    "sample_seconds": "process.sample_mode_duration",
}


def add_process_args(parser: argparse.ArgumentParser) -> None:
    """Attach the shared process flags to a subcommand parser."""
    gpu_group = parser.add_mutually_exclusive_group()
    gpu_group.add_argument(
        "--cpu", action="store_true", help="Force CPU (process.use_gpu=False)"
    )
    gpu_group.add_argument(
        "--gpu", action="store_true", help="Force GPU (process.use_gpu=True)"
    )

    autocast_group = parser.add_mutually_exclusive_group()
    autocast_group.add_argument(
        "--autocast", action="store_true", help="Enable autocast (UVR_AUTOCAST still wins)"
    )
    autocast_group.add_argument(
        "--no-autocast", action="store_true", help="Disable autocast"
    )

    parser.add_argument(
        "--device",
        default=None,
        metavar="ID",
        help="GPU device id from list_gpu_devices (e.g. 0, mps, directml)",
    )
    parser.add_argument(
        "--format",
        type=str.upper,
        choices=[fmt.value for fmt in SaveFormat],
        default=None,
        help="Export format (case-insensitive)",
    )
    parser.add_argument(
        "--wav-type",
        choices=[wav.value for wav in WavType],
        default=None,
        help="WAV sample format",
    )
    parser.add_argument(
        "--mp3-bitrate",
        choices=[rate.value for rate in Mp3Bitrate],
        default=None,
        help="MP3 bitrate",
    )
    parser.add_argument(
        "--flac-depth",
        choices=[depth.value for depth in FlacBitDepth],
        default=None,
        help="FLAC bit depth",
    )
    parser.add_argument(
        "--normalize", action="store_true", help="Normalize outputs"
    )
    parser.add_argument(
        "--match-mix", action="store_true", help="Match the mix level"
    )
    parser.add_argument(
        "--sample", action="store_true", help="Sample mode (short excerpt only)"
    )
    parser.add_argument(
        "--sample-seconds",
        type=int,
        default=None,
        metavar="N",
        help="Sample-mode duration in seconds",
    )

    split_group = parser.add_mutually_exclusive_group()
    split_group.add_argument(
        "--vocal-split",
        default=None,
        metavar="MODEL",
        help=(
            "Enable the vocal splitter with this karaoke/BV model. The value is "
            "required — `--vocal-split MODEL`, never a bare flag."
        ),
    )
    split_group.add_argument(
        "--no-vocal-split",
        action="store_true",
        help="Disable the vocal splitter for this run",
    )
    parser.add_argument(
        "--save-split-inst",
        action="store_true",
        help="Also save the vocal splitter's instrumental",
    )

    parser.add_argument(
        "--set",
        action="append",
        default=None,
        dest="set_items",
        metavar="section.field=value",
        help=(
            "Escape hatch for any typed setting; repeatable. Applied after the "
            "named flags above, so a later --set wins."
        ),
    )


def collect_overrides(
    args: argparse.Namespace,
    *,
    resolved_vocal_splitter: Optional[str] = None,
) -> list[tuple[str, Any]]:
    """Compile parsed flags into ordered ``(path, value)`` override pairs.

    ``--set`` is appended last so it can override every named flag, including
    the resolved ``--vocal-split`` pair supplied by the command module.
    """
    overrides: list[tuple[str, Any]] = []

    for dest, (path, value) in _BOOL_FLAG_PATHS.items():
        if getattr(args, dest, False):
            overrides.append((path, value))

    for dest, path in _VALUE_FLAG_PATHS.items():
        value = getattr(args, dest, None)
        if value is not None:
            overrides.append((path, value))

    if resolved_vocal_splitter is not None:
        overrides.extend([
            ("process.vocal_splitter", resolved_vocal_splitter),
            ("process.vocal_splitter_enabled", True),
        ])

    if getattr(args, "sample_seconds", None) is not None:
        # Duration without --sample would otherwise be stored and ignored.
        if not getattr(args, "sample", False):
            overrides.append(("process.sample_mode", True))

    for item in getattr(args, "set_items", None) or []:
        overrides.append(parse_setting_assignment(item))

    return overrides


def overrides_to_argv(overrides: Sequence[tuple[str, Any]]) -> list[str]:
    """Serialize override pairs for a ``separate`` subprocess."""
    argv: list[str] = []
    for path, raw_value in overrides:
        value = enum_value(raw_value)
        text = str(value).lower() if isinstance(value, bool) else str(value)
        argv.extend(["--set", f"{path}={text}"])
    return argv
