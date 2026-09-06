"""Typed option groups shared by every assembled model configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence, Tuple

from ..model_identity import ModelArtifacts
from ..stem_roles import ModelStemSemantics
from ..stems import StemRoute


@dataclass
class ModelIdentity:
    model_name: str = ""
    canonical_id: str = ""
    model_display_label: str = ""
    backend_name: str = ""
    model_artifacts: Optional[ModelArtifacts] = None
    process_method: str = ""
    model_path: Optional[str] = None
    model_basename: Optional[str] = None
    model_hash: Optional[str] = None
    model_status: bool = False
    model_and_process_tag: Optional[str] = None


@dataclass
class ExportOptions:
    wav_type_set: Any = None
    mp3_bit_set: str = ""
    flac_bit_set: str = "16-bit"
    opus_bit_set: str = "192k"
    save_format: str = ""
    is_normalization: bool = False
    is_match_mix_level: bool = False
    is_prevent_export_clipping: bool = False
    amplification_threshold: float = 0.0


@dataclass
class DeviceOptions:
    use_gpu: bool = False
    device_set: str = ""
    is_use_directml: bool = False


@dataclass
class EnsembleMemberFlags:
    is_ensemble_mode: bool = False
    is_4_stem_ensemble: bool = False
    is_multi_stem_ensemble: bool = False
    ensemble_primary_stem: Optional[str] = None
    ensemble_secondary_stem: Optional[str] = None


@dataclass(init=False)
class StemRouting:
    """Native yaml/hash stem keys and selected export routes.

    ``primary_stem`` / ``secondary_stem`` / ``primary_stem_native`` keep the
    checkpoint spelling. They are never rewritten to ``lead_only`` or UVR
    Title Case. Filenames and exclusive picks use :func:`stem_concept`.
    """

    primary_stem: Optional[str] = None
    secondary_stem: Optional[str] = None
    primary_stem_native: Optional[str] = None
    primary_model_primary_stem: Optional[str] = None
    _mdx_model_stems: list[str] = field(default_factory=list, repr=False)
    _demucs_source_list: Sequence[str] = ()
    available_routes: Tuple[StemRoute, ...] = ()
    selected_routes: Tuple[StemRoute, ...] = ()
    semantics: ModelStemSemantics | None = None
    selected_routes_explicit: bool = False

    def __init__(
        self,
        primary_stem: Optional[str] = None,
        secondary_stem: Optional[str] = None,
        primary_stem_native: Optional[str] = None,
        primary_model_primary_stem: Optional[str] = None,
        mdx_model_stems: Tuple[str, ...] = (),
        demucs_source_list: Tuple[str, ...] = (),
        available_routes: Tuple[StemRoute, ...] = (),
        selected_routes: Tuple[StemRoute, ...] = (),
        semantics: ModelStemSemantics | None = None,
        selected_routes_explicit: bool = False,
    ) -> None:
        self.primary_stem = primary_stem
        self.secondary_stem = secondary_stem
        self.primary_stem_native = primary_stem_native
        self.primary_model_primary_stem = primary_model_primary_stem
        self.mdx_model_stems = mdx_model_stems
        self.demucs_source_list = demucs_source_list
        self.available_routes = available_routes
        self.selected_routes = selected_routes
        self.semantics = semantics
        self.selected_routes_explicit = selected_routes_explicit

    @property
    def mdx_model_stems(self) -> Tuple[str, ...]:
        return tuple(self._mdx_model_stems)

    @mdx_model_stems.setter
    def mdx_model_stems(self, value: Sequence[str]) -> None:
        self._mdx_model_stems = list(value)

    @property
    def demucs_source_list(self) -> Tuple[str, ...]:
        return tuple(self._demucs_source_list)

    @demucs_source_list.setter
    def demucs_source_list(self, value: Sequence[str]) -> None:
        self._demucs_source_list = list(value)


@dataclass(init=False)
class SecondaryChain:
    """Resolved auxiliary models in their execution/construction order."""

    secondary_model: Any = None
    secondary_model_scale: Optional[float] = None
    _secondary_model_4_stem: list[Any] = field(default_factory=list, repr=False)
    _secondary_model_4_stem_scale: list[Optional[float]] = field(default_factory=list, repr=False)
    _secondary_model_4_stem_names: list[str] = field(default_factory=list, repr=False)
    _secondary_model_4_stem_model_names_list: list[Any] = field(default_factory=list, repr=False)
    demucs_4_stem_added_count: int = 0
    is_demucs_4_stem_secondaries: bool = False
    pre_proc_model: Any = None
    vocal_split_model: Any = None
    is_secondary_model_activated: bool = False
    pre_proc_model_activated: bool = False
    is_vocal_split_model_activated: bool = False

    def __init__(
        self,
        secondary_model: Any = None,
        secondary_model_scale: Optional[float] = None,
        secondary_model_4_stem: Tuple[Any, ...] = (),
        secondary_model_4_stem_scale: Tuple[Optional[float], ...] = (),
        pre_proc_model: Any = None,
        vocal_split_model: Any = None,
        is_secondary_model_activated: bool = False,
        pre_proc_model_activated: bool = False,
        is_vocal_split_model_activated: bool = False,
        secondary_model_4_stem_names: Tuple[str, ...] = (),
        secondary_model_4_stem_model_names_list: Tuple[Any, ...] = (),
        demucs_4_stem_added_count: int = 0,
        is_demucs_4_stem_secondaries: bool = False,
    ) -> None:
        self.secondary_model = secondary_model
        self.secondary_model_scale = secondary_model_scale
        self.secondary_model_4_stem = secondary_model_4_stem
        self.secondary_model_4_stem_scale = secondary_model_4_stem_scale
        self.secondary_model_4_stem_names = secondary_model_4_stem_names
        self.secondary_model_4_stem_model_names_list = secondary_model_4_stem_model_names_list
        self.demucs_4_stem_added_count = demucs_4_stem_added_count
        self.is_demucs_4_stem_secondaries = is_demucs_4_stem_secondaries
        self.pre_proc_model = pre_proc_model
        self.vocal_split_model = vocal_split_model
        self.is_secondary_model_activated = is_secondary_model_activated
        self.pre_proc_model_activated = pre_proc_model_activated
        self.is_vocal_split_model_activated = is_vocal_split_model_activated

    @property
    def secondary_model_4_stem(self) -> Tuple[Any, ...]:
        return tuple(self._secondary_model_4_stem)

    @secondary_model_4_stem.setter
    def secondary_model_4_stem(self, value: Sequence[Any]) -> None:
        self._secondary_model_4_stem = list(value)

    @property
    def secondary_model_4_stem_scale(self) -> Tuple[Optional[float], ...]:
        return tuple(self._secondary_model_4_stem_scale)

    @secondary_model_4_stem_scale.setter
    def secondary_model_4_stem_scale(self, value: Sequence[Optional[float]]) -> None:
        self._secondary_model_4_stem_scale = list(value)

    @property
    def secondary_model_4_stem_names(self) -> Tuple[str, ...]:
        return tuple(self._secondary_model_4_stem_names)

    @secondary_model_4_stem_names.setter
    def secondary_model_4_stem_names(self, value: Sequence[str]) -> None:
        self._secondary_model_4_stem_names = list(value)

    @property
    def secondary_model_4_stem_model_names_list(self) -> Tuple[Any, ...]:
        return tuple(self._secondary_model_4_stem_model_names_list)

    @secondary_model_4_stem_model_names_list.setter
    def secondary_model_4_stem_model_names_list(self, value: Sequence[Any]) -> None:
        self._secondary_model_4_stem_model_names_list = list(value)


@dataclass
class CommonRunOptions:
    """Cross-family inference and auxiliary-pass switches."""

    DENOISER_MODEL: str = ""
    DEVERBER_MODEL: str = ""
    all_models: Any = None
    bv_model_rebalance: float | None = 0.0
    deverb_vocal_opt: Any = None
    ensemble_pair_roles: tuple[object, ...] = ()
    is_bv_model: bool = False
    is_change_def: bool = False
    is_deverb_vocals: bool = False
    is_dry_check: bool = False
    is_get_hash_dir_only: bool = False
    is_inst_only_voc_splitter: bool = False
    is_karaoke: bool = False
    is_karaoke_curated: bool = False
    is_pitch_change: bool = False
    is_pre_proc_model: bool = False
    is_save_inst_vocal_splitter: bool = False
    is_save_vocal_only: bool = False
    is_sec_bv_rebalance: bool = False
    is_secondary_model: bool = False
    is_vocal_split_model: bool = False
    model_hash_dir: str | None = None
    secondary_model_bass: Any = None
    secondary_model_drums: Any = None
    secondary_model_other: Any = None
    secondary_model_scale_bass: float | None = None
    secondary_model_scale_drums: float | None = None
    secondary_model_scale_other: float | None = None
    semitone_shift: float = 0.0
