"""Structural widget interfaces used by framework-light UI helpers."""

from __future__ import annotations

from typing import Protocol, Sequence

from core.settings import Settings


class InputPathsRow(Protocol):
    def set_paths(self, paths: Sequence[str], notify: bool = ...) -> None: ...


class OutputPathRow(Protocol):
    def set_path(self, path: str, notify: bool = ...) -> None: ...


class SwitchRow(Protocol):
    def set_active(self, active: bool) -> None: ...


class SampleModeRow(Protocol):
    def set_title(self, title: str) -> None: ...

    def set_subtitle(self, subtitle: str) -> None: ...

    def set_active(self, active: bool) -> None: ...


class FormatRow(Protocol):
    def apply_from_settings(self, settings: Settings) -> None: ...
