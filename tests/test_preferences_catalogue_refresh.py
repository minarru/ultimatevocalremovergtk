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

    def test_profile_load_applies_live_theme_and_diagnostic_policy(self) -> None:
        from gi.repository import Adw

        from core import debug_log
        from core.settings import Settings
        from core.types.settings_enums import ColorScheme
        from ui.application import apply_color_scheme

        dialog = self._dialog()
        style = Adw.StyleManager.get_default()
        self.addCleanup(style.set_color_scheme, style.get_color_scheme())
        self.addCleanup(
            debug_log.update_policy,
            level=debug_log.current_level(),
            include_sensitive=debug_log.include_sensitive(),
        )
        profile = Settings.defaults()
        profile.ui.color_scheme = ColorScheme.LIGHT
        for data in (profile.to_dict(), profile.to_json_dict()):
            with self.subTest(nested="process" in data):
                apply_color_scheme("dark")
                debug_log.update_policy(level="trace", include_sensitive=True)
                with mock.patch.object(dialog._profiles, "load", return_value=data):
                    dialog._on_load_profile_confirmed(None, "load", "test")
                self.assertEqual(style.get_color_scheme(), Adw.ColorScheme.FORCE_LIGHT)
                self.assertEqual(debug_log.current_level(), "errors")
                self.assertFalse(debug_log.include_sensitive())

    def test_reset_applies_default_theme_and_diagnostic_policy(self) -> None:
        from gi.repository import Adw

        from core import debug_log
        from ui.application import apply_color_scheme

        dialog = self._dialog()
        style = Adw.StyleManager.get_default()
        self.addCleanup(style.set_color_scheme, style.get_color_scheme())
        self.addCleanup(
            debug_log.update_policy,
            level=debug_log.current_level(),
            include_sensitive=debug_log.include_sensitive(),
        )
        apply_color_scheme("dark")
        debug_log.update_policy(level="trace", include_sensitive=True)
        dialog._on_reset_confirmed(None, "reset")
        self.assertEqual(style.get_color_scheme(), Adw.ColorScheme.DEFAULT)
        self.assertEqual(debug_log.current_level(), "errors")
        self.assertFalse(debug_log.include_sensitive())

    def test_reload_keeps_zero_chunk_overlap_visible_without_writing(self) -> None:
        dialog = self._dialog()
        dialog.settings.process.long_file_chunk_overlap_seconds = 0.0
        with mock.patch.object(dialog, "_persist") as persist:
            dialog._reload_widgets()
        self.assertEqual(dialog.long_chunk_overlap_row.get_value(), 0.0)
        self.assertEqual(dialog.settings.process.long_file_chunk_overlap_seconds, 0.0)
        persist.assert_not_called()

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

            def force_revalidate_catalogue_evidence(
                self,
                _on_complete: Callable[[object], None],
            ) -> tuple[str, ...]:
                return ()

        class DeferredThread:
            instances: list["DeferredThread"] = []

            def __init__(
                self, *, target: Callable[..., None], args: tuple[int, ...], daemon: bool
            ) -> None:
                self.target = lambda: target(*args)
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

    def test_refresh_publishes_sources_then_returns_while_evidence_updates(self) -> None:
        import ui.preferences as preferences
        from core.catalogue_types import RefreshMode, RefreshReport, SourceId

        class Manager:
            def __init__(self) -> None:
                self.last_refresh_report = RefreshReport(
                    mode=RefreshMode.FORCE,
                    succeeded=(SourceId.UPSTREAM,),
                    upstream_live=True,
                    usable=True,
                )
                self.completion: Callable[[object], None] | None = None
                self.force_calls = 0

            def refresh(self) -> bool:
                return True

            def update_model_settings(self, _repo: object) -> bool:
                return True

            def force_revalidate_catalogue_evidence(
                self,
                on_complete: Callable[[object], None],
            ) -> tuple[str, ...]:
                self.force_calls += 1
                self.completion = on_complete
                return ("https://example.test/model.yaml",)

        class DeferredThread:
            instances: list["DeferredThread"] = []

            def __init__(
                self, *, target: Callable[..., None], args: tuple[int, ...], daemon: bool
            ) -> None:
                self.target = lambda: target(*args)
                self.daemon = daemon
                self.instances.append(self)

            def start(self) -> None:
                return None

        manager = Manager()
        dialog = self._dialog(manager)
        with mock.patch.object(preferences.threading, "Thread", DeferredThread):
            dialog.catalogue_cache_refresh_button.emit("clicked")

        with mock.patch.object(
            preferences,
            "idle_on_main",
            side_effect=lambda callback, *args: callback(*args),
        ):
            DeferredThread.instances[-1].target()

        self.assertEqual(manager.force_calls, 1)
        self.assertIsNotNone(manager.completion)
        self.assertTrue(dialog.catalogue_cache_refresh_button.get_sensitive())
        self.assertFalse(dialog.catalogue_cache_refresh_spinner.get_spinning())
        self.assertEqual(
            dialog.catalogue_cache_refresh_row.get_subtitle(),
            "Catalogue refreshed; output details updating",
        )

    def test_refresh_worker_settles_when_evidence_fetch_is_disabled_or_disallowed(self) -> None:
        import core.catalogue_stem_cache as csc
        import ui.preferences as preferences
        from bundled.constants import MDX_ARCH_TYPE
        from core.access_policy import access_policy
        from core.catalog_sources import EntryMeta
        from core.catalogue_types import (
            CatalogueEvidenceState,
            RefreshMode,
            RefreshReport,
            SourceId,
        )
        from core.downloads import DownloadManager

        for disabled, allow_network in ((True, True), (False, False)):
            with self.subTest(disabled=disabled, allow_network=allow_network):
                csc._reset_worker_state_for_tests()
                manager = DownloadManager()
                meta = EntryMeta(
                    label="Rejected",
                    display="Rejected",
                    arch=MDX_ARCH_TYPE,
                    files={
                        "m.ckpt": "https://example.test/m.ckpt",
                        "m.yaml": "https://example.test/m.yaml",
                    },
                    catalogue_evidence_status=CatalogueEvidenceState.UNAVAILABLE,
                )
                manager.catalogue_meta = {meta.label: meta}
                manager.catalogue_meta_by_family = {"mdx": {meta.label: meta}}
                manager._last_refresh_report = RefreshReport(
                    mode=RefreshMode.FORCE,
                    succeeded=(SourceId.UPSTREAM,),
                    upstream_live=True,
                    usable=True,
                )
                dialog = self._dialog(manager)
                dialog.settings.process.auto_update_model_params = False
                refresh_messages: list[str] = []

                def run_idle(
                    callback: Callable[..., object],
                    *args: object,
                    _messages: list[str] = refresh_messages,
                ) -> object:
                    if args and isinstance(args[0], str):
                        _messages.append(str(args[0]))
                    return callback(*args)

                with (
                    mock.patch.object(manager, "refresh", return_value=True),
                    mock.patch.object(
                        preferences,
                        "idle_on_main",
                        side_effect=run_idle,
                    ),
                    mock.patch.dict(
                        os.environ,
                        {"UVR_DISABLE_CATALOGUE_STEMS": "1" if disabled else "0"},
                    ),
                    access_policy(
                        allow_network=allow_network,
                        allow_metadata_writes=False,
                        allow_cache_writes=False,
                    ),
                ):
                    dialog._catalogue_cache_refresh_worker(dialog._catalogue_refresh_generation)

                self.assertEqual(
                    dialog.catalogue_cache_refresh_row.get_subtitle(),
                    "Catalogue cache refreshed",
                )
                self.assertEqual(
                    manager.catalogue_meta_by_family["mdx"][meta.label].catalogue_evidence_status,
                    CatalogueEvidenceState.UNAVAILABLE,
                )
                self.assertEqual(manager._evidence.pending, set())
                self.assertEqual(manager._evidence.force_pending, set())
                self.assertEqual(manager._evidence.callbacks, [])
                self.assertNotIn(
                    "Catalogue refreshed; output details updating",
                    refresh_messages,
                )
                csc._reset_worker_state_for_tests()

    def test_prestarted_worker_immediate_completion_settles_after_updating_feedback(self) -> None:
        import tempfile
        import threading

        import core.catalogue_stem_cache as csc
        import ui.preferences as preferences
        from bundled.constants import MDX_ARCH_TYPE
        from core.access_policy import access_policy
        from core.catalog_sources import EntryMeta
        from core.catalogue_types import (
            CatalogueEvidenceState,
            RefreshMode,
            RefreshReport,
            SourceId,
        )
        from core.downloads import DownloadManager

        manager = DownloadManager()
        meta = EntryMeta(
            label="Immediate",
            display="Immediate",
            arch=MDX_ARCH_TYPE,
            files={
                "m.ckpt": "https://example.test/m.ckpt",
                "m.yaml": "https://example.test/m.yaml",
            },
            catalogue_evidence_status=CatalogueEvidenceState.UNAVAILABLE,
        )
        manager.catalogue_meta = {meta.label: meta}
        manager.catalogue_meta_by_family = {"mdx": {meta.label: meta}}
        manager.mdx_download_list = {meta.label: meta.files}
        manager._last_refresh_report = RefreshReport(
            mode=RefreshMode.FORCE,
            succeeded=(SourceId.UPSTREAM,),
            upstream_live=True,
            usable=True,
        )
        manager._coordinator = mock.MagicMock()
        cache_notified = threading.Event()
        manager._coordinator.notify_metadata.side_effect = lambda _labels: cache_notified.wait(
            timeout=0.2
        )
        messages: list[str] = []

        def fetch_immediately(
            url: str,
            *,
            force: bool,
            policy: object,
        ) -> bool:
            del force, policy
            csc.remember_stems(
                url,
                ["Vocals", "Instrumental"],
                "Vocals",
                content_sha256="b" * 64,
                ok=True,
            )
            return True

        def run_idle(callback: Callable[..., object], *args: object) -> object:
            result = callback(*args)
            if args and isinstance(args[0], str):
                messages.append(str(args[0]))
            elif callback == dialog._finish_catalogue_evidence_refresh:
                messages.append(str(dialog.catalogue_cache_refresh_row.get_subtitle()))
            return result

        original_ensure_worker_started = csc.ensure_worker_started

        def ensure_and_wait() -> None:
            original_ensure_worker_started()
            self.assertTrue(cache_notified.wait(timeout=1.0), "cache worker did not finish")
            self.assertTrue(csc._worker_idle.wait(timeout=1.0), "cache worker did not drain")

        csc._reset_worker_state_for_tests()
        csc.subscribe(cache_notified.set)
        dialog = self._dialog(manager)
        dialog.settings.process.auto_update_model_params = False
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "catalogue_stem_cache.json")
            with (
                mock.patch.object(manager, "refresh", return_value=True),
                mock.patch.object(csc, "_cache_path", return_value=cache_path),
                mock.patch.object(csc, "_fetch_and_remember", side_effect=fetch_immediately),
                mock.patch.object(csc, "ensure_worker_started", side_effect=ensure_and_wait),
                mock.patch.object(preferences, "idle_on_main", side_effect=run_idle),
                access_policy(
                    allow_network=True,
                    allow_metadata_writes=False,
                    allow_cache_writes=False,
                ),
            ):
                csc.clear_catalogue_stem_cache()
                original_ensure_worker_started()
                dialog._catalogue_cache_refresh_worker(dialog._catalogue_refresh_generation)

        self.assertEqual(
            messages,
            [
                "Catalogue refreshed; output details updating",
                "Catalogue refreshed; output details updated",
            ],
        )
        self.assertEqual(
            dialog.catalogue_cache_refresh_row.get_subtitle(),
            "Catalogue refreshed; output details updated",
        )
        self.assertEqual(manager._evidence.pending, set())
        self.assertEqual(manager._evidence.force_pending, set())
        self.assertEqual(manager._evidence.callbacks, [])
        self.assertFalse(csc.is_pending("https://example.test/m.yaml"))
        csc._reset_worker_state_for_tests()

    def test_evidence_completion_feedback_reports_aggregate_failures(self) -> None:
        import ui.preferences as preferences

        summary = SimpleNamespace(unavailable=2, stale=1)

        self.assertEqual(
            preferences.catalogue_evidence_refresh_feedback(summary),
            "Catalogue refreshed; output details finished with 2 unavailable and 1 using previous details",
        )

    def test_evidence_completion_callback_updates_feedback_on_main_thread(self) -> None:
        import ui.preferences as preferences

        dialog = self._dialog()
        summary = SimpleNamespace(unavailable=1, stale=0)
        idle_calls: list[tuple[object, tuple[object, ...]]] = []

        with mock.patch.object(
            preferences,
            "idle_on_main",
            side_effect=lambda callback, *args: idle_calls.append((callback, args)),
        ):
            dialog._on_catalogue_evidence_refresh_completed(
                summary, dialog._catalogue_refresh_generation
            )

        self.assertEqual(
            idle_calls,
            [
                (
                    dialog._finish_catalogue_evidence_refresh,
                    (summary, dialog._catalogue_refresh_generation),
                )
            ],
        )

    def test_previous_evidence_completion_cannot_replace_new_refresh_feedback(self) -> None:
        import ui.preferences as preferences

        manager = mock.Mock()
        manager.refresh.return_value = True
        manager.last_refresh_report = SimpleNamespace(failed=(), stale=(), usable=True)
        callbacks = []
        manager.force_revalidate_catalogue_evidence.side_effect = lambda callback: (
            callbacks.append(callback) or ["pending"]
        )
        dialog = self._dialog(manager)
        dialog.settings.process.auto_update_model_params = False
        with (
            mock.patch.object(preferences, "idle_on_main", side_effect=lambda fn, *args: fn(*args)),
            mock.patch.object(preferences.threading, "Thread") as thread,
            mock.patch.object(dialog, "add_toast") as toast,
        ):
            dialog._on_catalogue_cache_refresh(dialog.catalogue_cache_refresh_button)
            job = thread.call_args.kwargs
            job["target"](*job.get("args", ()))
            dialog._on_catalogue_cache_refresh(dialog.catalogue_cache_refresh_button)
            self.assertEqual(
                dialog.catalogue_cache_refresh_row.get_subtitle(), "Refreshing catalogue cache…"
            )
            toast.reset_mock()
            callbacks[0](SimpleNamespace(unavailable=2, stale=0))
            self.assertEqual(
                dialog.catalogue_cache_refresh_row.get_subtitle(), "Refreshing catalogue cache…"
            )
            toast.assert_not_called()
            job = thread.call_args.kwargs
            job["target"](*job.get("args", ()))
            callbacks[1](SimpleNamespace(unavailable=0, stale=0))
            self.assertEqual(
                dialog.catalogue_cache_refresh_row.get_subtitle(),
                "Catalogue refreshed; output details updated",
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

    def test_closed_dialog_suppresses_only_late_ui_deliveries(self) -> None:
        from ui.preferences import PreferencesDialog

        dialog = self._dialog()
        dialog._persist_timeout_id = 1
        dialog._flush_persist = mock.Mock()
        with mock.patch('ui.preferences.GLib.source_remove'):
            dialog._on_dialog_closed()
        dialog._flush_persist.assert_called_once_with()
        with (
            mock.patch.object(dialog, 'add_toast') as toast,
            mock.patch('ui.widgets.rows.set_combo_values') as options,
        ):
            dialog._finish_catalogue_cache_refresh(
                'late refresh', dialog._catalogue_refresh_generation
            )
            dialog._finish_catalogue_evidence_refresh(
                mock.Mock(), dialog._catalogue_refresh_generation
            )
            dialog._apply_gpu_devices([('1', 'GPU')])
            toast.assert_not_called()
            options.assert_not_called()
        # The worker still updates the shared cache before its discarded UI delivery.
        with (
            mock.patch('core.gpu.list_gpu_devices', return_value=[('1', 'GPU')]),
            mock.patch('ui.preferences.idle_on_main', side_effect=lambda fn, *args: fn(*args)),
        ):
            PreferencesDialog._probe_gpu_devices(dialog)
        self.assertEqual(dialog.context.gpu_devices, [('1', 'GPU')])


if __name__ == "__main__":
    unittest.main()
