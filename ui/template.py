"""Typed helpers for loading GtkBuilder documents from the resource bundle."""

from __future__ import annotations

from typing import TypeVar

from gi.repository import Adw, GObject, Gtk

from .resources import RESOURCE_PREFIX, require_resource_bundle

T = TypeVar("T", bound=GObject.Object)


def load_builder(name: str) -> Gtk.Builder:
    """Load ``resources/ui/<name>.blp`` through its compiled resource alias."""
    resource_path = f"{RESOURCE_PREFIX}/ui/{name}.ui"
    require_resource_bundle(resource_path)
    # GtkBuilder resolves type names without touching Python's lazy GI classes.
    # Direct dialog entry points may run before an Adw.Application registers them.
    Adw.init()
    return Gtk.Builder.new_from_resource(resource_path)


def object_from_builder(builder: Gtk.Builder, name: str, kind: type[T]) -> T:
    """Return a named builder object narrowed to its required GObject type."""
    obj = builder.get_object(name)
    if not isinstance(obj, kind):
        raise TypeError(f"{name}: expected {kind.__name__}, got {type(obj).__name__}")
    return obj
