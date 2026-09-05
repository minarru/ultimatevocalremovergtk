"""Cross-tab file, output and format options synced from typed settings.

Input paths, the export folder, output format, GPU conversion and sample mode
are shared across the Separation, Ensemble and Audio Tools surfaces. Call
:func:`apply_shared_file_options` when a tab becomes active so widgets reflect
the latest in-memory settings without writing spurious changes back. A
:class:`SharedSettingsSession` owns each page's typed edit baselines and commits
only changed fields, preserving newer edits made through another page.
"""

from __future__ import annotations

import os
import typing
from dataclasses import dataclass, replace
from typing import AbstractSet, Callable, Generic, Iterable, Optional, Protocol, Sequence, TypeVar

from bundled.constants import WAV
from core.input_discovery import (
    partition_input_paths,
)
from core.input_discovery import (
    prune_unreadable_paths as prune_unreadable_paths,
)
from core.input_discovery import (
    remove_unreadable_from_paths as remove_unreadable_from_paths,
)
from core.settings import Settings
from core.types import SaveFormat
from core.types.settings_enums import DeverbVocalOpt, FlacBitDepth, Mp3Bitrate, OpusBitrate, WavType

from .protocols import (
    FormatEdit,
    FormatRow,
    InputPathsRow,
    OutputPathRow,
    ReadableFormatRow,
    ReadableInputPathsRow,
    ReadableOutputPathRow,
    ReadableSwitchRow,
    ReadableVocalSplitRow,
    SampleModeRow,
    SwitchRow,
    VocalSplitEdit,
)

INPUT_FILES_WARN = 100
INPUT_FILES_MAX = 500

#: Stable title for the sample-mode switch row (the duration lives in the
#: subtitle so the title stays constant for scanability and screen readers).
SAMPLE_MODE_TITLE = "Sample mode"


def sample_mode_subtitle(duration: int) -> str:
    """Subtitle describing how much audio sample mode processes."""
    return f"Process only the first {int(duration)} s"


def gpu_dependent_enabled(is_gpu_conversion: bool) -> bool:
    """Whether GPU-only options (FP16 autocast, device pick) should be editable.

    ``is_autocast`` wraps CUDA ``torch.autocast`` (see ``engines/amp_runtime.py``)
    and has no effect on CPU runs, so its row is dimmed rather than hidden —
    per the GNOME HIG, an inapplicable control stays discoverable.
    """
    return bool(is_gpu_conversion)


def apply_sample_mode_label(sample_row: typing.Any, duration: int) -> None:
    """Set the stable title + duration subtitle on a sample-mode switch row."""
    sample_row.set_title(SAMPLE_MODE_TITLE)
    if hasattr(sample_row, "set_subtitle"):
        sample_row.set_subtitle(sample_mode_subtitle(duration))


_REASON_OUTPUT_MISSING = "Choose an output folder"
_REASON_OUTPUT_STALE = "Output folder no longer exists — select a new folder"
_REASON_OUTPUT_READONLY = "Output folder is not writable — choose another folder"
_REASON_INPUT_MISSING = "Select an input audio file"
_REASON_UNREADABLE_INPUTS = "Remove unreadable inputs"


@dataclass(frozen=True)
class InputSanitizeResult:
    removed_missing: int = 0
    truncated_count: int = 0
    large_batch: bool = False


def export_path_blocked_reason(path: str) -> Optional[str]:
    """Return a start-blocking message for ``path``, or ``None`` when export is ready."""
    path = (path or "").strip()
    if not path:
        return _REASON_OUTPUT_MISSING
    if not os.path.isdir(path):
        return _REASON_OUTPUT_STALE
    if not os.access(path, os.W_OK):
        return _REASON_OUTPUT_READONLY
    return None


def export_path_is_valid(path: str) -> bool:
    return export_path_blocked_reason(path) is None


def sanitize_input_paths(
    paths: Sequence[str],
    *,
    max_files: int = INPUT_FILES_MAX,
) -> tuple[list[str], InputSanitizeResult]:
    """Dedupe, drop missing files, and enforce the selection cap."""
    existing, missing = partition_input_paths(paths)
    removed_missing = len(missing)
    truncated_count = 0
    if len(existing) > max_files:
        truncated_count = len(existing) - max_files
        existing = existing[:max_files]
    large_batch = len(existing) >= INPUT_FILES_WARN
    return existing, InputSanitizeResult(
        removed_missing=removed_missing,
        truncated_count=truncated_count,
        large_batch=large_batch,
    )


def input_paths_blocked_reason(
    paths: Sequence[str],
    *,
    unreadable_paths: Optional[AbstractSet[str]] = None,
) -> Optional[str]:
    """Return a start-blocking message, or ``None`` when inputs are ready.

    Never-verified selections only require at least one existing file. After
    Verify Inputs marks failures, Start stays blocked while any failed path
    remains in the selection.
    """
    if not paths:
        return _REASON_INPUT_MISSING
    existing = False
    for path in paths:
        if not path:
            continue
        if unreadable_paths and path in unreadable_paths:
            return _REASON_UNREADABLE_INPUTS
        if os.path.isfile(path):
            existing = True
    if not existing:
        return _REASON_INPUT_MISSING
    return None


def format_input_sanitize_toasts(
    result: InputSanitizeResult,
    *,
    include_missing: bool = False,
    include_large_batch: bool = True,
) -> list[str]:
    """Build user-facing toast messages from a sanitize result."""
    messages: list[str] = []
    if include_missing and result.removed_missing:
        count = result.removed_missing
        noun = "file" if count == 1 else "files"
        messages.append(f"Removed {count} saved input {noun} that no longer exist")
    if result.truncated_count:
        messages.append(f"Only the first {INPUT_FILES_MAX} files were added")
    if include_large_batch and result.large_batch:
        messages.append("100+ input files selected — processing may take a long time")
    return messages


@dataclass(frozen=True)
class SharedFileOptions:
    input_paths: list[str]
    export_path: str
    save_format: str
    is_gpu_conversion: bool
    is_autocast: bool
    sample_duration: int
    model_sample_mode: bool


def read_shared_file_options(settings: Settings) -> SharedFileOptions:
    """Read the keys every mode page shares from ``settings``."""
    process = settings.process
    return SharedFileOptions(
        input_paths=list(process.input_paths or []),
        export_path=process.export_path or "",
        save_format=process.save_format or WAV,
        is_gpu_conversion=bool(process.use_gpu),
        is_autocast=bool(process.autocast),
        sample_duration=int(process.sample_mode_duration or 30),
        model_sample_mode=bool(process.sample_mode),
    )


def apply_shared_file_options(
    settings: Settings,
    *,
    input_row: Optional[InputPathsRow] = None,
    input_rows: Optional[Iterable[InputPathsRow]] = None,
    output_row: Optional[OutputPathRow] = None,
    format_row: Optional[FormatRow] = None,
    gpu_row: Optional[SwitchRow] = None,
    autocast_row: Optional[SwitchRow] = None,
    sample_row: Optional[SampleModeRow] = None,
) -> SharedFileOptions:
    """Push shared settings values into the supplied option rows."""
    options = read_shared_file_options(settings)
    cleaned, _result = sanitize_input_paths(options.input_paths)
    if cleaned != options.input_paths:
        settings.process.input_paths = cleaned
        options = replace(options, input_paths=cleaned)

    rows: list[InputPathsRow] = []
    if input_row is not None:
        rows.append(input_row)
    if input_rows is not None:
        rows.extend(input_rows)

    for row in rows:
        row.set_paths(options.input_paths, notify=False)

    if output_row is not None:
        output_row.set_path(options.export_path, notify=False)
    if format_row is not None:
        format_row.apply_from_settings(settings)
    if gpu_row is not None:
        gpu_row.set_active(options.is_gpu_conversion)
    if autocast_row is not None:
        autocast_row.set_active(options.is_autocast)
    if sample_row is not None:
        apply_sample_mode_label(sample_row, options.sample_duration)
        sample_row.set_active(options.model_sample_mode)

    return options


T = TypeVar("T")


class SharedBindingHandle(Protocol):
    """Type-erased operations; values and writers remain paired inside bindings."""

    def adopt(self) -> None: ...

    def commit(self, settings: Settings, *, explicit: bool) -> None: ...


class SharedBinding(Generic[T]):
    """Track the last displayed value, never a stale copy of shared Settings."""

    def __init__(
        self,
        read_widget: Callable[[], T],
        write_setting: Callable[[Settings, T], None],
        *,
        available: Callable[[], bool] = lambda: True,
    ) -> None:
        self._read = read_widget
        self._write = write_setting
        self._available = available
        self._baseline: tuple[T] | None = None

    @property
    def available(self) -> bool:
        return self._available()

    def adopt(self) -> None:
        self._baseline = (self._read(),) if self.available else None

    def commit(self, settings: Settings, *, explicit: bool) -> None:
        if not self.available:
            self._baseline = None
            return
        value = self._read()
        # A newly populated lazy picker is an observation until a real edit.
        if explicit or (self._baseline is not None and value != self._baseline[0]):
            self._write(settings, value)
        self._baseline = (value,)


@dataclass(frozen=True)
class SharedSettingsBindings:
    input_paths: SharedBinding[tuple[str, ...]] | None = None
    export_path: SharedBinding[str] | None = None
    save_format: SharedBinding[SaveFormat] | None = None
    wav_type: SharedBinding[WavType] | None = None
    flac_bit_depth: SharedBinding[FlacBitDepth] | None = None
    mp3_bitrate: SharedBinding[Mp3Bitrate] | None = None
    opus_bitrate: SharedBinding[OpusBitrate] | None = None
    use_gpu: SharedBinding[bool] | None = None
    autocast: SharedBinding[bool] | None = None
    sample_mode: SharedBinding[bool] | None = None
    vocal_splitter_enabled: SharedBinding[bool] | None = None
    vocal_splitter: SharedBinding[str] | None = None
    save_inst_vocal_splitter: SharedBinding[bool] | None = None
    deverb_vocals: SharedBinding[bool] | None = None
    deverb_vocal_opt: SharedBinding[DeverbVocalOpt] | None = None

    def all(self) -> tuple[SharedBindingHandle, ...]:
        return tuple(
            binding
            for binding in (
                self.input_paths,
                self.export_path,
                self.save_format,
                self.wav_type,
                self.flac_bit_depth,
                self.mp3_bitrate,
                self.opus_bitrate,
                self.use_gpu,
                self.autocast,
                self.sample_mode,
                self.vocal_splitter_enabled,
                self.vocal_splitter,
                self.save_inst_vocal_splitter,
                self.deverb_vocals,
                self.deverb_vocal_opt,
            )
            if binding is not None
        )

    def active_quality(self) -> SharedBindingHandle | None:
        for binding in (self.wav_type, self.flac_bit_depth, self.mp3_bitrate, self.opus_bitrate):
            if binding is not None and binding.available:
                return binding
        return None

    def vocal_field(self, event: VocalSplitEdit) -> SharedBindingHandle | None:
        return {
            VocalSplitEdit.ENABLED: self.vocal_splitter_enabled,
            VocalSplitEdit.MODEL: self.vocal_splitter,
            VocalSplitEdit.SAVE_INSTRUMENTALS: self.save_inst_vocal_splitter,
            VocalSplitEdit.DEVERB: self.deverb_vocals,
            VocalSplitEdit.DEVERB_OPTION: self.deverb_vocal_opt,
        }[event]


class SharedSettingsSession:
    """One page's edits to shared fields, with refresh and active-page guards."""

    def __init__(
        self,
        settings: Settings,
        bindings: SharedSettingsBindings,
        *,
        can_commit: Callable[[], bool],
    ) -> None:
        self.bindings = bindings
        self._settings = settings
        self._can_commit = can_commit
        self._loading = 0

    @property
    def loading(self) -> bool:
        return self._loading > 0

    @property
    def editable(self) -> bool:
        return not self.loading and self._can_commit()

    def refresh(self, apply_widgets: Callable[[], None]) -> None:
        self._loading += 1
        try:
            apply_widgets()
            for binding in self.bindings.all():
                binding.adopt()
        finally:
            self._loading -= 1

    def adopt(self, binding: SharedBindingHandle | None) -> None:
        if binding is not None:
            binding.adopt()

    def commit(self, *, edited: Iterable[SharedBindingHandle | None] = ()) -> None:
        if not self.editable:
            return
        explicit = tuple(edited)
        for binding in self.bindings.all():
            binding.commit(self._settings, explicit=binding in explicit)

    def format_changed(self, event: FormatEdit) -> None:
        if not self.editable:
            return
        quality = self.bindings.active_quality()
        if event is FormatEdit.FORMAT:
            # The row restored this quality from live Settings while switching.
            self.adopt(quality)
            self.commit(edited=(self.bindings.save_format,))
        else:
            self.commit(edited=(quality,))

    def vocal_changed(self, event: VocalSplitEdit) -> None:
        self.commit(edited=(self.bindings.vocal_field(event),))


# Direct assignments preserve each reader/writer's exact type. No flat paths or
# whole-process snapshots: fields without a control remain with their owner.


def _write_input_paths(settings: Settings, value: tuple[str, ...]) -> None:
    settings.process.input_paths = list(value)


def _write_export_path(settings: Settings, value: str) -> None:
    settings.process.export_path = value


def _write_save_format(settings: Settings, value: SaveFormat) -> None:
    settings.process.save_format = value


def _write_wav_type(settings: Settings, value: WavType) -> None:
    settings.process.wav_type = value


def _write_flac_bit_depth(settings: Settings, value: FlacBitDepth) -> None:
    settings.process.flac_bit_depth = value


def _write_mp3_bitrate(settings: Settings, value: Mp3Bitrate) -> None:
    settings.process.mp3_bitrate = value


def _write_opus_bitrate(settings: Settings, value: OpusBitrate) -> None:
    settings.process.opus_bitrate = value


def _write_use_gpu(settings: Settings, value: bool) -> None:
    settings.process.use_gpu = value


def _write_autocast(settings: Settings, value: bool) -> None:
    settings.process.autocast = value


def _write_sample_mode(settings: Settings, value: bool) -> None:
    settings.process.sample_mode = value


def _write_vocal_splitter_enabled(settings: Settings, value: bool) -> None:
    settings.process.vocal_splitter_enabled = value


def _write_vocal_splitter(settings: Settings, value: str) -> None:
    settings.process.vocal_splitter = value


def _write_save_inst_vocal_splitter(settings: Settings, value: bool) -> None:
    settings.process.save_inst_vocal_splitter = value


def _write_deverb_vocals(settings: Settings, value: bool) -> None:
    settings.process.deverb_vocals = value


def _write_deverb_vocal_opt(settings: Settings, value: DeverbVocalOpt) -> None:
    settings.process.deverb_vocal_opt = value


def shared_settings_bindings(
    *,
    input_row: ReadableInputPathsRow | None = None,
    output_row: ReadableOutputPathRow | None = None,
    format_row: ReadableFormatRow | None = None,
    gpu_row: ReadableSwitchRow | None = None,
    autocast_row: ReadableSwitchRow | None = None,
    sample_row: ReadableSwitchRow | None = None,
    vocal_row: ReadableVocalSplitRow | None = None,
) -> SharedSettingsBindings:
    return SharedSettingsBindings(
        input_paths=SharedBinding(lambda: tuple(input_row.paths), _write_input_paths)
        if input_row is not None
        else None,
        export_path=SharedBinding(lambda: output_row.path, _write_export_path)
        if output_row is not None
        else None,
        save_format=SharedBinding(lambda: SaveFormat(format_row.save_format), _write_save_format)
        if format_row is not None
        else None,
        wav_type=SharedBinding(
            lambda: WavType(format_row.quality_value),
            _write_wav_type,
            available=lambda: format_row.save_format == SaveFormat.WAV,
        )
        if format_row is not None
        else None,
        flac_bit_depth=SharedBinding(
            lambda: FlacBitDepth(format_row.quality_value),
            _write_flac_bit_depth,
            available=lambda: format_row.save_format == SaveFormat.FLAC,
        )
        if format_row is not None
        else None,
        mp3_bitrate=SharedBinding(
            lambda: Mp3Bitrate(format_row.quality_value),
            _write_mp3_bitrate,
            available=lambda: format_row.save_format == SaveFormat.MP3,
        )
        if format_row is not None
        else None,
        opus_bitrate=SharedBinding(
            lambda: OpusBitrate(format_row.quality_value),
            _write_opus_bitrate,
            available=lambda: format_row.save_format == SaveFormat.OPUS,
        )
        if format_row is not None
        else None,
        use_gpu=SharedBinding(gpu_row.get_active, _write_use_gpu) if gpu_row is not None else None,
        autocast=SharedBinding(autocast_row.get_active, _write_autocast)
        if autocast_row is not None
        else None,
        sample_mode=SharedBinding(sample_row.get_active, _write_sample_mode)
        if sample_row is not None
        else None,
        vocal_splitter_enabled=SharedBinding(
            lambda: vocal_row.enabled, _write_vocal_splitter_enabled
        )
        if vocal_row is not None
        else None,
        vocal_splitter=SharedBinding(
            lambda: vocal_row.model_value,
            _write_vocal_splitter,
            available=lambda: vocal_row.model_write_allowed,
        )
        if vocal_row is not None
        else None,
        save_inst_vocal_splitter=SharedBinding(
            lambda: vocal_row.save_instrumentals, _write_save_inst_vocal_splitter
        )
        if vocal_row is not None
        else None,
        deverb_vocals=SharedBinding(lambda: vocal_row.deverb, _write_deverb_vocals)
        if vocal_row is not None
        else None,
        deverb_vocal_opt=SharedBinding(
            lambda: DeverbVocalOpt(vocal_row.deverb_option), _write_deverb_vocal_opt
        )
        if vocal_row is not None
        else None,
    )
