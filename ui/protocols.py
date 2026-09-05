"""Structural widget interfaces used by framework-light UI helpers."""

from __future__ import annotations

from enum import Enum, auto
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


class FormatEdit(Enum):
    FORMAT = auto()
    QUALITY = auto()


class VocalSplitEdit(Enum):
    ENABLED = auto()
    MODEL = auto()
    SAVE_INSTRUMENTALS = auto()
    DEVERB = auto()
    DEVERB_OPTION = auto()


class ReadableInputPathsRow(Protocol):
    @property
    def paths(self) -> Sequence[str]: ...


class ReadableOutputPathRow(Protocol):
    @property
    def path(self) -> str: ...


class ReadableSwitchRow(Protocol):
    def get_active(self) -> bool: ...


class ReadableFormatRow(Protocol):
    @property
    def save_format(self) -> str: ...

    @property
    def quality_value(self) -> str: ...


class ReadableVocalSplitRow(Protocol):
    @property
    def enabled(self) -> bool: ...

    @property
    def model_value(self) -> str: ...

    @property
    def model_write_allowed(self) -> bool: ...

    @property
    def save_instrumentals(self) -> bool: ...

    @property
    def deverb(self) -> bool: ...

    @property
    def deverb_option(self) -> str: ...
