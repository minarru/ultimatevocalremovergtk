"""Rendered Download Center controls for the public model catalogue."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock


def _purpose_page_titles(stack: Any) -> list[str]:
    """Titles in PURPOSE_PAGE_OPTIONS order, for Adw.ViewStack or Gtk.Stack."""
    from core.model_scores import PURPOSE_PAGE_OPTIONS

    titles: list[str] = []
    for value, _label in PURPOSE_PAGE_OPTIONS:
        child = stack.get_child_by_name(value)
        if child is None:
            titles.append("")
            continue
        page = stack.get_page(child)
        titles.append(page.get_title() or "")
    return titles


@unittest.skipUnless(
    os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"),
    "GTK widget construction needs a display",
)
class DownloadCenterPublicUiTests(unittest.TestCase):
    def test_header_has_public_menu_without_password_control(self) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        from core.downloads import DownloadManager
        from core.settings import Settings
        from ui.download_center import DownloadCenterWindow

        context = SimpleNamespace(settings=Settings.defaults())
        center = DownloadCenterWindow(None, context, DownloadManager(), mock.MagicMock())
        self.addCleanup(center.window.destroy)

        icon_names: list[str] = []
        stack: list[Gtk.Widget] = [center.window]
        while stack:
            widget = stack.pop()
            if isinstance(widget, (Gtk.Button, Gtk.MenuButton)):
                icon = widget.get_icon_name()
                if icon:
                    icon_names.append(icon)
            child = widget.get_first_child()
            while child is not None:
                stack.append(child)
                child = child.get_next_sibling()

        self.assertIn("open-menu-symbolic", icon_names)
        self.assertNotIn("dialog-password-symbolic", icon_names)

    def test_header_switcher_uses_purpose_pages(self) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk

        from core.downloads import DownloadManager
        from core.model_scores import PURPOSE_PAGE_OPTIONS, PURPOSE_VOCALS
        from core.settings import Settings
        from ui.download_center import DownloadCenterWindow

        context = SimpleNamespace(settings=Settings.defaults())
        center = DownloadCenterWindow(None, context, DownloadManager(), mock.MagicMock())
        self.addCleanup(center.window.destroy)

        self.assertEqual(center.stack.get_visible_child_name(), PURPOSE_VOCALS)
        # libadwaita 1.7+ uses InlineViewSwitcher + ViewStack; CI's Ubuntu
        # gir1.2-adw-1 does not, so Download Center falls back to Gtk.Stack.
        self.assertIsInstance(center.stack, (Adw.ViewStack, Gtk.Stack))
        self.assertEqual(
            _purpose_page_titles(center.stack),
            [label for _value, label in PURPOSE_PAGE_OPTIONS],
        )
        inline_switcher_type = getattr(Adw, "InlineViewSwitcher", None)
        if inline_switcher_type is not None and isinstance(center.switcher, inline_switcher_type):
            self.assertFalse(cast(Any, center.switcher).get_homogeneous())
        else:
            self.assertIsInstance(center.switcher, Gtk.StackSwitcher)

    def test_header_switcher_falls_back_without_inline_view_switcher(self) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Gtk

        from core.downloads import DownloadManager
        from core.model_scores import PURPOSE_PAGE_OPTIONS, PURPOSE_VOCALS
        from core.settings import Settings
        from ui.download_center import DownloadCenterWindow

        real_hasattr = hasattr

        def _hasattr(obj: object, name: str) -> bool:
            if name == "InlineViewSwitcher":
                return False
            return real_hasattr(obj, name)

        context = SimpleNamespace(settings=Settings.defaults())
        with mock.patch("ui.download_center.hasattr", _hasattr):
            center = DownloadCenterWindow(None, context, DownloadManager(), mock.MagicMock())
        self.addCleanup(center.window.destroy)

        self.assertIsInstance(center.stack, Gtk.Stack)
        self.assertIsInstance(center.switcher, Gtk.StackSwitcher)
        self.assertEqual(center.stack.get_visible_child_name(), PURPOSE_VOCALS)
        self.assertEqual(
            _purpose_page_titles(center.stack),
            [label for _value, label in PURPOSE_PAGE_OPTIONS],
        )

    def test_network_filter_options_are_arch_value_then_label(self) -> None:
        from bundled.constants import MDX_ARCH_TYPE, VR_ARCH_TYPE
        from core.model_scores import (
            ARCH_FILTER_ALL,
            NETWORK_FILTER_OPTIONS,
            NETWORK_MEL_BAND,
        )
        from ui.download_center import _ARCH_FILTER_OPTIONS

        self.assertEqual(_ARCH_FILTER_OPTIONS, NETWORK_FILTER_OPTIONS)
        mapping = dict(_ARCH_FILTER_OPTIONS)
        self.assertEqual(mapping[ARCH_FILTER_ALL], "Any network")
        self.assertEqual(mapping[VR_ARCH_TYPE], "VR Arch")
        self.assertEqual(mapping[MDX_ARCH_TYPE], "MDX-Net")
        self.assertEqual(mapping[NETWORK_MEL_BAND], "Mel-Band Roformer")

    def test_select_catalogue_opens_restore_and_apollo_network(self) -> None:
        from bundled.constants import APOLLO_ARCH_TYPE
        from core.downloads import DownloadManager
        from core.model_scores import PURPOSE_RESTORE
        from core.settings import Settings
        from ui.download_center import DownloadCenterWindow
        from ui.widgets.rows import get_combo_value

        context = SimpleNamespace(settings=Settings.defaults())
        center = DownloadCenterWindow(None, context, DownloadManager(), mock.MagicMock())
        self.addCleanup(center.window.destroy)

        center.select_catalogue(purpose=PURPOSE_RESTORE, arch=APOLLO_ARCH_TYPE)

        self.assertEqual(center.stack.get_visible_child_name(), PURPOSE_RESTORE)
        self.assertEqual(center._purpose, PURPOSE_RESTORE)
        self.assertEqual(center._arch_filter, APOLLO_ARCH_TYPE)
        self.assertEqual(get_combo_value(center.arch_row), "Apollo")

    def test_select_catalogue_vr_uses_vr_arch_type_not_display_label(self) -> None:
        from bundled.constants import VR_ARCH_TYPE
        from core.downloads import DownloadManager
        from core.model_scores import PURPOSE_VOCALS
        from core.settings import Settings
        from ui.download_center import DownloadCenterWindow
        from ui.widgets.rows import get_combo_value

        context = SimpleNamespace(settings=Settings.defaults())
        center = DownloadCenterWindow(None, context, DownloadManager(), mock.MagicMock())
        self.addCleanup(center.window.destroy)

        center.select_catalogue(purpose=PURPOSE_VOCALS, arch=VR_ARCH_TYPE)

        self.assertEqual(center.stack.get_visible_child_name(), PURPOSE_VOCALS)
        self.assertEqual(center._arch_filter, VR_ARCH_TYPE)
        self.assertEqual(get_combo_value(center.arch_row), "VR Arch")


class DownloadCenterOpenTests(unittest.TestCase):
    def test_open_applies_hint_to_existing_window(self) -> None:
        from bundled.constants import DEMUCS_ARCH_TYPE
        from core.model_scores import PURPOSE_STEMS
        from ui.download import open_download_center

        existing = mock.MagicMock()
        context = SimpleNamespace(_download_center_window=existing)
        with mock.patch("ui.download.start_download_size_cache_warmup"):
            open_download_center(
                mock.MagicMock(),
                context,
                purpose=PURPOSE_STEMS,
                arch=DEMUCS_ARCH_TYPE,
            )

        existing.present.assert_called_once()
        existing.select_catalogue.assert_called_once_with(
            purpose=PURPOSE_STEMS, arch=DEMUCS_ARCH_TYPE
        )

    def test_open_without_hint_does_not_reset_existing_window(self) -> None:
        from ui.download import open_download_center

        existing = mock.MagicMock()
        context = SimpleNamespace(_download_center_window=existing)
        with mock.patch("ui.download.start_download_size_cache_warmup"):
            open_download_center(mock.MagicMock(), context)

        existing.present.assert_called_once()
        existing.select_catalogue.assert_not_called()

    def test_sep_banner_passes_method_hint(self) -> None:
        from bundled.constants import MDX_ARCH_TYPE
        from core.model_scores import PURPOSE_VOCALS
        from ui.window import MainWindow

        win = SimpleNamespace(
            _active_view=lambda: SimpleNamespace(method_key=MDX_ARCH_TYPE),
            context=mock.MagicMock(),
        )
        with mock.patch("ui.download.open_download_center") as opener:
            MainWindow._on_sep_banner_clicked(cast(Any, win), mock.MagicMock())

        opener.assert_called_once()
        self.assertIs(opener.call_args.args[0], win)
        self.assertEqual(opener.call_args.kwargs["purpose"], PURPOSE_VOCALS)
        self.assertEqual(opener.call_args.kwargs["arch"], MDX_ARCH_TYPE)

    def test_apollo_banner_opens_restore_with_apollo_network(self) -> None:
        from bundled.constants import APOLLO_ARCH_TYPE
        from core.model_scores import PURPOSE_RESTORE
        from ui.audio_tools.window import AudioToolsPage

        page = object.__new__(AudioToolsPage)
        page._banner_mode = "apollo"
        page.window = mock.MagicMock()
        page.context = mock.MagicMock()
        with mock.patch("ui.download.open_download_center") as opener:
            AudioToolsPage._on_audio_banner_clicked(page)

        opener.assert_called_once()
        self.assertIs(opener.call_args.args[0], page.window)
        self.assertIs(opener.call_args.args[1], page.context)
        self.assertEqual(opener.call_args.kwargs["purpose"], PURPOSE_RESTORE)
        self.assertEqual(opener.call_args.kwargs["arch"], APOLLO_ARCH_TYPE)
