"""JSON settings persistence with one-shot pickle import."""

from __future__ import annotations

import json
import os
import pickle
from typing import Any

from core.debug_log import debug
from core.paths import (
    SETTINGS_JSON_FILE,
    SETTINGS_PICKLE_BAK,
    SETTINGS_PICKLE_FILE,
)

from .coerce import coerce_json_dict
from .model import Settings


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
    }
    return {key: value for key, value in stored.items() if key in allowed}


def _apply_autocast_default(settings: Settings, *, had_autocast: bool) -> None:
    if had_autocast:
        return
    from engines.amp_runtime import recommend_autocast

    settings.process.autocast = bool(recommend_autocast(settings.process.device))


def load_settings(path: str | None = None) -> Settings:
    """Load settings from JSON, importing legacy pickle once when needed."""
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

    pkl_path = SETTINGS_PICKLE_FILE
    if os.path.isfile(pkl_path):
        try:
            flat = _load_pickle_flat(pkl_path)
            had_autocast = "is_autocast" in flat
            settings = Settings.from_flat(flat)
            settings.path = json_path
            _apply_autocast_default(settings, had_autocast=had_autocast)
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
