"""Tk-free Apollo (music restoration) model discovery + recognition.

This is the framework-agnostic port of ``UVR.py``'s ``ApolloModelData`` class and
the Apollo model-menu discovery logic. It performs md5-hash based model
recognition: a checkpoint's hash is looked up in ``APOLLO_HASH_DIR/<hash>.json``
to find its ``config_yaml``, which is then read from ``APOLLO_CONFIG_PATH`` to
extract the four model build parameters (``sr`` / ``win`` / ``feature_dim`` /
``layer``) the Apollo architecture needs.

Nothing here imports ``torch``; the heavy inference module
(``ml.apollo_inference``) is imported lazily by the audio-tools runner. The
yaml config is read with ``PyYAML`` (already a dependency).

An *unrecognized* model (one whose hash has no ``<hash>.json``) is handled via an
optional ``on_unrecognized`` callback (installed by the GTK layer, analogous to
:attr:`core.ModelRepository.on_unrecognized_model`). The callback receives
this :class:`ApolloModelData` and returns a params dict (``{"config_yaml": ...}``)
or ``None``; a returned dict is persisted to ``<hash>.json`` so the model is
recognised on subsequent runs.
"""

import hashlib
import json
import os
from typing import Any, Callable, List, MutableMapping, Optional

from . import paths

#: Checkpoint extensions Apollo models ship as.
APOLLO_EXTENSIONS = (".ckpt", ".bin")


def list_apollo_models() -> List[str]:
    """Return the file names of every Apollo checkpoint in ``APOLLO_MODELS_DIR``."""
    directory = paths.APOLLO_MODELS_DIR
    if not os.path.isdir(directory):
        return []
    names = [
        entry
        for entry in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, entry))
        and entry.lower().endswith(APOLLO_EXTENSIONS)
    ]
    return sorted(names)


def checkpoint_md5(checkpoint_path: str) -> str:
    """MD5 used to key Apollo model-data JSON (tail bytes, whole file fallback).

    Shared by :meth:`ApolloModelData.get_model_hash` and the download-time
    auto-registration in :mod:`core.apollo_registry`; both must produce the
    identical digest or a freshly downloaded model is not recognised.
    """
    try:
        with open(checkpoint_path, "rb") as handle:
            handle.seek(-10000 * 1024, 2)
            return hashlib.md5(handle.read()).hexdigest()
    except Exception:
        with open(checkpoint_path, "rb") as fallback_file:
            return hashlib.md5(fallback_file.read()).hexdigest()


def list_config_files() -> List[str]:
    """Return the available Apollo config yaml file names (without extension)."""
    directory = paths.APOLLO_CONFIG_PATH
    if not os.path.isdir(directory):
        return []
    return sorted(
        os.path.splitext(name)[0]
        for name in os.listdir(directory)
        if name.lower().endswith(".yaml")
    )


class ApolloModelData:
    """Resolve one Apollo checkpoint's build params + raw config (Tk-free port)."""

    def __init__(
        self,
        apollo_model: str,
        model_hash_table: Optional[dict] = None,
        on_unrecognized: Optional[Callable[["ApolloModelData"], Optional[dict]]] = None,
        is_dry_check: bool = False,
        persistent_hash_table: Optional[MutableMapping[str, Any]] = None,
    ):
        self.is_dry_check = is_dry_check
        self.apollo_model_name = apollo_model
        self._on_unrecognized = on_unrecognized
        self._model_hash_table = model_hash_table if model_hash_table is not None else {}
        self._persistent_hash_table = persistent_hash_table
        self.extracted_params: Optional[dict] = None
        self.config: Optional[dict] = None
        self.apollo_model_location = os.path.join(paths.APOLLO_MODELS_DIR, apollo_model)

        self.model_hash, self.model_status = self.get_model_hash()
        self.model_params = self.get_model_data()

        if self.model_params:
            config_path = os.path.join(paths.APOLLO_CONFIG_PATH, self.model_params["config_yaml"])
            self.extracted_params, self.config = self.extract_model_params(config_path)

        self.is_model_status = bool(self.extracted_params)

    def get_model_hash(self):
        """MD5 of the checkpoint (cached). Mirrors ``ModelConfig.get_model_hash``.

        ``persistent_hash_table`` is the stat-guarded settings table; the
        in-memory ``model_hash_table`` is not, so a checkpoint replaced at the
        same path must be caught by the former before the latter is trusted.
        """
        from .model_hash_cache import is_stale, lookup_trusted, remember

        path = self.apollo_model_location
        if not os.path.isfile(path):
            return None, False

        cache = self._model_hash_table
        persistent = self._persistent_hash_table
        if persistent is not None:
            trusted = lookup_trusted(persistent, path)
            if trusted:
                cache[path] = trusted
                return trusted, True
            if is_stale(persistent, path):
                cache.pop(path, None)

        model_hash = cache.get(path)
        if not model_hash:
            model_hash = checkpoint_md5(path)
            cache[path] = model_hash
            if persistent is not None:
                remember(persistent, path, model_hash)
        return model_hash, True

    def get_model_data(self) -> Optional[dict]:
        model_settings_json = os.path.join(paths.APOLLO_HASH_DIR, f"{self.model_hash}.json")

        if not self.model_status:
            return None
        if os.path.isfile(model_settings_json):
            with open(model_settings_json, "r") as json_file:
                return json.load(json_file)
        return self._get_model_data_from_callback()

    def _get_model_data_from_callback(self) -> Optional[dict]:
        if self.is_dry_check or not callable(self._on_unrecognized):
            return None
        params = self._on_unrecognized(self)
        if params:
            self._persist_model_data(params)
        return params

    def _persist_model_data(self, params: dict) -> None:
        os.makedirs(paths.APOLLO_HASH_DIR, exist_ok=True)
        dump_path = os.path.join(paths.APOLLO_HASH_DIR, f"{self.model_hash}.json")
        with open(dump_path, "w") as outfile:
            outfile.write(json.dumps(params, indent=4))

    @staticmethod
    def extract_model_params(config_path: str):
        """Read the yaml config and pull out the four Apollo build parameters."""
        extracted_params, config = None, None
        try:
            import yaml

            with open(config_path, "r") as file:
                config = yaml.safe_load(file)

            model_params = config.get("model", {})
            extracted_params = {
                "sr": model_params.get("sr"),
                "win": model_params.get("win"),
                "feature_dim": model_params.get("feature_dim"),
                "layer": model_params.get("layer"),
            }
        except Exception as exc:  # mirrors UVR's report-and-continue
            from .debug_log import debug

            debug("model", f"apollo config read failed: {type(exc).__name__}: {exc}")

        return extracted_params, config
