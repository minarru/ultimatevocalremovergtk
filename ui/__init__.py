"""GTK4 + libadwaita front end for Ultimate Vocal Remover (Linux-only).

This package hosts the ``Adw.Application``, the main window and (in later phases)
the separation UI, settings and dialogs. It drives the Tk-free backend in
:mod:`core`, marshaling the backend's worker-thread callbacks onto the GTK
main loop via :mod:`ui.dispatch`.

Importing this package requires the system PyGObject stack (gi / GTK 4.0 / Adw 1);
the required versions are pinned here before ``gi.repository`` is imported.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

APP_ID = "org.uvr.UltimateVocalRemover"
APP_TITLE = "Ultimate Vocal Remover"
