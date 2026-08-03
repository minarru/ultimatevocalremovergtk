"""Typed access to per-widget state stashed on GTK instances.

Rows built by :mod:`ui.widgets.rows` and friends keep a little state on the
widget itself — the ``Gtk.Scale`` inside an ``Adw.ActionRow``, the value list
behind a discrete slider, the stored ids behind a combo. The widgets are
constructed by GTK, not subclassed by us, so there is nowhere else to put it.

Real GTK stubs reject the pattern outright: ``Adw.ActionRow`` does not declare
``_uvr_scale``, so ``row._uvr_scale = scale`` is an unknown-attribute error.
Routing it through ``setattr``/``getattr`` here keeps the runtime behaviour
byte-for-byte and tells the checker the dynamic access is deliberate, while
confining the unchecked part to four small functions instead of ~90 call sites.

Keys are the same ``_uvr_``-prefixed names as before, so anything reading these
widgets from outside (tests, GTK Inspector) is unaffected.
"""

from typing import Any


def stash(widget: object, key: str, value: Any) -> None:
    """Attach ``value`` to ``widget`` under ``key``."""
    setattr(widget, key, value)


def fetch(widget: object, key: str, default: Any = None) -> Any:
    """Read ``key`` off ``widget``, or ``default`` when it was never stashed."""
    return getattr(widget, key, default)


def has(widget: object, key: str) -> bool:
    """Whether ``key`` has been stashed on ``widget``."""
    return hasattr(widget, key)


def drop(widget: object, key: str) -> None:
    """Remove ``key`` from ``widget``; a no-op when it is not set."""
    try:
        delattr(widget, key)
    except AttributeError:
        pass
