"""Capture deliberate application emissions while retaining real file diagnostics."""

from contextlib import contextmanager
from typing import Iterator
from unittest import TestCase, mock

from core import glib_log


@contextmanager
def expected_event(test: TestCase, name: str) -> Iterator[list[str]]:
    """Assert one named event; unrelated emissions still reach their real sink."""
    messages: list[str] = []
    original = glib_log.emit

    def emit(domain: str, message: str, *, level: str = "debug") -> None:
        if message.split(" ", 1)[0] == f"event={name}":
            messages.append(message)
        else:
            original(domain, message, level=level)

    with mock.patch("core.glib_log.emit", side_effect=emit):
        yield messages
    test.assertEqual(len(messages), 1, messages)


@contextmanager
def expected_stderr_line(test: TestCase, message: str) -> Iterator[None]:
    """Remove one asserted fixture line, forwarding every other stderr line."""
    import io
    import sys
    from contextlib import redirect_stderr

    output = io.StringIO()
    try:
        with redirect_stderr(output):
            yield
    finally:
        lines = output.getvalue().splitlines(keepends=True)
        matches = [line for line in lines if line.rstrip("\n") == message]
        for line in lines:
            if line not in matches:
                sys.stderr.write(line)
        test.assertEqual(matches, [message + "\n"])
