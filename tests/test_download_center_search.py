"""Regression tests for Download Center catalogue search filtering."""

from __future__ import annotations

import os
import unittest
from typing import Any, cast
from unittest.mock import patch

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
        from ui.catalogue_browser import CatalogueBrowserState
        win.browser = CatalogueBrowserState()
        from ui.lifetime import UiLifetime
        win._lifetime = UiLifetime()
        win._listening = False
        win._sort_mode = "name"
        win._arch_filter = "all"
        win._hide_unsupported = False
        win._purpose = PURPOSE_ALL
        cast(Any, win).manager = SimpleNamespace(latest_snapshot=None,catalogue_meta_by_family={},catalogue_meta={})
        search = Gtk.SearchEntry()
        search.set_text("MelBand")
        win._search_entries = {"mdx": search}
        row = Adw.ActionRow()
        stash(row, "_uvr_model_name", raw)

        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, row, "mdx")
        self.assertTrue(win._row_matches_filter(row, "mdx"))

    def test_live_filter_matches_an_unsupported_reason(self) -> None:
        from types import SimpleNamespace

        from gi.repository import Adw, Gtk

        from core.model_scores import PURPOSE_ALL
        from ui.download_center import DownloadCenterWindow

        win = object.__new__(DownloadCenterWindow)
        from ui.catalogue_browser import CatalogueBrowserState
        win.browser = CatalogueBrowserState()
        from ui.lifetime import UiLifetime
        win._lifetime = UiLifetime()
        win._listening = False
        win._sort_mode = "name"
        win._arch_filter = "all"
        win._hide_unsupported = False
        win._purpose = PURPOSE_ALL
        cast(Any, win).manager = SimpleNamespace(latest_snapshot=None,catalogue_meta_by_family={},catalogue_meta={})
        search = Gtk.SearchEntry()
        search.set_text("newer build")
        win._search_entries = {"mdx": search}
        row = Adw.ActionRow()
        stash(row, "_uvr_model_name", "Future Model")
        stash(row, "_uvr_unsupported", True)
        stash(row, "_uvr_unsupported_reason", "needs a newer build")

        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, row, "mdx")
        self.assertTrue(win._row_matches_filter(row, "mdx"))

    def test_download_row_uses_the_exact_id_aware_display(self) -> None:
        from types import SimpleNamespace

        from gi.repository import Gtk

        from bundled.constants import VR_ARCH_TYPE
        from core.catalog_sources import EntryMeta
        from ui.download_center import DownloadCenterWindow

        selection = "VR Arch Single Model v5: 1_HP-UVR"
        raw = {"1_HP-UVR.pth": "https://example.invalid/1_HP-UVR.pth"}
        win = cast(Any, object.__new__(DownloadCenterWindow))
        from ui.catalogue_browser import CatalogueBrowserState
        win.browser = CatalogueBrowserState()
        from ui.lifetime import UiLifetime
        win._lifetime = UiLifetime()
        win._listening = False
        win._sort_mode = "name"
        win._arch_filter = "all"
        win.manager = SimpleNamespace(latest_snapshot=None,
            catalogue_meta={
                selection: EntryMeta(
                    label=selection,
                    display="1_HP-UVR",
                    arch=VR_ARCH_TYPE,
                    files=raw,
                    checkpoint="1_HP-UVR.pth",
                )
            },
            vr_download_list={selection: raw},
            mdx_download_list={},
            demucs_download_list={},
            apollo_download_list={},
        )
        win._row_checks = {}
        win._row_actions = {}
        win._list_boxes = {VR_ARCH_TYPE: Gtk.ListBox()}

        with patch("core.model_scores.load_model_scores", return_value={}):
            win._add_model_row(VR_ARCH_TYPE, selection)

        self.assertEqual(
            win._row_actions[(VR_ARCH_TYPE, selection)].get_title(),
            "VR v5 — HP 1",
        )

    def test_live_filter_matches_the_exact_id_aware_display(self) -> None:
        from types import SimpleNamespace

        from gi.repository import Adw, Gtk

        from bundled.constants import VR_ARCH_TYPE
        from core.catalog_sources import EntryMeta
        from core.model_scores import PURPOSE_ALL
        from ui.download_center import DownloadCenterWindow
        from ui.widget_state import stash

        selection = "VR Arch Single Model v5: 1_HP-UVR"
        raw = {"1_HP-UVR.pth": "https://example.invalid/1_HP-UVR.pth"}
        win = cast(Any, object.__new__(DownloadCenterWindow))
        from ui.catalogue_browser import CatalogueBrowserState
        win.browser = CatalogueBrowserState()
        from ui.lifetime import UiLifetime
        win._lifetime = UiLifetime()
        win._listening = False
        win._sort_mode = "name"
        win._arch_filter = "all"
        win._hide_unsupported = False
        win._purpose = PURPOSE_ALL
        win.manager = SimpleNamespace(latest_snapshot=None,
            catalogue_meta={
                selection: EntryMeta(
                    label=selection,
                    display="1_HP-UVR",
                    arch=VR_ARCH_TYPE,
                    files=raw,
                    checkpoint="1_HP-UVR.pth",
                )
            }
        )
        search = Gtk.SearchEntry()
        search.set_text("HP 1")
        win._search_entries = {VR_ARCH_TYPE: search}
        row = Adw.ActionRow()
        stash(row, "_uvr_model_name", selection)
        stash(row, "_uvr_display_name", "HP 1")

        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, row, VR_ARCH_TYPE)
        self.assertTrue(win._row_matches_filter(row, VR_ARCH_TYPE))

    def test_dual_model_matches_vocals_and_instrumental_pages(self) -> None:
        from types import SimpleNamespace

        from gi.repository import Adw

        from bundled.constants import MDX_ARCH_TYPE
        from core.catalog_sources import EntryMeta
        from core.model_scores import (
            ARCH_FILTER_ALL,
            PURPOSE_INSTRUMENTAL,
            PURPOSE_KARAOKE,
            PURPOSE_VOCALS,
        )
        from core.model_stem_semantics import INTENT_DUAL_VOC_INST
        from ui.download_center import DownloadCenterWindow

        label = "MelBand Roformer | InstVoc HQ"
        win = cast(Any, object.__new__(DownloadCenterWindow))
        from ui.catalogue_browser import CatalogueBrowserState
        win.browser = CatalogueBrowserState()
        from ui.lifetime import UiLifetime
        win._lifetime = UiLifetime()
        win._listening = False
        win._sort_mode = "name"
        win._arch_filter = "all"
        win._hide_unsupported = False
        win._arch_filter = ARCH_FILTER_ALL
        win.manager = SimpleNamespace(latest_snapshot=None,
            catalogue_meta={
                label: EntryMeta(
                    label=label,
                    display=label,
                    arch=MDX_ARCH_TYPE,
                    intent=INTENT_DUAL_VOC_INST,
                )
            },
            catalogue_meta_by_family={
                "mdx": {
                    label: EntryMeta(
                        label=label,
                        display=label,
                        arch=MDX_ARCH_TYPE,
                        intent=INTENT_DUAL_VOC_INST,
                    )
                }
            },
        )
        win._search_entries = {}
        row = Adw.ActionRow()
        stash(row, "_uvr_model_name", label)
        stash(row, "_uvr_arch", MDX_ARCH_TYPE)

        win._purpose = PURPOSE_VOCALS
        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, row, MDX_ARCH_TYPE)
        self.assertTrue(win._row_matches_filter(row, MDX_ARCH_TYPE))
        win._purpose = PURPOSE_INSTRUMENTAL
        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, row, MDX_ARCH_TYPE)
        self.assertTrue(win._row_matches_filter(row, MDX_ARCH_TYPE))
        win._purpose = PURPOSE_KARAOKE
        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, row, MDX_ARCH_TYPE)
        self.assertFalse(win._row_matches_filter(row, MDX_ARCH_TYPE))

    def test_cinematic_and_cleanup_use_fx_and_removal_pages(self) -> None:
        from types import SimpleNamespace

        from gi.repository import Adw

        from bundled.constants import MDX_ARCH_TYPE
        from core.catalog_sources import EntryMeta
        from core.catalogue_types import StemSemanticProjection
        from core.model_scores import (
            ARCH_FILTER_ALL,
            PURPOSE_FX,
            PURPOSE_REMOVAL,
            PURPOSE_STEMS,
        )
        from core.model_stem_semantics import INTENT_SPECIAL_FX, INTENT_SPECIALTY_STEM
        from ui.download_center import DownloadCenterWindow

        crowd = "MelBand Roformer | Crowd by Aufr33"
        echo = "De-Echo Normal"
        stems = "SCnet: 4-stem model"
        crowd_meta = EntryMeta(
            label=crowd,
            display=crowd,
            arch=MDX_ARCH_TYPE,
            intent=INTENT_SPECIALTY_STEM,
            stem_semantics=StemSemanticProjection(
                backend_primary_stem=None,
                backend_target_stem=None,
                logical_primary_role="cinematic.crowd",
                logical_secondary_role=None,
                status="reviewed",
                context="full_mix",
                routes=(),
            ),
        )
        echo_meta = EntryMeta(
            label=echo,
            display=echo,
            arch=MDX_ARCH_TYPE,
            intent=INTENT_SPECIAL_FX,
        )
        win = cast(Any, object.__new__(DownloadCenterWindow))
        from ui.catalogue_browser import CatalogueBrowserState
        win.browser = CatalogueBrowserState()
        from ui.lifetime import UiLifetime
        win._lifetime = UiLifetime()
        win._listening = False
        win._sort_mode = "name"
        win._arch_filter = "all"
        win._hide_unsupported = False
        win._arch_filter = ARCH_FILTER_ALL
        win.manager = SimpleNamespace(latest_snapshot=None,
            catalogue_meta={crowd: crowd_meta, echo: echo_meta},
            catalogue_meta_by_family={"mdx": {crowd: crowd_meta, echo: echo_meta}},
        )
        win._search_entries = {}

        def _row(name: str) -> Adw.ActionRow:
            row = Adw.ActionRow()
            stash(row, "_uvr_model_name", name)
            stash(row, "_uvr_arch", MDX_ARCH_TYPE)
            return row

        crowd_row = _row(crowd)
        echo_row = _row(echo)
        stem_row = _row(stems)

        win._purpose = PURPOSE_FX
        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, crowd_row, MDX_ARCH_TYPE)
        self.assertTrue(win._row_matches_filter(crowd_row, MDX_ARCH_TYPE))
        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, echo_row, MDX_ARCH_TYPE)
        self.assertFalse(win._row_matches_filter(echo_row, MDX_ARCH_TYPE))
        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, stem_row, MDX_ARCH_TYPE)
        self.assertFalse(win._row_matches_filter(stem_row, MDX_ARCH_TYPE))
        win._purpose = PURPOSE_REMOVAL
        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, crowd_row, MDX_ARCH_TYPE)
        self.assertFalse(win._row_matches_filter(crowd_row, MDX_ARCH_TYPE))
        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, echo_row, MDX_ARCH_TYPE)
        self.assertTrue(win._row_matches_filter(echo_row, MDX_ARCH_TYPE))
        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, stem_row, MDX_ARCH_TYPE)
        self.assertFalse(win._row_matches_filter(stem_row, MDX_ARCH_TYPE))
        win._purpose = PURPOSE_STEMS
        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, crowd_row, MDX_ARCH_TYPE)
        self.assertFalse(win._row_matches_filter(crowd_row, MDX_ARCH_TYPE))
        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, echo_row, MDX_ARCH_TYPE)
        self.assertFalse(win._row_matches_filter(echo_row, MDX_ARCH_TYPE))
        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, stem_row, MDX_ARCH_TYPE)
        self.assertTrue(win._row_matches_filter(stem_row, MDX_ARCH_TYPE))

    def test_mel_band_network_filter_excludes_classic_mdx(self) -> None:
        from types import SimpleNamespace

        from gi.repository import Adw

        from bundled.constants import MDX_ARCH_TYPE
        from core.model_scores import NETWORK_CLASSIC_MDX, NETWORK_MEL_BAND, PURPOSE_ALL
        from ui.download_center import DownloadCenterWindow

        win = cast(Any, object.__new__(DownloadCenterWindow))
        from ui.catalogue_browser import CatalogueBrowserState
        win.browser = CatalogueBrowserState()
        from ui.lifetime import UiLifetime
        win._lifetime = UiLifetime()
        win._listening = False
        win._sort_mode = "name"
        win._arch_filter = "all"
        win._hide_unsupported = False
        win._purpose = PURPOSE_ALL
        win.manager = SimpleNamespace(latest_snapshot=None,catalogue_meta_by_family={},catalogue_meta={})
        win._search_entries = {}

        mel = Adw.ActionRow()
        stash(mel, "_uvr_model_name", "MelBand Roformer | Inst v1")
        stash(mel, "_uvr_arch", MDX_ARCH_TYPE)
        stash(mel, "_uvr_network", NETWORK_MEL_BAND)
        classic = Adw.ActionRow()
        stash(classic, "_uvr_model_name", "MDX-Net Model: Kim Vocal 2")
        stash(classic, "_uvr_arch", MDX_ARCH_TYPE)
        stash(classic, "_uvr_network", NETWORK_CLASSIC_MDX)

        win._arch_filter = NETWORK_MEL_BAND
        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, mel, MDX_ARCH_TYPE)
        self.assertTrue(win._row_matches_filter(mel, MDX_ARCH_TYPE))
        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, classic, MDX_ARCH_TYPE)
        self.assertFalse(win._row_matches_filter(classic, MDX_ARCH_TYPE))

        win._arch_filter = MDX_ARCH_TYPE
        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, mel, MDX_ARCH_TYPE)
        self.assertTrue(win._row_matches_filter(mel, MDX_ARCH_TYPE))
        from tests.browser_ui_helpers import seed_browser_row
        seed_browser_row(win, classic, MDX_ARCH_TYPE)
        self.assertTrue(win._row_matches_filter(classic, MDX_ARCH_TYPE))


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
