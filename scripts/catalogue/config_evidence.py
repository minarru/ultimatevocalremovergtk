"""Config evidence for the one-snapshot catalogue publication pipeline."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import (
    Any,
    List,
    Optional,
    Tuple,
)

from catalogue import cache, locations
from catalogue.cache import DEFAULT_FETCH_POLICY, FetchPolicy, _cache_path
from core.model_data import (
    _mdx_c_training,
    load_mdx_c_config_data,
)


def _yaml_paths(yaml_name: str, yaml_url: str = "") -> List[str]:
    """Strict generator-owned YAML locations, most authoritative first.

    Checked-in configs are deliberate seeds. The optional second path is the
    URL-keyed generator cache. Arbitrary installed configs under UVR_DATA_DIR
    are intentionally absent.
    """
    candidates = [os.path.join(locations._BUNDLED_MDX_YAML_DIR, yaml_name)]
    if yaml_url:
        candidates.append(_cache_path(locations.YAML_CACHE_DIR, yaml_url, yaml_name))
    return candidates


def _yaml_source_label(yaml_name: str, config_path: str) -> str:
    """Stable provenance for checked-in versus generator-cache evidence."""
    where = "remote_yaml" if locations.YAML_CACHE_DIR in config_path else "bundled_yaml"
    return f"{where}:{yaml_name}"


def _training_fields(training: Any) -> Tuple[List[str], str]:
    if training is None:
        return [], ""
    if isinstance(training, dict):
        instruments = list(training.get("instruments") or [])
        target = training.get("target_instrument") or ""
        return instruments, str(target) if target else ""
    instruments = list(getattr(training, "instruments", None) or [])
    target = getattr(training, "target_instrument", None) or ""
    return instruments, str(target) if target else ""


def _architecture_from_config(yaml_name: str, config: Any) -> str:
    """Infer architecture from already-loaded bytes without reopening runtime state."""
    if not isinstance(config, dict):
        return ""
    if config.get("cls") == "Bandit":
        return "Bandit"
    model = config.get("model") or {}
    if not isinstance(model, dict):
        return "MDX23C"
    if "band_specs" in model:
        return "Bandit"
    if "band_SR" in model or "sources" in model:
        if any(str(key).startswith("tran_") for key in model):
            return "SCNet Tran"
        if "masked" in yaml_name.lower():
            return "SCNet Masked"
        return "SCNet"
    if "num_bands" in model:
        return "Mel-Band Roformer"
    if "freqs_per_bands" in model:
        return "BS Roformer"
    return "MDX23C"


def _architecture_from_yaml_name(yaml_name: str) -> str:
    """Deterministic informational hint used only when config evidence is absent."""
    low = yaml_name.casefold()
    if "bandit" in low:
        return "Bandit"
    if "scnet" in low:
        if "tran" in low:
            return "SCNet Tran"
        if "masked" in low:
            return "SCNet Masked"
        return "SCNet"
    if "melband" in low or "mel_band" in low:
        return "Mel-Band Roformer"
    if "roformer" in low:
        return "Roformer"
    if "mdx23" in low:
        return "MDX23C"
    return ""


@dataclass(frozen=True, slots=True)
class YamlEvidence:
    instruments: list[str]
    target_instrument: str
    architecture: str
    metadata_source: str
    content_sha256: str


def parse_yaml_evidence(data: bytes, *, yaml_name: str, metadata_source: str) -> YamlEvidence:
    """Interpret exactly the supplied bytes through the shared MDX parser."""
    config = load_mdx_c_config_data(data)
    instruments, target = _training_fields(_mdx_c_training(config))
    return YamlEvidence(
        instruments,
        target,
        _architecture_from_config(yaml_name, config),
        metadata_source,
        hashlib.sha256(data).hexdigest(),
    )


def load_yaml_evidence(
    yaml_name: str,
    yaml_url: str = "",
    *,
    policy: FetchPolicy = DEFAULT_FETCH_POLICY,
    allow_network: Optional[bool] = None,
) -> YamlEvidence:
    if allow_network is not None:
        policy = FetchPolicy(
            allow_network=allow_network,
            refresh=policy.refresh,
            max_age=policy.max_age,
            allow_metadata_writes=policy.allow_metadata_writes,
            allow_cache_writes=policy.allow_cache_writes,
        )
    if not yaml_name:
        return YamlEvidence([], "", "", "", "")
    bundled_path = _yaml_paths(yaml_name, yaml_url)[0]
    config_path = bundled_path if os.path.isfile(bundled_path) else ""

    source = ""
    config_data: Optional[bytes] = None
    if config_path:
        source = _yaml_source_label(yaml_name, config_path)
    elif yaml_url:
        # This boundary owns both fetch and persistence policy. In particular,
        # refresh must revalidate an existing cache entry, and no path here may
        # write to runtime model config storage.
        config_data, fetched_path = cache.fetch_yaml_bytes(yaml_url, yaml_name, policy=policy)
        if fetched_path:
            config_path = fetched_path
        if config_data is not None:
            source = f"remote_yaml:{yaml_name}"
    if not config_path and config_data is None:
        inferred = _infer_from_yaml_name(yaml_name)
        if inferred[0] or inferred[1]:
            return YamlEvidence(
                inferred[0],
                inferred[1],
                inferred[2],
                f"yaml_name_heuristic:{yaml_name}",
                "",
            )
        return YamlEvidence([], "", "", "", "")
    try:
        if config_data is None:
            with open(config_path, "rb") as config_file:
                config_data = config_file.read()
        return parse_yaml_evidence(config_data, yaml_name=yaml_name, metadata_source=source)
    except Exception:
        inferred = _infer_from_yaml_name(yaml_name)
        return YamlEvidence(
            inferred[0], inferred[1], inferred[2], f"yaml_parse_failed:{yaml_name}", ""
        )


def _load_yaml_meta(
    yaml_name: str,
    yaml_url: str = "",
    *,
    policy: FetchPolicy = DEFAULT_FETCH_POLICY,
    allow_network: Optional[bool] = None,
) -> Tuple[List[str], str, str, str, str]:
    """Tuple adapter for callers of the original collection helper."""
    value = load_yaml_evidence(yaml_name, yaml_url, policy=policy, allow_network=allow_network)
    return (
        value.instruments,
        value.target_instrument,
        value.architecture,
        value.metadata_source,
        value.content_sha256,
    )


def _infer_from_yaml_name(yaml_name: str) -> Tuple[List[str], str, str]:
    low = yaml_name.lower()
    arch = _architecture_from_yaml_name(yaml_name)
    if "4stem" in low or "4_stem" in low or "musdb18" in low or "dnr_bandit" in low:
        return [], "", arch
    if any(k in low for k in ("instvoc", "duality", "2_stem", "2stem")):
        return ["instrumental", "vocals"], "", arch
    if any(k in low for k in ("inst", "instrumental", "fno", "crowd", "guitar", "metal")):
        return ["other", "vocals"], "other", arch
    if any(
        k in low
        for k in (
            "voc",
            "karaoke",
            "aspiration",
            "bve",
            "revive",
            "chorus",
            "male_female",
            "big_beta",
            "kim_ft",
        )
    ):
        return ["other", "vocals"], "vocals", arch
    if any(k in low for k in ("dereverb", "deverb", "denoise", "echo", "bleed")):
        return ["no_reverb"], "no_reverb", arch
    return [], "", arch
