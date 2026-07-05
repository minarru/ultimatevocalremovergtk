"""Keyboard Shortcuts window for UVR.

Builds and presents a "Keyboard Shortcuts" overview like other GTK/GNOME apps.
The accelerators are pulled straight from :data:`ui.hints.KEYBOARD_ACCELERATORS`
so the window can never drift from the bindings actually installed on the app;
only the human-readable titles and the section grouping live here.

The modern :class:`Adw.ShortcutsDialog` (libadwaita 1.8+) is preferred, with a
graceful fallback to :class:`Gtk.ShortcutsWindow` on older runtimes.

Entry point: :func:`present_shortcuts`.
"""

from typing import List, Tuple

from gi.repository import Adw, Gtk

from .hints import KEYBOARD_ACCELERATORS

# Logical groups: (section title, [(action name, display title), ...]). The
# accelerator for each action is looked up in ``KEYBOARD_ACCELERATORS``; any
# action with no accelerator is skipped.
_SECTIONS: List[Tuple[str, List[Tuple[str, str]]]] = [
    (
        "Processing",
        [
            ("win.start", "Start processing"),
            ("win.stop", "Stop"),
        ],
    ),
    (
        "Modes",
        [
            ("win.ensemble", "Ensemble Mode"),
            ("win.audio_tools", "Audio Tools"),
        ],
    ),
    (
        "Application",
        [
            ("win.settings", "Settings"),
            ("win.download", "Download Center"),
            ("win.view_inputs", "View / Verify Inputs"),
            ("win.error_log", "Error Log"),
            ("win.updates", "Check for Updates"),
            ("win.about", "About"),
        ],
    ),
    (
        "General",
        [
            ("win.shortcuts", "Keyboard Shortcuts"),
            ("app.quit", "Quit"),
        ],
    ),
]


def _accelerator_for(action_name: str) -> str:
    """Return the first accelerator string for ``action_name`` (or "")."""
    accels = KEYBOARD_ACCELERATORS.get(action_name) or []
    return accels[0] if accels else ""


def _build_adw_dialog() -> "Adw.ShortcutsDialog":
    dialog = Adw.ShortcutsDialog()
    for section_title, items in _SECTIONS:
        section = Adw.ShortcutsSection(title=section_title)
        added = False
        for action_name, title in items:
            accelerator = _accelerator_for(action_name)
            if not accelerator:
                continue
            section.add(Adw.ShortcutsItem(title=title, accelerator=accelerator))
            added = True
        if added:
            dialog.add(section)
    return dialog


def _build_gtk_window(parent_window) -> "Gtk.ShortcutsWindow":
    section = Gtk.ShortcutsSection(visible=True)
    for section_title, items in _SECTIONS:
        group = Gtk.ShortcutsGroup(title=section_title, visible=True)
        added = False
        for action_name, title in items:
            accelerator = _accelerator_for(action_name)
            if not accelerator:
                continue
            group.add_shortcut(
                Gtk.ShortcutsShortcut(title=title, accelerator=accelerator, visible=True)
            )
            added = True
        if added:
            section.add_group(group)

    window = Gtk.ShortcutsWindow()
    window.add_section(section)
    window.set_transient_for(parent_window)
    window.set_modal(True)
    return window


def present_shortcuts(parent_window) -> None:
    """Build and present the Keyboard Shortcuts overview for ``parent_window``."""
    if hasattr(Adw, "ShortcutsDialog"):
        _build_adw_dialog().present(parent_window)
    else:
        _build_gtk_window(parent_window).present()
