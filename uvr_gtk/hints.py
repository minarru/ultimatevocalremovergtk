"""Help-hints (tooltips) + keyboard accelerators.

Two reusable facilities other views/the main window can adopt:

* **Help hints** - tooltips for the main controls. Register ``(widget, text)``
  pairs with a :class:`HelpHintManager` (or use :func:`set_tooltip` for one-off
  widgets); tooltips are always shown on hover. :meth:`HelpHintManager.refresh`
  re-applies them (e.g. after rebuilding rows).

* **Keyboard accelerators** - :data:`KEYBOARD_ACCELERATORS` maps the window/app
  action names UVR exposes to accelerator strings, and :func:`apply_accelerators`
  installs them on a :class:`Gtk.Application`. The coordinator registers the
  matching actions; this module only declares the bindings + the apply helper.
"""

from typing import Dict, List, Optional

from gi.repository import Adw, Gtk

from uvr_gtk.help_text import (
    AUDIO_TOOLS_HELP,
    COMMAND_TEXT_HELP,
    IS_GPU_CONVERSION_HELP,
    MODEL_SAMPLE_MODE_HELP,
    OUTPUT_FORMAT_HINT,
    PROCESS_METHOD_HINT,
    SAVE_CURRENT_SETTINGS_HELP,
    SAVE_STEM_ONLY_HELP,
    SETTINGS_HELP,
    STOP_HELP,
    VIEW_TAB_HINTS,
)


def set_tooltip(widget, text: Optional[str]) -> None:
    """Apply a tooltip to ``widget`` (clears when ``text`` is empty)."""
    widget.set_tooltip_text(text or None)


def set_icon_button_a11y(widget, text: Optional[str]) -> None:
    """Set tooltip and accessible label for an icon-only button."""
    set_tooltip(widget, text)
    widget.update_property([Gtk.AccessibleProperty.LABEL], [text or ""])


def add_help_hint(widget, text: str, settings=None) -> None:
    """Set ``widget``'s tooltip to ``text``.

    A lightweight, stateless helper for views that don't need the manager.
    ``settings`` is accepted for call-site compatibility and ignored.
    """
    set_tooltip(widget, text)


class HelpHintManager:
    """Tracks help-hint widgets and applies their tooltips."""

    def __init__(self, settings=None):
        self.settings = settings
        self._registry: List = []

    def register(self, widget, text: str):
        """Register a widget + hint text and apply it immediately."""
        self._registry.append((widget, text))
        set_tooltip(widget, text)
        return widget

    def refresh(self) -> None:
        """Re-apply every registered tooltip (e.g. after rebuilding rows)."""
        for widget, text in self._registry:
            set_tooltip(widget, text)

# Curated reuse of UVR help-hint text for shared main-window controls.
SHARED_HINTS: Dict[str, str] = {
    "stop": STOP_HELP,
    "settings": SETTINGS_HELP,
    "console": COMMAND_TEXT_HELP,
    "saved_settings": SAVE_CURRENT_SETTINGS_HELP,
    "process_method": PROCESS_METHOD_HINT,
    "gpu_conversion": IS_GPU_CONVERSION_HELP,
    "stem_only": SAVE_STEM_ONLY_HELP,
    "sample_mode": MODEL_SAMPLE_MODE_HELP,
    "audio_tools": AUDIO_TOOLS_HELP,
}


def install_view_tab_tooltips(
    switcher: Adw.ViewSwitcher, hints: Optional[Dict[str, str]] = None
) -> None:
    """Attach tooltips to the tab buttons in an ``Adw.ViewSwitcher``.

    ``hints`` maps ``Adw.ViewStack`` page ``name`` to tooltip text. Page order is
    matched to toggle buttons left-to-right after the switcher is mapped.
    """
    hints = VIEW_TAB_HINTS if hints is None else hints

    def apply(_switcher: Adw.ViewSwitcher) -> None:
        stack = _switcher.get_stack()
        if stack is None:
            return
        tips = [hints.get(page.get_name(), "") for page in stack.get_pages()]

        buttons: List[Gtk.ToggleButton] = []

        def collect(widget) -> None:
            if isinstance(widget, Gtk.ToggleButton):
                buttons.append(widget)
            child = widget.get_first_child()
            while child is not None:
                collect(child)
                child = child.get_next_sibling()

        collect(_switcher)
        for button, tip in zip(buttons, tips):
            if tip:
                set_tooltip(button, tip)

    def on_map(_switcher):
        apply(_switcher)

    switcher.connect("map", on_map)
    if switcher.get_mapped():
        apply(switcher)


# Action name -> list of accelerator strings (Gtk accelerator syntax). These
# cover the menu/aux actions UVR exposes; the coordinator registers the actions.
KEYBOARD_ACCELERATORS: Dict[str, List[str]] = {
    "win.settings": ["<primary>comma"],
    "win.download": ["<primary>d"],
    "win.about": ["F1"],
    "win.updates": ["<primary>u"],
    "win.error_log": ["<primary>e"],
    "win.view_inputs": ["<primary>i"],
    "win.ensemble": ["<primary>l"],
    "win.audio_tools": ["<primary>t"],
    "win.start": ["<primary>Return"],
    "win.stop": ["<primary>period"],
    "win.shortcuts": ["<primary>question"],
    "app.quit": ["<primary>q"],
}


def apply_accelerators(app, accelerators: Optional[Dict[str, List[str]]] = None) -> None:
    """Install ``accelerators`` on a :class:`Gtk.Application`.

    Defaults to :data:`KEYBOARD_ACCELERATORS`. Actions with an empty list are
    skipped. Call after the matching actions have been added so the bindings
    resolve. Safe to call repeatedly.
    """
    table = KEYBOARD_ACCELERATORS if accelerators is None else accelerators
    for action_name, accels in table.items():
        if accels:
            app.set_accels_for_action(action_name, accels)
