"""Core separation main window.

This is the GTK4 / libadwaita port of ``UVR.py``'s ``MainWindow`` core
separation surface. It provides:

* a "Process method" dropdown (``Adw.ComboRow``) that swaps the visible option
  panel in a ``Gtk.Stack`` (VR Architecture / MDX-Net / Demucs), each panel
  contributed by a :class:`uvr_gtk.views.MethodView`;
* input file(s) and output folder choosers with native drag and drop;
* the shared main-window options (output format, GPU conversion, sample mode);
* Start / Stop and a progress bar in a collapsible log panel at the bottom of
  the window (run controls always visible; log output expands above them), all
  wired to
  :class:`uvr_core.JobRunner` through :mod:`uvr_gtk.dispatch` so worker-thread
  callbacks land on the GTK main loop.

Settings are persisted through the shared :class:`uvr_gtk.context.AppContext`
using the exact ``DEFAULT_DATA`` keys, so the Phase 2 settings window and the
Phase 3 advanced panels read and write the same model.

Settings, Ensemble, Audio Tools, the Download Center, About, Updates, the
Error Log and the input viewer are all reachable through window
actions wired in :meth:`MainWindow._install_actions`, with keyboard accelerators
and help-hint tooltips installed from :mod:`uvr_gtk.hints`.
"""

import os
import time
from typing import Optional

from gi.repository import Adw, Gio, GLib, Gtk

from data.constants import (
    FLAC,
    INPUT_FOLDER_ENTRY_HELP,
    MDX_ARCH_TYPE,
    MP3,
    OUTPUT_FOLDER_ENTRY_HELP,
    SAMPLE_MODE_CHECKBOX,
    STOP_PROCESS_CONFIRM,
    STOP_PROCESSING,
    WAV,
)

_OPEN_FOLDER_LABEL = "Open Folder"
_OPEN_FOLDER_ERROR = "Couldn't open the output folder: {message}"
_NOTIFY_COMPLETE_TITLE = "{label} complete"
_NOTIFY_COMPLETE_BODY = "Saved to {folder}"
_NOTIFY_COMPLETE_BODY_PLAIN = "Processing finished."
_NOTIFY_FAILED_TITLE = "{label} failed"
_NOTIFY_FAILED_BODY = "Open the app to see the error log."
_NOTIFY_ICONS = {
    "uvr-complete": "emblem-ok-symbolic",
    "uvr-failed": "dialog-error-symbolic",
}
_PROGRESS_STARTING = "Starting…"
_PROGRESS_DONE = "Done"

#: Cadence (ms) and step of the indeterminate progress pulse shown before the
#: first real fractional update arrives, and the epsilon under which a fraction
#: is still treated as "no real progress yet".
_PULSE_INTERVAL_MS = 120
_PULSE_STEP = 0.08
_PROGRESS_EPSILON = 0.001

#: Toast shown after copying the log to the clipboard.
_LOG_COPIED_TOAST = "Log copied"

#: Blocking-reason strings toasted from the shared Start dispatch when a
#: required field is missing.
_REASON_INPUT = "Select an input audio file"
_REASON_OUTPUT = "Choose an output folder"
_REASON_MODEL = "Choose a model"

from . import APP_ID, APP_TITLE
from .audio_tools import AudioToolsPage
from .context import AppContext
from .dispatch import gtk_job_callbacks
from .ensemble import EnsemblePage
from .hints import (
    HelpHintManager,
    OUTPUT_FORMAT_HINT,
    SHARED_HINTS,
    apply_accelerators,
    install_view_tab_tooltips,
    set_tooltip,
)
from .views import METHOD_VIEWS
from .widgets.columns import build_columns_box, set_columns_narrow, wrap_options_scroller
from .widgets.file_chooser import InputFilesRow, OutputFolderRow
from .widgets.log_panel import LogPanel
from .widgets.rows import get_combo_value, make_combo_row, make_switch_row, set_combo_value


class _SeparationTarget:
    """Run-target adapter making the separation surface dispatch uniformly.

    The separation page is built and driven directly by :class:`MainWindow`
    (its columns are repopulated as the method changes), so rather than wrap it
    in a separate controller object this thin adapter delegates the uniform
    run-target interface (:meth:`start` / :meth:`stop` / :meth:`on_activated` /
    :meth:`on_deactivated` / :attr:`error_key`) back to the window. This lets the
    shared Start/Stop dispatch treat separation, ensemble and audio tools
    identically.
    """

    def __init__(self, window: "MainWindow"):
        self.window = window

    @property
    def error_key(self) -> str:
        return self.window._active_view().method_key

    def on_activated(self) -> None:
        self.window._activate_separation()

    def on_deactivated(self) -> None:
        pass

    def start(self, callbacks) -> None:
        self.window._start_separation(callbacks)

    def start_blocked_reason(self) -> Optional[str]:
        return self.window._separation_blocked_reason()

    def stop(self) -> None:
        self.window.context.runner.stop()

    def pause(self) -> None:
        self.window.context.runner.pause()

    def unpause(self) -> None:
        self.window.context.runner.unpause()


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.context = AppContext()
        self.settings = self.context.settings

        self.set_title(APP_TITLE)
        # Restore the persisted geometry (falling back to the default size), and
        # keep a modest minimum so it can't open uselessly small. The minimum
        # stays under the 880sp breakpoint so it never fights the wide/narrow
        # column flip.
        self.set_size_request(640, 560)
        width = int(self.settings.get("window_width", 1040) or 1040)
        height = int(self.settings.get("window_height", 720) or 720)
        self.set_default_size(width, height)
        if bool(self.settings.get("window_maximized")):
            self.maximize()

        self._views = [view_cls(self.context, self._on_settings_changed) for view_cls in METHOD_VIEWS]
        self._views_by_stack = {view.stack_name: view for view in self._views}
        self._views_by_method = {view.method_key: view for view in self._views}
        self._views_by_title = {view.title: view for view in self._views}

        self._install_actions()

        # The currently selected method view, whose option groups are placed
        # into the responsive columns by ``_populate_columns``.
        self._current_view = None

        self._pulse_source_id = None

        page = self._build_content()
        self.log_panel = LogPanel()
        self.console = self.log_panel.console
        self.progressbar = self.log_panel.progressbar
        self.start_button = self.log_panel.start_button
        self.stop_button = self.log_panel.stop_button
        self.log_copy_button = self.log_panel.log_copy_button
        self.log_clear_button = self.log_panel.log_clear_button
        self.progressbar.set_pulse_step(_PULSE_STEP)
        self.start_button.connect("clicked", self._on_start)
        self.stop_button.connect("clicked", self._on_stop)
        self.log_copy_button.connect("clicked", self._on_log_copy)
        self.log_clear_button.connect("clicked", self._on_log_clear)
        self.log_panel.expand_button.connect("toggled", self._on_log_panel_expand_toggled)

        root = Gtk.Overlay()
        root.set_child(page)
        root.add_overlay(self.log_panel)
        self.log_panel.set_halign(Gtk.Align.CENTER)
        self.log_panel.set_valign(Gtk.Align.END)
        self.log_panel.set_margin_bottom(12)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(self._build_header())
        toolbar_view.set_content(root)
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(toolbar_view)
        self.set_content(self.toast_overlay)

        # Collapse the two option columns into a single column when the window
        # is narrow. ``set_orientation`` is driven from the apply/unapply
        # signals (explicit and PyGObject-safe vs. an enum ``add_setter``).
        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 880sp"))
        narrow.connect("apply", self._on_breakpoint_narrow)
        narrow.connect("unapply", self._on_breakpoint_wide)
        self.add_breakpoint(narrow)

        self._hint_manager = HelpHintManager(self.settings)
        self._register_hints()
        self._apply_accelerators()

        self._load_from_settings()
        self.connect("close-request", self._on_close_request)

    # -- Construction -----------------------------------------------------------

    def _build_header(self) -> Adw.HeaderBar:
        header = Adw.HeaderBar()

        switcher = Adw.ViewSwitcher()
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        switcher.set_stack(self.content_stack)
        install_view_tab_tooltips(switcher)
        header.set_title_widget(switcher)

        self.log_toggle = Gtk.ToggleButton(icon_name="utilities-terminal-symbolic")
        set_tooltip(self.log_toggle, "Show or hide the processing log")
        self.log_toggle.connect("toggled", self._on_log_toggle)
        header.pack_end(self.log_toggle)

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        set_tooltip(menu_button, "Main menu")
        menu_button.set_menu_model(self._build_primary_menu())
        header.pack_end(menu_button)

        return header

    def _build_primary_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        tools = Gio.Menu()
        tools.append("View / Verify Inputs", "win.view_inputs")
        tools.append("Download Center", "win.download")
        tools.append("Error Log", "win.error_log")
        menu.append_section(None, tools)
        info = Gio.Menu()
        info.append("Settings", "win.settings")
        info.append("Check for Updates", "win.updates")
        info.append("Keyboard Shortcuts", "win.shortcuts")
        info.append("About", "win.about")
        menu.append_section(None, info)
        return menu

    def _build_content(self) -> Gtk.Widget:
        # Static groups are kept as attributes so they can be reparented between
        # the columns alongside the per-method groups.
        self.files_group = self._build_files_group()
        self.method_group = self._build_method_group()
        self.shared_group = self._build_shared_group()

        # Separation page: two side-by-side columns when wide, collapsed to one
        # when narrow (the breakpoint in ``__init__`` flips this box and every
        # other page's column box together). The columns are repopulated as the
        # active method changes, so the column references are kept.
        self._columns_box, self._col_start, self._col_end = build_columns_box()
        self._populate_columns()

        # Proactive empty-state hint: a full-width banner above the two columns,
        # shown only when the active method has no installed models. It opens the
        # in-app Download Center and auto-hides once models appear (see
        # ``_update_sep_banner``, driven from method switch / load / refresh).
        self._sep_banner = Adw.Banner(
            title="No models installed for this method. Open the Download Center to get models.",
            button_label="Download Models",
            revealed=False,
        )
        self._sep_banner.add_css_class("app-banner")
        self._sep_banner.connect("button-clicked", self._on_sep_banner_clicked)
        separation_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        separation_page.set_valign(Gtk.Align.START)
        separation_page.append(self._sep_banner)
        scroller = wrap_options_scroller(self._columns_box)
        separation_page.append(scroller)

        # Ensemble Mode and Audio Tools are embedded as sibling pages that reuse
        # the same responsive two-column layout and the shared run controls.
        self._ensemble_page = EnsemblePage(self, self.context)
        self._audio_tools_page = AudioToolsPage(self, self.context)

        # Runnable mode pages only; the shared console lives in the collapsible
        # log panel toggled from the header and auto-expanded when a run starts.
        self.content_stack = Adw.ViewStack()
        self.content_stack.add_titled_with_icon(
            separation_page, "separation", "Separation", "audio-x-generic-symbolic"
        )
        self.content_stack.add_titled_with_icon(
            self._ensemble_page.widget, "ensemble", "Ensemble", "media-playlist-shuffle-symbolic"
        )
        self.content_stack.add_titled_with_icon(
            self._audio_tools_page.widget, "audio_tools", "Audio Tools", "applications-utilities-symbolic"
        )

        # Every page's columns_box is flipped together by the responsive
        # breakpoint (see ``_on_breakpoint_narrow`` / ``_on_breakpoint_wide``).
        self._column_boxes = [
            self._columns_box,
            self._ensemble_page.columns_box,
            self._audio_tools_page.columns_box,
        ]

        # Shared Start/Stop dispatch to the run target of the visible tab.
        # ``_running_target`` pins the dispatch to whatever actually started, so
        # Stop and error reporting stay correct even if the user switches tabs
        # mid-run.
        self._separation_target = _SeparationTarget(self)
        self._targets = {
            "separation": self._separation_target,
            "ensemble": self._ensemble_page,
            "audio_tools": self._audio_tools_page,
        }
        self._run_target = self._separation_target
        self._running_target = None
        self._stop_confirm_dialog = None
        self._run_output_dir = ""
        self._run_label = "Processing"
        self._run_started_at = 0.0
        self.content_stack.connect("notify::visible-child", self._on_visible_child)

        self.content_stack.set_vexpand(True)
        return self.content_stack

    def _populate_columns(self) -> None:
        """(Re)distribute the option groups across the two columns.

        Called at build time (static groups only) and whenever the active
        method changes. Groups are removed from their current column and
        re-appended so the layout reflects ``self._current_view``.

        The split is balanced to keep the two columns close in height: the left
        column holds Files -> Method -> Basic options and ends with the short
        collapsed Advanced expander, while the right column runs Save stems ->
        Output and options (the user-preferred top order) and ends with the tall
        Secondary/pre-process/vocal-split models group. This moves the tall
        secondary group off the already-heavy left side so the lower groups stay
        nearer the fold on launch.
        """
        for column in (self._col_start, self._col_end):
            child = column.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                column.remove(child)
                child = nxt

        self._col_start.append(self.files_group)
        self._col_start.append(self.method_group)

        view = self._current_view
        if view is not None:
            self._col_start.append(view.group)
            self._col_start.append(view.advanced_group)
            self._col_end.append(view.stem_group)
            self._col_end.append(self.shared_group)
            self._col_end.append(view.secondary_group)
        else:
            self._col_end.append(self.shared_group)

    def _show_method(self, view) -> None:
        """Make ``view`` the active method and refresh the column layout."""
        if view is self._current_view:
            return
        self._current_view = view
        view._sync_only_active()
        self._populate_columns()
        self._update_sep_banner()

    def _update_sep_banner(self) -> None:
        """Reveal the empty-state banner when the active method has no models."""
        banner = getattr(self, "_sep_banner", None)
        if banner is None:
            return
        banner.set_revealed(not self._active_view().has_any_models())

    def _on_sep_banner_clicked(self, _banner: Adw.Banner) -> None:
        self._on_download(None, None)

    def _on_breakpoint_narrow(self, _breakpoint) -> None:
        # Single stacked column on every page: drop homogeneity so groups size
        # by their own natural height instead of being forced to equal heights.
        for columns_box in self._column_boxes:
            set_columns_narrow(columns_box, True)

    def _on_breakpoint_wide(self, _breakpoint) -> None:
        for columns_box in self._column_boxes:
            set_columns_narrow(columns_box, False)

    def _sync_log_panel_expanded(self, expanded: bool) -> None:
        if self.log_panel.get_expanded() != expanded:
            self.log_panel.set_expanded(expanded)
        if self.log_toggle.get_active() != expanded:
            self.log_toggle.set_active(expanded)

    def _reveal_log_panel(self, revealed: bool) -> None:
        self._sync_log_panel_expanded(revealed)

    def _on_log_toggle(self, toggle: Gtk.ToggleButton) -> None:
        self._sync_log_panel_expanded(toggle.get_active())

    def _on_log_panel_expand_toggled(self, button: Gtk.ToggleButton) -> None:
        if self.log_toggle.get_active() != button.get_active():
            self.log_toggle.set_active(button.get_active())

    def _start_pulse(self) -> None:
        if self._pulse_source_id is not None:
            return
        self.progressbar.pulse()
        self._pulse_source_id = GLib.timeout_add(_PULSE_INTERVAL_MS, self._on_pulse_tick)

    def _on_pulse_tick(self) -> bool:
        self.progressbar.pulse()
        return GLib.SOURCE_CONTINUE

    def _stop_pulse(self) -> None:
        if self._pulse_source_id is not None:
            GLib.source_remove(self._pulse_source_id)
            self._pulse_source_id = None

    def _on_log_clear(self, _button: Gtk.Button) -> None:
        self.console.clear()

    def _on_log_copy(self, _button: Gtk.Button) -> None:
        text = self.console.get_text()
        if not text:
            return
        self.console.get_clipboard().set(text)
        self._toast(_LOG_COPIED_TOAST)

    def _build_files_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Files")
        view_inputs_button = Gtk.Button(icon_name="view-list-symbolic", valign=Gtk.Align.CENTER)
        view_inputs_button.add_css_class("flat")
        set_tooltip(view_inputs_button, "View or verify selected inputs")
        view_inputs_button.set_action_name("win.view_inputs")
        group.set_header_suffix(view_inputs_button)
        self.input_row = InputFilesRow(self._on_inputs_changed)
        self.output_row = OutputFolderRow(self._on_output_changed)
        group.add(self.input_row)
        group.add(self.output_row)
        return group

    def _build_method_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Conversion method")
        self.method_row = make_combo_row(
            "Process method",
            [view.title for view in self._views],
            icon_name="system-run-symbolic",
        )
        self.method_row.connect("notify::selected", self._on_method_selected)
        group.add(self.method_row)
        return group

    def _build_shared_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Output and options")

        self.format_row = make_combo_row("Output format", [WAV, FLAC, MP3], icon_name="audio-x-generic-symbolic")
        self.format_row.connect("notify::selected", self._on_format_changed)
        group.add(self.format_row)

        self.gpu_row = make_switch_row("GPU conversion", icon_name="pci-card-symbolic")
        self.gpu_row.connect("notify::active", self._on_gpu_changed)
        group.add(self.gpu_row)

        duration = self.settings.get("model_sample_mode_duration", 30)
        self.sample_row = make_switch_row(SAMPLE_MODE_CHECKBOX(duration), icon_name="preferences-system-time-symbolic")
        self.sample_row.connect("notify::active", self._on_sample_changed)
        group.add(self.sample_row)

        return group

    def _install_actions(self) -> None:
        handlers = {
            "settings": self._on_open_settings,
            "ensemble": self._on_ensemble,
            "audio_tools": self._on_audio_tools,
            "download": self._on_download,
            "about": self._on_about,
            "updates": self._on_updates,
            "error_log": self._on_error_log,
            "view_inputs": self._on_view_inputs,
            "start": self._on_start_action,
            "stop": self._on_stop_action,
            "shortcuts": self._on_shortcuts,
        }
        for name, handler in handlers.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

    def _register_hints(self) -> None:
        self._hint_manager.register(self.stop_button, SHARED_HINTS["stop"])
        self._hint_manager.register(self.gpu_row, SHARED_HINTS["gpu_conversion"])
        self._hint_manager.register(self.sample_row, SHARED_HINTS["sample_mode"])
        self._hint_manager.register(self.console, SHARED_HINTS["console"])
        self._hint_manager.register(self.log_toggle, "Status messages and progress output from the current run")
        self._hint_manager.register(self.method_row, SHARED_HINTS["process_method"])
        self._hint_manager.register(self.format_row, OUTPUT_FORMAT_HINT)
        self._hint_manager.register(self.input_row, INPUT_FOLDER_ENTRY_HELP)
        self._hint_manager.register(self.output_row, OUTPUT_FOLDER_ENTRY_HELP)

    def _apply_accelerators(self) -> None:
        app = self.get_application()
        if app is not None:
            apply_accelerators(app)

    # -- Settings load / persist ------------------------------------------------

    def _load_from_settings(self) -> None:
        for view in self._views:
            view.load()

        self.input_row.set_paths(self.settings.get("input_paths") or [], notify=False)
        self.output_row.set_path(self.settings.get("export_path") or "", notify=False)
        set_combo_value(self.format_row, self.settings.get("save_format", WAV))
        self.gpu_row.set_active(bool(self.settings.get("is_gpu_conversion")))
        self.sample_row.set_title(SAMPLE_MODE_CHECKBOX(self.settings.get("model_sample_mode_duration", 30)))
        self.sample_row.set_active(bool(self.settings.get("model_sample_mode")))

        method = self.settings.get("chosen_process_method", MDX_ARCH_TYPE)
        view = self._views_by_method.get(method) or self._views_by_method.get(MDX_ARCH_TYPE) or self._views[0]
        set_combo_value(self.method_row, view.title)
        # ``set_combo_value`` only emits ``notify::selected`` when the index
        # actually changes, so populate the columns explicitly here too.
        self._show_method(view)
        self._update_sep_banner()

        # The embedded mode pages load their own slice of the settings model.
        self._ensemble_page.load()
        self._audio_tools_page.load()

        if getattr(self, "_hint_manager", None) is not None:
            self._hint_manager.refresh()

    def _active_view(self):
        return self._current_view or self._views[0]

    def _sync_shared_from_settings(self) -> None:
        """Re-read the cross-tab shared keys into the separation widgets.

        Input file(s), output folder and the output/format/GPU/sample options
        are shared across every mode; re-reading them when the separation tab
        becomes active keeps a selection made on another tab in view.
        """
        self.input_row.set_paths(self.settings.get("input_paths") or [], notify=False)
        self.output_row.set_path(self.settings.get("export_path") or "", notify=False)
        set_combo_value(self.format_row, self.settings.get("save_format", WAV))
        self.gpu_row.set_active(bool(self.settings.get("is_gpu_conversion")))
        self.sample_row.set_title(SAMPLE_MODE_CHECKBOX(self.settings.get("model_sample_mode_duration", 30)))
        self.sample_row.set_active(bool(self.settings.get("model_sample_mode")))

    def _activate_separation(self) -> None:
        self.settings.set("chosen_process_method", self._active_view().method_key)
        self._sync_shared_from_settings()

    def _on_visible_child(self, *_args) -> None:
        """Track the run target as the visible tab changes.

        On every tab other than Ensemble, ``chosen_process_method`` is restored
        to the active separation method so it never persists as ``ENSEMBLE_MODE``
        (mirroring the old ensemble window restoring the method on close); the
        Ensemble page sets ``ENSEMBLE_MODE`` itself in ``on_activated``.
        """
        name = self.content_stack.get_visible_child_name()
        if name is None:
            return
        target = self._targets.get(name)
        if target is None:
            return
        if name != "ensemble":
            self.settings.set("chosen_process_method", self._active_view().method_key)
        self._run_target = target
        target.on_activated()

    def _on_settings_changed(self) -> None:
        """Settings-changed hook handed to the method views.

        In-memory updates are flushed to disk on Start and on close, so nothing
        needs to happen here; it exists to satisfy the view callback contract.
        """

    def _on_method_selected(self, *_args) -> None:
        title = get_combo_value(self.method_row)
        view = self._views_by_title.get(title)
        if view is None:
            return
        self._show_method(view)
        self.settings.set("chosen_process_method", view.method_key)

    def _on_inputs_changed(self) -> None:
        self.settings.set("input_paths", list(self.input_row.paths))

    def _on_external_inputs_changed(self, paths) -> None:
        self.input_row.set_paths(list(paths), notify=False)
        self.settings.set("input_paths", list(paths))

    def _on_output_changed(self) -> None:
        self.settings.set("export_path", self.output_row.path)

    def _on_format_changed(self, *_args) -> None:
        self.settings.set("save_format", get_combo_value(self.format_row))

    def _on_gpu_changed(self, *_args) -> None:
        self.settings.set("is_gpu_conversion", self.gpu_row.get_active())

    def _on_sample_changed(self, *_args) -> None:
        self.settings.set("model_sample_mode", self.sample_row.get_active())

    def _on_close_request(self, *_args) -> bool:
        self._flush_settings()
        self._save_geometry()
        self.context.save_settings()
        return False

    def _save_geometry(self) -> None:
        # Only record the un-maximized size so a later un-maximize restores a
        # sane window; the maximized flag is always stored.
        if not self.is_maximized():
            width, height = self.get_default_size()
            if width > 0 and height > 0:
                self.settings.set("window_width", width)
                self.settings.set("window_height", height)
        self.settings.set("window_maximized", self.is_maximized())

    def _flush_settings(self) -> None:
        active = self._active_view()
        for view in self._views:
            view.save(include_stem_only=(view is active))
        self.settings.set("chosen_process_method", self._active_view().method_key)
        self.settings.set("input_paths", list(self.input_row.paths))
        self.settings.set("export_path", self.output_row.path)
        self.settings.set("save_format", get_combo_value(self.format_row))
        self.settings.set("is_gpu_conversion", self.gpu_row.get_active())
        self.settings.set("model_sample_mode", self.sample_row.get_active())

    # -- Run control ------------------------------------------------------------

    def _on_start(self, _button: Gtk.Button) -> None:
        # The Start button stays clickable while idle; surface the precise
        # reason as a toast (and don't start) when the active target isn't ready.
        target = self._run_target
        try:
            reason = target.start_blocked_reason()
        except Exception:  # noqa: BLE001 - readiness check must never break the UI
            reason = None
        if reason is not None:
            self._toast(reason)
            return

        # Build the shared callbacks (progress bar + single console + shared
        # completion/error handlers) once and hand them to the active run target.
        callbacks = gtk_job_callbacks(
            on_progress=self._on_progress,
            on_console=self.console.append,
            on_complete=self._on_complete,
            on_stopped=self._on_stopped,
            on_error=self._on_error,
        )
        target.start(callbacks)

    def _separation_blocked_reason(self) -> Optional[str]:
        """First reason the separation run can't start, or ``None`` when ready."""
        input_paths = list(self.input_row.paths)
        if not input_paths or not os.path.isfile(input_paths[0]):
            return _REASON_INPUT
        if not os.path.isdir(self.output_row.path):
            return _REASON_OUTPUT
        if not self._active_view().has_model():
            return _REASON_MODEL
        return None

    def _start_separation(self, callbacks) -> None:
        """Separation run-target body (launch on the shared widgets).

        Readiness is validated by :meth:`_on_start` before dispatch.
        """
        self._flush_settings()

        input_paths = list(self.input_row.paths)
        self.context.save_settings()
        self.begin_run(self._separation_target)

        try:
            self.context.runner.start(input_paths, callbacks)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.fail_to_start(f"Unable to start separation: {exc}", exc)

    def begin_run(self, target) -> None:
        """Shared "a run has started" bookkeeping for any run target.

        Clears the single console, resets the progress bar, flips Start/Stop and
        surfaces the live log. ``target`` is pinned as the running target so Stop
        and error reporting stay correct even if the user switches tabs mid-run.
        """
        self._running_target = target
        self._run_output_dir = self.settings.get("export_path") or ""
        self._run_label = self._run_label_for(target)
        self._run_started_at = time.monotonic()
        self.console.clear()
        self.progressbar.set_fraction(0.0)
        self.progressbar.set_text(_PROGRESS_STARTING)
        self._start_pulse()
        self._set_running(True)
        # Expand the log panel so live output is in view.
        self._reveal_log_panel(True)

    def _run_label_for(self, target) -> str:
        if target is self._separation_target:
            return "Separation"
        if target is self._ensemble_page:
            return "Ensemble"
        if target is self._audio_tools_page:
            return "Audio tools"
        return "Processing"

    def fail_to_start(self, message: str, exc: BaseException) -> None:
        """Recover the UI when a run target could not even launch its worker."""
        self._stop_pulse()
        self._set_running(False)
        self.console.append(f"\n{message}\n")
        self._report_error(message, exc)
        self._running_target = None

    def _on_start_action(self, _action: Gio.SimpleAction, _param) -> None:
        if self.start_button.get_sensitive():
            self._on_start(self.start_button)

    def _on_stop_action(self, _action: Gio.SimpleAction, _param) -> None:
        if self.stop_button.get_sensitive():
            self._on_stop(self.stop_button)

    def _on_stop(self, _button: Gtk.Button) -> None:
        if not self.stop_button.get_sensitive():
            return
        if self._stop_confirm_dialog is not None:
            return
        self._present_stop_confirm()

    def _present_stop_confirm(self) -> None:
        heading, body = STOP_PROCESS_CONFIRM
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("stop", "Stop")
        dialog.set_response_appearance("stop", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        target = self._running_target
        if target is not None and hasattr(target, "pause"):
            target.pause()

        def on_response(_dlg, response: str) -> None:
            self._stop_confirm_dialog = None
            if response == "stop":
                self._confirm_stop()
            elif target is not None and hasattr(target, "unpause"):
                target.unpause()

        self._stop_confirm_dialog = dialog
        dialog.connect("response", on_response)
        dialog.present(self)

    def _confirm_stop(self) -> None:
        target = self._running_target
        if target is None:
            return
        self.console.append(f"\n{STOP_PROCESSING}\n")
        target.stop()
        self._finish_run_ui(stopped=True)

    def _finish_run_ui(self, *, stopped: bool = False) -> None:
        self._stop_pulse()
        self._set_running(False)
        self._running_target = None
        self.progressbar.set_fraction(0.0)
        self.progressbar.set_text("Stopped" if stopped else "")

    def _on_stopped(self) -> None:
        """Worker reported a cooperative stop (between files/models)."""
        self._finish_run_ui(stopped=True)

    def _on_complete(self) -> None:
        self._stop_pulse()
        self._set_running(False)
        self.progressbar.set_fraction(1.0)
        self.progressbar.set_text(_PROGRESS_DONE)
        self._running_target = None
        output_dir = self._run_output_dir
        self._show_complete_toast(output_dir)
        self._send_completion_notification(output_dir)

    def _on_error(self, exc: BaseException) -> None:
        self._stop_pulse()
        self._set_running(False)
        self.progressbar.set_text("")
        self._report_error(f"Process failed: {exc}", exc)
        self._send_failure_notification()
        self._running_target = None

    def _show_complete_toast(self, output_dir: str) -> None:
        toast = Adw.Toast.new("Process complete.")
        if output_dir and os.path.isdir(output_dir):
            toast.set_button_label(_OPEN_FOLDER_LABEL)
            toast.connect("button-clicked", self._on_open_output_folder, output_dir)
        self.toast_overlay.add_toast(toast)

    def _on_open_output_folder(self, _toast: Adw.Toast, output_dir: str) -> None:
        launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(output_dir))
        launcher.launch(self, None, self._on_output_folder_launched)

    def _on_output_folder_launched(self, launcher: Gtk.FileLauncher, result) -> None:
        try:
            launcher.launch_finish(result)
        except GLib.Error as exc:
            self._toast(_OPEN_FOLDER_ERROR.format(message=exc.message))

    def _send_completion_notification(self, output_dir: str) -> None:
        title = _NOTIFY_COMPLETE_TITLE.format(label=self._run_label)
        if output_dir:
            body = _NOTIFY_COMPLETE_BODY.format(folder=os.path.basename(os.path.normpath(output_dir)))
        else:
            body = _NOTIFY_COMPLETE_BODY_PLAIN
        self._send_notification("uvr-complete", title, body)

    def _send_failure_notification(self) -> None:
        title = _NOTIFY_FAILED_TITLE.format(label=self._run_label)
        self._send_notification("uvr-failed", title, _NOTIFY_FAILED_BODY)

    def _send_notification(self, ident: str, title: str, body: str) -> None:
        try:
            app = self.get_application()
            if app is None:
                return
            notification = Gio.Notification.new(title)
            notification.set_body(body)
            icon_name = _NOTIFY_ICONS.get(ident, APP_ID)
            try:
                notification.set_icon(Gio.ThemedIcon.new(icon_name))
            except Exception:  # noqa: BLE001 - icon is best-effort
                pass
            app.send_notification(ident, notification)
        except Exception:  # noqa: BLE001 - notifications must never break a run
            pass

    def _on_progress(self, fraction: float) -> None:
        if fraction > _PROGRESS_EPSILON:
            self._stop_pulse()
            self.progressbar.set_fraction(fraction)
            self.progressbar.set_text(self._progress_text(fraction))

    def _progress_text(self, fraction: float) -> str:
        percent = int(round(fraction * 100))
        elapsed = max(0.0, time.monotonic() - self._run_started_at)
        parts = [f"{percent}%", f"{self._format_mmss(elapsed)} elapsed"]
        if fraction > 0.01 and fraction < 1.0:
            remaining = elapsed * (1.0 - fraction) / fraction
            parts.append(f"~{self._format_mmss(remaining)} left")
        return " · ".join(parts)

    @staticmethod
    def _format_mmss(seconds: float) -> str:
        total = int(seconds)
        return f"{total // 60}:{total % 60:02d}"

    def _report_error(self, message: str, exc: BaseException) -> None:
        from .errorlog import log_error

        target = self._running_target or self._run_target
        key = target.error_key if target is not None else self._active_view().method_key
        log_error(key, exc)
        toast = Adw.Toast.new(message)
        toast.set_button_label("Error Log")
        toast.set_action_name("win.error_log")
        self.toast_overlay.add_toast(toast)

    def _set_running(self, running: bool) -> None:
        self.start_button.set_sensitive(not running)
        self.stop_button.set_sensitive(running)

    # -- Misc -------------------------------------------------------------------

    def _on_open_settings(self, _action: Gio.SimpleAction, _param) -> None:
        from .preferences import PreferencesDialog

        dialog = PreferencesDialog(self.context, on_settings_reloaded=self._load_from_settings)
        dialog.present(self)

    def _on_ensemble(self, _action: Gio.SimpleAction, _param) -> None:
        self.content_stack.set_visible_child_name("ensemble")

    def _on_audio_tools(self, _action: Gio.SimpleAction, _param) -> None:
        self.content_stack.set_visible_child_name("audio_tools")

    def _on_download(self, _action: Gio.SimpleAction, _param) -> None:
        from .download import open_download_center

        open_download_center(self, self.context, on_models_changed=self._refresh_models)

    def _refresh_models(self) -> None:
        # New model files may add hash/name mappings and change stem filtering.
        self.context.repo.reload_mappers()
        self.context.repo.invalidate_stem_check()
        for view in self._views:
            view.refresh_models()
        self._update_sep_banner()

    def _on_about(self, _action: Gio.SimpleAction, _param) -> None:
        from .about import open_about

        open_about(self)

    def _on_updates(self, _action: Gio.SimpleAction, _param) -> None:
        from .updates import open_update_view

        open_update_view(self, self.context)

    def _on_error_log(self, _action: Gio.SimpleAction, _param) -> None:
        from .errorlog import open_error_log

        open_error_log(self)

    def _on_view_inputs(self, _action: Gio.SimpleAction, _param) -> None:
        from .inputs import open_view_inputs

        open_view_inputs(self, self.context, on_inputs_changed=self._on_external_inputs_changed)

    def _on_shortcuts(self, _action: Gio.SimpleAction, _param) -> None:
        from .shortcuts import present_shortcuts

        present_shortcuts(self)

    def toast(self, message: str) -> None:
        """Show a transient toast (public so the embedded pages can use it)."""
        self.toast_overlay.add_toast(Adw.Toast.new(message))

    def _toast(self, message: str) -> None:
        self.toast(message)
