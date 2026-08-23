"""Transactional local model metadata shared by registration and GUI editing."""

from __future__ import annotations

import os
from typing import Any

from bundled.constants import APOLLO_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE

from . import paths
from .json_store import locked_json_path, read_json_object, write_json_atomic


class ModelRegistryService:
    def __init__(self, repo: Any | None = None):
        self.repo = repo

    @staticmethod
    def metadata_path(process_method: str, model_hash: str) -> str:
        directory = {
            VR_ARCH_TYPE: paths.VR_HASH_DIR,
            MDX_ARCH_TYPE: paths.MDX_HASH_DIR,
            APOLLO_ARCH_TYPE: paths.APOLLO_HASH_DIR,
        }.get(process_method)
        if directory is None or not model_hash:
            raise ValueError("local metadata is supported only for hashed VR, MDX, and Apollo models")
        return os.path.join(directory, f"{model_hash}.json")

    def read_local(self, process_method: str, model_hash: str) -> dict[str, Any] | None:
        path = self.metadata_path(process_method, model_hash)
        if not os.path.isfile(path):
            return None
        try:
            return read_json_object(path)
        except (OSError, ValueError):
            return None

    @staticmethod
    def registered_id(model_hash: str) -> str | None:
        if not model_hash or not os.path.isfile(paths.REGISTERED_MODEL_INDEX):
            return None
        try:
            value = read_json_object(paths.REGISTERED_MODEL_INDEX).get(model_hash)
        except (OSError, ValueError):
            return None
        return str(value) if value else None

    @staticmethod
    def remember_registered(model_hash: str, canonical_id: str) -> bool:
        """Record hash -> canonical id ownership.

        Returns whether this call changed the index. Callers that ignore the
        return stay source-compatible; the download finalizer uses it to tell a
        genuine repair apart from a re-run over an already-indexed model, so an
        unchanged ``exists`` transfer does not republish.
        """
        if not model_hash or not canonical_id:
            raise ValueError("registered models require a hash and canonical ID")
        with locked_json_path(paths.REGISTERED_MODEL_INDEX):
            try:
                index = read_json_object(paths.REGISTERED_MODEL_INDEX)
            except (OSError, ValueError):
                index = {}
            if index.get(model_hash) == canonical_id:
                return False
            index[model_hash] = canonical_id
            write_json_atomic(paths.REGISTERED_MODEL_INDEX, index)
            return True

    @staticmethod
    def forget_registered(model_hash: str) -> None:
        with locked_json_path(paths.REGISTERED_MODEL_INDEX):
            try:
                index = read_json_object(paths.REGISTERED_MODEL_INDEX)
            except (OSError, ValueError):
                return
            if model_hash in index:
                del index[model_hash]
                write_json_atomic(paths.REGISTERED_MODEL_INDEX, index)

    @classmethod
    def index_downloaded(
        cls, family: str, jobs: list[tuple[str, str]] | tuple[tuple[str, str], ...]
    ) -> bool:
        """Record hashes downloaded through a catalogue without scanning inventory.

        Returns whether any ownership entry was added or repaired.
        """
        changed = False
        extensions = {
            "vr": (".pth",), "mdx": (".onnx", ".ckpt"),
            "apollo": (".ckpt", ".bin"),
        }.get(family, ())
        for _url, checkpoint in jobs:
            if not str(checkpoint).casefold().endswith(extensions):
                continue
            if not os.path.isfile(checkpoint):
                continue
            if family == "apollo":
                from .apollo import checkpoint_md5

                model_hash = checkpoint_md5(checkpoint)
            else:
                from .mdx_c_registry import compute_checkpoint_hash

                model_hash = str(compute_checkpoint_hash(checkpoint) or "")
            if model_hash:
                from .model_identity import ModelId

                if cls.remember_registered(
                    model_hash,
                    str(ModelId(family, os.path.splitext(os.path.basename(checkpoint))[0])),
                ):
                    changed = True
        return changed
    def write_local(
        self, process_method: str, model_hash: str, payload: dict[str, Any],
        *, replace: bool = True,
    ) -> str:
        if not payload:
            raise ValueError("model metadata must be a non-empty object")
        path = self.metadata_path(process_method, model_hash)
        if os.path.exists(path) and not replace:
            raise ValueError(f"local metadata already exists for hash {model_hash}")
        write_json_atomic(path, payload)
        if self.repo is not None:
            self.repo.invalidate_models()
        return path

    @staticmethod
    def validate_payload(
        family: str, payload: dict[str, Any], *, model_path: str = ""
    ) -> dict[str, Any]:
        if not payload:
            raise ValueError("model metadata must be a non-empty object")
        result = dict(payload)
        if family == "vr":
            parameter = str(result.get("vr_model_param") or "")
            if not parameter:
                raise ValueError("VR metadata requires vr_model_param")
            parameter_name = parameter if parameter.endswith(".json") else f"{parameter}.json"
            if os.path.basename(parameter_name) != parameter_name or not os.path.isfile(
                os.path.join(paths.VR_PARAM_DIR, parameter_name)
            ):
                raise ValueError(f"VR parameter file was not found: {parameter}")
            if not result.get("primary_stem"):
                raise ValueError("VR metadata requires primary_stem")
            for key in ("nout", "nout_lstm"):
                if key in result and int(result[key]) <= 0:
                    raise ValueError(f"{key} must be positive")
        elif family == "mdx":
            is_mdx_c = str(model_path).casefold().endswith(".ckpt") or "config_yaml" in result
            if is_mdx_c:
                config = str(result.get("config_yaml") or "")
                if not config.endswith((".yaml", ".yml")):
                    raise ValueError("MDX-C metadata requires a YAML config")
                from .mdx_c_registry import infer_mdx_c_architecture

                if os.path.basename(config) != config or not infer_mdx_c_architecture(config)[0]:
                    raise ValueError(f"MDX-C configuration is invalid or missing: {config}")
            else:
                for key in ("mdx_dim_f_set", "mdx_dim_t_set", "mdx_n_fft_scale_set"):
                    if int(result.get(key) or 0) <= 0:
                        raise ValueError(f"classic MDX metadata requires positive {key}")
                result["compensate"] = float(result.get("compensate", 1.035))
                if not result.get("primary_stem"):
                    raise ValueError("classic MDX metadata requires primary_stem")
        elif family == "apollo":
            config = str(result.get("config_yaml") or "")
            if not config.endswith((".yaml", ".yml")):
                raise ValueError("Apollo metadata requires config_yaml")
            config_path = os.path.join(paths.APOLLO_CONFIG_PATH, os.path.basename(config))
            if os.path.basename(config) != config or not os.path.isfile(config_path):
                raise ValueError(f"Apollo configuration was not found: {config}")
            try:
                from .apollo import ApolloModelData

                extracted, _raw = ApolloModelData.extract_model_params(config_path)
            except (OSError, TypeError, ValueError) as exc:
                raise ValueError(f"Apollo configuration is invalid: {config}") from exc
            if not extracted:
                raise ValueError(f"Apollo configuration is invalid: {config}")
        else:
            raise ValueError(f"local metadata is not supported for {family} models")
        return result

    def configure(
        self, family: str, process_method: str, model_hash: str,
        payload: dict[str, Any], *, model_path: str = "", replace: bool = False,
    ) -> str:
        validated = self.validate_payload(family, payload, model_path=model_path)
        return self.write_local(process_method, model_hash, validated, replace=replace)

    def reset_local(self, process_method: str, model_hash: str) -> bool:
        path = self.metadata_path(process_method, model_hash)
        if not os.path.isfile(path):
            return False
        os.remove(path)
        if self.repo is not None:
            self.repo.invalidate_models()
        return True
