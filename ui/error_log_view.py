"""Error Log presentation and scroll-following, independent of error storage."""

from collections.abc import Callable

from gi.repository import Adw, Gio, GLib, Gtk

from .template import object_from_builder


class ErrorLogView:
    def __init__(self, builder: Gtk.Builder):
        self.window = object_from_builder(builder, "window", Adw.Window)
        self.buffer = object_from_builder(builder, "buffer", Gtk.TextBuffer)
        self.pages = object_from_builder(builder, "pages", Gtk.Stack)
        self.scroll = object_from_builder(builder, "scroll", Gtk.ScrolledWindow)
        self.jump_button = object_from_builder(builder, "jump_button", Gtk.Button)
        self.jump_revealer = object_from_builder(builder, "jump_revealer", Gtk.Revealer)
        self.copy_button = object_from_builder(builder, "copy_button", Gtk.Button)
        self.toasts = object_from_builder(builder, "toasts", Adw.ToastOverlay)
        self.clear_action = Gio.SimpleAction.new("clear", None)
        actions = Gio.SimpleActionGroup()
        actions.add_action(self.clear_action)
        self.window.insert_action_group("error-log", actions)
        self._text = ""
        self._follow = True
        self._adjusting = False
        self._pending: int | None = None
        self._closed = False
        adjustment = self.scroll.get_vadjustment()
        self._handlers = [
            adjustment.connect("value-changed", self._scrolled),
            adjustment.connect("changed", self._viewport_changed),
        ]
        self._jump_handler = self.jump_button.connect("clicked", self._jump)
        self._copy_handler: int | None = None

    def update(self, text: str) -> None:
        if self._closed:
            return
        if text == self._text:
            self._update_empty_state()
            return
        self._adjusting = True
        try:
            if text.startswith(self._text):
                self.buffer.insert(self.buffer.get_end_iter(), text[len(self._text) :])
            else:
                self.buffer.set_text(text)
            self._text = text
            if not text:
                self._follow = True
        finally:
            self._adjusting = False
        self._update_empty_state()
        self._queue_scroll()

    def _update_empty_state(self) -> None:
        has_text = bool(self._text)
        self.pages.set_visible_child_name("log" if has_text else "empty")
        self.copy_button.set_sensitive(has_text)
        self.clear_action.set_enabled(has_text)
        self._sync_jump()

    def _at_bottom(self) -> bool:
        adj = self.scroll.get_vadjustment()
        return adj.get_value() >= adj.get_upper() - adj.get_page_size() - 2

    def _sync_jump(self) -> None:
        reveal = bool(self._text) and not self._at_bottom()
        self.jump_button.set_can_target(reveal)
        self.jump_button.set_can_focus(reveal)
        self.jump_revealer.set_reveal_child(reveal)

    def _scrolled(self, _adjustment: Gtk.Adjustment) -> None:
        if not self._adjusting and self._pending is None:
            self._follow = self._at_bottom()
        self._sync_jump()

    def _viewport_changed(self, _adjustment: Gtk.Adjustment) -> None:
        self._queue_scroll()

    def _queue_scroll(self) -> None:
        if self._pending is None and not self._closed:
            self._pending = GLib.idle_add(self._settle_scroll)

    def _settle_scroll(self) -> bool:
        self._pending = None
        self._adjusting = True
        try:
            if self._follow:
                adj = self.scroll.get_vadjustment()
                adj.set_value(max(adj.get_lower(), adj.get_upper() - adj.get_page_size()))
            self._sync_jump()
        finally:
            self._adjusting = False
        return GLib.SOURCE_REMOVE

    def _jump(self, _button: Gtk.Button) -> None:
        self._follow = True
        self._queue_scroll()

    def connect_copy(self, callback: Callable[[Gtk.Button], None]) -> None:
        self._copy_handler = self.copy_button.connect("clicked", callback)

    def copied(self) -> None:
        self.toasts.add_toast(Adw.Toast(title="Error log copied"))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.jump_button.disconnect(self._jump_handler)
        if self._copy_handler is not None:
            self.copy_button.disconnect(self._copy_handler)
            self._copy_handler = None
        if self._pending is not None:
            GLib.source_remove(self._pending)
            self._pending = None
        adjustment = self.scroll.get_vadjustment()
        for handler in self._handlers:
            adjustment.disconnect(handler)
        self._handlers.clear()
