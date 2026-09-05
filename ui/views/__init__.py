"""Processing-method views for the separation window.

Importing this package registers the built-in method views (VR, MDX-Net,
Demucs) into :data:`ui.views.base.METHOD_VIEWS`. Later phases add sibling
modules (e.g. ensemble, audio tools) and decorate their classes with
``@register_method_view`` to appear in the window's view switcher.
"""

from importlib import import_module as _import_module

from .base import METHOD_VIEWS, MethodView, register_method_view

# Import order sets the view-switcher order.
for _module in ("vr", "mdx", "demucs"):
    _import_module(f".{_module}", __name__)

__all__ = ["METHOD_VIEWS", "MethodView", "register_method_view"]
