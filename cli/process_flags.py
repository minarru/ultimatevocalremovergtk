"""Process flags shared by ``separate`` and ``ensemble``.

Every named flag compiles to a ``(settings path, value)`` pair. Named flags and
``--set`` therefore share the typed ``SettingsResolver`` path, with ``--set``
remaining the final CLI layer.
"""

from __future__ import annotations

import argparse
from typing import Any, Optional, Sequence

from core.settings.coerce import enum_value
from core.settings.access import parse_setting_assignment
from core.types import FlacBitDepth, Mp3Bitrate, SaveFormat, WavType

# dest -> settings path for symmetric BooleanOptionalAction flags.
_BOOL_FLAG_PATHS: dict[str, str] = {
    "autocast": "process.autocast",
    "normalize": "process.normalization",
    "match_mix": "process.match_mix_level",
    "sample": "process.sample_mode",
    "save_split_inst": "process.save_inst_vocal_splitter",
    "model_folders": "process.create_model_folder",
    "include_model_name": "process.add_model_name",
}

# dest -> settings path, for flags whose value is written straight through
_VALUE_FLAG_PATHS: dict[str, str] = {
    "format": "process.save_format",
    "wav_type": "process.wav_type",
    "mp3_bitrate": "process.mp3_bitrate",
    "flac_depth": "process.flac_bit_depth",
    "sample_seconds": "process.sample_mode_duration",
}


def add_process_args(parser: argparse.ArgumentParser) -> None:
    """Attach the shared process flags to a subcommand parser."""
    performance = parser.add_argument_group("Performance")
    performance.add_argument(
        "--autocast",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable autocast (UVR_AUTOCAST still wins)",
    )
    performance.add_argument(
        "--device",
        default=None,
        metavar="ID",
        help="auto, cpu, cuda:N, mps, or directml:N (default: auto)",
    )
    output = parser.add_argument_group("Output format")
    output.add_argument(
        "--format",
        type=str.upper,
        choices=[fmt.value for fmt in SaveFormat],
        default=None,
        help="Export format (case-insensitive)",
    )
    output.add_argument(
        "--wav-type",
        choices=[wav.value for wav in WavType],
        default=None,
        help="WAV sample format",
    )
    output.add_argument(
        "--mp3-bitrate",
        choices=[rate.value for rate in Mp3Bitrate],
        default=None,
        help="MP3 bitrate",
    )
    output.add_argument(
        "--flac-depth",
        choices=[depth.value for depth in FlacBitDepth],
        default=None,
        help="FLAC bit depth",
    )
    output.add_argument(
        "--model-folders",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Place outputs in per-model folders",
    )
    output.add_argument(
        "--include-model-name",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Include the canonical model label in output filenames",
    )
    post = parser.add_argument_group("Post-processing")
    post.add_argument(
        "--normalize", action=argparse.BooleanOptionalAction, default=None,
        help="Enable or disable output normalization"
    )
    post.add_argument(
        "--match-mix", action=argparse.BooleanOptionalAction, default=None,
        help="Enable or disable mix-level matching"
    )
    performance.add_argument(
        "--sample", action=argparse.BooleanOptionalAction, default=None,
        help="Enable or disable sample mode"
    )
    performance.add_argument(
        "--sample-seconds",
        type=int,
        default=None,
        metavar="N",
        help="Sample-mode duration in seconds",
    )

    split_group = post.add_mutually_exclusive_group()
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
    post.add_argument(
        "--save-split-inst",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable saving the splitter instrumental",
    )

    advanced = parser.add_argument_group("Advanced settings")
    advanced.add_argument(
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

    for dest, path in _BOOL_FLAG_PATHS.items():
        value = getattr(args, dest, None)
        if value is not None:
            overrides.append((path, bool(value)))

    if getattr(args, "no_vocal_split", False):
        overrides.append(("process.vocal_splitter_enabled", False))

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
        if getattr(args, "sample", None) is not True:
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
