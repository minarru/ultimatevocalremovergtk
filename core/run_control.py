"""Cooperative pause / stop helpers for background workers."""

import time

from .debug_log import debug, verbose


class ProcessStopped(Exception):
    """Raised when the user stops a run between work units."""


def wait_if_paused(runner) -> None:
    """Block the worker while ``runner.pause()`` is active."""
    while getattr(runner, "_is_paused", False) and not getattr(runner, "_is_stopped", False):
        if verbose():
            debug("worker", "paused waiting")
        time.sleep(0.05)


def check_stopped(runner) -> None:
    """Wait out any pause, then abort the worker loop if a stop was requested."""
    wait_if_paused(runner)
    if getattr(runner, "_is_stopped", False):
        debug("worker", "check_stopped raising ProcessStopped")
        raise ProcessStopped()


def pausable_callback(runner, callback):
    """Wrap a worker callback so pause/stop are honored during long inference steps."""
    def wrapper(*args, **kwargs):
        check_stopped(runner)
        return callback(*args, **kwargs)

    return wrapper
