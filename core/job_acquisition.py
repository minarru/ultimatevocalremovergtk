"""Acquire active MDX configurations, then refresh exact dependency identities."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, Protocol

from .job_plan_types import Diagnostic
from .model_identity import ModelRecord

if TYPE_CHECKING:
    from .job_dependencies import PlanningIdentities


class MdxConfigurationFiles(Protocol):
    def fallback_yaml(self, backend_name: str) -> str | None: ...
    def exists(self, yaml_name: str) -> bool: ...
    def ensure(self, yaml_name: str, *, allow_network: bool) -> bool: ...


class DefaultMdxConfigurationFiles:
    def fallback_yaml(self, backend_name: str) -> str | None:
        from .mdx_c_registry import yaml_for_checkpoint

        return yaml_for_checkpoint(backend_name)

    def exists(self, yaml_name: str) -> bool:
        from . import paths

        return os.path.isfile(os.path.join(paths.MDX_C_CONFIG_PATH, yaml_name))

    def ensure(self, yaml_name: str, *, allow_network: bool) -> bool:
        from .mdx_config_fetch import ensure_mdx_c_config

        return bool(ensure_mdx_c_config(yaml_name, allow_network=allow_network))


@dataclass(frozen=True)
class ConfigurationAcquisition:
    dependencies: Mapping[str, ModelRecord]
    available: bool
    diagnostics: tuple[Diagnostic, ...] = ()


def mdx_yaml_config_names(record: ModelRecord, configs: MdxConfigurationFiles) -> tuple[str, ...]:
    if record.family != "mdx":
        return ()
    if record.mdx is not None and record.mdx.kind == "classic_onnx":
        return ()
    names = tuple(
        name
        for name in record.artifacts.supporting_filenames
        if name.casefold().endswith((".yaml", ".yml"))
    )
    if names:
        return names
    if record.mdx is not None and record.mdx.kind != "classic_onnx":
        yaml_name = configs.fallback_yaml(record.backend_name)
        if yaml_name:
            return (yaml_name,)
    return ()


def is_repairable_mdx_config_dependency(
    record: ModelRecord, configs: MdxConfigurationFiles
) -> bool:
    """Whether planning may fetch one exact missing MDX-C YAML for this record."""
    names = mdx_yaml_config_names(record, configs)
    return (
        record.family == "mdx"
        and record.installed
        and not record.identity_complete
        and record.mdx is None
        and record.artifacts.primary_filename.casefold().endswith(".ckpt")
        and len(names) == 1
        and str(record.identity_error or "").startswith("unknown MDX YAML architecture")
    )


def acquire_configurations(
    dependencies: Mapping[str, ModelRecord],
    identities: PlanningIdentities,
    configs: MdxConfigurationFiles,
    *,
    allow_network: bool,
) -> ConfigurationAcquisition:
    refresh_needed = False
    try:
        for record in dependencies.values():
            for yaml_name in mdx_yaml_config_names(record, configs):
                if configs.exists(yaml_name):
                    if is_repairable_mdx_config_dependency(record, configs):
                        refresh_needed = True
                    continue
                if not allow_network:
                    raise ValueError(f"MDX configuration {yaml_name!r} is not available offline")
                if configs.ensure(yaml_name, allow_network=True):
                    refresh_needed = True
                else:
                    raise ValueError(f"MDX configuration {yaml_name!r} could not be downloaded")
        resolved = dict(dependencies)
        if refresh_needed:
            identities.invalidate()
            resolved = {path: identities.lookup(record.id) for path, record in dependencies.items()}
        for path, record in resolved.items():
            if not record.identity_complete:
                detail = record.identity_error or "identity metadata is incomplete"
                raise ValueError(f"{path} references model {record.id!r}: {detail}")
    except ValueError as exc:
        return ConfigurationAcquisition(
            dependencies, False, (Diagnostic("model.configuration", str(exc)),)
        )
    return ConfigurationAcquisition(resolved, True)
