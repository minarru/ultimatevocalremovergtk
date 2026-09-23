"""Bundled constants package (facade).

Domain modules live alongside this file; all public names are re-exported
here so ``from bundled.constants import X`` and ``import *`` keep working.
"""

from .defaults import *  # noqa: F403
from .formats import *  # noqa: F403
from .messages import *  # noqa: F403
from .platform_info import *  # noqa: F403
from .process import *  # noqa: F403
from .stems import *  # noqa: F403
from .urls import *  # noqa: F403


def __getattr__(name: str):
    """Lazy re-export for legacy ``from bundled.constants import …_HELP`` imports."""
    if name.endswith("_HELP"):
        import ui.help_text as _help_text

        return getattr(_help_text, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
