"""Allow ``python -m core`` to invoke the headless CLI."""

from .cli import main

raise SystemExit(main())
