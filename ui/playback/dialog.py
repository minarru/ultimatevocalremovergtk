"""Compare stems dialog: one input's tracks, one audible at a time."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Sequence

from gi.repository import Adw, GObject, Gtk, Pango

from core.listening import ComparisonSet

from ..dialogs.utils import close_on_escape, present_modal_dialog
from ..files import open_folder_in_file_manager
from ..gtk_narrow import root_window
from ..template import load_builder, object_from_builder
from ..widgets.color_fade import FadingWindow
from .engine import PlaybackControls
from .view import CompareView

if TYPE_CHECKING:
    from .waveforms import PeakLoading

_TITLE = "Compare Stems"
_WINDOW_MIN_WIDTH = 360
_WINDOW_MIN_HEIGHT = 294
_WINDOW_DEFAULT_WIDTH = 600


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
        open_in_window: bool = False,
    ) -> None:
        self._sets = list(sets)
        self._engine = engine
        self._output_dir = output_dir
        self._on_toast = on_toast
        self._on_closed = on_closed
        self._parent: Gtk.Window | None = None
        self._open_in_window = open_in_window
        # Set once the content moves out of the dialog into its own window.
        self.window: FadingWindow | None = None
        self._window_toasts: Adw.ToastOverlay | None = None

        builder = load_builder("compare-stems-dialog")
        self.dialog = object_from_builder(builder, "dialog", Adw.Dialog)
        self._toolbar = object_from_builder(builder, "toolbar", Adw.ToolbarView)
        self.window_title = object_from_builder(builder, "window_title", Adw.WindowTitle)
        self.input_dropdown = object_from_builder(builder, "input_dropdown", Gtk.DropDown)
        self.folder_button = object_from_builder(builder, "folder_button", Gtk.Button)
        self.popout_button = object_from_builder(builder, "popout_button", Gtk.Button)
        self.view = CompareView(engine, peaks=waveforms)
        self.view.on_error = self._toast
        self._toolbar.set_content(self.view)

        self.folder_button.set_visible(bool(output_dir))
        self.folder_button.connect("clicked", self._on_open_folder)
        self.popout_button.connect("clicked", lambda _b: self.pop_out())
        self._dialog_closed_id = self.dialog.connect("closed", self._on_dialog_closed)

        # Capture phase: a focused radio or button would otherwise consume Space first.
        self._keys = Gtk.EventControllerKey()
        self._keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._keys.connect(
            "key-pressed", lambda _c, keyval, _code, _state: self.view.handle_key(keyval)
        )
        self.dialog.add_controller(self._keys)

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
        if self._sets:
            self.view.show_tracks(self._sets[0].tracks)

    # -- public ----------------------------------------------------------------

    def present(self, parent: Gtk.Window | None) -> None:
        self._parent = parent
        if self.window is not None:
            self.window.present()
        elif self._open_in_window:
            self.pop_out()
        else:
            present_modal_dialog(self.dialog, parent)

    def pop_out(self) -> None:
        """Move the content into its own window, keeping playback running."""
        if self.window is not None:
            return
        width = self.dialog.get_width() or _WINDOW_DEFAULT_WIDTH
        height = self.dialog.get_height() or -1
        # Closing the dialog now only hands its content over; it must not unload.
        self.dialog.disconnect(self._dialog_closed_id)
        self.dialog.remove_controller(self._keys)
        self.dialog.set_child(None)
        if self.dialog.get_parent() is not None:
            self.dialog.force_close()

        window = FadingWindow(title=_TITLE)
        window.set_default_size(max(width, _WINDOW_MIN_WIDTH), height)
        window.set_size_request(_WINDOW_MIN_WIDTH, _WINDOW_MIN_HEIGHT)
        if self._parent is not None:
            window.set_transient_for(self._parent)
        toasts = Adw.ToastOverlay(child=self._toolbar)
        window.set_content(toasts)
        window.add_controller(self._keys)
        close_on_escape(window)
        window.connect("close-request", self._on_window_close_request)
        self.popout_button.set_visible(False)
        self.window = window
        self._window_toasts = toasts
        window.present()

    def close(self) -> None:
        if self.window is not None:
            self.window.close()
        else:
            self.dialog.force_close()
        self.view.shutdown()

    # -- signal handlers -------------------------------------------------------

    def _on_input_changed(self, dropdown: Gtk.DropDown, _pspec: object) -> None:
        position = self._engine.position
        if self._engine.playing:
            self._engine.pause()
        self.view.show_tracks(self._sets[dropdown.get_selected()].tracks, position=position)

    def _on_open_folder(self, _button: Gtk.Button) -> None:
        window = self.window or self._parent or root_window(self.dialog)
        if window is None:
            return
        open_folder_in_file_manager(window, self._output_dir, on_error=self._toast)

    def _on_dialog_closed(self, _dialog: Adw.Dialog) -> None:
        self._finish()

    def _on_window_close_request(self, _window: Gtk.Window) -> bool:
        self._finish()
        return False

    def _finish(self) -> None:
        self.view.shutdown()
        if self._on_closed is not None:
            self._on_closed()

    def _toast(self, message: str) -> None:
        # The main window may be hidden behind a popped-out window.
        if self._window_toasts is not None:
            self._window_toasts.add_toast(Adw.Toast.new(message))
        elif self._on_toast is not None:
            self._on_toast(message)


__all__ = ["CompareDialog"]
