"""Sample trim: choose which part of each input sample mode processes.

Edits stay in the dialog until Apply; closing any other way discards them. The
range moves by dragging the waveform, clicking outside the range, or Shift+Left
and Shift+Right. Its length changes by dragging a trim handle or Shift+Up and
Shift+Down; an input whose length was never changed follows the Preferences
sample duration.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Callable, Mapping, Sequence

from gi.repository import Gdk, Gtk

from core.listening import Track
from core.sample_mode import (
    SAMPLE_LENGTH_MAX,
    SAMPLE_LENGTH_MIN,
    fitted_sample_start,
    sample_start,
    seconds_text,
)

from ..template import load_builder, object_from_builder
from .engine import PlaybackControls
from .input_picker import InputPicker
from .range_loop import RangeLoop
from .surface import PlaybackSurface
from .view import CompareView, mmss

if TYPE_CHECKING:
    from core.waveform import Peaks

    from .waveforms import PeakCallback, PeakLoading

_TITLE = "Choose Sample Range"
# Seconds one Shift+arrow moves the range or changes its length; also the grid
# that dragging a handle snaps the length to.
_STEP = 1.0
_MOVE_KEYS = {Gdk.KEY_Left: -_STEP, Gdk.KEY_Right: _STEP}
_LENGTH_KEYS = {Gdk.KEY_Down: -_STEP, Gdk.KEY_Up: _STEP}
_MODIFIERS = Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK
# Inputs whose peaks are computed ahead around the shown one, nearest first: the
# picker is usually stepped through, and each warm decodes a whole file.
_WARM_AHEAD = 2
_WARM_BEHIND = 1

#: An applied edit: the start (``None`` for 0:00) and the length (``None`` to
#: follow the Preferences sample duration).
RangeEdit = tuple[float | None, float | None]


class TrimDialog:
    def __init__(
        self,
        inputs: Sequence[str],
        engine: PlaybackControls,
        *,
        duration: float,
        starts: Mapping[str, float],
        on_apply: Callable[[dict[str, RangeEdit]], None],
        lengths: Mapping[str, float] | None = None,
        waveforms: PeakLoading | None = None,
        warmer: PeakLoading | None = None,
        open_in_window: bool = False,
        on_toast: Callable[[str], None] | None = None,
        on_closed: Callable[[], None] | None = None,
    ) -> None:
        self._inputs = [os.path.abspath(path) for path in inputs]
        self._duration = float(duration)
        self._starts = dict(starts)
        self._lengths = dict(lengths or {})
        self._on_apply = on_apply
        # Edited inputs only: their start, and their own length or ``None``.
        self._pending: dict[str, tuple[float, float | None]] = {}
        self._current = 0
        #: The current input's range as text, at the end of its row.
        self.range_label: Gtk.Label | None = None

        self.loop = RangeLoop(engine)
        self._warmer = warmer
        self._on_closed = on_closed
        peaks = waveforms
        if waveforms is not None and warmer is not None and len(self._inputs) > 1:
            peaks = _ThenWarm(waveforms, self._warm_neighbours)
        self.view = CompareView(self.loop, peaks=peaks, row_suffix=self._range_suffix)
        self._forward_duration = self.loop.on_duration
        self.loop.on_duration = self._relay_duration
        self.surface = PlaybackSurface(
            self.view,
            title=_TITLE,
            open_in_window=open_in_window,
            commit=True,
            track_keys=False,
            range_keys=True,
            on_key=self._on_key,
            on_toast=on_toast,
            on_closed=self._on_surface_closed,
        )
        builder = load_builder("trim-dialog")
        self.cancel_button = object_from_builder(builder, "cancel_button", Gtk.Button)
        self.reset_button = object_from_builder(builder, "reset_button", Gtk.Button)
        self.apply_button = object_from_builder(builder, "apply_button", Gtk.Button)
        self.picker = InputPicker(
            _TITLE, [os.path.basename(path) for path in self._inputs], self._show
        )
        self.surface.pack_start(self.cancel_button)
        self.surface.pack_start(self.reset_button)
        self.surface.pack_end(self.apply_button)
        self.surface.set_title_widget(self.picker.widget)
        self.cancel_button.connect("clicked", lambda _b: self.close())
        self.reset_button.connect("clicked", lambda _b: self._set_range(0.0, self._duration))
        self.apply_button.connect("clicked", self._on_apply_clicked)
        if self._inputs:
            self._show(0)

    def present(self, parent: Gtk.Window | None) -> None:
        self.surface.present(parent)

    def set_duration(self, duration: float) -> None:
        """Follow a Preferences sample length change on inputs without their own."""
        duration = float(duration)
        if duration <= 0 or duration == self._duration:
            return
        self._duration = duration
        if not self._inputs:
            return
        path = self._inputs[self._current]
        if self._custom_length_of(path) is not None:
            self._sync_reset()
            return
        shown = self._start_of(path)
        total = self.loop.duration
        fitted = fitted_sample_start(shown, duration, total if total > 0 else None)
        if fitted != shown:
            self._set_range(fitted, duration)
            return
        self._show_range(shown, duration)
        position = self.loop.position
        if position < self.loop.range_start or position > self.loop.range_end:
            self.loop.seek(position)

    def close(self) -> None:
        self.surface.close()

    # -- inputs ----------------------------------------------------------------

    def _relay_duration(self, seconds: float) -> None:
        self._forward_duration(seconds)
        if seconds <= 0 or not self._inputs:
            return
        path = self._inputs[self._current]
        shown, length = self._start_of(path), self._length_of(path)
        fitted = fitted_sample_start(shown, length, seconds)
        if fitted != shown:
            self._set_range(fitted, length)
        else:
            # A short input's range now ends with the file.
            self._sync_range_label()

    def _start_of(self, path: str) -> float:
        if path in self._pending:
            return self._pending[path][0]
        return sample_start(self._starts, path)

    def _custom_length_of(self, path: str) -> float | None:
        if path in self._pending:
            return self._pending[path][1]
        length = self._lengths.get(path)
        return float(length) if length is not None and length > 0 else None

    def _length_of(self, path: str) -> float:
        custom = self._custom_length_of(path)
        return self._duration if custom is None else custom

    def _show(self, index: int) -> None:
        if self.loop.playing:
            self.loop.pause()
        if self._warmer is not None:
            self._warmer.cancel()
        self._current = index
        path = self._inputs[index]
        start, length = self._start_of(path), self._length_of(path)
        self.loop.set_range(start, length)
        self.view.show_tracks((Track(os.path.basename(path), path),), selected=0, position=start)
        # One row and no track switching, so its number key would point nowhere.
        for hint in self.view.key_hints:
            hint.set_visible(False)
        waveform = self.view.waveforms[0]
        waveform.set_range(start, length)
        waveform.set_range_resizable(SAMPLE_LENGTH_MIN, SAMPLE_LENGTH_MAX, _STEP)
        waveform.on_range_changed = self._set_range
        waveform.on_range_preview = self._preview_range
        self._sync_reset()
        self._sync_range_label()

    def _warm_neighbours(self) -> None:
        """Compute the peaks of the inputs around the shown one, nearest first."""
        if self._warmer is None:
            return
        current, last = self._current, len(self._inputs) - 1
        order: list[int] = []
        for step in range(1, max(_WARM_AHEAD, _WARM_BEHIND) + 1):
            if step <= _WARM_AHEAD and current + step <= last:
                order.append(current + step)
            if step <= _WARM_BEHIND and current - step >= 0:
                order.append(current - step)
        if order:
            self._warmer.load([self._inputs[index] for index in order], 0, _ignore_peaks)

    def _on_surface_closed(self) -> None:
        if self._warmer is not None:
            self._warmer.cancel()
        if self._on_closed is not None:
            self._on_closed()

    def _set_range(self, start: float, length: float) -> None:
        """Record ``start`` and ``length`` for the current input and play from the start."""
        path = self._inputs[self._current]
        custom = None if abs(length - self._duration) < 1e-6 else length
        self._pending[path] = (max(0.0, start), custom)
        self._show_range(start, length)
        self.loop.seek(start)

    def _show_range(self, start: float, length: float) -> None:
        self.loop.set_range(start, length)
        if self.view.waveforms:
            self.view.waveforms[0].set_range(start, length)
        self._sync_reset()
        self._sync_range_label()

    def _known_total(self) -> float | None:
        total = self.loop.duration
        if total <= 0 and self.view.waveforms:
            total = self.view.waveforms[0].timeline
        return total if total > 0 else None

    def _nudge(self, seconds: float) -> None:
        length = self._length_of(self._inputs[self._current])
        current = self.loop.range_start
        start = fitted_sample_start(current + seconds, length, self._known_total())
        if start != current:
            self._set_range(start, length)

    def _resize(self, seconds: float) -> None:
        """Lengthen or shorten the range at its end, pulling the start back if needed."""
        current = self._length_of(self._inputs[self._current])
        total = self._known_total()
        high = SAMPLE_LENGTH_MAX if total is None else min(SAMPLE_LENGTH_MAX, total)
        # A range longer than the file changes from the part that is shown.
        current = min(current, high) if total is not None else current
        length = min(max(current + seconds, min(SAMPLE_LENGTH_MIN, high)), high)
        if length == current:
            return
        self._set_range(fitted_sample_start(self.loop.range_start, length, total), length)

    def _sync_reset(self) -> None:
        current = self._inputs[self._current] if self._inputs else ""
        self.reset_button.set_sensitive(
            bool(current)
            and (self._start_of(current) > 0 or self._custom_length_of(current) is not None)
        )

    def _range_suffix(self, _index: int, _track: Track) -> Gtk.Widget:
        label = Gtk.Label(valign=Gtk.Align.CENTER)
        label.add_css_class("dim-label")
        label.add_css_class("numeric")
        self.range_label = label
        return label

    def _sync_range_label(self) -> None:
        self._label_range(self.loop.range_start, self.loop.range_end)

    def _preview_range(self, start: float, length: float) -> None:
        """Follow a handle or range drag before it is committed."""
        end = start + length
        total = self.loop.duration
        self._label_range(start, min(end, total) if total > 0 else end)

    def _label_range(self, start: float, end: float) -> None:
        if self.range_label is None:
            return
        first, last = mmss(start), mmss(end)
        seconds = seconds_text(round(max(0.0, end - start), 1))
        self.range_label.set_label(f"{first} – {last} · {seconds} s")
        self.range_label.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [f"Sample range {first} to {last}, {seconds} seconds"],
        )

    # -- keys ------------------------------------------------------------------

    def _on_key(self, keyval: int, state: Gdk.ModifierType) -> bool:
        if not self._inputs or (state & _MODIFIERS) != Gdk.ModifierType.SHIFT_MASK:
            return False
        if keyval in _MOVE_KEYS:
            self._nudge(_MOVE_KEYS[keyval])
            return True
        if keyval in _LENGTH_KEYS:
            self._resize(_LENGTH_KEYS[keyval])
            return True
        return False

    def _on_apply_clicked(self, _button: Gtk.Button) -> None:
        edits: dict[str, RangeEdit] = {
            path: (start if start > 0 else None, length)
            for path, (start, length) in self._pending.items()
        }
        self._on_apply(edits)
        self.close()


class _ThenWarm:
    """The shown input's peak loading; once they land, ``after`` warms the others."""

    def __init__(self, loader: PeakLoading, after: Callable[[], None]) -> None:
        self._loader = loader
        self._after = after

    def load(self, paths: Sequence[str], first: int, on_peaks: PeakCallback) -> None:
        def delivered(index: int, peaks: Peaks | None) -> None:
            on_peaks(index, peaks)
            self._after()

        self._loader.load(paths, first, delivered)

    def cancel(self) -> None:
        self._loader.cancel()


def _ignore_peaks(_index: int, _peaks: Peaks | None) -> None:
    """Warming only fills the cache; the waveform draws from it on a switch."""


__all__ = ["RangeEdit", "TrimDialog"]
