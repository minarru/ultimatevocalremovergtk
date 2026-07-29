"""Typed nested settings model (JSON-backed)."""

from core.settings_model import SettingsModel

from .defaults import SETTINGS_SCHEMA_VERSION
from .io import load_settings, save_settings
from .model import Settings

__all__ = [
    "SETTINGS_SCHEMA_VERSION",
    "Settings",
    "SettingsModel",
    "load_settings",
    "save_settings",
]
