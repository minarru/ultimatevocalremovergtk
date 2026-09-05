"""GTK host adapter for shared run control; concrete page access stays here."""

from __future__ import annotations

from typing import TYPE_CHECKING

from gi.repository import Adw, Gio, Gtk

from core.settings import Settings

from .protocols import RunTarget

if TYPE_CHECKING:
    from .window import MainWindow


class GtkRunHost:
    def __init__(self, window: MainWindow):
        self.window = window

    @property
    def settings(self) -> Settings:
        return self.window.settings

    @property
    def repo(self):
        return self.window.context.repo

    @property
    def target(self) -> RunTarget | None:
        return self.window._run_target

    @property
    def context_target(self) -> RunTarget:
        tab = self.window.content_stack.get_visible_child_name()
        if tab == 'ensemble':
            return self.window._ensemble_page
        if tab == 'audio_tools':
            return self.window._audio_tools_page
        return self.window._separation_target

    @property
    def dialog_parent(self) -> Gtk.Window:
        return self.window

    @property
    def fallback_error_key(self) -> str:
        return self.window._active_view().method_key

    def get_application(self):
        return self.window.get_application()

    def toast(self, message: str) -> None:
        self.window.toast(message)

    def add_toast(self, toast: Adw.Toast) -> None:
        self.window.toast_overlay.add_toast(toast)

    def set_pulse(self, active: bool) -> None:
        if active:
            self.window._start_pulse()
        else:
            self.window._stop_pulse()

    def append_console(self, text: str) -> None:
        self.window.console.append(text)

    def clear_console(self) -> None:
        self.window.console.clear()

    def set_progress_text(self, text: str) -> None:
        self.window.log_panel.set_progress_text(text)

    def set_progress_fraction(self, fraction: float) -> None:
        self.window.log_panel.set_progress_fraction(fraction)

    def clear_progress(self) -> None:
        self.window.log_panel.clear_progress()

    def set_run_label(self, label: str) -> None:
        self.window.log_panel.set_run_label(label)

    def mark_run_complete(self) -> None:
        self.window.log_panel.mark_run_complete()

    def reveal_log(self) -> None:
        self.window._reveal_log_panel(True)

    def prepare_log(self) -> None:
        self.window.log_panel.prepare_for_run()

    def start_enabled(self) -> bool:
        return self.window.start_button.get_sensitive()

    def stop_enabled(self) -> bool:
        return self.window.stop_button.get_sensitive()

    def enable_start(self, enabled: bool) -> None:
        self.window.start_button.set_sensitive(enabled)

    def enable_stop(self, enabled: bool) -> None:
        self.window.stop_button.set_sensitive(enabled)

    def start_label(self) -> str | None:
        return self.window.start_button.get_label()

    def set_start_label(self, label: str) -> None:
        self.window.start_button.set_label(label)

    def describe_start(self, description: str) -> None:
        self.window.start_button.set_tooltip_text(description)
        self.window.start_button.update_property(
            [Gtk.AccessibleProperty.DESCRIPTION], [description]
        )

    def refresh_readiness(self) -> None:
        self.window._refresh_start_readiness()

    def set_options_sensitive(self, sensitive: bool) -> None:
        for page in self.window._options_pages:
            page.set_sensitive(sensitive)

    def set_edit_actions_sensitive(self, sensitive: bool) -> None:
        for name in ('settings', 'view_inputs', 'model_options', 'download'):
            action = self.window.lookup_action(name)
            if isinstance(action, Gio.SimpleAction):
                action.set_enabled(sensitive)
        if sensitive:
            self.window._sync_model_options_action()
            deferred = self.window._deferred_model_refresh
            if deferred is not None:
                self.window._apply_model_refresh(source=deferred)

    def bind_run_settings(self, settings: Settings) -> None:
        self.window.context.runner.settings = settings

    def restore_runner_settings(self) -> None:
        self.window.context.restore_runner_settings()
        self.window._audio_tools_page.restore_runner_settings()

    def run_output_dir(self) -> str:
        return (
            self.window.context.runner.settings.process.export_path
            or self.settings.process.export_path
            or ''
        )

    def exported_after_oom(self) -> bool:
        return self.window.context.runner.last_oom_exported

    def active_download_count(self) -> int:
        return self.window.context.active_download_count()

    def stop_context_workers(self, *, force: bool = False) -> None:
        self.window.context.stop_all_workers(force=force)

    def stop_all_workers(self, *, force: bool = False) -> None:
        self.stop_context_workers(force=force)
        self.window._audio_tools_page.stop_started_worker(force=force)

    def destroy(self) -> None:
        self.window.destroy()

    def release_inference_memory(
        self,
        *,
        wait_for_stop: float = 0.0,
        force_if_alive: bool = False,
        clear_weight_cache: bool = False,
        park_weights: bool = False,
    ) -> None:
        self.window.context.runner.release_inference_memory(
            wait_for_stop=wait_for_stop,
            force_if_alive=force_if_alive,
            clear_weight_cache=clear_weight_cache,
            park_weights=park_weights,
        )
        self.window._audio_tools_page.runner.release_inference_memory(
            wait_for_stop=wait_for_stop,
            force_if_alive=force_if_alive,
            clear_weight_cache=clear_weight_cache,
            park_weights=park_weights,
        )
