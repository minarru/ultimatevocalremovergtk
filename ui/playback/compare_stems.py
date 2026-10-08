"""Compare Stems: one input's tracks at a time, one audible at a time."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Sequence

from gi.repository import Gtk

from core.listening import ComparisonSet

from ..files import open_folder_in_file_manager
from ..template import load_builder, object_from_builder
from .engine import PlaybackControls
from .input_picker import InputPicker
from .surface import PlaybackSurface
from .view import CompareView

if TYPE_CHECKING:
    from .waveforms import PeakLoading

_TITLE = "Compare Stems"


class CompareStemsDialog:
    def __init__(
        self,
        sets: Sequence[ComparisonSet],
        engine: PlaybackControls,
        *,
        waveforms: PeakLoading | None = None,
        output_dir: str = "",
        on_toast: Callable[[str], None] | None = None,
        on_closed: Callable[[], None] | None = None,
        open_in_window: bool = False,
    ) -> None:
        self._sets = list(sets)
        self._engine = engine
        self._output_dir = output_dir
        self.view = CompareView(engine, peaks=waveforms)
        self.surface = PlaybackSurface(
            self.view,
            title=_TITLE,
            open_in_window=open_in_window,
            on_toast=on_toast,
            on_closed=on_closed,
        )

        builder = load_builder("compare-stems")
        self.folder_button = object_from_builder(builder, "folder_button", Gtk.Button)
        self.picker = InputPicker(_TITLE, [s.name for s in self._sets], self._on_input_changed)
        self.window_title = self.picker.window_title
        self.input_dropdown = self.picker.dropdown
        self.surface.pack_start(self.folder_button)
        self.surface.set_title_widget(self.picker.widget)
        self.folder_button.set_visible(bool(output_dir))
        self.folder_button.connect("clicked", self._on_open_folder)

        if self._sets:
            self.view.show_tracks(self._sets[0].tracks)

    def present(self, parent: Gtk.Window | None) -> None:
        self.surface.present(parent)

    def close(self) -> None:
        self.surface.close()

    def _on_input_changed(self, index: int) -> None:
        position = self._engine.position
        if self._engine.playing:
            self._engine.pause()
        self.view.show_tracks(self._sets[index].tracks, position=position)

    def _on_open_folder(self, _button: Gtk.Button) -> None:
        window = self.surface.toplevel()
        if window is None:
            return
        open_folder_in_file_manager(window, self._output_dir, on_error=self.surface.toast)


__all__ = ["CompareStemsDialog"]
