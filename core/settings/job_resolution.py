"""Typed settings construction shared by jobs, scripts, and frontends."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from bundled.constants import (
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
    MDX_ARCH_TYPE,
    VR_ARCH_PM,
)

from ..model_identity import ModelIdentityService
from ..types import ProcessMethod
from .access import apply_settings_overrides
from .model import Settings
from .resolution import apply_environment_overrides, validate_processing_settings

METHOD_ALIASES = {
    "mdx": MDX_ARCH_TYPE,
    "mdx-net": MDX_ARCH_TYPE,
    "demucs": DEMUCS_ARCH_TYPE,
    "vr": VR_ARCH_PM,
    "vr-architecture": VR_ARCH_PM,
    "ensemble": ENSEMBLE_MODE,
    "ensemble mode": ENSEMBLE_MODE,
}

def coerce_process_method(value: str | None) -> str | None:
    if value is None:
        return None
    token = str(value).strip().casefold()
    if token in METHOD_ALIASES:
        return METHOD_ALIASES[token]
    for method in (VR_ARCH_PM, MDX_ARCH_TYPE, DEMUCS_ARCH_TYPE, ENSEMBLE_MODE):
        if token == method.casefold():
            return method
    raise ValueError(f"unknown processing family {value!r}")


def resolve_splitter_identity(reference: str, settings: Settings, repo: Any) -> str:
    service = ModelIdentityService(repo)
    pool = list(repo.karaoke_model_list(settings))
    records: dict[str, str] = {}
    for tag in pool:
        try:
            records[service.canonical_id_from_member_tag(tag)] = tag
        except ValueError:
            continue
    try:
        record = service.resolve(reference)
    except ValueError:
        matches = [model_id for model_id, tag in records.items() if reference.casefold() in tag.casefold()]
        if len(matches) != 1:
            raise ValueError(f"unknown or ambiguous vocal splitter {reference!r}") from None
        return matches[0]
    if record.id not in records:
        raise ValueError(f"model {record.id} is not an installed vocal splitter")
    return record.id


@dataclass(frozen=True)
class SettingsLayer:
    source: str
    values: tuple[tuple[str, Any], ...]


class SettingsResolver:
    def resolve(
        self,
        base: Settings | None = None,
        *,
        layers: Iterable[SettingsLayer] = (),
        export_path: str | None = None,
        method: str | None = None,
        stable_naming: bool = False,
        base_provenance: Mapping[str, str] | None = None,
    ) -> tuple[Settings, dict[str, str]]:
        settings = copy.deepcopy(base) if base is not None else Settings.defaults()
        provenance: dict[str, str] = {
            f"{section}.{name}": "built-in"
            for section, values in settings.to_json_dict().items()
            if isinstance(values, dict)
            for name in values
        }
        provenance.update(base_provenance or {})
        if export_path is not None:
            settings.process.export_path = export_path
            provenance["process.export_path"] = "cli"
        resolved_method = coerce_process_method(method)
        if resolved_method is not None:
            settings.process.method = ProcessMethod(resolved_method)
            provenance["process.method"] = "derived"
        if stable_naming:
            for path, value in (
                ("process.create_model_folder", False),
                ("process.testing_audio", False),
                ("process.add_model_name", False),
            ):
                apply_settings_overrides(settings, [(path, value)])
                provenance[path] = "derived"
        for layer in layers:
            apply_settings_overrides(settings, layer.values)
            provenance.update({path: layer.source for path, _value in layer.values})
        for path in apply_environment_overrides(settings):
            provenance[path] = "environment"
        validate_processing_settings(settings)
        return settings, provenance


__all__ = [
    "SettingsLayer", "SettingsResolver",
    "coerce_process_method", "resolve_splitter_identity",
]
