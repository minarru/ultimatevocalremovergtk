"""Classic palettes follow the Tkinter colors and clear when another scheme is chosen."""

from __future__ import annotations

import os
import typing
import unittest

if typing.TYPE_CHECKING:
    from gi.repository import Gdk, Graphene


def _channel(color: object, name: str) -> float:
    return float(getattr(color, name))


def _rgba(spec: str) -> Gdk.RGBA:
    from gi.repository import Gdk

    color = Gdk.RGBA()
    color.parse(spec)
    return color


def _rect() -> Graphene.Rect:
    from gi.repository import Graphene

    return Graphene.Rect().init(0, 0, 10, 10)


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class ClassicPaletteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tests.private_gtk import require_private_gtk

        require_private_gtk()
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.color-scheme")
        cls._app.register()

    def tearDown(self) -> None:
        from ui.application import apply_color_scheme

        apply_color_scheme("auto")

    def test_classic_and_classic_light_recolor_the_window(self) -> None:
        from gi.repository import Adw, GLib, Gtk

        from ui.application import apply_color_scheme
        from ui.preferences import _COLOR_SCHEME_OPTIONS

        self.assertEqual(
            [value for _label, value in _COLOR_SCHEME_OPTIONS],
            ["auto", "light", "dark", "classic", "classic-light"],
        )
        style = Adw.StyleManager.get_default()

        classic = self._foreground("classic")
        self.assertEqual(style.get_color_scheme(), Adw.ColorScheme.FORCE_DARK)
        self.assertAlmostEqual(_channel(classic, "red"), 244 / 255, delta=0.02)
        self.assertAlmostEqual(_channel(classic, "green"), 244 / 255, delta=0.02)
        self.assertAlmostEqual(_channel(classic, "blue"), 244 / 255, delta=0.02)

        classic_light = self._foreground("classic-light")
        self.assertEqual(style.get_color_scheme(), Adw.ColorScheme.FORCE_LIGHT)
        self.assertAlmostEqual(_channel(classic_light, "red"), 14 / 255, delta=0.02)
        self.assertAlmostEqual(_channel(classic_light, "green"), 14 / 255, delta=0.02)
        self.assertAlmostEqual(_channel(classic_light, "blue"), 15 / 255, delta=0.02)

        apply_color_scheme("dark")
        restored = self._foreground("dark")
        self.assertEqual(style.get_color_scheme(), Adw.ColorScheme.FORCE_DARK)
        self.assertGreater(_channel(restored, "red"), 0.99)
        del GLib, Gtk

    def test_scheme_changes_fade_only_when_the_scheme_differs(self) -> None:
        from unittest.mock import patch

        from ui.application import apply_color_scheme

        apply_color_scheme("dark")
        with patch("ui.application.begin_color_fades") as fade:
            apply_color_scheme("dark")
            fade.assert_not_called()
            apply_color_scheme("classic")
            apply_color_scheme("classic")
            self.assertEqual(fade.call_count, 1)
            apply_color_scheme("not-a-scheme")
            apply_color_scheme("auto")
            self.assertEqual(fade.call_count, 2)

    def test_color_fade_draws_the_captured_frame_until_the_animation_ends(self) -> None:
        from gi.repository import GLib, Gtk

        from ui.widgets.color_fade import ColorFade

        class _FadingWindow(Gtk.Window):
            def __init__(self) -> None:
                super().__init__()
                self.fade = ColorFade(self)

            def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
                frame = Gtk.Snapshot()
                Gtk.Window.do_snapshot(self, frame)
                self.fade.draw(snapshot, frame.to_node())

        window = _FadingWindow()
        window.add_css_class("background")
        window.set_default_size(80, 60)
        fade = window.fade
        fade.begin()
        self.assertFalse(fade.active, "an unmapped window has no frame to fade from")

        settings = Gtk.Settings.get_default()
        assert settings is not None
        animations = settings.get_property("gtk-enable-animations")
        settings.set_property("gtk-enable-animations", True)
        self.addCleanup(settings.set_property, "gtk-enable-animations", animations)
        window.present()
        self.addCleanup(window.close)
        context = GLib.MainContext.default()
        deadline = GLib.get_monotonic_time() + 2_000_000
        while (
            not window.get_mapped() or fade._last_frame is None
        ) and GLib.get_monotonic_time() < deadline:
            context.iteration(False)
        fade.begin()
        self.assertTrue(fade.active, "the window keeps the frame it last drew")
        alphas: set[float] = set()
        deadline = GLib.get_monotonic_time() + 3_000_000
        while fade.active and GLib.get_monotonic_time() < deadline:
            context.iteration(False)
            alphas.add(fade._alpha)
        self.assertFalse(fade.active)
        self.assertTrue(any(0.0 < alpha < 1.0 for alpha in alphas), alphas)

        class _Clock:
            def __init__(self) -> None:
                self.now = 0

            def get_frame_time(self) -> int:
                return self.now

        clock = _Clock()
        fade.begin()
        fade._on_tick(window, clock)  # pyright: ignore[reportArgumentType]
        clock.now = 400_000
        fade._on_tick(window, clock)  # pyright: ignore[reportArgumentType]
        self.assertTrue(fade.active, "a stalled frame must not consume the fade")
        self.assertGreater(fade._alpha, 0.5)

        settings.set_property("gtk-enable-animations", False)
        fade.begin()
        self.assertFalse(fade.active, "disabled animations skip straight to the new colors")

    def test_palette_sits_below_the_users_gtk_css(self) -> None:
        from gi.repository import Gtk

        from ui import resources

        self.assertGreater(resources._PALETTE_PRIORITY, resources._DEV_CSS_PRIORITY)
        self.assertGreater(resources._DEV_CSS_PRIORITY, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.assertLess(resources._PALETTE_PRIORITY, Gtk.STYLE_PROVIDER_PRIORITY_USER)

    def test_builder_windows_take_part_in_scheme_fades(self) -> None:
        from unittest.mock import patch

        from gi.repository import Adw

        from ui.template import load_builder, object_from_builder
        from ui.widgets.color_fade import FadingWindow, begin_color_fades

        for name in ("download-center", "error-console"):
            window = object_from_builder(load_builder(name), "window", Adw.Window)
            self.assertIsInstance(window, FadingWindow, name)
        window = FadingWindow()
        window.present()
        self.addCleanup(window.close)
        with patch.object(FadingWindow, "begin_color_fade") as begin:
            begin_color_fades()
        begin.assert_called()

    def test_a_fade_during_a_fade_starts_from_the_blend_on_screen(self) -> None:
        from gi.repository import Gsk, Gtk

        from ui.widgets.color_fade import ColorFade

        fade = ColorFade(Gtk.Box())
        old = Gsk.ColorNode.new(_rgba("red"), _rect())
        new = Gsk.ColorNode.new(_rgba("blue"), _rect())
        fade._image = old
        fade._alpha = 0.5
        fade.draw(Gtk.Snapshot(), new)
        last = fade._last_frame
        assert last is not None
        self.assertIsNot(last, new, "mid-fade the recorded frame includes the old image")
        self.assertIsNot(last, old)

    def _foreground(self, name: str) -> object:
        from gi.repository import GLib, Gtk

        from ui.application import apply_color_scheme

        apply_color_scheme(name)
        window = Gtk.Window()
        window.add_css_class("background")
        window.set_default_size(80, 60)
        window.present()
        self.addCleanup(window.close)
        deadline = GLib.get_monotonic_time() + 2_000_000
        color = window.get_color()
        while GLib.get_monotonic_time() < deadline:
            GLib.MainContext.default().iteration(False)
            color = window.get_color()
            if window.get_realized() and _channel(color, "alpha") > 0:
                break
        return color
