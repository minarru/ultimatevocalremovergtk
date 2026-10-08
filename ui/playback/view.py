"""Track list, waveforms and transport shared by the listening tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Sequence

from gi.repository import Adw, Gdk, Gtk, Pango

from core.listening import Track

from ..resources import RESOURCE_PREFIX, require_resource_bundle
from ..widgets.waveform import WaveformView
from .engine import PlaybackControls

if TYPE_CHECKING:
    from core.waveform import Peaks

    from .waveforms import PeakLoading

RowSuffix = Callable[[int, Track], Gtk.Widget | None]

_SEEK_STEP = 5.0
_PLAY_ICON = "media-playback-start-symbolic"
_PAUSE_ICON = "media-playback-pause-symbolic"
_NUMBER_KEYS = {getattr(Gdk, f"KEY_{n}"): n - 1 for n in range(1, 10)}
_NUMBER_KEYS.update({getattr(Gdk, f"KEY_KP_{n}"): n - 1 for n in range(1, 10)})
_TEMPLATE_RESOURCE = f"{RESOURCE_PREFIX}/ui/compare-view.ui"
require_resource_bundle(_TEMPLATE_RESOURCE)


def _mmss(seconds: float) -> str:
    whole = max(0, int(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


def _ignore_error(_message: str) -> None:
    return None


@Gtk.Template(resource_path=_TEMPLATE_RESOURCE)
class CompareView(Gtk.Box):
    """One audible track at a time, each row with its own waveform."""

    __gtype_name__ = "UvrCompareView"

    track_list: Gtk.ListBox = Gtk.Template.Child("track_list")
    play_button: Gtk.Button = Gtk.Template.Child("play_button")
    back_button: Gtk.Button = Gtk.Template.Child("back_button")
    forward_button: Gtk.Button = Gtk.Template.Child("forward_button")
    elapsed_label: Gtk.Label = Gtk.Template.Child("elapsed_label")
    total_label: Gtk.Label = Gtk.Template.Child("total_label")

    def __init__(
        self,
        engine: PlaybackControls,
        *,
        peaks: PeakLoading | None = None,
        row_suffix: RowSuffix | None = None,
    ) -> None:
        Adw.init()
        super().__init__()
        self._engine = engine
        self._peak_loader = peaks
        self._row_suffix = row_suffix
        #: Receives user-facing text when playback cannot start at all.
        self.on_error: Callable[[str], None] = _ignore_error
        self._building = False
        # Peaks still in flight when the view shuts down must not repaint it.
        self._accept_peaks = False
        # The shared time axis: the engine's duration once known, else the longest
        # track whose peaks have arrived, so rows stay aligned if the query fails.
        self._engine_duration = 0.0
        self._peak_duration = 0.0
        self.rows: list[Gtk.ListBoxRow] = []
        self.titles: list[Gtk.Label] = []
        self.waveforms: list[WaveformView] = []
        self.key_hints: list[Gtk.Label] = []
        self.checks: list[Gtk.CheckButton] = []

        self.play_button.connect("clicked", lambda _b: self._engine.toggle())
        self.back_button.connect("clicked", lambda _b: self._skip(-_SEEK_STEP))
        self.forward_button.connect("clicked", lambda _b: self._skip(_SEEK_STEP))
        self.track_list.connect("row-activated", self._on_row_activated)

        engine.on_position = self._on_position
        engine.on_duration = self._on_duration
        engine.on_state = self._on_state
        engine.on_track_error = self._on_track_error
        engine.on_error = self._on_engine_error

    # -- public ----------------------------------------------------------------

    def show_tracks(
        self, tracks: Sequence[Track], *, selected: int | None = None, position: float = 0.0
    ) -> None:
        """Rebuild the rows and load ``tracks``; ``selected`` defaults to the first output."""
        self._cancel_peaks()
        self._building = True
        for row in self.rows:
            self.track_list.remove(row)
        self.rows = []
        self.titles = []
        self.waveforms = []
        self.key_hints = []
        self.checks = []
        self._engine_duration = 0.0
        self._peak_duration = 0.0
        self._apply_timeline()
        if not tracks:
            self._building = False
            self.play_button.set_sensitive(False)
            return
        group: Gtk.CheckButton | None = None
        for row_index, track in enumerate(tracks):
            check = self._add_row(track, row_index, position)
            if group is None:
                group = check
            else:
                check.set_group(group)
        if selected is None or not 0 <= selected < len(tracks):
            selected = 1 if len(tracks) > 1 else 0
        self.checks[selected].set_active(True)
        self.play_button.set_sensitive(True)
        self._engine.load(tracks, selected=selected, position=position)
        # The engine falls back to another track when the default one fails to load.
        actual = self._engine.selected
        if 0 <= actual < len(self.checks):
            self.checks[actual].set_active(True)
        self._building = False
        self._accept_peaks = True
        if self._peak_loader is not None:
            self._peak_loader.load(
                [track.path for track in tracks], self._engine.selected, self._on_peaks
            )

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

    def shutdown(self) -> None:
        """Stop peak work, then release the audio device."""
        self._cancel_peaks()
        self._engine.unload()

    # -- building --------------------------------------------------------------

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
        suffix = self._row_suffix(index, track) if self._row_suffix is not None else None
        if suffix is not None:
            header.append(suffix)

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
        self.track_list.append(row)

        self.rows.append(row)
        self.titles.append(title)
        self.waveforms.append(waveform)
        self.checks.append(check)
        return check

    def _select(self, index: int) -> None:
        if not self.checks[index].get_active():
            self.checks[index].set_active(True)
        else:
            self._engine.select(index)

    def _skip(self, seconds: float) -> None:
        self._engine.seek(self._engine.position + seconds)

    def _cancel_peaks(self) -> None:
        self._accept_peaks = False
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

    def _on_peaks(self, index: int, peaks: Peaks | None) -> None:
        if not self._accept_peaks or not 0 <= index < len(self.waveforms):
            return
        self.waveforms[index].set_peaks(peaks)
        if peaks is not None and peaks.duration > self._peak_duration:
            self._peak_duration = peaks.duration
            self._apply_timeline()

    def _apply_timeline(self) -> None:
        timeline = self._engine_duration if self._engine_duration > 0 else self._peak_duration
        self.total_label.set_label(_mmss(timeline))
        for waveform in self.waveforms:
            waveform.set_timeline(timeline)

    # -- engine callbacks ------------------------------------------------------

    def _on_position(self, seconds: float) -> None:
        self.elapsed_label.set_label(_mmss(seconds))
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
        self.on_error(f"Couldn't start playback. {message}")


__all__ = ["CompareView", "RowSuffix"]
