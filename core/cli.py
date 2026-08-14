"""Deprecated location for the headless CLI — it now lives in :mod:`cli`.

``python -m core.cli`` and ``python -m core`` keep working; new callers should
use ``python -m cli``. :mod:`cli` is imported lazily inside :func:`main` so that
importing this module never inverts the ``cli -> core`` layering.
"""

from __future__ import annotations

from typing import Optional, Sequence


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Delegate to :func:`cli.main.main`."""
    from cli.main import main as _main

    return _main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
