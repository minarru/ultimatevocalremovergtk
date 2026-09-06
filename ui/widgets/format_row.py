"""Combined output-format row: format + its per-format quality option.

A single :class:`Adw.ActionRow` carrying two side-by-side :class:`Gtk.DropDown`
widgets. The second dropdown's model, label and settings key swap with the
selected format (WAV type / MP3 bitrate / FLAC bit depth / Opus bitrate), so the
three processing pages expose the complete export choice in one row instead of
sending the user to a separate Preferences page.

The unselected formats' settings keys are left untouched, so switching WAV ->
MP3 -> WAV restores the previously chosen WAV type.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass
from typing import Callable, Optional

from gi.repository import Adw, Gtk

from bundled.constants import (
    FLAC,
    FLAC_BIT_DEPTHS,
    MP3,
    MP3_BIT_RATES,
    OPUS,
    OPUS_BIT_RATES,
    WAV,
    WAV_TYPE,
)
from core.settings import Settings
from core.types import SaveFormat
from ui.help_text import FLAC_BIT_DEPTH_HINT, OUTPUT_FORMAT_HINT, WAV_TYPE_HINT
from ui.resources import RESOURCE_PREFIX, require_resource_bundle

from ..protocols import FormatEdit
from ..settings_bind import enum_value, get_flat, set_flat
from .rows import set_row_icon

_TEMPLATE_RESOURCE = f"{RESOURCE_PREFIX}/ui/output_format_row.ui"
require_resource_bundle(_TEMPLATE_RESOURCE)

FORMATS = (WAV, FLAC, MP3, OPUS)

#: No existing constant covers MP3 bitrate; ``ui/help_text.py`` has a style
#: validator test (``tests/test_help_text.py``) so it stays local to this
#: widget rather than widening that module's surface.
MP3_BITRATE_HINT = "Bitrate used when encoding MP3 output"
OPUS_BITRATE_HINT = (
    "Target bitrate for Opus output; encoding varies around this value and resamples to 48 kHz"
)


@dataclass(frozen=True)
class QualitySpec:
    """The quality dropdown's configuration for one output format."""

    label: str
    values: tuple[str, ...]
    setting_key: str
    default: str
    hint: str


_QUALITY_SPECS = {
    WAV: QualitySpec("WAV type", tuple(WAV_TYPE), "wav_type_set", "PCM_16", WAV_TYPE_HINT),
    MP3: QualitySpec("MP3 bitrate", tuple(MP3_BIT_RATES), "mp3_bit_set", "320k", MP3_BITRATE_HINT),
    FLAC: QualitySpec(
        "FLAC bit depth",
        tuple(FLAC_BIT_DEPTHS),
        "flac_bit_set",
        "16-bit",
        FLAC_BIT_DEPTH_HINT,
    ),
    OPUS: QualitySpec(
        "Opus bitrate",
        tuple(OPUS_BIT_RATES),
        "opus_bit_set",
        "192k",
        OPUS_BITRATE_HINT,
    ),
}


def quality_spec(save_format: str) -> QualitySpec:
    """Return the quality-dropdown spec for ``save_format`` (WAV when unknown)."""
    return _QUALITY_SPECS.get(save_format, _QUALITY_SPECS[WAV])


def _selected_string(drop: Gtk.DropDown) -> Optional[str]:
    # get_selected_item() is typed GObject.Object | None; only Gtk.StringObject
    # carries get_string.
    item = drop.get_selected_item()
    return item.get_string() if isinstance(item, Gtk.StringObject) else None


def _select_string(drop: Gtk.DropDown, value: str) -> bool:
    model = drop.get_model()
    if not isinstance(model, Gtk.StringList):
        return False
    for index in range(model.get_n_items()):
        if model.get_string(index) == value:
            drop.set_selected(index)
            return True
    return False


@Gtk.Template(resource_path=_TEMPLATE_RESOURCE)
class OutputFormatRow(Adw.ActionRow):
    """Output format plus its quality sub-option, side by side in one row."""

    __gtype_name__ = "OutputFormatRow"

    _format_drop: Gtk.DropDown = Gtk.Template.Child("format_drop")
    _quality_drop: Gtk.DropDown = Gtk.Template.Child("quality_drop")

    def __init__(self, on_changed: Callable[[FormatEdit], None]):
        super().__init__()
        set_row_icon(self, "waveform-symbolic")
        self._on_changed = on_changed
        self._syncing = False
        #: Cached from the last ``apply_from_settings`` call so an interactive
        #: format switch can restore the newly selected format's *stored*
        #: quality value instead of resetting it to the spec default. ``None``
        #: until the row has been applied at least once (e.g. constructed but
        #: never loaded, as in some tests) — callers fall back to the default
        #: in that case.
        self._settings = None

        self._format_drop.set_model(Gtk.StringList.new(list(FORMATS)))
        self._format_drop.set_tooltip_text(OUTPUT_FORMAT_HINT)
        self._format_drop.update_property([Gtk.AccessibleProperty.LABEL], ["Output format"])
        self._format_drop.connect("notify::selected", self._on_format_selected)

        self._quality_drop.set_model(Gtk.StringList.new(list(quality_spec(WAV).values)))
        self._quality_drop.connect("notify::selected", self._on_quality_selected)
        self._apply_quality_labels(WAV)

    # -- State ------------------------------------------------------------------

    @property
    def save_format(self) -> str:
        return _selected_string(self._format_drop) or WAV

    @property
    def quality_key(self) -> str:
        return quality_spec(self.save_format).setting_key

    @property
    def quality_value(self) -> str:
        spec = quality_spec(self.save_format)
        return _selected_string(self._quality_drop) or spec.default

    def set_save_format(self, value: str) -> None:
        if not _select_string(self._format_drop, value):
            _select_string(self._format_drop, WAV)

    # -- Settings ---------------------------------------------------------------

    def apply_from_settings(self, settings: Settings) -> None:
        """Restore both dropdowns from ``settings`` without emitting changes."""
        self._settings = settings
        self._syncing = True
        try:
            self.set_save_format(settings.process.save_format or WAV)
            self._reload_quality(settings)
        finally:
            self._syncing = False

    def persist_to_settings(self, settings: Settings) -> None:
        """Write the format and *only its own* quality key back to ``settings``."""
        settings.process.save_format = SaveFormat(self.save_format)
        set_flat(settings, self.quality_key, self.quality_value)

    # -- Internals --------------------------------------------------------------

    def _reload_quality(self, settings: Settings) -> None:
        spec = quality_spec(self.save_format)
        self._quality_drop.set_model(Gtk.StringList.new(list(spec.values)))
        stored = get_flat(settings, spec.setting_key, spec.default)
        self._select_quality_value(enum_value(stored), spec)
        self._apply_quality_labels(self.save_format)

    def _select_quality_value(self, value: typing.Any, spec: QualitySpec) -> None:
        if not _select_string(self._quality_drop, str(value)):
            _select_string(self._quality_drop, spec.default)

    def _stored_quality_value(self, spec: QualitySpec) -> str:
        """The value saved for ``spec``'s key, or its default with no settings yet."""
        if self._settings is None:
            return spec.default
        stored = get_flat(self._settings, spec.setting_key, spec.default)
        return str(enum_value(stored))

    def _apply_quality_labels(self, save_format: str) -> None:
        spec = quality_spec(save_format)
        self._quality_drop.set_tooltip_text(spec.hint)
        self._quality_drop.update_property([Gtk.AccessibleProperty.LABEL], [spec.label])

    def _on_format_selected(self, *_args: typing.Any) -> None:
        if self._syncing:
            return
        spec = quality_spec(self.save_format)
        self._syncing = True
        try:
            self._quality_drop.set_model(Gtk.StringList.new(list(spec.values)))
            # Restore the newly selected format's own stored value (e.g. the
            # WAV type from before an earlier switch to MP3), not the spec
            # default — see the module docstring's WAV -> MP3 -> WAV contract.
            self._select_quality_value(self._stored_quality_value(spec), spec)
            self._apply_quality_labels(self.save_format)
        finally:
            self._syncing = False
        self._on_changed(FormatEdit.FORMAT)

    def _on_quality_selected(self, *_args: typing.Any) -> None:
        if self._syncing:
            return
        self._on_changed(FormatEdit.QUALITY)
