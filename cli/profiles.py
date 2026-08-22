"""Sparse CLI profiles layered independently from GUI settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from core.paths import SETTINGS_CACHE_DIR, SETTINGS_DATA_FILE
from core.json_store import read_json_object, safe_json_path, write_json_atomic
from core.model_identity import FAMILIES, parse_stored_model_id
from core.settings import Settings
from core.settings.access import set_path, validate_setting_path, validate_setting_value

PROFILE_SCHEMA_VERSION = 1
PROFILE_DIR = os.path.join(SETTINGS_CACHE_DIR, "cli")
IDENTITY_SETTING_PATHS = frozenset({
    "process.method",
    "process.export_path",
    "process.input_paths",
    "process.model_hash_table",
    "vr.model",
    "mdx.model",
    "demucs.model",
    "ensemble.chosen_ensemble",
    "ensemble.selected_models",
})
MODEL_REFERENCE_SETTING_PATHS = frozenset({
    "audio_tools.apollo_model",
    "process.vocal_splitter",
    "vr.voc_inst_secondary_model", "vr.other_secondary_model",
    "vr.bass_secondary_model", "vr.drums_secondary_model",
    "mdx.voc_inst_secondary_model", "mdx.other_secondary_model",
    "mdx.bass_secondary_model", "mdx.drums_secondary_model",
    "demucs.voc_inst_secondary_model", "demucs.other_secondary_model",
    "demucs.bass_secondary_model", "demucs.drums_secondary_model",
    "demucs.pre_proc_model",
})


@dataclass
class LoadedProfile:
    name: str
    source: str
    path: Optional[str] = None
    model: Optional[str] = None
    ensemble: Optional[str] = None
    members: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    validation_warnings: list[str] = field(
        default_factory=list, repr=False, compare=False
    )

    @property
    def inherited_identity(self) -> bool:
        return bool(self.model or self.ensemble or self.members)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "name": self.name,
            "source": self.source,
            "path": self.path,
            "model": self.model,
            "ensemble": self.ensemble,
            "members": list(self.members),
            "settings": dict(self.settings),
        }


def profile_path(name: str) -> str:
    clean = str(name).strip()
    if (
        not clean
        or clean in {".", "..", "defaults", "gui"}
        or os.path.basename(clean) != clean
    ):
        raise ValueError(f"invalid profile name {name!r}")
    return safe_json_path(PROFILE_DIR, clean)


def _model_syntax_warning(path: str, value: Any) -> str | None:
    from bundled.constants import CHOOSE_MODEL, NO_MODEL

    if value is None or (
        isinstance(value, str) and value in {"", CHOOSE_MODEL, NO_MODEL}
    ):
        return None
    if isinstance(value, str):
        try:
            parse_stored_model_id(value)
        except ValueError:
            pass
        else:
            return None
    return (
        f"{path}: expected canonical model ID family:basename or a permitted "
        f"sentinel; preserved {value!r}; run 'uvr models list' to find IDs"
    )


def _profile_syntax_warnings(
    model: Any, members: list[str], values: dict[str, Any]
) -> list[str]:
    references = [("model", model)]
    references.extend(
        (f"members[{index}]", member) for index, member in enumerate(members)
    )
    references.extend(
        (path, values[path])
        for path in sorted(MODEL_REFERENCE_SETTING_PATHS.intersection(values))
    )
    return [
        warning
        for path, value in references
        if (warning := _model_syntax_warning(path, value)) is not None
    ]


def _qualify_stored_model(family: str, model: str) -> str | None:
    raw = str(model or "").strip()
    if not raw or raw.casefold() in {"choose model", "no model selected", "none"}:
        return None
    prefix = raw.partition(":")[0].casefold()
    if prefix in FAMILIES:
        return raw
    return f"{family}:{raw}"


def _identity_from_gui(settings: Settings) -> tuple[Optional[str], Optional[str], list[str]]:
    from bundled.constants import DEMUCS_ARCH_TYPE, ENSEMBLE_MODE, MDX_ARCH_TYPE, VR_ARCH_PM

    method = settings.process.method.value
    if method == ENSEMBLE_MODE:
        chosen = str(settings.ensemble.chosen_ensemble or "")
        members = list(settings.ensemble.selected_models or [])
        return None, chosen or None, members
    family = {
        VR_ARCH_PM: "vr",
        MDX_ARCH_TYPE: "mdx",
        DEMUCS_ARCH_TYPE: "demucs",
    }.get(method)
    section = {"vr": settings.vr, "mdx": settings.mdx, "demucs": settings.demucs}.get(family or "")
    model = str(getattr(section, "model", "") or "") if section is not None else ""
    return (_qualify_stored_model(family, model) if family else None), None, []


def _flatten_settings(settings: Settings) -> dict[str, Any]:
    payload = settings.to_json_dict()
    flat: dict[str, Any] = {}
    for section, values in payload.items():
        if section in {"schema_version", "ui", "audio_tools"} or not isinstance(values, dict):
            continue
        for field_name, value in values.items():
            path = f"{section}.{field_name}"
            if path not in IDENTITY_SETTING_PATHS and not isinstance(value, dict):
                flat[path] = value
    return flat


def apply_profile_values(settings: Settings, values: dict[str, Any]) -> None:
    for setting_path, value in values.items():
        if setting_path in IDENTITY_SETTING_PATHS:
            raise ValueError(
                f"profile setting {setting_path!r} is job identity/state; use the profile identity fields"
            )
        validate_setting_path(settings, setting_path, allow_containers=True)
        if not isinstance(value, (dict, list)):
            validate_setting_value(settings, setting_path, value)
        set_path(settings, setting_path, value)


def load_profile(spec: Optional[str]) -> tuple[Settings, LoadedProfile]:
    if spec in (None, "", "defaults"):
        return Settings.defaults(), LoadedProfile(name="defaults", source="built-in")
    if spec == "gui":
        settings = Settings.load(SETTINGS_DATA_FILE)
        model, ensemble, members = _identity_from_gui(settings)
        return settings, LoadedProfile(
            name="gui",
            source="gui",
            path=settings.path,
            model=model,
            ensemble=ensemble,
            members=members,
            settings=_flatten_settings(settings),
            validation_warnings=list(settings.validation_warnings),
        )
    path = spec if os.path.isfile(spec) else profile_path(spec)
    if not os.path.isfile(path):
        raise ValueError(f"profile not found: {spec!r}")
    payload = read_json_object(path)
    if payload.get("schema_version") != PROFILE_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported profile schema {payload.get('schema_version')!r}; "
            f"expected {PROFILE_SCHEMA_VERSION}"
        )
    values = payload.get("settings") or {}
    if not isinstance(values, dict):
        raise ValueError("profile settings must be an object")
    settings = Settings.defaults()
    # Profiles and manifests are typed JSON and may preserve list-valued
    # settings. ``--set`` intentionally remains scalar-only.
    apply_profile_values(settings, values)
    members = payload.get("members") or []
    if not isinstance(members, list) or not all(isinstance(item, str) for item in members):
        raise ValueError("profile members must be an array of model IDs")
    if payload.get("model") and (payload.get("ensemble") or members):
        raise ValueError("a profile cannot combine a primary model with ensemble identity")
    if payload.get("ensemble") and members:
        raise ValueError("a profile must choose an ensemble preset or a member list, not both")
    model = payload.get("model")
    validation_warnings = _profile_syntax_warnings(model, members, values)
    profile = LoadedProfile(
        name=str(payload.get("name") or os.path.splitext(os.path.basename(path))[0]),
        source="profile",
        path=path,
        model=model,
        ensemble=payload.get("ensemble"),
        members=list(members),
        settings=dict(values),
        validation_warnings=validation_warnings,
    )
    settings.validation_warnings.extend(validation_warnings)
    return settings, profile


def save_profile(profile: LoadedProfile, *, replace: bool = False) -> str:
    path = profile_path(profile.name)
    if os.path.exists(path) and not replace:
        raise ValueError(f"profile {profile.name!r} already exists; pass --replace")
    payload = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "name": profile.name,
        "model": profile.model,
        "ensemble": profile.ensemble,
        "members": profile.members,
        "settings": profile.settings,
    }
    write_json_atomic(path, payload)
    return path


def list_profiles() -> list[str]:
    if not os.path.isdir(PROFILE_DIR):
        return []
    return sorted(
        os.path.splitext(name)[0]
        for name in os.listdir(PROFILE_DIR)
        if name.endswith(".json") and os.path.isfile(os.path.join(PROFILE_DIR, name))
    )
