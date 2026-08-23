"""JSON settings persistence with one-shot pickle import."""

from __future__ import annotations

import json
import os
import pickle
from typing import Any

from core import glib_log
from core.debug_log import debug
from core.paths import (
    SETTINGS_JSON_FILE,
    SETTINGS_PICKLE_BAK,
    SETTINGS_PICKLE_FILE,
)

from .coerce import coerce_json_dict
from .model import Settings

#: Cap on ``settings.json.bad`` siblings kept before we stop moving files aside.
_MAX_PRESERVED = 5


def _preserve_unreadable(path: str, exc: Exception) -> None:
    """Move an unloadable settings file aside and warn, before defaults win.

    Without this, a settings.json we failed to read is silently replaced by
    defaults on the next save, losing the user's whole configuration. Mirrors
    how the legacy pickle import preserves ``data.pkl`` as ``data.pkl.bak``.
    """
    target = f"{path}.bad"
    if os.path.exists(target):
        for n in range(2, _MAX_PRESERVED + 1):
            candidate = f"{path}.bad.{n}"
            if not os.path.exists(candidate):
                target = candidate
                break
        else:
            glib_log.emit(
                "uvr-settings",
                f"settings file unreadable ({type(exc).__name__}: {exc}); "
                f"{_MAX_PRESERVED} copies already preserved, leaving {path} in place",
                level="warning",
            )
            return

    try:
        os.rename(path, target)
    except OSError as rename_exc:
        glib_log.emit(
            "uvr-settings",
            f"settings file unreadable ({type(exc).__name__}: {exc}) and could not "
            f"be preserved ({rename_exc}); continuing with defaults",
            level="warning",
        )
        return

    glib_log.emit(
        "uvr-settings",
        f"settings file unreadable ({type(exc).__name__}: {exc}); "
        f"preserved as {target}, continuing with defaults",
        level="warning",
    )


def save_settings(settings: Settings, path: str | None = None) -> None:
    target = path or settings.path or SETTINGS_JSON_FILE
    if target.endswith(".pkl"):
        target = SETTINGS_JSON_FILE if path is None else target.replace(".pkl", ".json")
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    tmp_path = f"{target}.tmp"
    payload = settings.to_json_dict()
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.replace(tmp_path, target)
    settings.path = target
    debug("settings", f"save_settings ok path={target}")


def _load_pickle_flat(path: str) -> dict[str, Any]:
    with open(path, "rb") as handle:
        stored = pickle.load(handle)
    if not isinstance(stored, dict):
        return {}
    from bundled.constants import DEFAULT_DATA

    allowed = set(DEFAULT_DATA.keys()) | {
        "ensemble_main_stem",
        "ensemble_type",
        "selected_models",
        "chosen_ensemble",
        # Dropped from DEFAULT_DATA; still read so pickle import can migrate
        # them into process.stem_focus sentinels.
        "is_primary_stem_only",
        "is_secondary_stem_only",
        "is_primary_stem_only_Demucs",
        "is_secondary_stem_only_Demucs",
    }
    return {key: value for key, value in stored.items() if key in allowed}


def _apply_autocast_default(settings: Settings, *, had_autocast: bool) -> None:
    if had_autocast:
        return
    from engines.amp_runtime import recommend_autocast

    settings.process.autocast = bool(recommend_autocast(settings.process.device))


def load_settings(path: str | None = None) -> Settings:
    """Load settings from JSON, importing legacy pickle once when needed."""
    from core.access_policy import current_access_policy

    allow_metadata_writes = current_access_policy().allow_metadata_writes
    if path and path.endswith(".pkl"):
        json_sibling = path[:-4] + ".json"
        # Prefer JSON sibling once migration has already written it.
        if os.path.isfile(json_sibling):
            return load_settings(json_sibling)
        if os.path.isfile(path):
            flat = _load_pickle_flat(path)
            had_autocast = "is_autocast" in flat
            settings = Settings.from_flat(flat)
            settings.path = json_sibling
            _apply_autocast_default(settings, had_autocast=had_autocast)
            if allow_metadata_writes:
                save_settings(settings, json_sibling)
                backup_path = f"{path}.bak"
                if path == SETTINGS_PICKLE_FILE and not os.path.exists(SETTINGS_PICKLE_BAK):
                    os.rename(path, SETTINGS_PICKLE_BAK)
                elif not os.path.exists(backup_path) and os.path.isfile(path):
                    try:
                        os.rename(path, backup_path)
                    except OSError:
                        pass
            return settings
        settings = Settings.defaults()
        settings.path = json_sibling
        _apply_autocast_default(settings, had_autocast=False)
        return settings

    json_path = path or SETTINGS_JSON_FILE

    if os.path.isfile(json_path):
        try:
            with open(json_path, encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("settings root must be an object")
            settings = Settings.from_json_dict(coerce_json_dict(data))
            settings.path = json_path
            debug("settings", f"load_settings source=json path={json_path}")
            return settings
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            debug(
                "settings",
                f"load_settings json failed error={type(exc).__name__}: {exc}",
            )
            if allow_metadata_writes:
                _preserve_unreadable(json_path, exc)

    pkl_path = SETTINGS_PICKLE_FILE
    if os.path.isfile(pkl_path):
        try:
            flat = _load_pickle_flat(pkl_path)
            had_autocast = "is_autocast" in flat
            settings = Settings.from_flat(flat)
            settings.path = json_path
            _apply_autocast_default(settings, had_autocast=had_autocast)
            if allow_metadata_writes:
                save_settings(settings, json_path)
                if not os.path.exists(SETTINGS_PICKLE_BAK):
                    os.rename(pkl_path, SETTINGS_PICKLE_BAK)
            debug("settings", f"load_settings source=pickle-import path={json_path}")
            return settings
        except (OSError, ValueError, pickle.UnpicklingError, EOFError) as exc:
            debug(
                "settings",
                f"load_settings pickle failed error={type(exc).__name__}: {exc}",
            )

    settings = Settings.defaults()
    settings.path = json_path
    _apply_autocast_default(settings, had_autocast=False)
    debug("settings", f"load_settings source=defaults path={json_path}")
    return settings
