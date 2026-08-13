"""Regression tests for Download Center catalogue search filtering."""

from __future__ import annotations

import os
import unittest
from typing import Any, cast
from ui.widget_state import fetch, stash


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class CatalogueActionRowResolveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        # Application init is enough for ActionRow construction under a display.
        cls._app = Adw.Application(application_id="org.uvr.test.catalogue-search")
        cls._app.register()

    def test_resolve_returns_action_row_itself(self) -> None:
        from gi.repository import Adw

        from ui.download_center import resolve_catalogue_action_row

        action = Adw.ActionRow()
        stash(action, "_uvr_model_name", "MDX-Net Model: Kim Vocal 2")
        resolved = resolve_catalogue_action_row(action)
        self.assertIs(resolved, action)
        assert resolved is not None
        self.assertEqual(fetch(resolved, "_uvr_model_name"), "MDX-Net Model: Kim Vocal 2")

    def test_internal_child_is_not_the_action_row(self) -> None:
        from gi.repository import Adw

        action = Adw.ActionRow()
        child = action.get_child()
        self.assertIsNotNone(child)
        self.assertFalse(isinstance(child, Adw.ActionRow))

    def test_live_filter_matches_the_canonical_name_shown_to_user(self) -> None:
        from types import SimpleNamespace

        from gi.repository import Adw, Gtk

        from core.model_scores import PURPOSE_ALL
        from ui.download_center import DownloadCenterWindow

        raw = "Roformer Model: Mel-Band Roformer | Inst v2 by Unwa"
        win = object.__new__(DownloadCenterWindow)
        win._hide_unsupported = False
        win._purpose = PURPOSE_ALL
        cast(Any, win).manager = SimpleNamespace(catalogue_meta={})
        search = Gtk.SearchEntry()
        search.set_text("MelBand")
        win._search_entries = {"mdx": search}
        row = Adw.ActionRow()
        stash(row, "_uvr_model_name", raw)

        self.assertTrue(win._row_matches_filter(row, "mdx"))

    def test_live_filter_matches_an_unsupported_reason(self) -> None:
        from types import SimpleNamespace

        from gi.repository import Adw, Gtk

        from core.model_scores import PURPOSE_ALL
        from ui.download_center import DownloadCenterWindow

        win = object.__new__(DownloadCenterWindow)
        win._hide_unsupported = False
        win._purpose = PURPOSE_ALL
        cast(Any, win).manager = SimpleNamespace(catalogue_meta={})
        search = Gtk.SearchEntry()
        search.set_text("newer build")
        win._search_entries = {"mdx": search}
        row = Adw.ActionRow()
        stash(row, "_uvr_model_name", "Future Model")
        stash(row, "_uvr_unsupported", True)
        stash(row, "_uvr_unsupported_reason", "needs a newer build")

        self.assertTrue(win._row_matches_filter(row, "mdx"))


class CanonicalSearchTests(unittest.TestCase):
    def test_query_matches_canonical_name(self) -> None:
        from ui.download_center import catalogue_matches

        names = ["Roformer Model: Mel-Band Roformer | Inst v2 by Unwa"]
        # "MelBand" appears only in the canonical rendering, not the raw label.
        self.assertEqual(catalogue_matches(names, "MelBand"), names)

    def test_query_still_matches_raw_label(self) -> None:
        from ui.download_center import catalogue_matches

        names = ["Roformer Model: Mel-Band Roformer | Inst v2 by Unwa"]
        self.assertEqual(catalogue_matches(names, "Mel-Band"), names)

    def test_non_matching_query_filtered_out(self) -> None:
        from ui.download_center import catalogue_matches

        names = ["Roformer Model: Mel-Band Roformer | Inst v2 by Unwa"]
        self.assertEqual(catalogue_matches(names, "demucs"), [])


class RowSubtitleTests(unittest.TestCase):
    def test_scored_model_names_its_stem(self) -> None:
        from core.model_scores import format_sdr_subtitle

        self.assertEqual(
            format_sdr_subtitle(10.94, "1.2 GB", stem="vocals"),
            "vocals 10.9 SDR · 1.2 GB",
        )

    def test_unscored_model_falls_back_to_stems(self) -> None:
        from core.model_scores import format_sdr_subtitle

        self.assertEqual(
            format_sdr_subtitle(None, "890 MB", extra="vocals, other"),
            "vocals, other · 890 MB",
        )


if __name__ == "__main__":
    unittest.main()
