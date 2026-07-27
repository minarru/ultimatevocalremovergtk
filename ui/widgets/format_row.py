"""Combined output-format row: format + its per-format quality option.

A single :class:`Adw.ActionRow` carrying two side-by-side :class:`Gtk.DropDown`
widgets. The second dropdown's model, label and settings key swap with the
selected format (WAV type / MP3 bitrate / FLAC bit depth), so the three
processing pages expose the complete export choice in one row instead of
sending the user to a separate Preferences page.

The unselected formats' settings keys are left untouched, so switching WAV ->
MP3 -> WAV restores the previously chosen WAV type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from gi.repository import Adw, Gtk

from bundled.constants import (
    FLAC,
    FLAC_BIT_DEPTHS,
    MP3,
    MP3_BIT_RATES,
    WAV,
    WAV_TYPE,
)

from ui.help_text import FLAC_BIT_DEPTH_HINT, OUTPUT_FORMAT_HINT, WAV_TYPE_HINT

from .rows import set_row_icon

#: Minimum width for the quality dropdown so it doesn't resize when the model
#: swaps between short ("320k") and long ("32-bit Float") values.
_QUALITY_MIN_WIDTH = 132
_FORMAT_MIN_WIDTH = 96

FORMATS = (WAV, FLAC, MP3)

#: No existing constant covers MP3 bitrate; ``ui/help_text.py`` has a style
#: validator test (``tests/test_help_text.py``) so it stays local to this
#: widget rather than widening that module's surface.
MP3_BITRATE_HINT = "Bitrate used when encoding MP3 output"


@dataclass(frozen=True)
class QualitySpec:
    """The quality dropdown's configuration for one output format."""

    label: str
    values: tuple[str, ...]
    setting_key: str
    default: str
    hint: str


_QUALITY_SPECS = {
    WAV: QualitySpec(
        "WAV type", tuple(WAV_TYPE), "wav_type_set", "PCM_16", WAV_TYPE_HINT
    ),
    MP3: QualitySpec(
        "MP3 bitrate", tuple(MP3_BIT_RATES), "mp3_bit_set", "320k", MP3_BITRATE_HINT
    ),
    FLAC: QualitySpec(
        "FLAC bit depth",
        tuple(FLAC_BIT_DEPTHS),
        "flac_bit_set",
        "16-bit",
        FLAC_BIT_DEPTH_HINT,
    ),
}


def quality_spec(save_format: str) -> QualitySpec:
    """Return the quality-dropdown spec for ``save_format`` (WAV when unknown)."""
    return _QUALITY_SPECS.get(save_format, _QUALITY_SPECS[WAV])


def _dropdown(values, min_width: int) -> Gtk.DropDown:
    drop = Gtk.DropDown.new_from_strings(list(values))
    drop.set_valign(Gtk.Align.CENTER)
    drop.set_size_request(min_width, -1)
    return drop


def _selected_string(drop: Gtk.DropDown) -> Optional[str]:
    item = drop.get_selected_item()
    return item.get_string() if item is not None else None


def _select_string(drop: Gtk.DropDown, value: str) -> bool:
    model = drop.get_model()
    for index in range(model.get_n_items()):
        if model.get_string(index) == value:
            drop.set_selected(index)
            return True
    return False


class OutputFormatRow(Adw.ActionRow):
    """Output format plus its quality sub-option, side by side in one row."""

    def __init__(self, on_changed: Callable[[], None]):
        super().__init__(title="Output format")
        set_row_icon(self, "waveform-symbolic")
        self._on_changed = on_changed
        self._syncing = False

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_valign(Gtk.Align.CENTER)

        self._format_drop = _dropdown(FORMATS, _FORMAT_MIN_WIDTH)
        self._format_drop.set_tooltip_text(OUTPUT_FORMAT_HINT)
        self._format_drop.update_property(
            [Gtk.AccessibleProperty.LABEL], ["Output format"]
        )
        self._format_drop.connect("notify::selected", self._on_format_selected)
        box.append(self._format_drop)

        self._quality_drop = _dropdown(quality_spec(WAV).values, _QUALITY_MIN_WIDTH)
        self._quality_drop.connect("notify::selected", self._on_quality_selected)
        box.append(self._quality_drop)

        self.add_suffix(box)
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

    def apply_from_settings(self, settings) -> None:
        """Restore both dropdowns from ``settings`` without emitting changes."""
        self._syncing = True
        try:
            self.set_save_format(settings.get("save_format", WAV))
            self._reload_quality(settings)
        finally:
            self._syncing = False

    def persist_to_settings(self, settings) -> None:
        """Write the format and *only its own* quality key back to ``settings``."""
        settings.set("save_format", self.save_format)
        settings.set(self.quality_key, self.quality_value)

    # -- Internals --------------------------------------------------------------

    def _reload_quality(self, settings) -> None:
        spec = quality_spec(self.save_format)
        self._quality_drop.set_model(Gtk.StringList.new(list(spec.values)))
        stored = settings.get(spec.setting_key, spec.default)
        if not _select_string(self._quality_drop, str(stored)):
            _select_string(self._quality_drop, spec.default)
        self._apply_quality_labels(self.save_format)

    def _apply_quality_labels(self, save_format: str) -> None:
        spec = quality_spec(save_format)
        self._quality_drop.set_tooltip_text(spec.hint)
        self._quality_drop.update_property(
            [Gtk.AccessibleProperty.LABEL], [spec.label]
        )

    def _on_format_selected(self, *_args) -> None:
        if self._syncing:
            return
        spec = quality_spec(self.save_format)
        self._syncing = True
        try:
            self._quality_drop.set_model(Gtk.StringList.new(list(spec.values)))
            _select_string(self._quality_drop, spec.default)
            self._apply_quality_labels(self.save_format)
        finally:
            self._syncing = False
        self._on_changed()

    def _on_quality_selected(self, *_args) -> None:
        if self._syncing:
            return
        self._on_changed()
