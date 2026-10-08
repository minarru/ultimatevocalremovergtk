"""Dialog or window hosting for a listening tool's ``CompareView``.

A surface opens as an ``Adw.Dialog`` over the main window, or as its own window
when ``ui.listening_in_window`` is set; the dialog can pop out into a window
without interrupting playback. Construction wires ``view.on_error`` to the
surface toast, so callers load tracks only after the surface exists.
"""

from __future__ import annotations

from typing import Callable

from gi.repository import Adw, Gdk, Gtk

from ..dialogs.utils import close_on_escape, present_modal_dialog
from ..gtk_narrow import root_window
from ..template import load_builder, object_from_builder
from ..widgets.color_fade import FadingWindow
from .view import CompareView

_WINDOW_MIN_WIDTH = 360
_WINDOW_MIN_HEIGHT = 294
_WINDOW_DEFAULT_WIDTH = 600

#: A tool's own keys, tried before the view's; True when the key was handled.
KeyHandler = Callable[[int, Gdk.ModifierType], bool]


class PlaybackSurface:
    def __init__(
        self,
        view: CompareView,
        *,
        title: str,
        open_in_window: bool = False,
        commit: bool = False,
        track_keys: bool = True,
        range_keys: bool = False,
        on_key: KeyHandler | None = None,
        on_toast: Callable[[str], None] | None = None,
        on_closed: Callable[[], None] | None = None,
    ) -> None:
        self.view = view
        self._title = title
        self._open_in_window = open_in_window
        # A commit surface holds edits until its own Apply: no close button and
        # no closing on a backdrop click, so a stray click cannot discard them.
        self._commit = commit
        self._on_toast = on_toast
        self._on_closed = on_closed
        self._parent: Gtk.Window | None = None
        self._finished = False
        # Set once the content moves out of the dialog into its own window.
        self.window: FadingWindow | None = None
        self._window_toasts: Adw.ToastOverlay | None = None

        builder = load_builder("playback-surface")
        self.dialog = object_from_builder(builder, "dialog", Adw.Dialog)
        self._toolbar = object_from_builder(builder, "toolbar", Adw.ToolbarView)
        self._header = object_from_builder(builder, "header", Adw.HeaderBar)
        self.popout_button = object_from_builder(builder, "popout_button", Gtk.Button)
        self.end_box = object_from_builder(builder, "end_box", Gtk.Box)
        self.track_key_rows: tuple[Gtk.Widget, Gtk.Widget] = (
            object_from_builder(builder, "track_keys_key", Gtk.Label),
            object_from_builder(builder, "track_keys_label", Gtk.Label),
        )
        for widget in self.track_key_rows:
            widget.set_visible(track_keys)
        self.range_key_rows: tuple[Gtk.Widget, ...] = tuple(
            object_from_builder(builder, name, Gtk.Label)
            for name in (
                "range_keys_key",
                "range_keys_label",
                "length_keys_key",
                "length_keys_label",
            )
        )
        for widget in self.range_key_rows:
            widget.set_visible(range_keys)
        if commit:
            self._header.set_show_start_title_buttons(False)
            self._header.set_show_end_title_buttons(False)
        self.dialog.set_title(title)
        self._toolbar.set_content(view)
        view.on_error = self.toast
        self.popout_button.connect("clicked", lambda _b: self.pop_out())
        self._dialog_closed_id = self.dialog.connect("closed", self._on_dialog_closed)

        # Capture phase: a focused radio or button would otherwise consume Space first.
        self.keys = Gtk.EventControllerKey()
        self.keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._on_key = on_key
        self.keys.connect("key-pressed", self._on_key_pressed)
        self.dialog.add_controller(self.keys)

    # -- tool content ----------------------------------------------------------

    def pack_start(self, widget: Gtk.Widget) -> None:
        self._header.pack_start(widget)

    def pack_end(self, widget: Gtk.Widget) -> None:
        """Add ``widget`` at the far end, after the surface's own buttons."""
        self._header.remove(self.end_box)
        self._header.pack_end(widget)
        self._header.pack_end(self.end_box)

    def set_title_widget(self, widget: Gtk.Widget) -> None:
        self._header.set_title_widget(widget)

    # -- hosting ---------------------------------------------------------------

    def present(self, parent: Gtk.Window | None) -> None:
        self._parent = parent
        if self.window is not None:
            self.window.present()
        elif self._open_in_window:
            self.pop_out()
        else:
            present_modal_dialog(self.dialog, parent, dismiss_on_backdrop=not self._commit)

    def pop_out(self) -> None:
        """Move the content into its own window, keeping playback running."""
        if self.window is not None:
            return
        width = self.dialog.get_width() or _WINDOW_DEFAULT_WIDTH
        height = self.dialog.get_height() or -1
        # Closing the dialog now only hands its content over; it must not unload.
        self.dialog.disconnect(self._dialog_closed_id)
        self.dialog.remove_controller(self.keys)
        self.dialog.set_child(None)
        if self.dialog.get_parent() is not None:
            self.dialog.force_close()

        window = FadingWindow(title=self._title)
        window.set_default_size(max(width, _WINDOW_MIN_WIDTH), height)
        window.set_size_request(_WINDOW_MIN_WIDTH, _WINDOW_MIN_HEIGHT)
        if self._parent is not None:
            window.set_transient_for(self._parent)
        toasts = Adw.ToastOverlay(child=self._toolbar)
        window.set_content(toasts)
        window.add_controller(self.keys)
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
        self._finish()

    def toplevel(self) -> Gtk.Window | None:
        """The window a tool's own dialogs should sit over."""
        return self.window or self._parent or root_window(self.dialog)

    def toast(self, message: str) -> None:
        # The main window may be hidden behind a popped-out window.
        if self._window_toasts is not None:
            self._window_toasts.add_toast(Adw.Toast.new(message))
        elif self._on_toast is not None:
            self._on_toast(message)

    # -- signal handlers -------------------------------------------------------

    def _on_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        if self._on_key is not None and self._on_key(keyval, state):
            return True
        return self.view.handle_key(keyval)

    def _on_dialog_closed(self, _dialog: Adw.Dialog) -> None:
        self._finish()

    def _on_window_close_request(self, _window: Gtk.Window) -> bool:
        self._finish()
        return False

    def _finish(self) -> None:
        # Both an explicit close and the dialog's own ``closed`` can arrive.
        if self._finished:
            return
        self._finished = True
        self.view.shutdown()
        if self._on_closed is not None:
            self._on_closed()


__all__ = ["KeyHandler", "PlaybackSurface"]
