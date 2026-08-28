"""MDX runtime-contract view construction for the unified model manifest."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from core.mdx_runtime_contract import (
    MdxConfigEvidence,
    MdxRuntimeContract,
    MdxRuntimeContractRegistry,
    load_mdx_runtime_contract_document,
)
from core.model_stem_manifest import StemSemanticsRegistry
from core.paths import BASE_PATH

_BUNDLED_MDX_CONFIG_DIR = (
    Path(BASE_PATH) / "models" / "MDX_Net_Models" / "model_data" / "mdx_c_configs"
)


def mdx_runtime_registry() -> MdxRuntimeContractRegistry:
    """Return the runtime view from the one validated bundled registry."""
    from .loader import load_model_manifest

    return load_model_manifest().runtime


@lru_cache(maxsize=None)
def bundled_catalogue_config_evidence(
    model_id: str,
    config_yaml: str,
) -> MdxConfigEvidence | None:
    """Return exact bundled evidence for one manifest-associated config.

    Runtime-contract records already carry immutable parsed evidence. Other
    reviewed catalogue records may point at a checked-in generator seed; those
    bytes are parsed here only after the exact model/config association is
    confirmed by the unified manifest.
    """
    from core.model_data import load_mdx_c_config_data

    from .loader import load_model_manifest

    record = load_model_manifest().models.get(model_id)
    if record is None:
        return None
    associated = record.catalogue_evidence.config_yaml
    if associated and associated.casefold() != config_yaml.casefold():
        return None
    configured = next(
        (
            evidence
            for name, evidence in record.config_evidence.items()
            if name.casefold() == config_yaml.casefold()
        ),
        None,
    )
    if configured is not None:
        return configured
    if not associated:
        return None
    metadata_source = record.catalogue_evidence.metadata_source
    if metadata_source != f"bundled_yaml:{associated}":
        return None
    path = _BUNDLED_MDX_CONFIG_DIR / associated
    try:
        data = path.read_bytes()
        document = load_mdx_c_config_data(data)
    except Exception:
        return None
    training = document.get("training") if isinstance(document, Mapping) else None
    if not isinstance(training, Mapping):
        return None
    raw_instruments = training.get("instruments")
    if not isinstance(raw_instruments, (list, tuple)) or not raw_instruments:
        return None
    instruments = tuple(str(item) for item in raw_instruments)
    raw_target = training.get("target_instrument")
    target = None if raw_target in (None, "") else str(raw_target)
    source = path.relative_to(Path(BASE_PATH)).as_posix()
    return MdxConfigEvidence(
        training_instruments=instruments,
        target_instrument=target,
        content_sha256=hashlib.sha256(data).hexdigest(),
        sources=(source,),
    )


def build_runtime_view(
    contracts: Mapping[str, object],
    *,
    registry: StemSemanticsRegistry,
    model_config_evidence: Mapping[str, Mapping[str, MdxConfigEvidence]],
) -> MdxRuntimeContractRegistry:
    parsed = load_mdx_runtime_contract_document(
        {"schema_version": 2, "contracts": dict(contracts)},
        registry=registry,
    )
    projected: dict[str, MdxRuntimeContract] = {}
    for model_id, contract in parsed.contracts.items():
        semantic_declaration = registry.models[model_id]
        config_evidence = model_config_evidence[model_id]
        if contract.config_evidence != config_evidence:
            raise ValueError(
                f"runtime contract {model_id!r} config evidence drifted during projection"
            )
        projected[model_id] = replace(
            contract,
            native_signature=semantic_declaration.native_signature,
            config_evidence=config_evidence,
        )
    return MdxRuntimeContractRegistry(MappingProxyType(projected), parsed.warning)
