"""Compare stems dialog: one input's tracks, one audible at a time."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Sequence

from gi.repository import Adw, Gdk, GObject, Gtk, Pango

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


def _input_factory(*, ellipsize: bool) -> Gtk.SignalListItemFactory:
    """Input names for the header picker; the button ellipsizes, the list does not."""
    factory = Gtk.SignalListItemFactory()

    def setup(_factory: Gtk.SignalListItemFactory, item: GObject.Object) -> None:
        if not isinstance(item, Gtk.ListItem):
            return
        label = Gtk.Label(xalign=0)
        if ellipsize:
            label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            label.set_max_width_chars(28)
        item.set_child(label)

    def bind(_factory: Gtk.SignalListItemFactory, item: GObject.Object) -> None:
        if not isinstance(item, Gtk.ListItem):
            return
        label, name = item.get_child(), item.get_item()
        if isinstance(label, Gtk.Label) and isinstance(name, Gtk.StringObject):
            label.set_label(name.get_string())

    factory.connect("setup", setup)
    factory.connect("bind", bind)
    return factory


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
        # The shared time axis: the engine's duration once known, else the longest
        # track whose peaks have arrived, so rows stay aligned if the query fails.
        self._engine_duration = 0.0
        self._peak_duration = 0.0

        builder = load_builder("compare-stems-dialog")
        self.dialog = object_from_builder(builder, "dialog", Adw.Dialog)
        self.window_title = object_from_builder(builder, "window_title", Adw.WindowTitle)
        self.input_dropdown = object_from_builder(builder, "input_dropdown", Gtk.DropDown)
        self._track_list = object_from_builder(builder, "track_list", Gtk.ListBox)
        self.play_button = object_from_builder(builder, "play_button", Gtk.Button)
        self.back_button = object_from_builder(builder, "back_button", Gtk.Button)
        self.forward_button = object_from_builder(builder, "forward_button", Gtk.Button)
        self._elapsed = object_from_builder(builder, "elapsed_label", Gtk.Label)
        self._total = object_from_builder(builder, "total_label", Gtk.Label)
        self.folder_button = object_from_builder(builder, "folder_button", Gtk.Button)
        self.rows: list[Gtk.ListBoxRow] = []
        self.titles: list[Gtk.Label] = []
        self.waveforms: list[WaveformView] = []
        self.key_hints: list[Gtk.Label] = []
        self._checks: list[Gtk.CheckButton] = []

        self.play_button.connect("clicked", lambda _b: self._engine.toggle())
        self.back_button.connect("clicked", lambda _b: self._skip(-_SEEK_STEP))
        self.forward_button.connect("clicked", lambda _b: self._skip(_SEEK_STEP))
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
            self.input_dropdown.set_factory(_input_factory(ellipsize=True))
            self.input_dropdown.set_list_factory(_input_factory(ellipsize=False))
            self.input_dropdown.set_model(Gtk.StringList.new(names))
            self.window_title.set_visible(False)
            self.input_dropdown.set_visible(True)
            self.input_dropdown.connect("notify::selected", self._on_input_changed)
        elif self._sets:
            self.window_title.set_subtitle(self._sets[0].name)
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
            self._skip(-_SEEK_STEP)
            return True
        if keyval == Gdk.KEY_Right:
            self._skip(_SEEK_STEP)
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
        self.key_hints = []
        self._checks = []
        self._engine_duration = 0.0
        self._peak_duration = 0.0
        self._apply_timeline()
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
        check = Gtk.CheckButton()
        check.update_property([Gtk.AccessibleProperty.LABEL], [track.label])
        check.connect("toggled", self._on_check_toggled, index)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.append(check)
        title = Gtk.Label(label=track.label, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        header.append(title)
        if track.is_reference:
            badge = Gtk.Label(label="Reference", valign=Gtk.Align.CENTER)
            badge.add_css_class("uvr-pill")
            header.append(badge)
        header.append(Gtk.Box(hexpand=True))
        if index < len(_NUMBER_KEYS) // 2:
            hint = Gtk.Label(label=str(index + 1), valign=Gtk.Align.CENTER)
            hint.add_css_class("uvr-keycap")
            hint.add_css_class("dim-label")
            # The radio already names the row; the key is a visual aid only.
            hint.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
            header.append(hint)
            self.key_hints.append(hint)

        waveform = WaveformView(track.label)
        waveform.set_position(position)
        waveform.on_seek = lambda seconds: self._engine.seek(seconds)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        body.set_margin_top(10)
        body.set_margin_bottom(10)
        body.set_margin_start(12)
        body.set_margin_end(12)
        body.append(header)
        body.append(waveform)
        row = Gtk.ListBoxRow()
        row.add_css_class("uvr-compare-row")
        row.set_child(body)
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

    def _skip(self, seconds: float) -> None:
        self._engine.seek(self._engine.position + seconds)

    def _cancel_peaks(self) -> None:
        if self._peak_loader is not None:
            self._peak_loader.cancel()

    # -- signal handlers -------------------------------------------------------

    def _on_check_toggled(self, check: Gtk.CheckButton, index: int) -> None:
        if not check.get_active():
            return
        for row_index, (row, waveform) in enumerate(zip(self.rows, self.waveforms, strict=True)):
            waveform.set_active(row_index == index)
            if row_index == index:
                row.add_css_class("uvr-compare-active")
            else:
                row.remove_css_class("uvr-compare-active")
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
        if not 0 <= index < len(self.waveforms):
            return
        self.waveforms[index].set_peaks(peaks)
        if peaks is not None and peaks.duration > self._peak_duration:
            self._peak_duration = peaks.duration
            self._apply_timeline()

    def _apply_timeline(self) -> None:
        timeline = self._engine_duration if self._engine_duration > 0 else self._peak_duration
        self._total.set_label(_mmss(timeline))
        for waveform in self.waveforms:
            waveform.set_timeline(timeline)

    # -- engine callbacks ------------------------------------------------------

    def _on_position(self, seconds: float) -> None:
        self._elapsed.set_label(_mmss(seconds))
        for waveform in self.waveforms:
            waveform.set_position(seconds)

    def _on_duration(self, seconds: float) -> None:
        self._engine_duration = max(0.0, seconds)
        self._apply_timeline()

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
