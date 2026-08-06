"""Test package. Importing it arms the no-live-network guard (see net_guard)."""

from . import net_guard

net_guard.install()
