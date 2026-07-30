"""Shared helpers for modal ``Adw.Dialog`` presentation."""
import typing

from collections.abc import Callable
from typing import Any

from gi.repository import Adw, GLib, Gtk


class CollectInvalid(Exception):
    """Raised by a form ``collect()`` when input is invalid and the dialog should stay open.

    ``message`` is shown as a toast; ``widget`` (when provided) receives the
    ``error`` CSS class so the offending field is highlighted.
    """

    def __init__(self, message: str, widget: Gtk.Widget | None = None):
        super().__init__(message)
        self.message = message
        self.widget = widget


def close_on_escape(window: Gtk.Window) -> None:
    """Bind Escape so secondary ``Adw.Window``s close like ``Adw.Dialog``s."""
    if getattr(window, "_uvr_close_on_escape", False):
        return
    controller = Gtk.ShortcutController()
    controller.set_scope(Gtk.ShortcutScope.LOCAL)
    controller.add_shortcut(
        Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("Escape"),
            Gtk.CallbackAction.new(lambda *_: window.close() or True),
        )
    )
    window.add_controller(controller)
    window._uvr_close_on_escape = True


def _iter_widgets(root: Gtk.Widget):
    yield root
    child = root.get_first_child()
    while child:
        yield from _iter_widgets(child)
        child = child.get_next_sibling()


def _find_dimming_widget(root: Gtk.Widget) -> Gtk.Widget | None:
    for widget in _iter_widgets(root):
        if Gtk.Widget.get_css_name(widget) == "dimming":
            return widget
    return None


def _install_backdrop_dismiss(dimming: Gtk.Widget, on_dismiss: typing.Any) -> None:
    if getattr(dimming, "_uvr_backdrop_dismiss", False):
        return
    gesture = Gtk.GestureClick()
    gesture.connect("released", lambda *_: on_dismiss())
    dimming.add_controller(gesture)
    dimming._uvr_backdrop_dismiss = True


def _try_install_backdrop_dismiss(dialog: Adw.Dialog, parent: Gtk.Window | None) -> None:
    roots = [dialog]
    if parent is not None:
        roots.insert(0, parent)
    for root in roots:
        dimming = _find_dimming_widget(root)
        if dimming is not None:
            _install_backdrop_dismiss(dimming, lambda: dialog.close())
            return


def parent_window_width(parent: Gtk.Window | None, *, fallback: int = 440) -> int:
    """Best-effort width of ``parent`` for sizing a child dialog."""
    if parent is None:
        return fallback
    width = parent.get_width()
    if width > 1:
        return width
    default = parent.get_default_width()
    if default > 0:
        return default
    return fallback


def configure_dialog_width(dialog: Adw.Dialog, parent: Gtk.Window | None, *, fallback: int = 440) -> None:
    """Pin dialog content width to ``parent`` instead of shrinking to natural size."""
    dialog.set_content_width(parent_window_width(parent, fallback=fallback))
    dialog.set_follows_content_size(False)


def fill_dialog_width(widget: Gtk.Widget) -> None:
    """Make dialog body widgets use the full content width."""
    widget.set_hexpand(True)
    widget.set_halign(Gtk.Align.FILL)


def set_dialog_content(dialog: Adw.Dialog, content: Gtk.Widget) -> None:
    """Assign dialog body; an inner ``HeaderBar`` supplies the title and close button."""
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    toolbar.add_top_bar(header)
    toolbar.set_content(content)
    dialog.set_child(toolbar)


def set_form_dialog_content(
    dialog: Adw.Dialog,
    content: Gtk.Widget,
    *,
    on_save: Callable[[], None],
    save_label: str = "Save",
) -> Gtk.Button:
    """Assign dialog body and return its Save button for stateful forms."""
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()

    save = Gtk.Button(label=save_label)
    save.add_css_class("suggested-action")
    save.connect("clicked", lambda *_: on_save())
    header.pack_end(save)

    toolbar.add_top_bar(header)
    toolbar.set_content(content)
    dialog.set_child(toolbar)
    return save


def present_modal_dialog(dialog: Adw.Dialog, parent: Gtk.Window | None = None) -> None:
    """Present a modal dialog; clicking the dimmed backdrop closes it.

    ``Adw.FloatingSheet`` (the default desktop presentation) does not wire
    backdrop clicks to close, unlike ``Adw.BottomSheet``. This helper adds that
    gesture so behavior matches GNOME HIG expectations.
    """
    dialog.set_can_close(True)
    if parent is not None:
        dialog.present(parent)
    else:
        dialog.present()
    GLib.idle_add(_try_install_backdrop_dismiss, dialog, parent)


def run_blocking_dialog(
    dialog: Adw.Dialog,
    parent: Gtk.Window | None,
    *,
    content: Gtk.Widget,
    collect: Callable[[], Any] | None = None,
    save_label: str = "Save",
) -> Any:
    """Present a form dialog and block until it closes; return ``collect()`` on save."""
    state = {"result": None, "done": False}
    loop = GLib.MainLoop()

    def finish() -> None:
        if state["done"]:
            return
        state["done"] = True
        if loop.is_running():
            loop.quit()

    def on_save() -> None:
        if collect is not None:
            try:
                result = collect()
            except CollectInvalid as exc:
                if exc.widget is not None:
                    exc.widget.add_css_class("error")
                toast = Adw.Toast.new(exc.message)
                # Prefer a toast overlay on the dialog content when present.
                overlay = getattr(dialog, "_uvr_toast_overlay", None)
                if overlay is not None:
                    overlay.add_toast(toast)
                else:
                    # Fall back: keep dialog open and surface via parent if possible.
                    parent_toast = getattr(parent, "add_toast", None) if parent else None
                    if callable(parent_toast):
                        parent_toast(toast)
                    elif parent is not None and callable(getattr(parent, "toast", None)):
                        parent.toast(exc.message)
                return
            if result is None:
                # Distinct from CollectInvalid: cancelled / no selection.
                state["result"] = None
                dialog.close()
                return
            state["result"] = result
        dialog.close()

    dialog.connect("closed", lambda *_: finish())
    set_form_dialog_content(
        dialog,
        content,
        on_save=on_save,
        save_label=save_label,
    )
    present_modal_dialog(dialog, parent)
    loop.run()
    return state["result"]
