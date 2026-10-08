"""Dialog and window hosting shared by the listening tools."""

from __future__ import annotations

import os
import unittest
from typing import TYPE_CHECKING

from tests.playback_fakes import FakeEngine, FakeLoader, comparison_set

if TYPE_CHECKING:
    from ui.playback.surface import KeyHandler, PlaybackSurface


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class PlaybackSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tests.private_gtk import require_private_gtk

        require_private_gtk()
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        Adw.init()

    def _surface(
        self,
        *,
        open_in_window: bool = False,
        loader: bool = False,
        commit: bool = False,
        track_keys: bool = True,
        on_key: KeyHandler | None = None,
    ) -> tuple[PlaybackSurface, FakeEngine]:
        from ui.playback.surface import PlaybackSurface
        from ui.playback.view import CompareView

        engine = FakeEngine()
        view = CompareView(engine, peaks=FakeLoader(engine.calls) if loader else None)
        view.show_tracks(comparison_set("song", "Vocals").tracks)
        self.toasts: list[str] = []
        self.closed: list[bool] = []
        surface = PlaybackSurface(
            view,
            title="Compare Stems",
            open_in_window=open_in_window,
            commit=commit,
            track_keys=track_keys,
            on_key=on_key,
            on_toast=self.toasts.append,
            on_closed=lambda: self.closed.append(True),
        )
        return surface, engine

    def _unloads(self, engine: FakeEngine) -> int:
        return engine.calls.count(("unload",))

    def test_shortcuts_are_captured_before_focused_children(self) -> None:
        from gi.repository import Gtk

        # A focused radio or button would otherwise swallow Space before the dialog.
        surface, _ = self._surface()
        self.assertEqual(surface.keys.get_propagation_phase(), Gtk.PropagationPhase.CAPTURE)
        self.assertIs(surface.keys.get_widget(), surface.dialog)

    def test_keys_reach_the_view(self) -> None:
        from gi.repository import Gdk

        surface, engine = self._surface()
        surface.keys.emit("key-pressed", Gdk.KEY_space, 0, Gdk.ModifierType(0))
        self.assertEqual(engine.calls[-1], ("play",))

    def test_title_names_the_dialog(self) -> None:
        surface, _ = self._surface()
        self.assertEqual(surface.dialog.get_title(), "Compare Stems")

    def test_closed_signal_unloads_and_notifies(self) -> None:
        surface, engine = self._surface()
        surface.dialog.emit("closed")
        self.assertEqual(engine.calls[-1], ("unload",))
        self.assertEqual(self.closed, [True])

    def test_closed_signal_cancels_peaks_before_unload(self) -> None:
        surface, engine = self._surface(loader=True)
        engine.calls.clear()
        surface.dialog.emit("closed")
        self.assertEqual(engine.calls, [("peaks.cancel",), ("unload",)])

    def test_pop_out_window_takes_the_dialog_content_size(self) -> None:
        from unittest import mock

        surface, _ = self._surface()
        # A presented dialog spans its parent window; only its content is the sheet.
        with (
            mock.patch.object(surface.dialog, "get_width", return_value=1390),
            mock.patch.object(surface.dialog, "get_height", return_value=890),
            mock.patch.object(surface._toolbar, "get_width", return_value=600),
            mock.patch.object(surface._toolbar, "get_height", return_value=325),
        ):
            surface.pop_out()
        assert surface.window is not None
        self.assertEqual(tuple(surface.window.get_default_size()), (600, 325))

    def test_pop_out_moves_content_into_a_window_without_unloading(self) -> None:
        surface, engine = self._surface()
        self.assertTrue(surface.popout_button.get_visible())
        engine.calls.clear()
        surface.popout_button.emit("clicked")
        window = surface.window
        assert window is not None
        self.assertIsNone(surface.dialog.get_child())
        self.assertIs(window.get_root(), window)
        self.assertIs(surface.view.play_button.get_root(), window)
        self.assertFalse(surface.popout_button.get_visible())
        self.assertNotIn(("unload",), engine.calls)
        self.assertEqual(self.closed, [])
        # The handed-over dialog no longer owns playback.
        surface.dialog.emit("closed")
        self.assertEqual(self.closed, [])
        window.close()
        self.assertEqual(engine.calls[-1], ("unload",))
        self.assertEqual(self.closed, [True])

    def test_shortcuts_follow_the_popped_out_window(self) -> None:
        surface, _ = self._surface()
        surface.pop_out()
        self.assertIs(surface.keys.get_widget(), surface.window)
        surface.close()

    def test_open_in_window_presents_a_window_directly(self) -> None:
        surface, engine = self._surface(open_in_window=True)
        self.assertIsNone(surface.window)
        surface.present(None)
        window = surface.window
        assert window is not None
        self.assertTrue(window.get_visible())
        self.assertEqual(window.get_title(), "Compare Stems")
        # Presenting again raises the same window rather than building another.
        surface.present(None)
        self.assertIs(surface.window, window)
        surface.close()
        self.assertEqual(engine.calls[-1], ("unload",))

    def test_toasts_stay_in_the_popped_out_window(self) -> None:
        surface, _ = self._surface()
        surface.toast("before")
        surface.pop_out()
        surface.toast("after")
        self.assertEqual(self.toasts, ["before"])
        surface.close()

    def test_close_when_popped_out_unloads_once(self) -> None:
        surface, engine = self._surface()
        surface.pop_out()
        surface.close()
        self.assertEqual(self._unloads(engine), 1)
        self.assertEqual(self.closed, [True])

    def test_close_in_dialog_mode_unloads_once(self) -> None:
        surface, engine = self._surface()
        surface.close()
        surface.dialog.emit("closed")
        self.assertEqual(self._unloads(engine), 1)
        self.assertEqual(self.closed, [True])

    def test_engine_error_toasts_through_the_surface(self) -> None:
        surface, engine = self._surface()
        engine.on_error("No audio sink")
        self.assertFalse(surface.view.play_button.get_sensitive())
        self.assertEqual(self.toasts, ["Couldn't start playback. No audio sink"])

    def test_tool_widgets_go_into_the_header(self) -> None:
        from gi.repository import Adw, Gtk

        surface, _ = self._surface()
        start, title = Gtk.Button(), Gtk.Label()
        surface.pack_start(start)
        surface.set_title_widget(title)
        for widget in (start, title):
            self.assertIsNotNone(widget.get_ancestor(Adw.HeaderBar))

    def test_toplevel_prefers_the_popped_out_window(self) -> None:
        from gi.repository import Adw

        surface, _ = self._surface()
        parent = Adw.Window()
        self.addCleanup(parent.close)
        surface._parent = parent
        self.assertIs(surface.toplevel(), parent)
        surface.pop_out()
        self.assertIs(surface.toplevel(), surface.window)
        surface.close()

    def test_commit_surface_hides_title_buttons(self) -> None:
        surface, _ = self._surface(commit=True)
        header = surface._header
        self.assertFalse(header.get_show_start_title_buttons())
        self.assertFalse(header.get_show_end_title_buttons())

    def test_live_surface_keeps_title_buttons(self) -> None:
        surface, _ = self._surface()
        self.assertTrue(surface._header.get_show_end_title_buttons())

    def test_commit_surface_ignores_backdrop_clicks(self) -> None:
        from unittest import mock

        surface, _ = self._surface(commit=True)
        with mock.patch("ui.playback.surface.present_modal_dialog") as present:
            surface.present(None)
        self.assertIs(present.call_args.kwargs["dismiss_on_backdrop"], False)

    def test_track_keys_can_be_hidden(self) -> None:
        surface, _ = self._surface(track_keys=False)
        self.assertEqual([w.get_visible() for w in surface.track_key_rows], [False, False])

    def test_range_keys_are_hidden_by_default(self) -> None:
        surface, _ = self._surface()
        self.assertEqual([w.get_visible() for w in surface.range_key_rows], [False] * 4)

    def test_tool_keys_run_before_the_view(self) -> None:
        from gi.repository import Gdk

        seen: list[tuple[int, Gdk.ModifierType]] = []

        def on_key(keyval: int, state: Gdk.ModifierType) -> bool:
            seen.append((keyval, state))
            return keyval == Gdk.KEY_Left

        surface, engine = self._surface(on_key=on_key)
        shift = Gdk.ModifierType.SHIFT_MASK
        self.assertTrue(surface._on_key_pressed(surface.keys, Gdk.KEY_Left, 0, shift))
        self.assertNotIn("seek", [call[0] for call in engine.calls])
        self.assertTrue(surface._on_key_pressed(surface.keys, Gdk.KEY_Right, 0, shift))
        self.assertEqual(engine.calls[-1][0], "seek")
        self.assertEqual(seen, [(Gdk.KEY_Left, shift), (Gdk.KEY_Right, shift)])

    def test_pack_end_puts_tool_widgets_last(self) -> None:
        from gi.repository import Gtk

        surface, _ = self._surface()
        button = Gtk.Button(label="Apply")
        surface.pack_end(button)
        self.assertIs(button.get_prev_sibling(), surface.end_box)


if __name__ == "__main__":
    unittest.main()
