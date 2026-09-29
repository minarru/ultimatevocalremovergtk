"""Compare stems dialog: one input's tracks, one audible at a time."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Sequence

from gi.repository import Adw, Gdk, Gtk

from core.listening import ComparisonSet, Track

from ..dialogs.utils import present_modal_dialog
from ..files import open_folder_in_file_manager
from ..gtk_narrow import root_window
from ..template import load_builder, object_from_builder
from ..widgets.waveform import WaveformView
from .engine import PlaybackControls

if TYPE_CHECKING:
    from core.waveform import Peaks

    from .waveforms import PeakLoading

_SEEK_STEP = 5.0
_PLAY_ICON = "media-playback-start-symbolic"
_PAUSE_ICON = "media-playback-pause-symbolic"
_NUMBER_KEYS = {getattr(Gdk, f"KEY_{n}"): n - 1 for n in range(1, 10)}
_NUMBER_KEYS.update({getattr(Gdk, f"KEY_KP_{n}"): n - 1 for n in range(1, 10)})


def _mmss(seconds: float) -> str:
    whole = max(0, int(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


class CompareDialog:
    def __init__(
        self,
        sets: Sequence[ComparisonSet],
        engine: PlaybackControls,
        *,
        waveforms: PeakLoading | None = None,
        output_dir: str = "",
        on_toast: Callable[[str], None] | None = None,
        on_closed: Callable[[], None] | None = None,
    ) -> None:
        self._sets = list(sets)
        self._engine = engine
        self._peak_loader = waveforms
        self._output_dir = output_dir
        self._on_toast = on_toast
        self._on_closed = on_closed
        self._parent: Gtk.Window | None = None
        self._building = False

        builder = load_builder("compare-stems-dialog")
        self.dialog = object_from_builder(builder, "dialog", Adw.Dialog)
        self.input_dropdown = object_from_builder(builder, "input_dropdown", Gtk.DropDown)
        self._track_list = object_from_builder(builder, "track_list", Gtk.ListBox)
        self.play_button = object_from_builder(builder, "play_button", Gtk.Button)
        self._elapsed = object_from_builder(builder, "elapsed_label", Gtk.Label)
        self._total = object_from_builder(builder, "total_label", Gtk.Label)
        self.folder_button = object_from_builder(builder, "folder_button", Gtk.Button)
        self.rows: list[Gtk.ListBoxRow] = []
        self.titles: list[Gtk.Label] = []
        self.waveforms: list[WaveformView] = []
        self._checks: list[Gtk.CheckButton] = []

        self.play_button.update_property([Gtk.AccessibleProperty.LABEL], ["Play"])
        self.play_button.connect("clicked", lambda _b: self._engine.toggle())
        self._track_list.connect("row-activated", self._on_row_activated)
        self.folder_button.set_visible(bool(output_dir))
        self.folder_button.connect("clicked", self._on_open_folder)
        self.dialog.connect("closed", self._on_dialog_closed)

        # Capture phase: a focused radio or button would otherwise consume Space first.
        self._keys = Gtk.EventControllerKey()
        self._keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._keys.connect("key-pressed", lambda _c, keyval, _code, _state: self.handle_key(keyval))
        self.dialog.add_controller(self._keys)

        engine.on_position = self._on_position
        engine.on_duration = self._on_duration
        engine.on_state = self._on_state
        engine.on_track_error = self._on_track_error
        engine.on_error = self._on_engine_error

        if len(self._sets) > 1:
            total = len(self._sets)
            names = [f"{s.name}  {i} of {total}" for i, s in enumerate(self._sets, start=1)]
            self.input_dropdown.set_model(Gtk.StringList.new(names))
            self.input_dropdown.set_visible(True)
            self.input_dropdown.connect("notify::selected", self._on_input_changed)
        self._show_set(0, position=0.0)

    # -- public ----------------------------------------------------------------

    def present(self, parent: Gtk.Window | None) -> None:
        self._parent = parent
        present_modal_dialog(self.dialog, parent)

    def close(self) -> None:
        self._cancel_peaks()
        self.dialog.force_close()
        self._engine.unload()

    def handle_key(self, keyval: int) -> bool:
        if keyval == Gdk.KEY_space:
            self._engine.toggle()
            return True
        if keyval == Gdk.KEY_Left:
            self._engine.seek(self._engine.position - _SEEK_STEP)
            return True
        if keyval == Gdk.KEY_Right:
            self._engine.seek(self._engine.position + _SEEK_STEP)
            return True
        index = _NUMBER_KEYS.get(keyval)
        if index is not None and index < len(self.rows) and self.rows[index].get_sensitive():
            self._select(index)
            return True
        return False

    # -- building --------------------------------------------------------------

    def _show_set(self, index: int, *, position: float) -> None:
        cset = self._sets[index]
        self._cancel_peaks()
        self._building = True
        for row in self.rows:
            self._track_list.remove(row)
        self.rows = []
        self.titles = []
        self.waveforms = []
        self._checks = []
        group: Gtk.CheckButton | None = None
        for row_index, track in enumerate(cset.tracks):
            check = self._add_row(track, row_index, position)
            if group is None:
                group = check
            else:
                check.set_group(group)
        selected = 1 if len(cset.tracks) > 1 else 0
        self._checks[selected].set_active(True)
        self.play_button.set_sensitive(True)
        self._engine.load(cset.tracks, selected=selected, position=position)
        # The engine falls back to another track when the default one fails to load.
        actual = self._engine.selected
        if 0 <= actual < len(self._checks):
            self._checks[actual].set_active(True)
        self._building = False
        if self._peak_loader is not None:
            self._peak_loader.load(
                [track.path for track in cset.tracks], self._engine.selected, self._on_peaks
            )

    def _add_row(self, track: Track, index: int, position: float) -> Gtk.CheckButton:
        check = Gtk.CheckButton(valign=Gtk.Align.START)
        check.update_property([Gtk.AccessibleProperty.LABEL], [track.label])
        check.connect("toggled", self._on_check_toggled, index)

        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        title = Gtk.Label(label=track.label, xalign=0)
        details.append(title)
        if track.is_reference:
            caption = Gtk.Label(label="Reference", xalign=0)
            caption.add_css_class("dim-label")
            caption.add_css_class("caption")
            details.append(caption)
        waveform = WaveformView()
        waveform.set_margin_top(4)
        waveform.set_position(position)
        waveform.on_seek = lambda seconds: self._engine.seek(seconds)
        details.append(waveform)

        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        line.set_margin_top(8)
        line.set_margin_bottom(8)
        line.set_margin_start(12)
        line.set_margin_end(12)
        line.append(check)
        line.append(details)
        row = Gtk.ListBoxRow()
        row.set_child(line)
        self._track_list.append(row)

        self.rows.append(row)
        self.titles.append(title)
        self.waveforms.append(waveform)
        self._checks.append(check)
        return check

    def _select(self, index: int) -> None:
        if not self._checks[index].get_active():
            self._checks[index].set_active(True)
        else:
            self._engine.select(index)

    def _cancel_peaks(self) -> None:
        if self._peak_loader is not None:
            self._peak_loader.cancel()

    # -- signal handlers -------------------------------------------------------

    def _on_check_toggled(self, check: Gtk.CheckButton, index: int) -> None:
        if not check.get_active():
            return
        for row_index, waveform in enumerate(self.waveforms):
            waveform.set_active(row_index == index)
        # Rows are rebuilt before ``load``; the engine gets the selection from it.
        if not self._building:
            self._engine.select(index)

    def _on_row_activated(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        if row in self.rows and row.get_sensitive():
            self._select(self.rows.index(row))

    def _on_input_changed(self, dropdown: Gtk.DropDown, _pspec: object) -> None:
        position = self._engine.position
        if self._engine.playing:
            self._engine.pause()
        self._show_set(dropdown.get_selected(), position=position)

    def _on_open_folder(self, _button: Gtk.Button) -> None:
        window = self._parent or root_window(self.dialog)
        if window is None:
            return
        open_folder_in_file_manager(window, self._output_dir, on_error=self._toast)

    def _on_dialog_closed(self, _dialog: Adw.Dialog) -> None:
        self._cancel_peaks()
        self._engine.unload()
        if self._on_closed is not None:
            self._on_closed()

    def _on_peaks(self, index: int, peaks: Peaks | None) -> None:
        if 0 <= index < len(self.waveforms):
            self.waveforms[index].set_peaks(peaks)

    # -- engine callbacks ------------------------------------------------------

    def _on_position(self, seconds: float) -> None:
        self._elapsed.set_label(_mmss(seconds))
        for waveform in self.waveforms:
            waveform.set_position(seconds)

    def _on_duration(self, seconds: float) -> None:
        self._total.set_label(_mmss(seconds))
        for waveform in self.waveforms:
            waveform.set_timeline(seconds)

    def _on_state(self, playing: bool) -> None:
        self.play_button.set_icon_name(_PAUSE_ICON if playing else _PLAY_ICON)
        self.play_button.update_property(
            [Gtk.AccessibleProperty.LABEL], ["Pause" if playing else "Play"]
        )

    def _on_track_error(self, index: int, message: str) -> None:
        if 0 <= index < len(self.rows):
            self.rows[index].set_sensitive(False)
            self.rows[index].set_tooltip_text(message)

    def _on_engine_error(self, message: str) -> None:
        self.play_button.set_sensitive(False)
        self._toast(f"Couldn't start playback. {message}")

    def _toast(self, message: str) -> None:
        if self._on_toast is not None:
            self._on_toast(message)


__all__ = ["CompareDialog"]
