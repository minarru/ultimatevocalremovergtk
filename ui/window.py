"""Core separation main window.

This is the GTK4 / libadwaita port of ``UVR.py``'s ``MainWindow`` core
separation surface. It provides:

* a "Process method" dropdown (``Adw.ComboRow``) that swaps the visible option
  panel in a ``Gtk.Stack`` (VR Architecture / MDX-Net / Demucs), each panel
  contributed by a :class:`ui.views.MethodView`;
* input file(s) and output folder choosers with native drag and drop;
* the shared main-window options (output format, GPU conversion, sample mode);
* Start / Stop and a progress bar in a collapsible log panel at the bottom of
  the window (run controls always visible; log output expands above them), all
  wired to
  :class:`core.JobRunner` through :mod:`ui.dispatch` so worker-thread
  callbacks land on the GTK main loop.

Settings are persisted through the shared :class:`ui.context.AppContext`
using the exact ``DEFAULT_DATA`` keys, so the Phase 2 settings window and the
Phase 3 advanced panels read and write the same model.

Settings, Ensemble, Audio Tools, the Download Center, About, Updates, the
Error Log and the input viewer are all reachable through window
actions wired in :meth:`MainWindow._install_actions`, with keyboard accelerators
and help-hint tooltips installed from :mod:`ui.hints`.
"""

import os
from typing import Optional

from gi.repository import Adw, Gdk, Gio, Gtk

from bundled.constants import (
    INPUT_FOLDER_ENTRY_HELP,
    MDX_ARCH_TYPE,
    OUTPUT_FOLDER_ENTRY_HELP,
    VR_ARCH_PM,
    VR_ARCH_TYPE,
)

from . import APP_TITLE
from .audio_tools import AudioToolsPage
from .context import AppContext
from .ensemble import EnsemblePage
from .help_text import (
    MAIN_MENU_HINT,
    MODEL_OPTIONS_BUTTON_HINT,
    MODEL_OPTIONS_ROW_HINT,
    VIEW_INPUTS_BUTTON_HINT,
)
from .model_options import OPEN_CONTEXT_AUDIO_TOOLS, OPEN_CONTEXT_ENSEMBLE, OPEN_CONTEXT_SEPARATION, open_model_options_sheet
from .hints import (
    HelpHintManager,
    SHARED_HINTS,
    apply_accelerators,
    install_view_tab_tooltips,
    set_icon_button_a11y,
    set_tooltip,
)
from .dispatch import idle_on_main
from .files import open_folder_in_file_manager
from .run_control import RunController
from core.debug_log import debug
from .shared_settings import (
    SAMPLE_MODE_TITLE,
    apply_sample_mode_label,
    apply_shared_file_options,
    format_input_sanitize_toasts,
    gpu_dependent_enabled,
    sample_mode_subtitle,
    sanitize_input_paths,
)
from .views import METHOD_VIEWS
from .widgets.columns import (
    build_columns_box,
    options_scroller,
    set_columns_narrow,
    set_options_bottom_clearance,
    wrap_options_scroller,
)
from .widgets.file_chooser import InputFilesRow, OutputFolderRow
from .widgets.format_row import OutputFormatRow
from .widgets.log_panel import OVERLAY_MARGIN_BOTTOM, LogPanel
from .widgets.rows import get_combo_value, make_combo_row, make_switch_row, set_combo_value
from .widgets.download_queue_indicator import DownloadQueueIndicator
from .widgets.vocal_split_row import VocalSplitRow
from .download import init_download_queue_ui

#: Cadence (ms) and step of the indeterminate progress pulse shown before the
#: first real fractional update arrives.
_PULSE_INTERVAL_MS = 120
_PULSE_STEP = 0.08

#: Toast shown after copying the log to the clipboard.
_LOG_COPIED_TOAST = "Log copied"

#: Blocking-reason strings toasted from the shared Start dispatch when a
#: required field is missing.
_REASON_MODEL = "Choose a model"

# Tk / legacy settings may store the short process-method label instead of the
# Gtk view key (e.g. ``VR Arc`` vs ``VR Architecture``).
_METHOD_SETTING_ALIASES = {
    VR_ARCH_TYPE: VR_ARCH_PM,
}

#: Banner copy for a non-writable data folder. There is no in-app picker for
#: the data directory (it is resolved by ``core.paths`` from ``$UVR_DATA_DIR``,
#: the repo root, or the OS user-data dir), so the copy asks the user to fix
#: permissions rather than to choose a location.
_DATA_DIR_BANNER_TITLE = (
    "Can't write to the application data folder ({path}) — "
    "settings and downloads will fail. Fix its permissions to continue."
)


def data_dir_banner_state(data_dir: str) -> tuple[bool, str]:
    """Return ``(revealed, title)`` for the non-writable data-folder banner."""
    revealed = not os.access(data_dir, os.W_OK)
    return revealed, _DATA_DIR_BANNER_TITLE.format(path=data_dir)


def drop_target_row_name(tab_name, tool, dual_tools) -> Optional[str]:
    """Return which page's input row should receive a window-level file drop.

    Dual-input audio tools pair files positionally (left/right), so a drop with
    no drop point has no unambiguous meaning there — those keep their own
    per-row drop targets and are not routed.
    """
    if tab_name in ("separation", "ensemble"):
        return tab_name
    if tab_name == "audio_tools":
        return None if tool in dual_tools else "audio_tools"
    return None


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
        self.context.install_unrecognized_model_hook(lambda: self)

        self._install_actions()

        # The currently selected method view, whose option groups are placed
        # into the responsive columns by ``_populate_columns``.
        self._current_view = None
        self._columns_ready = False
        self._syncing_method_combo = False
        self._options_page = None
        self._model_options_sheet = None

        self._hint_manager = HelpHintManager()

        page = self._build_content()
        self.log_panel = LogPanel(
            on_expanded_changed=lambda *_: self._sync_options_bottom_clearance()
        )
        self.console = self.log_panel.console
        self.start_button = self.log_panel.start_button
        self.stop_button = self.log_panel.stop_button
        self.log_copy_button = self.log_panel.log_copy_button
        self.log_clear_button = self.log_panel.log_clear_button
        self.log_panel.set_progress_pulse_step(_PULSE_STEP)
        self.start_button.connect("clicked", self._on_start)
        self.stop_button.connect("clicked", self._on_stop)
        self.log_copy_button.connect("clicked", self._on_log_copy)
        self.log_clear_button.connect("clicked", self._on_log_clear)
        self.log_panel._progress_revealer.connect(
            "notify::child-revealed", lambda *_: self._sync_options_bottom_clearance()
        )
        self.log_panel._progress_revealer.connect(
            "notify::reveal-child", lambda *_: self._sync_options_bottom_clearance()
        )
        self.log_panel._log_revealer.connect(
            "notify::child-revealed", lambda *_: self._sync_options_bottom_clearance()
        )
        self.log_panel._log_revealer.connect(
            "notify::reveal-child", lambda *_: self._sync_options_bottom_clearance()
        )

        root = Gtk.Overlay()
        root.set_child(page)
        root.add_overlay(self.log_panel)
        window_drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        window_drop.connect("drop", self._on_window_drop)
        root.add_controller(window_drop)
        self.log_panel.set_halign(Gtk.Align.CENTER)
        self.log_panel.set_valign(Gtk.Align.END)
        self.log_panel.set_margin_bottom(OVERLAY_MARGIN_BOTTOM)

        self._download_queue_indicator = DownloadQueueIndicator()

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(self._build_header())
        # Narrow widths reveal a bottom ViewSwitcherBar; the header switcher is
        # swapped for a plain window title (Adwaita adaptive navigation).
        toolbar_view.add_bottom_bar(self._view_switcher_bar)
        toolbar_view.set_content(root)
        toolbar_view.set_vexpand(True)

        self._data_banner = Adw.Banner(button_label="Show Folder", revealed=False)
        self._data_banner.connect("button-clicked", self._on_data_banner_clicked)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.append(self._data_banner)
        outer.append(toolbar_view)
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(outer)
        self.set_content(self.toast_overlay)
        self._reveal_data_dir_banner_if_needed()

        init_download_queue_ui(self, self.context, on_models_changed=self._refresh_models)

        # Collapse the two option columns into a single column when the window
        # is narrow. ``set_orientation`` is driven from the apply/unapply
        # signals (explicit and PyGObject-safe vs. an enum ``add_setter``).
        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 880sp"))
        narrow.connect("apply", self._on_breakpoint_narrow)
        narrow.connect("unapply", self._on_breakpoint_wide)
        self.add_breakpoint(narrow)

        self._stale_export_toast_shown = False
        self._stale_inputs_toast_shown = False
        self._register_hints()
        self._apply_accelerators()

        self._load_from_settings()
        self.connect("map", self._on_window_mapped)
        self.connect("close-request", self._on_close_request)

    # -- Construction -----------------------------------------------------------

    def _build_header(self) -> Adw.HeaderBar:
        self._header = Adw.HeaderBar()

        self._view_switcher = Adw.ViewSwitcher()
        self._view_switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        self._view_switcher.set_stack(self.content_stack)
        install_view_tab_tooltips(self._view_switcher)
        self._header.set_title_widget(self._view_switcher)

        self._window_title = Adw.WindowTitle(title="Separation")
        self._view_switcher_bar = Adw.ViewSwitcherBar()
        self._view_switcher_bar.set_stack(self.content_stack)
        self._view_switcher_bar.set_reveal(False)
        install_view_tab_tooltips(self._view_switcher_bar)

        end_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        end_box.set_valign(Gtk.Align.CENTER)
        end_box.append(self._download_queue_indicator.widget)

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        set_icon_button_a11y(menu_button, MAIN_MENU_HINT)
        menu_button.set_menu_model(self._build_primary_menu())
        end_box.append(menu_button)

        self._header.pack_end(end_box)

        return self._header

    def _build_primary_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        tools = Gio.Menu()
        tools.append("Verify Inputs", "win.view_inputs")
        tools.append("Model options", "win.model_options")
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
        self.model_options_group = self._build_model_options_group()

        # Separation page: two side-by-side columns when wide, collapsed to one
        # when narrow (the breakpoint in ``__init__`` flips this box and every
        # other page's column box together). The columns are repopulated as the
        # active method changes, so the column references are kept.
        self._columns_box, self._col_start, self._col_end = build_columns_box()
        self._columns_ready = True
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
        self._sep_banner.connect("button-clicked", self._on_sep_banner_clicked)
        separation_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        separation_page.set_vexpand(True)
        separation_page.append(self._sep_banner)
        self._options_page = wrap_options_scroller(self._columns_box)
        separation_page.append(self._options_page)

        # Ensemble Mode and Audio Tools are embedded as sibling pages that reuse
        # the same responsive two-column layout and the shared run controls.
        self._ensemble_page = EnsemblePage(self, self.context)
        self._audio_tools_page = AudioToolsPage(self, self.context)

        # Runnable mode pages only; the shared console lives in the collapsible
        # log panel and auto-expands when a run starts.
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
        self._options_pages = [
            self._options_page,
            self._ensemble_page.options_page,
            self._audio_tools_page.options_page,
        ]

        # Shared Start/Stop dispatch to the run target of the visible tab.
        # ``RunController.running_target`` pins the dispatch to whatever actually
        # started, so Stop and error reporting stay correct even if the user
        # switches tabs mid-run.
        self._separation_target = _SeparationTarget(self)
        self._targets = {
            "separation": self._separation_target,
            "ensemble": self._ensemble_page,
            "audio_tools": self._audio_tools_page,
        }
        self._run_target = self._separation_target
        self._run_controller = RunController(self)
        self.content_stack.connect("notify::visible-child", self._on_visible_child)

        self.content_stack.set_vexpand(True)
        return self.content_stack

    def _populate_columns(self) -> None:
        """(Re)distribute the option groups across the two columns.

        Called at build time (static groups only) and whenever the active
        method changes. Groups are removed from their current column and
        re-appended so the layout reflects ``self._current_view``.

        The split keeps the common path on the left (Files, method, model,
        basic options, model-options entry) and the run/output path on the right
        (Save stems, Processing). Advanced and extra-model controls live in the
        model-options sheet instead of inline expanders.
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
            self._col_start.append(self.model_options_group)
            self._col_end.append(view.stem_group)
            self._col_end.append(self.shared_group)
        else:
            self._col_end.append(self.shared_group)

    def _show_method(self, view) -> None:
        """Make ``view`` the active method and refresh the column layout."""
        from core.debug_log import debug

        self._current_view = view
        debug("ui", f"method={getattr(view, 'title', view.method_key)}")
        if not self._columns_ready:
            return
        view._sync_only_active()
        self._populate_columns()
        self._update_sep_banner()
        self._refresh_separation_layout()

    def _refresh_separation_layout(self) -> None:
        """Force the options scroller to remeasure after column reparenting."""
        if self._current_view is None or self._options_page is None:
            return
        self._columns_box.queue_resize()
        scroller = options_scroller(self._options_page)
        scroller.queue_resize()
        clamp = scroller.get_child()
        if clamp is not None:
            clamp.queue_resize()

    def _on_window_mapped(self, *_args) -> None:
        from .download import start_download_size_cache_warmup

        start_download_size_cache_warmup(self.context)

        def refresh() -> None:
            if self._current_view is not None:
                self._populate_columns()
                self._refresh_separation_layout()
            self._sync_options_bottom_clearance()
            self._reveal_data_dir_banner_if_needed()

        idle_on_main(refresh)

    def _sync_options_bottom_clearance(self) -> None:
        """Keep scroll padding aligned with the floating log panel height."""
        clearance = self.log_panel.options_overlay_clearance()
        for columns_box in self._column_boxes:
            set_options_bottom_clearance(columns_box, clearance)
        for page in getattr(self, "_options_pages", ()):
            options_scroller(page).queue_allocate()

    def _reveal_data_dir_banner_if_needed(self) -> None:
        """Surface a non-writable data dir as a banner (not only a debug log line)."""
        banner = getattr(self, "_data_banner", None)
        if banner is None:
            return
        from core import paths

        revealed, title = data_dir_banner_state(paths.DATA_DIR)
        banner.set_title(title)
        banner.set_revealed(revealed)

    def _on_data_banner_clicked(self, _banner: Adw.Banner) -> None:
        from core import paths

        open_folder_in_file_manager(self, paths.DATA_DIR, on_error=self.toast)

    def _update_sep_banner(self) -> None:
        """Reveal the empty-state banner when the active method has no models."""
        banner = getattr(self, "_sep_banner", None)
        if banner is None:
            return
        banner.set_revealed(not self._active_view().has_any_models())
        self._refresh_start_readiness()

    def _on_sep_banner_clicked(self, _banner: Adw.Banner) -> None:
        self._on_download(None, None)

    def _on_breakpoint_narrow(self, _breakpoint) -> None:
        # Single stacked column on every page: drop homogeneity so groups size
        # by their own natural height instead of being forced to equal heights.
        for columns_box in self._column_boxes:
            set_columns_narrow(columns_box, True)
        self._header.set_title_widget(self._window_title)
        self._view_switcher_bar.set_reveal(True)

    def _on_breakpoint_wide(self, _breakpoint) -> None:
        for columns_box in self._column_boxes:
            set_columns_narrow(columns_box, False)
        self._header.set_title_widget(self._view_switcher)
        self._view_switcher_bar.set_reveal(False)

    def _sync_log_panel_expanded(self, expanded: bool) -> None:
        if self.log_panel.get_expanded() != expanded:
            self.log_panel.set_expanded(expanded)

    def _reveal_log_panel(self, revealed: bool) -> None:
        self._sync_log_panel_expanded(revealed)

    def _start_pulse(self) -> None:
        self.log_panel.start_progress_pulse(_PULSE_INTERVAL_MS)

    def _stop_pulse(self) -> None:
        self.log_panel.stop_progress_pulse()

    def _on_log_clear(self, _button: Gtk.Button) -> None:
        self.log_panel.clear_log()

    def _on_log_copy(self, _button: Gtk.Button) -> None:
        text = self.console.get_text()
        if not text:
            return
        self.console.get_clipboard().set(text)
        self.toast(_LOG_COPIED_TOAST)

    def _build_files_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Files")
        view_inputs_button = Gtk.Button(icon_name="view-list-symbolic", valign=Gtk.Align.CENTER)
        view_inputs_button.add_css_class("flat")
        set_icon_button_a11y(view_inputs_button, VIEW_INPUTS_BUTTON_HINT)
        view_inputs_button.set_action_name("win.view_inputs")
        group.set_header_suffix(view_inputs_button)
        self.input_row = InputFilesRow(
            self._on_inputs_changed,
            on_toast=self.toast,
            accept_any_getter=lambda: bool(self.settings.get("is_accept_any_input")),
            initial_folder_getter=lambda: (self.settings.get("input_paths") or [None])[0],
        )
        self.output_row = OutputFolderRow(self._on_output_changed, on_toast=self.toast)
        group.add(self.input_row)
        group.add(self.output_row)
        return group

    def _build_method_group(self) -> Adw.PreferencesGroup:
        # No group title: the "Process method" row already names the step, and
        # the adjacent (title-less) model group reads as one "pick method ->
        # pick model" block. This drops a redundant header from the separation
        # page (see also the per-arch title removed on the model group).
        group = Adw.PreferencesGroup()
        self.method_row = make_combo_row(
            "Process method",
            [view.title for view in self._views],
            icon_name="system-run-symbolic",
        )
        self.method_row.connect("notify::selected", self._on_method_selected)
        group.add(self.method_row)
        return group

    def _build_model_options_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup()
        self.model_options_row = Adw.ActionRow(
            title="Model options",
            subtitle="Batch size, secondary models, and more",
            activatable=True,
        )
        self.model_options_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        self.model_options_row.connect("activated", lambda *_: self._open_model_options())
        set_tooltip(self.model_options_row, MODEL_OPTIONS_ROW_HINT)
        group.add(self.model_options_row)
        return group

    def _build_shared_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Processing")

        self.format_row = OutputFormatRow(self._on_format_changed)
        group.add(self.format_row)

        self.gpu_row = make_switch_row("GPU conversion", icon_name="pci-card-symbolic")
        self.gpu_row.connect("notify::active", self._on_gpu_changed)
        group.add(self.gpu_row)

        self.autocast_row = make_switch_row(
            "FP16 autocast",
            subtitle="Faster VR/MDX/Roformer on modern NVIDIA GPUs",
            icon_name="emblem-system-symbolic",
        )
        self.autocast_row.connect("notify::active", self._on_autocast_changed)
        group.add(self.autocast_row)

        duration = self.settings.get("model_sample_mode_duration", 30)
        self.sample_row = make_switch_row(
            SAMPLE_MODE_TITLE,
            sample_mode_subtitle(duration),
            icon_name="preferences-system-time-symbolic",
        )
        self.sample_row.connect("notify::active", self._on_sample_changed)
        group.add(self.sample_row)

        self.vocal_split_row = VocalSplitRow(
            self.context.repo, self._on_vocal_split_changed, hints=self._hint_manager
        )
        group.add(self.vocal_split_row)

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
            "model_options": self._on_model_options,
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
        self._hint_manager.register(self.autocast_row, SHARED_HINTS["autocast"])
        self._hint_manager.register(self.sample_row, SHARED_HINTS["sample_mode"])
        self._hint_manager.register(self.console, SHARED_HINTS["console"])
        self._hint_manager.register(self.method_row, SHARED_HINTS["process_method"])
        self._hint_manager.register(self.input_row, INPUT_FOLDER_ENTRY_HELP)
        self._hint_manager.register(self.output_row, OUTPUT_FOLDER_ENTRY_HELP)
        self._hint_manager.register(self.model_options_row, MODEL_OPTIONS_ROW_HINT)
        from .help_text import PROGRESS_ETA_HINT

        self._hint_manager.register(self.log_panel._progress_label, PROGRESS_ETA_HINT)

    def _apply_accelerators(self) -> None:
        app = self.get_application()
        if app is not None:
            apply_accelerators(app)

    # -- Settings load / persist ------------------------------------------------

    def _load_from_settings(self) -> None:
        for view in self._views:
            view.load()

        raw_inputs = self.settings.get("input_paths") or []
        cleaned_inputs, input_result = sanitize_input_paths(raw_inputs)
        if cleaned_inputs != raw_inputs:
            self.settings.set("input_paths", cleaned_inputs)
        self.input_row.set_paths(cleaned_inputs, notify=False)
        self._maybe_notify_stale_inputs(input_result)
        export_path = self.settings.get("export_path") or ""
        self.output_row.set_path(export_path, notify=False)
        self._maybe_notify_stale_export_path()
        self.format_row.apply_from_settings(self.settings)
        self.vocal_split_row.apply_from_settings(self.settings)
        self.gpu_row.set_active(bool(self.settings.get("is_gpu_conversion")))
        self.autocast_row.set_active(bool(self.settings.get("is_autocast")))
        self._sync_gpu_dependent_rows()
        apply_sample_mode_label(self.sample_row, self.settings.get("model_sample_mode_duration", 30))
        self.sample_row.set_active(bool(self.settings.get("model_sample_mode")))

        method = self.settings.get("chosen_process_method") or MDX_ARCH_TYPE
        method = _METHOD_SETTING_ALIASES.get(method, method)
        view = self._views_by_method.get(method) or self._views_by_method.get(MDX_ARCH_TYPE) or self._views[0]
        self._syncing_method_combo = True
        try:
            set_combo_value(self.method_row, view.title)
        finally:
            self._syncing_method_combo = False
        # Always repopulate: the combo may already match ``view`` (so
        # ``notify::selected`` does not fire) and an earlier partial populate
        # can leave method-specific groups out of the column tree.
        self._show_method(view)
        idle_on_main(self._refresh_separation_layout)

        # The embedded mode pages load their own slice of the settings model.
        self._ensemble_page.load()
        self._audio_tools_page.load()
        self._sync_narrow_window_title()
        self._sync_model_options_action()

        if getattr(self, "_hint_manager", None) is not None:
            self._hint_manager.refresh()
        self._refresh_start_readiness()

    def _maybe_notify_stale_export_path(self) -> None:
        if getattr(self, "_stale_export_toast_shown", False):
            return
        if self.output_row.path and self.output_row.blocked_reason():
            self._stale_export_toast_shown = True
            idle_on_main(
                lambda: self.toast("Saved output folder no longer exists — select a new folder")
            )

    def _maybe_notify_stale_inputs(self, result) -> None:
        if self._stale_inputs_toast_shown:
            return
        messages = format_input_sanitize_toasts(
            result,
            include_missing=True,
            include_large_batch=False,
        )
        if not messages:
            return
        self._stale_inputs_toast_shown = True
        idle_on_main(lambda: self.toast(" ".join(messages)))

    def _active_view(self):
        return self._current_view or self._views[0]

    def _sync_shared_from_settings(self) -> None:
        """Re-read the cross-tab shared keys into the separation widgets."""
        apply_shared_file_options(
            self.settings,
            input_row=self.input_row,
            output_row=self.output_row,
            format_row=self.format_row,
            gpu_row=self.gpu_row,
            autocast_row=self.autocast_row,
            sample_row=self.sample_row,
        )
        self.vocal_split_row.apply_from_settings(self.settings)
        self._sync_gpu_dependent_rows()

    def _activate_separation(self) -> None:
        self.settings.set("chosen_process_method", self._active_view().method_key)
        self._sync_shared_from_settings()
        if self._current_view is not None:
            self._populate_columns()
            self._refresh_separation_layout()

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
        self._sync_narrow_window_title(name)
        self._sync_model_options_action(name)
        from core.debug_log import debug

        debug("ui", f"tab={name}")
        target.on_activated()
        self._refresh_start_readiness()

    def _sync_narrow_window_title(self, tab_name: Optional[str] = None) -> None:
        """Keep the narrow-layout header title aligned with the active tab."""
        name = tab_name or self.content_stack.get_visible_child_name()
        child = self.content_stack.get_visible_child()
        title = APP_TITLE
        if child is not None:
            page = self.content_stack.get_page(child)
            if page is not None and page.get_title():
                title = page.get_title()
        elif name == "separation":
            title = "Separation"
        elif name == "ensemble":
            title = "Ensemble"
        elif name == "audio_tools":
            title = "Audio Tools"
        self._window_title.set_title(title)

    def _sync_model_options_action(self, tab_name: Optional[str] = None) -> None:
        """Model options only apply to Separation / Ensemble runs."""
        name = tab_name or self.content_stack.get_visible_child_name()
        controller = getattr(self, "_run_controller", None)
        running = controller is not None and controller.is_running()
        enabled = name != "audio_tools" and not running
        action = self.lookup_action("model_options")
        if action is not None:
            action.set_enabled(enabled)
        if getattr(self, "model_options_row", None) is not None:
            self.model_options_row.set_sensitive(enabled)

    def _on_settings_changed(self) -> None:
        """Settings-changed hook handed to the method views.

        In-memory updates are flushed to disk on Start and on close. Readiness
        is refreshed here because method views call this hook after model edits.
        """
        self._refresh_start_readiness()

    def _on_method_selected(self, *_args) -> None:
        if self._syncing_method_combo or not self._columns_ready:
            return
        title = get_combo_value(self.method_row)
        if title is None:
            return
        view = self._views_by_title.get(title)
        if view is None:
            return
        self._show_method(view)
        self.settings.set("chosen_process_method", view.method_key)
        self._refresh_start_readiness()

    def _on_inputs_changed(self) -> None:
        paths = list(self.input_row.paths)
        self.settings.set("input_paths", paths)
        self.context.prune_unreadable_input_paths(paths)
        self._refresh_start_readiness()

    def _on_external_inputs_changed(self, paths) -> None:
        paths = list(paths)
        self.input_row.set_paths(paths, notify=False)
        self.settings.set("input_paths", paths)
        self.context.prune_unreadable_input_paths(paths)
        self._refresh_start_readiness()

    def _on_output_changed(self) -> None:
        self.settings.set("export_path", self.output_row.path)
        self._refresh_start_readiness()

    def _on_format_changed(self, *_args) -> None:
        self.format_row.persist_to_settings(self.settings)

    def _on_vocal_split_changed(self, *_args) -> None:
        self.vocal_split_row.persist_to_settings(self.settings)

    def _on_gpu_changed(self, *_args) -> None:
        self.settings.set("is_gpu_conversion", self.gpu_row.get_active())
        self._sync_gpu_dependent_rows()
        self._refresh_active_stem_metadata()

    def _on_autocast_changed(self, *_args) -> None:
        self.settings.set("is_autocast", self.autocast_row.get_active())

    def _on_sample_changed(self, *_args) -> None:
        self.settings.set("model_sample_mode", self.sample_row.get_active())
        self._refresh_active_stem_metadata()

    def _refresh_active_stem_metadata(self) -> None:
        view = self._active_view()
        if hasattr(view, "_update_stem_group_metadata"):
            view._update_stem_group_metadata()

    def _sync_gpu_dependent_rows(self) -> None:
        """Dim GPU-only options while GPU conversion is off."""
        self.autocast_row.set_sensitive(
            gpu_dependent_enabled(self.gpu_row.get_active())
        )

    def _on_close_request(self, *_args) -> bool:
        return self._run_controller.handle_close_request(self._finalize_close)

    def _finalize_close(self, deferred: bool) -> None:
        self._flush_settings()
        self._save_geometry()
        self._handle_settings_error(self.context.try_save_settings(trigger="close"))

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
        # The widgets below live on the Separation page only; they are kept in
        # sync with ``settings`` while Separation is visible (see
        # ``_activate_separation`` / ``_sync_shared_from_settings``), but go
        # stale the moment another tab is shown — Ensemble and Audio Tools each
        # have their own copies of these shared keys (format/quality, GPU,
        # autocast, sample mode, input/output paths) that stay live instead.
        # Flushing the stale Separation widgets here would clobber whatever the
        # other tab's own widgets just wrote, so only do it when Separation is
        # actually the visible tab.
        if self.content_stack.get_visible_child_name() == "separation":
            self.settings.set("input_paths", list(self.input_row.paths))
            self.settings.set("export_path", self.output_row.path)
            self.format_row.persist_to_settings(self.settings)
            self.vocal_split_row.persist_to_settings(self.settings)
            self.settings.set("is_gpu_conversion", self.gpu_row.get_active())
            self.settings.set("is_autocast", self.autocast_row.get_active())
            self.settings.set("model_sample_mode", self.sample_row.get_active())

    # -- Run control ------------------------------------------------------------

    def _on_start(self, _button: Gtk.Button) -> None:
        self._run_controller.handle_start(self._run_target)

    def _separation_blocked_reason(self) -> Optional[str]:
        """First reason the separation run can't start, or ``None`` when ready."""
        input_reason = self.input_row.blocked_reason(
            unreadable_paths=self.context.unreadable_input_paths
        )
        if input_reason:
            return input_reason
        output_reason = self.output_row.blocked_reason()
        if output_reason:
            return output_reason
        if not self._active_view().has_model():
            return _REASON_MODEL
        return None

    def _refresh_start_readiness(self) -> Optional[str]:
        controller = getattr(self, "_run_controller", None)
        if controller is None or not hasattr(self, "start_button"):
            return None
        return controller.refresh_start_readiness()

    def _start_separation(self, callbacks) -> None:
        """Separation run-target body (launch on the shared widgets)."""
        self._flush_settings()

        input_paths = list(self.input_row.paths)
        self.begin_run(self._separation_target)

        try:
            self._handle_settings_error(
                self.context.try_save_settings(trigger="start")
            )
            debug("ui", f"runner.start files={len(input_paths)}")
            self.context.runner.start(input_paths, callbacks)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.fail_to_start(f"Unable to start separation: {exc}", exc)

    def begin_run(self, target) -> None:
        """Shared run-start hook used by every embedded mode page."""
        self._run_controller.begin_run(target)

    def fail_to_start(self, message: str, exc: BaseException) -> None:
        """Shared run-start failure hook used by every embedded mode page."""
        self._run_controller.fail_to_start(message, exc)

    def _on_start_action(self, _action: Gio.SimpleAction, _param) -> None:
        self._run_controller.handle_start_action()

    def _on_stop_action(self, _action: Gio.SimpleAction, _param) -> None:
        self._run_controller.handle_stop_action()

    def _on_stop(self, _button: Gtk.Button) -> None:
        self._run_controller.handle_stop()

    # -- Misc -------------------------------------------------------------------

    def _sync_after_preferences(self) -> None:
        """Cheap re-read of the keys Preferences shares with the visible tab.

        Preferences only edits a handful of keys the processing pages mirror
        (format, GPU, sample mode), so a full ``_load_from_settings`` — which
        re-lists every model and reparents every option group — is far too
        heavy for a single switch flip.
        """
        target = self._targets.get(self.content_stack.get_visible_child_name())
        if target is not None:
            target.on_activated()
        self._refresh_start_readiness()

    def _on_open_settings(self, _action: Gio.SimpleAction, _param) -> None:
        from core.debug_log import debug

        debug("ui", "open settings")
        from .preferences import PreferencesDialog

        dialog = PreferencesDialog(
            self.context,
            on_settings_reloaded=self._load_from_settings,
            on_settings_applied=self._sync_after_preferences,
        )
        dialog.present(self)

    def _on_ensemble(self, _action: Gio.SimpleAction, _param) -> None:
        self.content_stack.set_visible_child_name("ensemble")

    def _on_audio_tools(self, _action: Gio.SimpleAction, _param) -> None:
        self.content_stack.set_visible_child_name("audio_tools")

    def _on_download(self, _action: Gio.SimpleAction, _param) -> None:
        from core.debug_log import debug

        debug("ui", "open download_center")
        from .download import open_download_center

        open_download_center(self, self.context, on_models_changed=self._refresh_models)

    def _refresh_models(self, *, source: str = "download_center") -> None:
        from core.debug_log import debug

        controller = getattr(self, "_run_controller", None)
        if controller is not None and controller.is_running():
            debug("ui", f"refresh_models deferred source={source} (run in progress)")
            self._deferred_model_refresh = source
            return
        self._apply_model_refresh(source=source)

    def _apply_model_refresh(self, *, source: str = "download_center") -> None:
        from core.debug_log import debug

        debug("ui", f"refresh_models source={source}")
        # New model files may add hash/name mappings and change stem filtering.
        self.context.repo.reload_mappers()
        self.context.repo.invalidate_stem_check()
        for view in self._views:
            view.refresh_models()
            method = getattr(view, "method_key", type(view).__name__)
            model_count = len(getattr(view, "list_models", lambda: [])())
            debug("model", f"refresh_models view={method} models={model_count}")
        # Apollo restoration models are downloadable too, but live on the Audio
        # Tools page rather than in ``self._views``.
        audio_tools = getattr(self, "_audio_tools_page", None)
        if audio_tools is not None:
            audio_tools.refresh_apollo_models()
        self._update_sep_banner()
        self._deferred_model_refresh = None

    def _on_about(self, _action: Gio.SimpleAction, _param) -> None:
        from core.debug_log import debug

        debug("ui", "open about")
        from .about import open_about

        open_about(self)

    def _on_updates(self, _action: Gio.SimpleAction, _param) -> None:
        from core.debug_log import debug

        debug("ui", "open updates")
        from .updates import open_update_view

        open_update_view(self, self.context)

    def _on_error_log(self, _action: Gio.SimpleAction, _param) -> None:
        from .errorlog import open_error_log

        open_error_log(self)

    def _input_row_for_drop(self):
        """Resolve the visible tab's input row, or ``None`` when not routable."""
        from core.audio_tools import DUAL_INPUT_TOOLS

        tab = self.content_stack.get_visible_child_name()
        tool = (
            self._audio_tools_page._current_tool()
            if tab == "audio_tools"
            else None
        )
        name = drop_target_row_name(tab, tool, DUAL_INPUT_TOOLS)
        if name == "separation":
            return self.input_row
        if name == "ensemble":
            return self._ensemble_page.input_row
        if name == "audio_tools":
            return self._audio_tools_page.inputs_row
        return None

    def _on_window_drop(self, _target, value, _x, _y) -> bool:
        row = self._input_row_for_drop()
        if row is None:
            return False
        # Delegate to the row's own handler so path expansion, the accept-any
        # setting, dedupe and the toasts all stay in one place.
        return row._on_drop(_target, value, _x, _y)

    def _on_view_inputs(self, _action: Gio.SimpleAction, _param) -> None:
        if self.content_stack.get_visible_child_name() == "audio_tools":
            from core.audio_tools import DUAL_INPUT_TOOLS

            page = self._audio_tools_page
            if page._current_tool() in DUAL_INPUT_TOOLS:
                page._on_open_dual_editor()
                return
        from .inputs import open_view_inputs

        open_view_inputs(self, self.context, on_inputs_changed=self._on_external_inputs_changed)

    def _on_model_options(self, _action: Gio.SimpleAction, _param) -> None:
        self._open_model_options()

    def _open_model_options(self, *, initial_stack: Optional[str] = None, context: Optional[str] = None) -> None:
        tab = self.content_stack.get_visible_child_name()
        if context is None:
            if tab == "ensemble":
                context = OPEN_CONTEXT_ENSEMBLE
            elif tab == "audio_tools":
                context = OPEN_CONTEXT_AUDIO_TOOLS
            else:
                context = OPEN_CONTEXT_SEPARATION
        # Audio Tools has no model options; the menu action is disabled there.
        if context == OPEN_CONTEXT_AUDIO_TOOLS:
            return

        selected_models = (
            self.settings.get("selected_models") or []
            if context == OPEN_CONTEXT_ENSEMBLE
            else []
        )
        self._model_options_sheet = open_model_options_sheet(
            self,
            views=self._views,
            views_by_stack=self._views_by_stack,
            settings=self.settings,
            context=context,
            active_method_key=self._active_view().method_key,
            selected_models=selected_models,
            initial_stack=initial_stack,
            existing=self._model_options_sheet,
        )

    def _on_shortcuts(self, _action: Gio.SimpleAction, _param) -> None:
        from .shortcuts import present_shortcuts

        present_shortcuts(self)

    def _handle_settings_error(self, error: Optional[str]) -> None:
        """Toast a settings-save failure and re-check the data-folder banner."""
        if not error:
            return
        self.toast(error)
        self._reveal_data_dir_banner_if_needed()

    def toast(self, message: str) -> None:
        """Show a transient toast (public so the embedded pages can use it)."""
        self.toast_overlay.add_toast(Adw.Toast.new(message))
