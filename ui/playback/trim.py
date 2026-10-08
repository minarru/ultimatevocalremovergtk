"""Sample trim: choose which N seconds of each input sample mode processes.

Edits stay in the dialog until Apply; closing any other way discards them. The
range moves by dragging the waveform, clicking outside the range, or Shift+Left
and Shift+Right.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Callable, Mapping, Sequence

from gi.repository import Gdk, Gtk

from core.listening import Track
from core.sample_mode import fitted_sample_start, sample_start

from ..template import load_builder, object_from_builder
from .engine import PlaybackControls
from .input_picker import InputPicker
from .range_loop import RangeLoop
from .surface import PlaybackSurface
from .view import CompareView, mmss

if TYPE_CHECKING:
    from .waveforms import PeakLoading

_TITLE = "Choose Sample Range"
# Seconds one Shift+Left or Shift+Right moves the range.
_NUDGE_STEP = 1.0
_NUDGE_KEYS = {Gdk.KEY_Left: -_NUDGE_STEP, Gdk.KEY_Right: _NUDGE_STEP}
_MODIFIERS = Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK


class TrimDialog:
    def __init__(
        self,
        inputs: Sequence[str],
        engine: PlaybackControls,
        *,
        duration: float,
        starts: Mapping[str, float],
        on_apply: Callable[[dict[str, float | None]], None],
        waveforms: PeakLoading | None = None,
        open_in_window: bool = False,
        on_toast: Callable[[str], None] | None = None,
        on_closed: Callable[[], None] | None = None,
    ) -> None:
        self._inputs = [os.path.abspath(path) for path in inputs]
        self._duration = float(duration)
        self._starts = dict(starts)
        self._on_apply = on_apply
        # Edited inputs only; ``None`` means the start goes back to 0:00.
        self._pending: dict[str, float | None] = {}
        self._current = 0
        #: The current input's range as text, at the end of its row.
        self.range_label: Gtk.Label | None = None

        self.loop = RangeLoop(engine)
        self.view = CompareView(self.loop, peaks=waveforms, row_suffix=self._range_suffix)
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
            on_closed=on_closed,
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
        self.reset_button.connect("clicked", lambda _b: self._move_to(0.0))
        self.apply_button.connect("clicked", self._on_apply_clicked)
        if self._inputs:
            self._show(0)

    def present(self, parent: Gtk.Window | None) -> None:
        self.surface.present(parent)

    def set_duration(self, duration: float) -> None:
        """Resize the open range when Preferences changes the sample length."""
        duration = float(duration)
        if duration <= 0 or duration == self._duration:
            return
        self._duration = duration
        if not self._inputs:
            return
        shown = self._start_of(self._inputs[self._current])
        total = self.loop.duration
        fitted = fitted_sample_start(shown, duration, total if total > 0 else None)
        if fitted != shown:
            self._move_to(fitted)
            return
        self.loop.set_range(shown, duration)
        if self.view.waveforms:
            self.view.waveforms[0].set_range(shown, duration)
        position = self.loop.position
        if position < self.loop.range_start or position > self.loop.range_end:
            self.loop.seek(position)
        self._sync_range_label()

    def close(self) -> None:
        self.surface.close()

    # -- inputs ----------------------------------------------------------------

    def _relay_duration(self, seconds: float) -> None:
        self._forward_duration(seconds)
        if seconds <= 0 or not self._inputs:
            return
        path = self._inputs[self._current]
        shown = self._start_of(path)
        fitted = fitted_sample_start(shown, self._duration, seconds)
        if fitted != shown:
            self._move_to(fitted)
        else:
            # A short input's range now ends with the file.
            self._sync_range_label()

    def _start_of(self, path: str) -> float:
        if path in self._pending:
            return self._pending[path] or 0.0
        return sample_start(self._starts, path)

    def _show(self, index: int) -> None:
        if self.loop.playing:
            self.loop.pause()
        self._current = index
        path = self._inputs[index]
        start = self._start_of(path)
        self.loop.set_range(start, self._duration)
        self.view.show_tracks((Track(os.path.basename(path), path),), selected=0, position=start)
        # One row and no track switching, so its number key would point nowhere.
        for hint in self.view.key_hints:
            hint.set_visible(False)
        waveform = self.view.waveforms[0]
        waveform.set_range(start, self._duration)
        waveform.on_range_moved = self._move_to
        self._sync_reset()
        self._sync_range_label()

    def _move_to(self, start: float) -> None:
        path = self._inputs[self._current]
        self._pending[path] = start if start > 0 else None
        self.loop.set_range(start, self._duration)
        if self.view.waveforms:
            self.view.waveforms[0].set_range(start, self._duration)
        self.loop.seek(start)
        self._sync_reset()
        self._sync_range_label()

    def _nudge(self, seconds: float) -> None:
        total = self.loop.duration
        if total <= 0 and self.view.waveforms:
            total = self.view.waveforms[0].timeline
        current = self.loop.range_start
        start = fitted_sample_start(current + seconds, self._duration, total if total > 0 else None)
        if start != current:
            self._move_to(start)

    def _sync_reset(self) -> None:
        current = self._inputs[self._current] if self._inputs else ""
        self.reset_button.set_sensitive(bool(current) and self._start_of(current) > 0)

    def _range_suffix(self, _index: int, _track: Track) -> Gtk.Widget:
        label = Gtk.Label(valign=Gtk.Align.CENTER)
        label.add_css_class("dim-label")
        label.add_css_class("numeric")
        self.range_label = label
        return label

    def _sync_range_label(self) -> None:
        if self.range_label is None:
            return
        first, last = mmss(self.loop.range_start), mmss(self.loop.range_end)
        self.range_label.set_label(f"{first} – {last}")
        self.range_label.update_property(
            [Gtk.AccessibleProperty.LABEL], [f"Sample range {first} to {last}"]
        )

    # -- keys ------------------------------------------------------------------

    def _on_key(self, keyval: int, state: Gdk.ModifierType) -> bool:
        step = _NUDGE_KEYS.get(keyval)
        if step is None or not self._inputs or (state & _MODIFIERS) != Gdk.ModifierType.SHIFT_MASK:
            return False
        self._nudge(step)
        return True

    def _on_apply_clicked(self, _button: Gtk.Button) -> None:
        self._on_apply(dict(self._pending))
        self.close()


__all__ = ["TrimDialog"]
