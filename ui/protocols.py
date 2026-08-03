"""Structural widget interfaces used by framework-light UI helpers."""

from __future__ import annotations

from typing import Protocol, Sequence, Tuple

from core.settings import Settings


class InputPathsRow(Protocol):
    def set_paths(self, paths: Sequence[str], notify: bool = ...) -> None: ...


class OutputPathRow(Protocol):
    def set_path(self, path: str, notify: bool = ...) -> None: ...


class SwitchRow(Protocol):
    # Positional-only: Adw.SwitchRow names this parameter ``is_active``, and a
    # protocol with a named parameter would not match it structurally.
    def set_active(self, active: bool, /) -> None: ...


class SampleModeRow(Protocol):
    def set_title(self, title: str) -> None: ...

    def set_subtitle(self, subtitle: str) -> None: ...

    def set_active(self, active: bool, /) -> None: ...


class WindowSizing(Protocol):
    """The bit of ``Gtk.Window`` that dialog sizing actually needs.

    Typing against this rather than ``Gtk.Window`` lets the sizing tests pass a
    two-method fake instead of constructing a real window.
    """

    def get_width(self) -> int: ...

    def get_default_size(self) -> Tuple[int, int]: ...


class FormatRow(Protocol):
    def apply_from_settings(self, settings: Settings) -> None: ...
