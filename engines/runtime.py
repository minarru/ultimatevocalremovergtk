"""Live model options and invocation data for one inference pass."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence, cast

from core.model_config import (
    DemucsOptions,
    DeviceOptions,
    EnsembleMemberFlags,
    ExportOptions,
    MDXOptions,
    ModelConfig,
    ModelIdentity,
    SecondaryChain,
    StemRouting,
    VROptions,
)
from core.model_config.base import CommonRunOptions
from core.process_data import ProcessData
from core.progress_ticks import InferenceProgress


def _is_model_config(model: object) -> bool:
    return isinstance(model, ModelConfig)


@dataclass(frozen=True)
class EngineInvocation:
    main_model_primary_stem_4_stem: str | None = None
    main_process_method: str | None = None
    is_return_dual: bool = True
    main_model_primary: str | None = None
    vocal_stem_path: Sequence[Any] | None = None
    master_inst_source: Any = None
    master_vocal_source: Any = None


@dataclass(frozen=True)
class EngineRunContext:
    model: ModelConfig
    process: ProcessData
    invocation: EngineInvocation

    @property
    def identity(self) -> ModelIdentity:
        # Legacy ModelConfig-shaped callers need no snapshot or conversion.
        if _is_model_config(self.model):
            return self.model.identity
        return cast(ModelIdentity, self.model)

    @property
    def export(self) -> ExportOptions:
        # Legacy ModelConfig-shaped callers need no snapshot or conversion.
        if _is_model_config(self.model):
            return self.model.export_options
        return cast(ExportOptions, self.model)

    @property
    def device(self) -> DeviceOptions:
        # Legacy ModelConfig-shaped callers need no snapshot or conversion.
        if _is_model_config(self.model):
            return self.model.device_options
        return cast(DeviceOptions, self.model)

    @property
    def ensemble(self) -> EnsembleMemberFlags:
        # Legacy ModelConfig-shaped callers need no snapshot or conversion.
        if _is_model_config(self.model):
            return self.model.ensemble_flags
        return cast(EnsembleMemberFlags, self.model)

    @property
    def routing(self) -> StemRouting:
        # Legacy ModelConfig-shaped callers need no snapshot or conversion.
        if _is_model_config(self.model):
            return self.model.stem_routing
        return cast(StemRouting, self.model)

    @property
    def secondary(self) -> SecondaryChain:
        # Legacy ModelConfig-shaped callers need no snapshot or conversion.
        if _is_model_config(self.model):
            return self.model.secondary_chain
        return cast(SecondaryChain, self.model)

    @property
    def common(self) -> CommonRunOptions:
        # Legacy ModelConfig-shaped callers need no snapshot or conversion.
        if _is_model_config(self.model):
            return self.model.common_options
        return cast(CommonRunOptions, self.model)

    @property
    def mdx(self) -> MDXOptions:
        # Legacy ModelConfig-shaped callers need no snapshot or conversion.
        if _is_model_config(self.model):
            return self.model._mdx_options
        return cast(MDXOptions, self.model)

    @property
    def demucs(self) -> DemucsOptions:
        # Legacy ModelConfig-shaped callers need no snapshot or conversion.
        if _is_model_config(self.model):
            return self.model._demucs_options
        return cast(DemucsOptions, self.model)

    @property
    def vr(self) -> VROptions:
        # Legacy ModelConfig-shaped callers need no snapshot or conversion.
        if _is_model_config(self.model):
            return self.model._vr_options
        return cast(VROptions, self.model)


@dataclass
class EngineState:
    """Mutable progress, source handles and export buffers owned by one pass."""

    progress_value: int = 0
    progress_total: int = 0
    _infer_progress: InferenceProgress = field(default_factory=InferenceProgress)
    _save_stem_total: int = 1
    _save_stem_index: int = 0
    primary_source: Any = None
    secondary_source: Any = None
    secondary_source_primary: Any = None
    secondary_source_secondary: Any = None
    primary_source_map: dict = field(default_factory=dict)
    secondary_source_map: dict = field(default_factory=dict)
    _ensemble_stem_buffers: dict = field(default_factory=dict)
    _ensemble_stem_paths: dict = field(default_factory=dict)

    # Materialized resources are absent until their original assignment point.
    device: Any = field(init=False, repr=False)
    run_type: Any = field(init=False, repr=False)
    _backend_name: Any = field(init=False, repr=False)
    demucs: Any = field(init=False, repr=False)
    model_run: Any = field(init=False, repr=False)
    _inference_model: Any = field(init=False, repr=False)
    _ort_session: Any = field(init=False, repr=False)
    _weight_cache_key: Any = field(init=False, repr=False)
    primary_model_name: Any = field(init=False, repr=False)
    primary_sources: Any = field(init=False, repr=False)
    master_inst_source: Any = field(init=False, repr=False)
    master_vocal_source: Any = field(init=False, repr=False)
    master_vocal_path: Any = field(init=False, repr=False)
    set_master_inst_source: Any = field(init=False, repr=False)
    audio_file_base_voc_split: Any = field(init=False, repr=False)
