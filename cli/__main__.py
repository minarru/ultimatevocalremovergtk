"""Allow ``python -m cli`` to run the headless CLI."""

from .main import main

raise SystemExit(main())
