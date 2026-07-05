"""Processing-method views for the separation window.

Importing this package registers the built-in method views (VR, MDX-Net,
Demucs) into :data:`ui.views.base.METHOD_VIEWS`. Later phases add sibling
modules (e.g. ensemble, audio tools) and decorate their classes with
``@register_method_view`` to appear in the window's view switcher.
"""

from .base import METHOD_VIEWS, MethodView, register_method_view
from . import vr, mdx, demucs  # noqa: F401 - import order sets the view-switcher order

__all__ = ["METHOD_VIEWS", "MethodView", "register_method_view"]
