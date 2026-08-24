"""Vocal splitter + deverb row (global settings, hosted on the run pages)."""

from __future__ import annotations
import typing
from types import SimpleNamespace

import os
import unittest
from unittest.mock import patch


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class VocalSplitRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.vocal-split-row")
        cls._app.register()

        # Patch network fetch to prevent test hangup on network unavailability
        cls._politrees_patcher = patch(
            "core.politrees_catalog.load_politrees_links", return_value=None
        )
        cls._politrees_patcher.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._politrees_patcher.stop()

    def _settings(self, **overrides: typing.Any):
        from core.settings import Settings

        settings = Settings.defaults()
        for key, value in overrides.items():
            settings.set(key, value)
        return settings

    def _row(self):
        from ui.widgets.vocal_split_row import VocalSplitRow
        from core.model_identity import ModelArtifacts, ModelRecord
        from core.model_repository import ModelRepository

        repo = ModelRepository()

        # Mutable so a test can install a model mid-session, the way a download
        # does, and count how often the (expensive) list is resolved.
        self.karaoke_models = ["vr:UVR-BVE-4B"]
        self.karaoke_calls = 0

        def patched_karaoke(settings: typing.Any):
            self.karaoke_calls += 1
            return list(self.karaoke_models)
        repo.karaoke_model_list = patched_karaoke

        def installed_records(_service: typing.Any):
            return tuple(
                ModelRecord(
                    id=model_id,
                    family="vr",
                    basename=model_id.partition(":")[2],
                    display=model_id.partition(":")[2],
                    backend_name=model_id.partition(":")[2],
                    artifacts=ModelArtifacts(model_id.partition(":")[2]),
                    installed=True,
                )
                for model_id in self.karaoke_models
            )

        identity_patcher = patch(
            "core.model_identity.ModelIdentityService.records",
            autospec=True,
            side_effect=installed_records,
        )
        identity_patcher.start()
        self.addCleanup(identity_patcher.stop)

        self.changed = 0

        def on_changed():
            self.changed += 1

        return VocalSplitRow(repo, on_changed)

    def _row_with_repo(self, repo: typing.Any) -> typing.Any:
        """A row over a real repository: nothing about eligibility is patched."""
        from ui.widgets.vocal_split_row import VocalSplitRow

        self.changed = 0

        def on_changed():
            self.changed += 1

        return VocalSplitRow(repo, on_changed)

    def test_applies_stored_switches(self):
        row = self._row()
        row.apply_from_settings(
            self._settings(is_set_vocal_splitter=True, is_deverb_vocals=True)
        )
        self.assertTrue(row.split_switch.get_active())
        self.assertTrue(row.deverb_switch.get_active())

    def test_applying_settings_does_not_fire_on_changed(self):
        row = self._row()
        row.apply_from_settings(self._settings(is_set_vocal_splitter=True))
        self.assertEqual(self.changed, 0)

    def test_auto_expands_when_either_switch_is_on(self):
        row = self._row()
        row.apply_from_settings(self._settings(is_deverb_vocals=True))
        self.assertTrue(row.get_expanded())

    def test_stays_collapsed_when_both_switches_are_off(self):
        row = self._row()
        row.apply_from_settings(
            self._settings(is_set_vocal_splitter=False, is_deverb_vocals=False)
        )
        self.assertFalse(row.get_expanded())

    def test_never_auto_collapses_a_manually_opened_section(self):
        row = self._row()
        row.set_expanded(True)
        row.apply_from_settings(
            self._settings(is_set_vocal_splitter=False, is_deverb_vocals=False)
        )
        self.assertTrue(row.get_expanded())

    def test_subtitle_reports_off_when_both_are_off(self):
        from ui.option_summaries import OFF

        row = self._row()
        row.apply_from_settings(self._settings(is_set_vocal_splitter=False))
        self.assertEqual(row.get_subtitle(), OFF)

    def test_subtitle_follows_a_switch_toggle(self):
        from ui.option_summaries import OFF

        row = self._row()
        row.apply_from_settings(self._settings(is_deverb_vocals=False))
        self.assertEqual(row.get_subtitle(), OFF)
        row.deverb_switch.set_active(True)
        self.assertIn("deverb", row.get_subtitle())

    def test_toggling_a_switch_fires_on_changed(self):
        row = self._row()
        row.apply_from_settings(self._settings())
        row.deverb_switch.set_active(True)
        self.assertGreaterEqual(self.changed, 1)

    def test_persist_writes_every_global_key(self):
        settings = self._settings()
        row = self._row()
        row.apply_from_settings(settings)
        row.split_switch.set_active(True)
        row.save_inst_switch.set_active(True)
        row.deverb_switch.set_active(True)
        row.persist_to_settings(settings)
        self.assertTrue(settings.get("is_set_vocal_splitter"))
        self.assertTrue(settings.get("is_save_inst_set_vocal_splitter"))
        self.assertTrue(settings.get("is_deverb_vocals"))
        self.assertIsNotNone(settings.get("deverb_vocal_opt"))

    def test_persist_does_not_clobber_an_unloaded_model_list(self):
        """Before the karaoke list is populated the stored tag must survive."""
        settings = self._settings(set_vocal_splitter="VR Arc: UVR-BVE-4B")
        row = self._row()
        row.apply_from_settings(settings)
        row.persist_to_settings(settings)
        self.assertEqual(settings.get("set_vocal_splitter"), "VR Arc: UVR-BVE-4B")

    def test_persist_clears_a_stored_tag_missing_from_the_model_list(self):
        """A deleted/renamed model cannot become active after a later install.

        Regression: expanding the row used to rebuild the combo from just the
        fresh (non-matching) list, silently landing the selection on index 0
        (``NO_MODEL``) and then persisting that over the user's real choice.
        """
        settings = self._settings(set_vocal_splitter="VR Arc: 5_HP-Karaoke-UVR-DELETED")
        row = self._row()
        row.apply_from_settings(settings)
        row.set_expanded(True)  # triggers _populate_models against the fresh list
        from ui.widgets.rows import get_combo_value

        self.assertEqual(get_combo_value(row.splitter_row), "No Model Selected")
        row.persist_to_settings(settings)
        self.assertEqual(settings.get("set_vocal_splitter"), "No Model Selected")
        self.assertFalse(settings.get("is_set_vocal_splitter"))

    def test_missing_stored_splitter_is_visible_until_valid_repick(self):
        from bundled.constants import NO_MODEL
        from ui.widgets.rows import combo_values, get_combo_value

        illegal = "VR Arc: 5_HP-Karaoke-UVR-DELETED"
        settings = self._settings(set_vocal_splitter=illegal)
        row = self._row()
        row.apply_from_settings(settings)
        row.set_expanded(True)

        self.assertEqual(settings.get("set_vocal_splitter"), illegal)
        self.assertEqual(get_combo_value(row.splitter_row), NO_MODEL)
        self.assertTrue(row.splitter_warning_row.get_visible())
        self.assertIn(illegal, row.splitter_warning_row.get_subtitle() or "")

        displayed = combo_values(row.splitter_row)
        row.splitter_row.set_selected(displayed.index("UVR-BVE-4B"))

        self.assertEqual(settings.get("set_vocal_splitter"), "vr:UVR-BVE-4B")
        self.assertFalse(row.splitter_warning_row.get_visible())

    def test_installed_refresh_does_not_clear_a_presented_missing_gate(self):
        from bundled.constants import NO_MODEL
        from ui.widgets.rows import combo_values, get_combo_value

        missing = "vr:UVR-BVE-5B"
        settings = self._settings(set_vocal_splitter=missing)
        row = self._row()
        row.apply_from_settings(settings)
        row.set_expanded(True)
        self.assertTrue(row.splitter_warning_row.get_visible())

        self.karaoke_models.append(missing)
        row.refresh_models()

        self.assertEqual(settings.get("set_vocal_splitter"), missing)
        self.assertEqual(get_combo_value(row.splitter_row), NO_MODEL)
        self.assertTrue(row.splitter_warning_row.get_visible())
        self.assertIn(missing, row.splitter_warning_row.get_subtitle() or "")

        displayed = combo_values(row.splitter_row)
        row.splitter_row.set_selected(displayed.index("UVR-BVE-5B"))
        self.assertEqual(settings.get("set_vocal_splitter"), missing)
        self.assertFalse(row.splitter_warning_row.get_visible())

    def test_shared_settings_repick_replaces_another_rows_stale_gate(self):
        from ui.widgets.vocal_split_row import VocalSplitRow
        from ui.widgets.rows import combo_values, get_combo_value

        missing = "vr:later"
        replacement = "vr:UVR-BVE-4B"
        settings = self._settings(set_vocal_splitter=missing)
        row_a = self._row()
        row_b = VocalSplitRow(row_a._repo, lambda: None)

        row_a.apply_from_settings(settings)
        row_a.set_expanded(True)
        self.assertTrue(row_a.splitter_warning_row.get_visible())

        row_b.apply_from_settings(settings)
        row_b.set_expanded(True)
        displayed = combo_values(row_b.splitter_row)
        row_b.splitter_row.set_selected(displayed.index("UVR-BVE-4B"))
        self.assertEqual(settings.get("set_vocal_splitter"), replacement)

        # A second page/row must treat the shared Settings object as authority.
        row_a.apply_from_settings(settings)
        self.assertEqual(get_combo_value(row_a.splitter_row), replacement)
        self.assertFalse(row_a.splitter_warning_row.get_visible())

        # Persisting an unrelated control must not resurrect row A's old gate.
        row_a.save_inst_switch.set_active(True)
        self.assertEqual(settings.get("set_vocal_splitter"), replacement)

    def test_persist_clears_a_stored_tag_when_karaoke_model_list_raises(self):
        from ui.widgets.vocal_split_row import VocalSplitRow
        from core.model_repository import ModelRepository

        repo = ModelRepository()

        def raising_karaoke(settings: typing.Any):
            raise RuntimeError("catalogue unavailable")

        repo.karaoke_model_list = raising_karaoke
        row = VocalSplitRow(repo, lambda: None)

        settings = self._settings(set_vocal_splitter="VR Arc: UVR-BVE-4B")
        row.apply_from_settings(settings)
        row.set_expanded(True)  # triggers _populate_models, which will raise internally
        row.persist_to_settings(settings)
        self.assertEqual(settings.get("set_vocal_splitter"), "No Model Selected")
        self.assertFalse(settings.get("is_set_vocal_splitter"))

    def test_dependent_rows_are_dimmed_while_their_switch_is_off(self):
        row = self._row()
        row.apply_from_settings(
            self._settings(is_set_vocal_splitter=False, is_deverb_vocals=False)
        )
        self.assertFalse(row.splitter_row.get_sensitive())
        self.assertFalse(row.save_inst_switch.get_sensitive())
        self.assertFalse(row.deverb_row.get_sensitive())

    def test_dependent_rows_wake_up_with_their_switch(self):
        row = self._row()
        row.apply_from_settings(self._settings())
        row.split_switch.set_active(True)
        self.assertTrue(row.splitter_row.get_sensitive())
        self.assertTrue(row.save_inst_switch.get_sensitive())
        self.assertFalse(row.deverb_row.get_sensitive())

    def test_expanding_populates_the_splitter_model_list(self):
        from ui.widgets.rows import combo_values

        row = self._row()
        row.apply_from_settings(self._settings())
        row.set_expanded(True)
        self.assertIn("UVR-BVE-4B", " ".join(combo_values(row.splitter_row)))

    def test_model_list_shows_friendly_names_but_stores_canonical_ids(self):
        """Combo displays friendly names while persisting canonical identities."""
        from ui.widgets.rows import combo_values, get_combo_value

        row = self._row()
        row.apply_from_settings(self._settings())
        row.set_expanded(True)

        # Displayed values should include the friendly name without prefix
        displayed = combo_values(row.splitter_row)
        self.assertIn("UVR-BVE-4B", displayed)
        self.assertNotIn("VR Arc:", " ".join(displayed))

        # Select the model and persist
        row.split_switch.set_active(True)
        row.splitter_row.set_selected(displayed.index("UVR-BVE-4B"))
        settings = self._settings()
        row.persist_to_settings(settings)

        # Stored value is independent from the friendly label.
        self.assertEqual(settings.get("set_vocal_splitter"), "vr:UVR-BVE-4B")

    def test_refresh_repopulates_an_already_expanded_row(self):
        """`_models_ready` latched True forever, so a karaoke model installed
        mid-session stayed invisible until the app restarted."""
        from ui.widgets.rows import combo_values

        row = self._row()
        row.apply_from_settings(self._settings())
        row.set_expanded(True)
        self.assertNotIn("UVR-BVE-5B", " ".join(combo_values(row.splitter_row)))

        self.karaoke_models.append("vr:UVR-BVE-5B")
        row.refresh_models()

        self.assertIn("UVR-BVE-5B", " ".join(combo_values(row.splitter_row)))

    def test_refresh_keeps_the_current_selection(self):
        from ui.widgets.rows import combo_values, get_combo_value

        row = self._row()
        row.apply_from_settings(self._settings())
        row.set_expanded(True)
        displayed = combo_values(row.splitter_row)
        row.splitter_row.set_selected(displayed.index("UVR-BVE-4B"))

        self.karaoke_models.append("vr:UVR-BVE-5B")
        row.refresh_models()

        self.assertEqual(get_combo_value(row.splitter_row), "vr:UVR-BVE-4B")
        settings = self._settings()
        row.persist_to_settings(settings)
        self.assertEqual(settings.get("set_vocal_splitter"), "vr:UVR-BVE-4B")

    def test_refresh_of_a_collapsed_row_defers_the_work(self):
        """Laziness pin: resolving the karaoke list hashes checkpoints, so a
        collapsed row must not pay for a refresh it cannot show."""
        from ui.widgets.rows import combo_values

        row = self._row()
        row.apply_from_settings(self._settings())
        self.assertFalse(row.get_expanded())
        calls_before = self.karaoke_calls

        self.karaoke_models.append("vr:UVR-BVE-5B")
        row.refresh_models()

        self.assertEqual(self.karaoke_calls, calls_before, "collapsed row must not resolve")
        row.set_expanded(True)
        self.assertIn("UVR-BVE-5B", " ".join(combo_values(row.splitter_row)))

    def test_refresh_flush_drops_a_selection_absent_from_the_new_list(self):
        from ui.widgets.rows import combo_values, get_combo_value
        from bundled.constants import NO_MODEL

        row = self._row()
        row.apply_from_settings(self._settings())
        row.set_expanded(True)
        displayed = combo_values(row.splitter_row)
        row.splitter_row.set_selected(displayed.index("UVR-BVE-4B"))

        # The selected model is gone from the fresh list (deleted or renamed).
        self.karaoke_models[:] = ["vr:UVR-BVE-5B"]
        row.refresh_models()

        self.assertEqual(get_combo_value(row.splitter_row), NO_MODEL)
        settings = self._settings()
        row.persist_to_settings(settings)
        self.assertEqual(settings.get("set_vocal_splitter"), NO_MODEL)
        self.assertFalse(settings.get("is_set_vocal_splitter"))

    def test_refresh_presents_only_karaoke_members_with_friendly_labels(self):
        """The splitter pool stays karaoke-only while labels get friendlier.

        Classification is faked per model, but the eligibility filter and the
        row's record projection are the real ones: a non-karaoke installed
        model must never reach the combo no matter how friendly its label is.
        """
        import tempfile
        from core import model_repository as model_repository_mod
        from core.model_repository import ModelRepository
        from ui.widgets.rows import combo_values, get_combo_value

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.environ["UVR_DATA_DIR"] = tmp.name
        self.addCleanup(lambda: os.environ.pop("UVR_DATA_DIR", None))

        repo = ModelRepository()
        repo._model_artifact_files = lambda family: (
            ["UVR_MDXNET_KARA_2.onnx", "plain_model.onnx"]
            if family == "mdx"
            else []
        )
        repo.mdx_name_select_MAPPER = {
            "UVR_MDXNET_KARA_2.onnx": "Karaoke Friendly",
            # Presentation wording is intentionally misleading: metadata alone
            # decides whether a Vocal Splitter row is eligible.
            "plain_model.onnx": "Karaoke-labelled decoy",
        }
        repo.default_change_model_tags = lambda: [
            "mdx:UVR_MDXNET_KARA_2",
            "mdx:plain_model",
        ]

        def fake_dry_check(
            settings: typing.Any,
            repo_: typing.Any,
            tag: typing.Any,
            identities: typing.Any,
        ) -> typing.Any:
            is_karaoke = tag == "mdx:UVR_MDXNET_KARA_2"
            return SimpleNamespace(
                canonical_id=tag,
                model_status=True,
                is_karaoke=is_karaoke,
                is_bv_model=False,
                mdx_model_stems=("other", "vocals") if is_karaoke else (),
                primary_stem_native="Instrumental" if is_karaoke else "",
                primary_stem="Instrumental" if is_karaoke else "",
                secondary_stem="Vocals" if is_karaoke else "",
                target_instrument="other" if is_karaoke else "",
            )

        row = self._row_with_repo(repo)
        with patch.object(
            model_repository_mod, "_dry_check_config", side_effect=fake_dry_check
        ):
            row.apply_from_settings(self._settings())
            row.set_expanded(True)

        displayed = combo_values(row.splitter_row)
        karaoke_label = "MDX-Net — UVR Karaoke 2"

        self.assertIn(karaoke_label, displayed)
        self.assertNotIn("Karaoke-labelled decoy", displayed)
        # The label is presentation; selecting it must store the canonical id.
        row.split_switch.set_active(True)
        row.splitter_row.set_selected(displayed.index(karaoke_label))
        self.assertEqual(get_combo_value(row.splitter_row), "mdx:UVR_MDXNET_KARA_2")
        self.assertNotIn("mdx:plain_model", row._splitter_ids)
        self.assertEqual(row._splitter_ids, {"mdx:UVR_MDXNET_KARA_2"})


if __name__ == "__main__":
    unittest.main()
