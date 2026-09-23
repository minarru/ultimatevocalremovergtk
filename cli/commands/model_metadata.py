"""Detailed runtime model inspection and semantic projection."""

from __future__ import annotations

import json
import os
from typing import Any

from core.settings import Settings


def _stem_semantics_fields(model: Any | None) -> dict[str, Any]:
    """Return the exact semantic projection without changing backend fields."""
    from core.model_stem_semantics import stem_semantics_projection
    from core.stems import model_stem_routes

    if model is None:
        return stem_semantics_projection(None).as_dict()
    # This is the shared runtime adapter.  It resolves an exact canonical ID
    # and native signature; it never maps a display label back to a role.
    model_stem_routes(model)
    return stem_semantics_projection(
        getattr(model, "stem_semantics", None),
        backend_primary=(
            getattr(model, "primary_stem_native", None) or getattr(model, "primary_stem", None)
        ),
        backend_target=getattr(model, "target_instrument", None),
    ).as_dict()


def _model_info(record: Any, repo: Any, *, detailed: bool = False) -> dict[str, Any]:
    if record.family == "apollo":
        from core.apollo import ApolloModelData
        from core.model_registry import ModelRegistryService
        from core.paths import APOLLO_MODELS_DIR

        backend_name = record.backend_name
        path = os.path.join(APOLLO_MODELS_DIR, backend_name)
        data = ApolloModelData(
            backend_name,
            model_hash_table=repo.model_hash_table,
            on_unrecognized=None,
            is_dry_check=True,
        )
        local = (
            ModelRegistryService(repo).read_local(record.method, data.model_hash)
            if data.model_hash
            else None
        )
        info = {
            **record.to_dict(),
            "installed": os.path.isfile(path),
            "configured": bool(data.is_model_status),
            "path": path,
            "hash": data.model_hash or None,
            "primary_stem": "Restored",
            "secondary_stem": None,
            "metadata_source": "model-local" if local else "model-catalog",
        }
        info.update(_stem_semantics_fields(None))
        if detailed:
            info.update(
                {
                    "metadata_sources": [{"provenance": info["metadata_source"]}],
                    "architectural_facts": {"config_yaml": getattr(data, "config_yaml", None)},
                    "model_native_recommendations": {},
                    "local_overrides": local,
                }
            )
        return info
    settings = Settings.defaults()
    section = getattr(settings, record.family)
    section.model = record.id
    settings.process.method = record.method
    try:
        model = repo.resolve_model_dry(settings, record.method, record.id)
    except (AttributeError, KeyError, OSError, ValueError):
        model = None
    info: dict[str, Any] = {
        **record.to_dict(),
        "installed": bool(record.installed),
        "configured": bool(model and model.model_status),
    }
    info.update(_stem_semantics_fields(model))
    if model is not None:
        path = str(getattr(model, "model_path", "") or "")
        local_path = str(getattr(model, "model_hash_dir", "") or "")
        info.update(
            {
                "path": path,
                "hash": getattr(model, "model_hash", None),
                "primary_stem": getattr(model, "primary_stem", None),
                "secondary_stem": getattr(model, "secondary_stem", None),
                "metadata_source": (
                    "model-local" if local_path and os.path.isfile(local_path) else "model-catalog"
                ),
            }
        )
        info.update(_stem_semantics_fields(model))
        if detailed:
            facts: dict[str, Any] = {}
            for name in (
                "model_samplerate",
                "primary_stem_native",
                "mdx_dim_f_set",
                "mdx_dim_t_set",
                "mdx_n_fft_scale_set",
                "mdx_model_stems",
                "demucs_version",
                "demucs_source_list",
                "demucs_stem_count",
                "is_mdx_c",
                "is_roformer",
                "is_target_instrument",
            ):
                value = getattr(model, name, None)
                if value not in (None, "", [], ()):
                    facts[name] = list(value) if isinstance(value, tuple) else value
            recommendations = {
                name: getattr(model, name)
                for name in ("compensate", "segment", "overlap_mdx", "overlap")
                if getattr(model, name, None) is not None
            }
            local_overrides = None
            if local_path and os.path.isfile(local_path):
                try:
                    with open(local_path, encoding="utf-8") as handle:
                        local_overrides = json.load(handle)
                except (OSError, json.JSONDecodeError):
                    local_overrides = {"unreadable": local_path}
            info.update(
                {
                    "metadata_sources": [
                        {"provenance": "model-catalog"},
                        *(
                            [{"provenance": "model-local", "path": local_path}]
                            if local_path and os.path.isfile(local_path)
                            else []
                        ),
                    ],
                    "architectural_facts": facts,
                    "model_native_recommendations": recommendations,
                    "local_overrides": local_overrides,
                }
            )
    return info
