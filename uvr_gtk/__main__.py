"""Allow ``python -m uvr_gtk`` to launch the GTK4 application."""

import sys

from .application import main

if __name__ == "__main__":
    sys.exit(main())
