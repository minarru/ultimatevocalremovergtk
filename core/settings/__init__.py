"""Typed nested settings model (JSON-backed)."""

from .defaults import SETTINGS_SCHEMA_VERSION
from .io import load_settings, save_settings
from .model import Settings

__all__ = [
    "SETTINGS_SCHEMA_VERSION",
    "Settings",
    "load_settings",
    "save_settings",
]
