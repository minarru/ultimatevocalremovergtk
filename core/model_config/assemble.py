"""Assembly entry point for typed model configurations."""

from __future__ import annotations

from typing import List, Optional, TYPE_CHECKING

from bundled.constants import (
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_CHECK,
    ENSEMBLE_MODE,
    MDX_ARCH_TYPE,
    VR_ARCH_PM,
    VR_ARCH_TYPE,
)

if TYPE_CHECKING:
    from ..model_data import ModelRepository
    from ..settings import Settings
    from . import ModelConfig


def assemble_model(
    settings: "Settings",
    repo: "ModelRepository",
    model: Optional[str] = None,
    arch_type: str = ENSEMBLE_MODE,
) -> List["ModelConfig"]:
    """Build the model configurations for one separation run."""
    from .config import ModelConfig
    from ..model_identity import ModelIdentityService

    identities = ModelIdentityService(repo)

    def engine_value(
        value: str, *, member: bool = False, family: str | None = None
    ) -> str:
        if str(value or "").split(":", 1)[0].casefold() not in {"vr", "mdx", "demucs"}:
            return value
        return identities.engine_value(value, member=member, family=family)

    if arch_type == ENSEMBLE_MODE:
        selected = settings.ensemble.selected_models or []
        models = [ModelConfig(settings, repo, engine_value(name, member=True)) for name in selected]
        valid = [item for item in models if item.model_status]
        skipped = len(models) - len(valid)
        if skipped:
            from ..debug_log import debug

            debug(
                "model",
                f"assemble_model skipped={skipped} valid={len(valid)} "
                f"({skipped} ensemble member(s) could not be resolved)",
            )
        if len(valid) < 2 and len(selected) >= 2:
            raise ValueError(
                "Too few valid ensemble members; check that selected models are installed."
            )
        from ..debug_log import debug

        debug("model", f"assemble_model ensemble members={len(valid)}")
        return valid
    if not model:
        raise ValueError(f"assemble_model requires a model name for {arch_type}")
    family = {
        VR_ARCH_TYPE: "vr", VR_ARCH_PM: "vr",
        MDX_ARCH_TYPE: "mdx", DEMUCS_ARCH_TYPE: "demucs",
    }.get(arch_type)
    model = engine_value(model, family=family)
    if arch_type == ENSEMBLE_CHECK:
        return [ModelConfig(settings, repo, model)]
    if arch_type in (VR_ARCH_TYPE, VR_ARCH_PM):
        return [ModelConfig(settings, repo, model, VR_ARCH_TYPE)]
    if arch_type == MDX_ARCH_TYPE:
        return [ModelConfig(settings, repo, model, MDX_ARCH_TYPE)]
    if arch_type == DEMUCS_ARCH_TYPE:
        return [ModelConfig(settings, repo, model, DEMUCS_ARCH_TYPE)]
    raise NotImplementedError(f"assemble_model: arch_type '{arch_type}' is not supported")
