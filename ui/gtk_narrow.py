"""Narrowing helpers for GTK APIs typed as returning a base class or None.

Several GTK4 getters are declared against an interface (``Gtk.Root``,
``Gio.ListModel``, ``GObject.Object``) or as nullable, while the call sites here
always want the concrete widget. Doing the ``isinstance`` narrowing once keeps
the checks honest instead of scattering casts, and each of these was previously
an unguarded dereference that would raise ``AttributeError`` on the None path.
"""

from typing import List, Optional

from gi.repository import Gio, Gtk


def root_window(widget: Gtk.Widget) -> Optional[Gtk.Window]:
    """The window hosting ``widget``.

    ``get_root()`` is typed ``Gtk.Root | None``, but the file/folder dialogs
    take a ``Gtk.Window`` parent. An unrooted widget legitimately has none.
    """
    root = widget.get_root()
    return root if isinstance(root, Gtk.Window) else None


def file_paths(model: Gio.ListModel) -> List[str]:
    """Local filesystem paths from a ``Gio.ListModel`` of ``Gio.File``.

    ``get_item`` is typed ``GObject.Object | None`` and ``Gio.File.get_path``
    returns None for non-local URIs, so both are filtered out here.
    """
    paths: List[str] = []
    for index in range(model.get_n_items()):
        item = model.get_item(index)
        if isinstance(item, Gio.File):
            path = item.get_path()
            if path:
                paths.append(path)
    return paths
