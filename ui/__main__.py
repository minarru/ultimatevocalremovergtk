"""Allow ``python -m ui`` to launch the GTK4 application."""

from core.debug_log import normalize_g_messages_debug_env

normalize_g_messages_debug_env()

import sys

from .application import main

if __name__ == "__main__":
    sys.exit(main())
