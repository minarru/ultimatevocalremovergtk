"""Allow ``python -m ui`` to launch the GTK4 application."""

import sys

from core.debug_log import normalize_g_messages_debug_env


def main() -> int:
    normalize_g_messages_debug_env()
    from .application import main as application_main

    return application_main()


if __name__ == "__main__":
    sys.exit(main())
