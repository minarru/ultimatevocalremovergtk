"""Exact reviewed MDX runtime source inventories.

The direct loader is strict and suitable for generation/build gates.  The
application loader catches that one typed failure, logs once through its cache,
and returns an empty unavailable registry so runtime consumers remain raw.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping, Sequence
from urllib.parse import urlsplit

from .debug_log import log_event
from .model_identity import parse_stored_model_id
from .model_stem_manifest import (
    BUNDLED_MANIFEST_PATH,
    StemSemanticsRegistry,
    load_stem_manifest,
)
from .paths import BASE_PATH, BUNDLED_DATA_DIR

BUNDLED_MDX_RUNTIME_CONTRACT_PATH = Path(BUNDLED_DATA_DIR) / "model_runtime_stem_contracts.json"
REVIEWED_MDX_HASH_RECORD_SOURCE = "models/MDX_Net_Models/model_data/model_data.json"
REVIEWED_MDX_HASH_RECORD_PATH = Path(BASE_PATH) / REVIEWED_MDX_HASH_RECORD_SOURCE

MdxRuntimeBackend = Literal["classic_onnx", "mdx_c_target", "mdx_c_multi"]
MdxRuntimeSource = Literal["catalogue", "installed"]

_ROOT_FIELDS = frozenset({"schema_version", "contracts"})
_CONTRACT_FIELDS = frozenset(
    {
        "backend",
        "native_signature",
        "primary_native",
        "config_yamls",
        "artifact_evidence",
        "config_evidence",
        "evidence",
    }
)
_EVIDENCE_FIELDS = frozenset({"artifact_sources", "runtime_metadata_sources", "review_note"})
_ARTIFACT_EVIDENCE_FIELDS = frozenset({"uvr_md5", "hash_record_source"})
_CONFIG_EVIDENCE_FIELDS = frozenset(
    {"training_instruments", "target_instrument", "content_sha256", "sources"}
)
_BACKENDS = frozenset({"classic_onnx", "mdx_c_target", "mdx_c_multi"})
_SOURCE_PREFIXES = (
    "http://",
    "https://",
    "bundled/",
    "models/",
    "cache:",
    "checked-in:",
)
_UVR_MD5_PATTERN = re.compile(r"[0-9a-f]{32}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


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
class MdxArtifactEvidence:
    uvr_md5: str
    hash_record_source: str


@dataclass(frozen=True, slots=True)
class MdxConfigEvidence:
    training_instruments: tuple[str, ...]
    target_instrument: str | None
    content_sha256: str
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MdxRuntimeContract:
    model_id: str
    backend: MdxRuntimeBackend
    native_signature: tuple[str, ...]
    primary_native: str
    config_yamls: tuple[str, ...]
    artifact_evidence: tuple[MdxArtifactEvidence, ...]
    config_evidence: Mapping[str, MdxConfigEvidence]
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
    artifact_digest_verified: bool = False


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
        if source.startswith(("bundled/", "models/")):
            source_path = Path(BASE_PATH) / source
            if not source_path.is_file():
                raise _error(path + (index,), f"local evidence source does not exist: {source}")
    return result


def _optional_string(value: object, path: tuple[str | int, ...]) -> str | None:
    if value is None:
        return None
    return _string(value, path)


def _lower_hex(
    value: object,
    path: tuple[str | int, ...],
    *,
    pattern: re.Pattern[str],
    label: str,
) -> str:
    text = _string(value, path)
    if pattern.fullmatch(text) is None:
        raise _error(path, f"must be a lowercase {label} digest")
    return text


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


def _artifact_evidence(
    value: object,
    path: tuple[str | int, ...],
) -> tuple[MdxArtifactEvidence, ...]:
    if not isinstance(value, list) or not value:
        raise _error(path, "must be a non-empty list")
    result: list[MdxArtifactEvidence] = []
    for index, raw_item in enumerate(value):
        item_path = path + (index,)
        item = _closed_mapping(raw_item, item_path, fields=_ARTIFACT_EVIDENCE_FIELDS)
        digest = _lower_hex(
            item["uvr_md5"],
            item_path + ("uvr_md5",),
            pattern=_UVR_MD5_PATTERN,
            label="UVR MD5",
        )
        hash_record_source = _string(
            item["hash_record_source"],
            item_path + ("hash_record_source",),
        )
        if hash_record_source != REVIEWED_MDX_HASH_RECORD_SOURCE:
            raise _error(
                item_path + ("hash_record_source",),
                f"must be {REVIEWED_MDX_HASH_RECORD_SOURCE!r}",
            )
        result.append(MdxArtifactEvidence(digest, hash_record_source))
    if len({item.uvr_md5 for item in result}) != len(result):
        raise _error(path, "duplicate UVR MD5 digest")
    return tuple(result)


def _config_evidence(
    value: object,
    path: tuple[str | int, ...],
    *,
    configs: tuple[str, ...],
) -> Mapping[str, MdxConfigEvidence]:
    raw_mapping = _mapping(value, path)
    if set(raw_mapping) != set(configs):
        raise _error(path, "keys must exactly match config_yamls")
    result: dict[str, MdxConfigEvidence] = {}
    for config_name in configs:
        item_path = path + (config_name,)
        item = _closed_mapping(
            raw_mapping[config_name],
            item_path,
            fields=_CONFIG_EVIDENCE_FIELDS,
        )
        result[config_name] = MdxConfigEvidence(
            training_instruments=_string_list(
                item["training_instruments"],
                item_path + ("training_instruments",),
                non_empty=True,
                casefold_unique=True,
            ),
            target_instrument=_optional_string(
                item["target_instrument"],
                item_path + ("target_instrument",),
            ),
            content_sha256=_lower_hex(
                item["content_sha256"],
                item_path + ("content_sha256",),
                pattern=_SHA256_PATTERN,
                label="SHA-256",
            ),
            sources=_source_list(item["sources"], item_path + ("sources",)),
        )
    return MappingProxyType(result)


def _reviewed_hash_records() -> Mapping[str, object]:
    try:
        document = json.loads(
            REVIEWED_MDX_HASH_RECORD_PATH.read_text(encoding="utf-8"),
            object_pairs_hook=_duplicate_aware_mapping,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _error(
            ("runtime_metadata",),
            f"could not read reviewed MDX hash records: {error}",
        ) from error
    return _mapping(document, ("runtime_metadata",))


def reviewed_mdx_hash_record_source(artifact_digest: str) -> str:
    """Return positive checked-in provenance for one exact mapper digest."""
    if _UVR_MD5_PATTERN.fullmatch(artifact_digest) is None:
        return ""
    try:
        records = _reviewed_hash_records()
    except MdxRuntimeContractError:
        return ""
    return REVIEWED_MDX_HASH_RECORD_SOURCE if artifact_digest in records else ""


def _training_fields(config: object) -> tuple[tuple[str, ...], str | None]:
    training = config.get("training") if isinstance(config, Mapping) else None
    if not isinstance(training, Mapping):
        return (), None
    raw_instruments = training.get("instruments")
    instruments = (
        tuple(str(item) for item in raw_instruments) if isinstance(raw_instruments, list) else ()
    )
    raw_target = training.get("target_instrument")
    target = str(raw_target) if raw_target not in (None, "") else None
    return instruments, target


def _validate_local_config_evidence(
    config_name: str,
    evidence: MdxConfigEvidence,
    path: tuple[str | int, ...],
) -> None:
    from .model_data import load_mdx_c_config_data

    for index, source in enumerate(evidence.sources):
        if not source.startswith(("bundled/", "models/")):
            continue
        source_path = Path(BASE_PATH) / source
        try:
            data = source_path.read_bytes()
        except OSError as error:
            raise _error(path + ("sources", index), f"could not read source: {error}") from error
        digest = hashlib.sha256(data).hexdigest()
        if digest != evidence.content_sha256:
            raise _error(path + ("content_sha256",), "does not match local source bytes")
        try:
            config = load_mdx_c_config_data(data)
        except Exception as error:
            raise _error(
                path + ("sources", index), f"could not parse source YAML: {error}"
            ) from error
        instruments, target = _training_fields(config)
        if instruments != evidence.training_instruments:
            raise _error(
                path + ("training_instruments",),
                f"does not match parsed {config_name} training.instruments",
            )
        if target != evidence.target_instrument:
            raise _error(
                path + ("target_instrument",),
                f"does not match parsed {config_name} training.target_instrument",
            )


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
    if type(schema_version) is not int or schema_version != 2:
        if schema_version == 1:
            raise _error(
                ("schema_version",),
                "schema 1 migration is not supported; require the exact integer 2",
            )
        raise _error(("schema_version",), "must be the exact integer 2")
    raw_contracts = _mapping(root["contracts"], ("contracts",))
    hash_records = _reviewed_hash_records()
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
        artifact_evidence = _artifact_evidence(
            value["artifact_evidence"],
            path + ("artifact_evidence",),
        )
        config_evidence = _config_evidence(
            value["config_evidence"],
            path + ("config_evidence",),
            configs=configs,
        )
        if backend == "classic_onnx":
            if len(signature) != 2:
                raise _error(path + ("native_signature",), "classic_onnx requires exactly two keys")
            if configs:
                raise _error(path + ("config_yamls",), "classic_onnx does not accept configs")
            if config_evidence:
                raise _error(
                    path + ("config_evidence",),
                    "classic_onnx does not accept config evidence",
                )
        elif backend == "mdx_c_target":
            if len(signature) != 1:
                raise _error(path + ("native_signature",), "mdx_c_target requires exactly one key")
            if not configs:
                raise _error(path + ("config_yamls",), "mdx_c_target requires configs")
            for config_name, config in config_evidence.items():
                if config.target_instrument != primary:
                    raise _error(
                        path + ("config_evidence", config_name, "target_instrument"),
                        "mdx_c_target requires the exact primary_native target",
                    )
                if primary not in config.training_instruments:
                    raise _error(
                        path + ("config_evidence", config_name, "training_instruments"),
                        "must contain primary_native",
                    )
        else:
            if len(signature) < 2:
                raise _error(path + ("native_signature",), "mdx_c_multi requires at least two keys")
            if not configs:
                raise _error(path + ("config_yamls",), "mdx_c_multi requires configs")
            for config_name, config in config_evidence.items():
                if config.target_instrument is not None:
                    raise _error(
                        path + ("config_evidence", config_name, "target_instrument"),
                        "mdx_c_multi requires a null target",
                    )
                if tuple(config.training_instruments) != signature:
                    raise _error(
                        path + ("config_evidence", config_name, "training_instruments"),
                        "mdx_c_multi requires the exact ordered native_signature",
                    )

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
        artifact_basename = model_id.removeprefix("mdx:")
        public_artifact_names = {
            Path(urlsplit(source).path).stem
            for source in evidence.artifact_sources
            if source.startswith("https://")
        }
        if artifact_basename not in public_artifact_names:
            raise _error(
                path + ("evidence", "artifact_sources"),
                f"must include an exact public artifact for {artifact_basename!r}",
            )
        if REVIEWED_MDX_HASH_RECORD_SOURCE not in evidence.runtime_metadata_sources:
            raise _error(
                path + ("evidence", "runtime_metadata_sources"),
                f"must include {REVIEWED_MDX_HASH_RECORD_SOURCE!r}",
            )
        for artifact_index, artifact in enumerate(artifact_evidence):
            record_path = path + ("artifact_evidence", artifact_index)
            raw_record = hash_records.get(artifact.uvr_md5)
            if raw_record is None:
                raise _error(record_path + ("uvr_md5",), "has no checked-in hash record")
            record = _mapping(raw_record, record_path + ("hash_record",))
            if backend == "classic_onnx":
                record_primary = record.get("primary_stem")
                if (
                    not isinstance(record_primary, str)
                    or record_primary.casefold() != primary.casefold()
                ):
                    raise _error(
                        record_path + ("uvr_md5",),
                        "checked-in hash record primary_stem disagrees with primary_native",
                    )
            else:
                record_config = record.get("config_yaml")
                if not isinstance(record_config, str) or record_config.casefold() not in {
                    config.casefold() for config in configs
                }:
                    raise _error(
                        record_path + ("uvr_md5",),
                        "checked-in hash record config_yaml is not accepted",
                    )
        for config_name, config in config_evidence.items():
            _validate_local_config_evidence(
                config_name,
                config,
                path + ("config_evidence", config_name),
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
            artifact_evidence=artifact_evidence,
            config_evidence=config_evidence,
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


def _config_evidence_for_name(
    contract: MdxRuntimeContract,
    config_yaml: str,
) -> MdxConfigEvidence | None:
    folded = config_yaml.casefold()
    return next(
        (
            evidence
            for name, evidence in contract.config_evidence.items()
            if name.casefold() == folded
        ),
        None,
    )


def reconcile_mdx_runtime_signature(
    model_id: str,
    *,
    observed_native_stems: Sequence[str],
    config_yaml: str = "",
    config_sha256: str = "",
    training_instruments: Sequence[str] = (),
    target_instrument: str = "",
    observed_primary_native: str = "",
    artifact_digest: str = "",
    hash_record_source: str = "",
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

    artifact_digest_verified = False
    if source == "installed":
        artifact = next(
            (item for item in contract.artifact_evidence if item.uvr_md5 == artifact_digest),
            None,
        )
        if artifact is None:
            return ReconciledMdxRuntimeSignature(
                observed,
                contract,
                False,
                "runtime-contract-mismatch "
                f"model_id={model_id} artifact digest={artifact_digest!r} "
                f"expected={tuple(item.uvr_md5 for item in contract.artifact_evidence)!r}",
            )
        if hash_record_source != artifact.hash_record_source:
            return ReconciledMdxRuntimeSignature(
                observed,
                contract,
                False,
                "runtime-contract-mismatch "
                f"model_id={model_id} hash-record-source={hash_record_source!r} "
                f"expected={artifact.hash_record_source!r}",
            )
        artifact_digest_verified = True

    if contract.config_yamls:
        config = _config_evidence_for_name(contract, config_yaml)
        if config is None:
            return ReconciledMdxRuntimeSignature(
                observed,
                contract,
                False,
                "runtime-contract-mismatch "
                f"model_id={model_id} config={config_yaml!r} "
                f"expected={contract.config_yamls!r}",
            )
        if config_sha256 != config.content_sha256:
            return ReconciledMdxRuntimeSignature(
                observed,
                contract,
                False,
                "runtime-contract-mismatch "
                f"model_id={model_id} config content SHA-256={config_sha256!r} "
                f"expected={config.content_sha256!r}",
                artifact_digest_verified,
            )
        actual_instruments = tuple(str(item) for item in training_instruments)
        if actual_instruments != config.training_instruments:
            return ReconciledMdxRuntimeSignature(
                observed,
                contract,
                False,
                "runtime-contract-mismatch "
                f"model_id={model_id} training.instruments={actual_instruments!r} "
                f"expected={config.training_instruments!r}",
                artifact_digest_verified,
            )
        actual_target = str(target_instrument) if target_instrument else None
        if actual_target != config.target_instrument:
            return ReconciledMdxRuntimeSignature(
                observed,
                contract,
                False,
                "runtime-contract-mismatch "
                f"model_id={model_id} training.target_instrument={actual_target!r} "
                f"expected={config.target_instrument!r}",
                artifact_digest_verified,
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
            artifact_digest_verified=artifact_digest_verified,
        )

    primary_matches = not observed_primary_native or (
        observed_primary_native.casefold() == contract.primary_native.casefold()
    )
    if _signature_matches(observed, contract.native_signature) and primary_matches:
        signature = contract.native_signature if source == "catalogue" else observed
        return ReconciledMdxRuntimeSignature(
            signature,
            contract,
            True,
            artifact_digest_verified=artifact_digest_verified,
        )
    return ReconciledMdxRuntimeSignature(
        observed,
        contract,
        False,
        "runtime-contract-mismatch "
        f"model_id={model_id} expected={contract.native_signature!r} "
        f"actual={observed!r} expected_primary={contract.primary_native!r} "
        f"actual_primary={observed_primary_native!r}",
        artifact_digest_verified,
    )


def reconcile_catalogue_mdx_runtime_signature(
    model_id: str,
    instruments: Sequence[str],
    *,
    target_instrument: str = "",
    config_yaml: str = "",
    config_sha256: str = "",
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
        config_sha256=config_sha256,
        training_instruments=instruments,
        target_instrument=target_instrument,
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
