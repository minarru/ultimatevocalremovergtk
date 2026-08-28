"""Preferences exposes a safe catalogue-cache recovery action."""

from __future__ import annotations

import os
import unittest
from collections.abc import Callable
from types import SimpleNamespace
from unittest import mock


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class PreferencesCatalogueRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.preferences-catalogue-refresh")
        cls._app.register()

    def _dialog(self, manager: object | None = None):
        from core.settings import Settings
        from ui.preferences import PreferencesDialog

        class Context:
            def __init__(self) -> None:
                self.settings = Settings.defaults()
                self.gpu_devices: list[tuple[str, str]] = []
                self.download_manager = manager
                self.repo = object()

            @staticmethod
            def try_save_settings(*, trigger: str) -> None:
                del trigger
                return None

        with mock.patch.object(PreferencesDialog, "_probe_gpu_devices"):
            return PreferencesDialog(Context())

    def test_maintenance_exposes_refresh_catalogue_cache_action(self) -> None:
        dialog = self._dialog()

        self.assertTrue(
            hasattr(dialog, "catalogue_cache_refresh_row"),
            "Preferences maintenance is missing the catalogue-cache action",
        )
        self.assertEqual(dialog.catalogue_cache_refresh_row.get_title(), "Refresh catalogue cache")
        subtitle = dialog.catalogue_cache_refresh_row.get_subtitle() or ""
        self.assertIn("download", subtitle.lower())
        self.assertEqual(dialog.catalogue_cache_refresh_button.get_label(), "Refresh")
        self.assertTrue(dialog.catalogue_cache_refresh_button.get_sensitive())

    def test_general_page_exposes_persistent_diagnostic_controls(self) -> None:
        from core.types.settings_enums import DiagnosticLevel

        dialog = self._dialog()

        self.assertEqual(dialog.diagnostic_level_row.get_title(), "Diagnostic logging")
        self.assertEqual(dialog.diagnostic_level_row.get_selected(), 0)
        self.assertFalse(dialog.diagnostic_sensitive_row.get_active())
        self.assertEqual(dialog.settings.diagnostics.level, DiagnosticLevel.ERRORS)

    def test_diagnostic_controls_apply_runtime_policy_immediately(self) -> None:
        from core.types.settings_enums import DiagnosticLevel

        dialog = self._dialog()
        with mock.patch("core.debug_log.update_policy") as update_policy:
            dialog.diagnostic_level_row.set_selected(2)
            dialog.diagnostic_sensitive_row.set_active(True)

        self.assertEqual(dialog.settings.diagnostics.level, DiagnosticLevel.TRACE)
        self.assertTrue(dialog.settings.diagnostics.include_sensitive)
        self.assertGreaterEqual(update_policy.call_count, 2)
        update_policy.assert_called_with(level="trace", include_sensitive=True)

    def test_refresh_action_runs_in_worker_and_restores_controls(self) -> None:
        import ui.preferences as preferences
        from core.catalogue_types import RefreshMode, RefreshReport, SourceId

        class Manager:
            def __init__(self) -> None:
                self.refreshes = 0
                self.model_updates = 0
                self.last_refresh_report = RefreshReport(
                    mode=RefreshMode.FORCE,
                    succeeded=(
                        SourceId.UPSTREAM,
                        SourceId.POLITREES,
                        SourceId.MVSEPLESS,
                    ),
                    upstream_live=True,
                    usable=True,
                )

            def refresh(self) -> bool:
                self.refreshes += 1
                return True

            def update_model_settings(self, _repo: object) -> bool:
                self.model_updates += 1
                return True

        class DeferredThread:
            instances: list["DeferredThread"] = []

            def __init__(self, *, target: Callable[[], None], daemon: bool) -> None:
                self.target = target
                self.daemon = daemon
                self.instances.append(self)

            def start(self) -> None:
                return None

        manager = Manager()
        dialog = self._dialog(manager)
        dialog.settings.process.auto_update_model_params = True

        with mock.patch.object(preferences.threading, "Thread", DeferredThread):
            dialog.catalogue_cache_refresh_button.emit("clicked")

        self.assertFalse(dialog.catalogue_cache_refresh_button.get_sensitive())
        self.assertTrue(dialog.catalogue_cache_refresh_spinner.get_visible())
        self.assertTrue(dialog.catalogue_cache_refresh_spinner.get_spinning())
        self.assertEqual(len(DeferredThread.instances), 1)

        with mock.patch.object(
            preferences,
            "idle_on_main",
            side_effect=lambda callback, *args: callback(*args),
        ):
            DeferredThread.instances[0].target()

        self.assertEqual(manager.refreshes, 1)
        self.assertEqual(manager.model_updates, 1)
        self.assertTrue(dialog.catalogue_cache_refresh_button.get_sensitive())
        self.assertFalse(dialog.catalogue_cache_refresh_spinner.get_visible())
        self.assertFalse(dialog.catalogue_cache_refresh_spinner.get_spinning())
        self.assertEqual(
            dialog.catalogue_cache_refresh_row.get_subtitle(),
            "Catalogue cache refreshed",
        )

    def test_refresh_feedback_distinguishes_partial_and_failed_results(self) -> None:
        import ui.preferences as preferences

        self.assertTrue(
            hasattr(preferences, "catalogue_refresh_feedback"),
            "Preferences is missing catalogue refresh result formatting",
        )
        partial = SimpleNamespace(
            failed=((SimpleNamespace(value="politrees"), "timeout"),),
            stale=(SimpleNamespace(value="mvsepless"),),
            usable=True,
        )

        self.assertEqual(
            preferences.catalogue_refresh_feedback(
                partial,
                online=True,
                model_settings_updated=True,
            ),
            "Catalogue cache partially refreshed; kept previous data for Politrees and Mvsepless",
        )
        self.assertEqual(
            preferences.catalogue_refresh_feedback(
                None,
                online=False,
                model_settings_updated=None,
                error="connection refused",
            ),
            "Couldn't refresh catalogue cache: connection refused. Previous cache kept.",
        )
        self.assertEqual(
            preferences.catalogue_refresh_feedback(
                SimpleNamespace(failed=(), stale=(), usable=True),
                online=True,
                model_settings_updated=False,
            ),
            "Catalogue cache refreshed, but model parameters could not be updated",
        )


if __name__ == "__main__":
    unittest.main()
