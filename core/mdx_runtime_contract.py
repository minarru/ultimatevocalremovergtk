"""Exact reviewed MDX runtime source inventories.

The direct loader is strict and suitable for generation/build gates.  The
application loader catches that one typed failure, logs once through its cache,
and returns an empty unavailable registry so runtime consumers remain raw.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping, Sequence

from .debug_log import log_event
from .model_identity import parse_stored_model_id
from .model_stem_manifest import (
    BUNDLED_MANIFEST_PATH,
    StemSemanticsRegistry,
    load_stem_manifest,
)
from .paths import BUNDLED_DATA_DIR

BUNDLED_MDX_RUNTIME_CONTRACT_PATH = Path(BUNDLED_DATA_DIR) / "model_runtime_stem_contracts.json"

MdxRuntimeBackend = Literal["classic_onnx", "mdx_c_target", "mdx_c_multi"]
MdxRuntimeSource = Literal["catalogue", "installed"]

_ROOT_FIELDS = frozenset({"schema_version", "contracts"})
_CONTRACT_FIELDS = frozenset(
    {
        "backend",
        "native_signature",
        "primary_native",
        "config_yamls",
        "evidence",
    }
)
_EVIDENCE_FIELDS = frozenset({"artifact_sources", "runtime_metadata_sources", "review_note"})
_BACKENDS = frozenset({"classic_onnx", "mdx_c_target", "mdx_c_multi"})
_SOURCE_PREFIXES = (
    "http://",
    "https://",
    "bundled/",
    "models/",
    "cache:",
    "checked-in:",
)


class MdxRuntimeContractError(ValueError):
    """A strict runtime-contract validation failure with its document path."""

    def __init__(self, path: tuple[str | int, ...], message: str) -> None:
        self.path = path
        self.message = message
        rendered = "".join(
            f"[{part}]" if isinstance(part, int) else ("." if index else "") + part
            for index, part in enumerate(path)
        )
        super().__init__(f"{rendered}: {message}")


@dataclass(frozen=True, slots=True)
class MdxRuntimeEvidence:
    artifact_sources: tuple[str, ...]
    runtime_metadata_sources: tuple[str, ...]
    review_note: str


@dataclass(frozen=True, slots=True)
class MdxRuntimeContract:
    model_id: str
    backend: MdxRuntimeBackend
    native_signature: tuple[str, ...]
    primary_native: str
    config_yamls: tuple[str, ...]
    evidence: MdxRuntimeEvidence


@dataclass(frozen=True, slots=True)
class MdxRuntimeContractRegistry:
    contracts: Mapping[str, MdxRuntimeContract]
    warning: str = ""

    @classmethod
    def empty(cls, warning: str = "") -> MdxRuntimeContractRegistry:
        return cls(MappingProxyType({}), warning)


@dataclass(frozen=True, slots=True)
class ReconciledMdxRuntimeSignature:
    """One exact lookup result; a warning means semantic review must stay raw."""

    native_signature: tuple[str, ...]
    contract: MdxRuntimeContract | None
    reviewed: bool
    warning: str = ""


def _error(path: tuple[str | int, ...], message: str) -> MdxRuntimeContractError:
    return MdxRuntimeContractError(path, message)


def _mapping(value: object, path: tuple[str | int, ...]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _error(path, "must be an object")
    if any(not isinstance(key, str) for key in value):
        raise _error(path, "keys must be strings")
    return value


def _closed_mapping(
    value: object,
    path: tuple[str | int, ...],
    *,
    fields: frozenset[str],
) -> Mapping[str, object]:
    document = _mapping(value, path)
    missing = sorted(fields.difference(document))
    if missing:
        raise _error(path + (missing[0],), "missing required field")
    unknown = sorted(set(document).difference(fields))
    if unknown:
        raise _error(path + (unknown[0],), "unknown field")
    return document


def _duplicate_aware_mapping(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _error(("runtime_contract",), f"duplicate key {key!r}")
        result[key] = value
    return result


def _string(value: object, path: tuple[str | int, ...]) -> str:
    if not isinstance(value, str) or not value:
        raise _error(path, "must be a non-empty string")
    if value != value.strip():
        raise _error(path, "must already be stripped")
    return value


def _string_list(
    value: object,
    path: tuple[str | int, ...],
    *,
    non_empty: bool,
    casefold_unique: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _error(path, "must be a list")
    result = tuple(_string(item, path + (index,)) for index, item in enumerate(value))
    if non_empty and not result:
        raise _error(path, "must contain at least one value")
    if len(set(result)) != len(result):
        raise _error(path, "duplicate value")
    if casefold_unique and len({item.casefold() for item in result}) != len(result):
        raise _error(path, "duplicate case-folded value")
    return result


def _source_list(value: object, path: tuple[str | int, ...]) -> tuple[str, ...]:
    result = _string_list(value, path, non_empty=True)
    for index, source in enumerate(result):
        if not source.startswith(_SOURCE_PREFIXES):
            raise _error(
                path + (index,),
                "must be an exact URL or checked-in/cache source identifier",
            )
    return result


def _canonical_mdx_id(value: str, path: tuple[str | int, ...]) -> str:
    try:
        model_id = parse_stored_model_id(value)
    except ValueError as error:
        raise _error(path, f"invalid canonical model ID: {error}") from error
    if model_id.family != "mdx":
        raise _error(path, "runtime contract ID must use the mdx family")
    return model_id.value


def _config_names(value: object, path: tuple[str | int, ...]) -> tuple[str, ...]:
    result = _string_list(value, path, non_empty=False, casefold_unique=True)
    for index, config in enumerate(result):
        if os.path.basename(config) != config or Path(config).suffix.casefold() not in {
            ".yaml",
            ".yml",
        }:
            raise _error(path + (index,), "must be a YAML config basename")
    return result


def _signature_matches(left: Sequence[str], right: Sequence[str]) -> bool:
    left_keys = tuple(item.casefold() for item in left)
    right_keys = tuple(item.casefold() for item in right)
    return len(left_keys) == len(right_keys) and set(left_keys) == set(right_keys)


def load_mdx_runtime_contract_document(
    document: object,
    *,
    registry: StemSemanticsRegistry,
) -> MdxRuntimeContractRegistry:
    """Strictly validate one complete runtime-contract document."""
    root = _closed_mapping(document, (), fields=_ROOT_FIELDS)
    schema_version = root["schema_version"]
    if type(schema_version) is not int or schema_version != 1:
        raise _error(("schema_version",), "must be the exact integer 1")
    raw_contracts = _mapping(root["contracts"], ("contracts",))
    contracts: dict[str, MdxRuntimeContract] = {}
    for raw_model_id, raw_contract in raw_contracts.items():
        path = ("contracts", raw_model_id)
        model_id = _canonical_mdx_id(raw_model_id, path)
        value = _closed_mapping(raw_contract, path, fields=_CONTRACT_FIELDS)
        backend_value = _string(value["backend"], path + ("backend",))
        if backend_value not in _BACKENDS:
            raise _error(path + ("backend",), "invalid backend")
        backend: MdxRuntimeBackend = backend_value  # type: ignore[assignment]
        signature = _string_list(
            value["native_signature"],
            path + ("native_signature",),
            non_empty=True,
            casefold_unique=True,
        )
        primary = _string(value["primary_native"], path + ("primary_native",))
        if primary not in signature:
            raise _error(path + ("primary_native",), "must be an exact native_signature member")
        configs = _config_names(value["config_yamls"], path + ("config_yamls",))
        if backend == "classic_onnx":
            if len(signature) != 2:
                raise _error(path + ("native_signature",), "classic_onnx requires exactly two keys")
            if configs:
                raise _error(path + ("config_yamls",), "classic_onnx does not accept configs")
        elif backend == "mdx_c_target":
            if len(signature) != 1:
                raise _error(path + ("native_signature",), "mdx_c_target requires exactly one key")
            if not configs:
                raise _error(path + ("config_yamls",), "mdx_c_target requires configs")
        else:
            if len(signature) < 2:
                raise _error(path + ("native_signature",), "mdx_c_multi requires at least two keys")
            if not configs:
                raise _error(path + ("config_yamls",), "mdx_c_multi requires configs")

        raw_evidence = _closed_mapping(
            value["evidence"], path + ("evidence",), fields=_EVIDENCE_FIELDS
        )
        evidence = MdxRuntimeEvidence(
            artifact_sources=_source_list(
                raw_evidence["artifact_sources"],
                path + ("evidence", "artifact_sources"),
            ),
            runtime_metadata_sources=_source_list(
                raw_evidence["runtime_metadata_sources"],
                path + ("evidence", "runtime_metadata_sources"),
            ),
            review_note=_string(
                raw_evidence["review_note"],
                path + ("evidence", "review_note"),
            ),
        )
        declaration = registry.models.get(model_id)
        if declaration is None:
            raise _error(path, "contract has no semantic manifest declaration")
        if not _signature_matches(signature, declaration.native_signature):
            raise _error(
                path + ("native_signature",),
                "does not match the semantic manifest signature",
            )
        contracts[model_id] = MdxRuntimeContract(
            model_id=model_id,
            backend=backend,
            native_signature=signature,
            primary_native=primary,
            config_yamls=configs,
            evidence=evidence,
        )
    return MdxRuntimeContractRegistry(MappingProxyType(contracts))


def load_mdx_runtime_contracts(
    path: Path,
    *,
    registry: StemSemanticsRegistry | None = None,
) -> MdxRuntimeContractRegistry:
    """Read and strictly validate the exact runtime-contract supplement."""
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_duplicate_aware_mapping,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _error(("runtime_contract",), f"could not read runtime contract: {error}") from error
    if registry is not None:
        semantic_registry = registry
    else:
        try:
            semantic_registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)
        except ValueError as error:
            raise _error(
                ("semantic_manifest",),
                f"could not validate semantic manifest parity: {error}",
            ) from error
    return load_mdx_runtime_contract_document(document, registry=semantic_registry)


@lru_cache(maxsize=1)
def load_bundled_mdx_runtime_contracts() -> MdxRuntimeContractRegistry:
    """Application boundary: log one failure and install an empty supplement."""
    try:
        return load_mdx_runtime_contracts(BUNDLED_MDX_RUNTIME_CONTRACT_PATH)
    except MdxRuntimeContractError as error:
        warning = f"runtime-contract-unavailable error={error}"
        log_event("model", "mdx_runtime_contract_invalid", level="error", error=str(error))
        return MdxRuntimeContractRegistry.empty(warning)


def reconcile_mdx_runtime_signature(
    model_id: str,
    *,
    observed_native_stems: Sequence[str],
    config_yaml: str = "",
    observed_primary_native: str = "",
    source: MdxRuntimeSource,
    contracts: MdxRuntimeContractRegistry | None = None,
) -> ReconciledMdxRuntimeSignature:
    """Reconcile one exact canonical ID without labels, aliases, or fuzzy lookup."""
    observed = tuple(str(native) for native in observed_native_stems if str(native))
    selected = contracts if contracts is not None else load_bundled_mdx_runtime_contracts()
    if selected.warning and model_id.startswith("mdx:"):
        return ReconciledMdxRuntimeSignature(observed, None, False, selected.warning)
    contract = selected.contracts.get(model_id)
    if contract is None:
        return ReconciledMdxRuntimeSignature(observed, None, False)

    if contract.config_yamls:
        accepted_configs = {name.casefold() for name in contract.config_yamls}
        if config_yaml.casefold() not in accepted_configs:
            return ReconciledMdxRuntimeSignature(
                observed,
                contract,
                False,
                "runtime-contract-mismatch "
                f"model_id={model_id} config={config_yaml!r} "
                f"expected={contract.config_yamls!r}",
            )
    elif config_yaml:
        return ReconciledMdxRuntimeSignature(
            observed,
            contract,
            False,
            f"runtime-contract-mismatch model_id={model_id} unexpected-config={config_yaml!r}",
        )

    # Classic catalogue rows often omit the computed inverse entirely.  The
    # exact artifact basename already produced ``model_id``; the contract is
    # the reviewed source inventory for that one artifact, not a name match.
    if source == "catalogue" and contract.backend == "classic_onnx":
        return ReconciledMdxRuntimeSignature(
            contract.native_signature,
            contract,
            True,
        )

    primary_matches = not observed_primary_native or (
        observed_primary_native.casefold() == contract.primary_native.casefold()
    )
    if _signature_matches(observed, contract.native_signature) and primary_matches:
        signature = contract.native_signature if source == "catalogue" else observed
        return ReconciledMdxRuntimeSignature(signature, contract, True)
    return ReconciledMdxRuntimeSignature(
        observed,
        contract,
        False,
        "runtime-contract-mismatch "
        f"model_id={model_id} expected={contract.native_signature!r} "
        f"actual={observed!r} expected_primary={contract.primary_native!r} "
        f"actual_primary={observed_primary_native!r}",
    )


def reconcile_catalogue_mdx_runtime_signature(
    model_id: str,
    instruments: Sequence[str],
    *,
    target_instrument: str = "",
    config_yaml: str = "",
    metadata_source: str = "",
    contracts: MdxRuntimeContractRegistry | None = None,
) -> ReconciledMdxRuntimeSignature:
    """Project collected config evidence through the same exact reconciler.

    Training instruments are not necessarily runtime outputs: an actual
    parsed MDX-C ``target_instrument`` config emits only that target.  This
    conversion lives here so collection, rendering, auditing, and the live
    Download Center cannot grow separate target/classic supplement rules.
    """
    selected = contracts if contracts is not None else load_bundled_mdx_runtime_contracts()
    contract = selected.contracts.get(model_id)
    parsed_config = config_yaml
    if not parsed_config and metadata_source.startswith(("bundled_yaml:", "remote_yaml:")):
        parsed_config = metadata_source.partition(":")[2]
    has_runtime_config = bool(parsed_config)
    if contract is not None and contract.backend == "classic_onnx":
        observed: tuple[str, ...] = ()
    elif target_instrument and has_runtime_config:
        observed = (str(target_instrument),)
    else:
        observed = tuple(str(native) for native in instruments if str(native))
    return reconcile_mdx_runtime_signature(
        model_id,
        observed_native_stems=observed,
        config_yaml=parsed_config,
        observed_primary_native=(
            str(target_instrument)
            if target_instrument and has_runtime_config
            else (observed[0] if observed and contract is not None else "")
        ),
        source="catalogue",
        contracts=selected,
    )


def is_catalogue_mdx_target_runtime(
    model_id: str,
    *,
    target_instrument: str = "",
    metadata_source: str = "",
    config_yaml: str = "",
) -> bool:
    """Whether exact parsed YAML evidence selects the one-target runtime path."""
    return bool(
        model_id.startswith("mdx:")
        and str(target_instrument)
        and (bool(config_yaml) or metadata_source.startswith(("bundled_yaml:", "remote_yaml:")))
    )
