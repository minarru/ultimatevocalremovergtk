from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

from bundled.constants import (
    CHOOSE_MODEL,
    DEFAULT,
    DENOISE_M,
    DENOISE_NONE,
    DEVERB_MAPPER,
    ENSEMBLE_MODE,
    ENSEMBLE_PARTITION,
    NO_MODEL,
    VOCAL_STEM,
)

from ... import paths
from .inputs import ModelBuildInputs

if TYPE_CHECKING:
    from ..config import ModelConfig
import os

from ...audio_io import resolve_wav_type_set
from ...settings.coerce import enum_value


def initialize_shared_options(model: ModelConfig, inputs: ModelBuildInputs) -> None:
    settings = inputs.settings
    model_name = inputs.model_name
    selected_process_method = inputs.selected_process_method
    is_secondary_model = inputs.is_secondary_model
    primary_model_primary_stem = inputs.primary_model_primary_stem
    is_pre_proc_model = inputs.is_pre_proc_model
    is_dry_check = inputs.is_dry_check
    is_change_def = inputs.is_change_def
    is_get_hash_dir_only = inputs.is_get_hash_dir_only
    is_vocal_split_model = inputs.is_vocal_split_model
    identity = inputs.identity
    process = inputs.settings.process
    mdx = inputs.settings.mdx
    demucs = inputs.settings.demucs

    from ..base import (
        CommonRunOptions,
        DeviceOptions,
        EnsembleMemberFlags,
        ExportOptions,
        ModelIdentity,
        SecondaryChain,
        StemRouting,
    )
    from ..demucs import DemucsOptions
    from ..mdx import MDXOptions
    from ..vr import VROptions

    model.identity = ModelIdentity()
    model.export_options = ExportOptions()
    model.device_options = DeviceOptions()
    model.ensemble_flags = EnsembleMemberFlags()
    model.stem_routing = StemRouting()
    model.secondary_chain = SecondaryChain()
    model.common_options = CommonRunOptions()
    # Cross-family legacy defaults remain available to shared engine code.
    model._vr_options = VROptions()
    model._mdx_options = MDXOptions(routing=model.stem_routing)
    model._demucs_options = DemucsOptions(routing=model.stem_routing)

    device_set = process.device or DEFAULT
    model.DENOISER_MODEL = paths.DENOISER_MODEL_PATH
    model.DEVERBER_MODEL = paths.DEVERBER_MODEL_PATH
    model.is_deverb_vocals = (
        process.deverb_vocals if os.path.isfile(paths.DEVERBER_MODEL_PATH) else False
    )
    model.deverb_vocal_opt = DEVERB_MAPPER[enum_value(process.deverb_vocal_opt)]
    denoise_opt = enum_value(mdx.denoise_option)
    model.is_denoise_model = bool(
        denoise_opt == DENOISE_M and os.path.isfile(paths.DENOISER_MODEL_PATH)
    )
    model.is_gpu_conversion = bool(process.use_gpu)
    model.use_gpu = model.is_gpu_conversion
    model.is_normalization = process.normalization
    model.is_match_mix_level = bool(process.match_mix_level)
    model.is_prevent_export_clipping = bool(process.prevent_export_clipping)
    try:
        model.amplification_threshold = float(process.amplification_threshold or 0.0)
    except (TypeError, ValueError):
        model.amplification_threshold = 0.0
    model.is_use_directml = bool(process.use_directml)
    model.is_denoise = denoise_opt != DENOISE_NONE
    model.is_mdx_c_seg_def = mdx.is_mdx_c_seg_def
    model.mdx_batch_size = 1 if mdx.batch_size is None else int(mdx.batch_size)
    model.mdxnet_stem_select = mdx.stems
    model.mdxnet_stems_selected = mdx.stems_selected or []
    model.overlap = float(demucs.overlap)
    model.overlap_mdx = 0.25 if mdx.overlap_mdx is None else float(mdx.overlap_mdx)
    model.overlap_mdx23 = int(mdx.overlap_mdx23)
    model.semitone_shift = float(process.semitone_shift)
    model.is_pitch_change = False if model.semitone_shift == 0 else True
    model.is_match_frequency_pitch = mdx.is_match_frequency_pitch
    model.is_mdx_ckpt = False
    model.is_mdx_c = False
    # Roformer models are MDX-C-style nets selected by their yaml config
    # (``is_roformer`` in the model-data JSON); ``is_target_instrument`` marks
    # a config that defines a single ``training.target_instrument``.
    model.is_roformer = False
    model.is_target_instrument = False
    model.model_type: str = ""
    model.is_mdx_combine_stems = mdx.is_mdx23_combine_stems
    model.is_mdx_include_stem_complement = mdx.is_mdx_include_stem_complement
    model.mdx_c_configs: Any = None
    model.mdx_config_yaml = ""
    model.mdx_config_sha256 = ""
    model.mdx_hash_record_source = ""
    model.mdx_runtime_reconciliation: Any = None
    model.mdx_model_stems: list[str] = []
    model.mdx_dim_f_set: int | None = None
    model.mdx_dim_t_set: int | None = None
    model.mdx_stem_count = 1
    model.compensate: float | None = None
    model.mdx_n_fft_scale_set: int | None = None
    model.wav_type_set = resolve_wav_type_set(settings)
    model.device_set = device_set.split(":")[-1].strip() if ":" in device_set else device_set
    model.mp3_bit_set = enum_value(process.mp3_bitrate)
    model.flac_bit_set = enum_value(process.flac_bit_depth)
    model.opus_bit_set = enum_value(process.opus_bitrate)
    model.save_format = process.save_format.value
    model.is_invert_spec = mdx.is_invert_spec
    model.is_mixer_mode = False
    model.demucs_stems = demucs.stems
    model.is_demucs_combine_stems = demucs.is_demucs_combine_stems
    model.demucs_source_list: Sequence[str] = []
    model.demucs_source_map: dict[str, int] = {}
    model.demucs_stem_count = 0
    model.mixer_path = paths.MDX_MIXER_PATH
    model.canonical_id = identity.id if identity is not None else ""
    model.stem_semantics = None
    model.model_display_label = identity.display if identity is not None else model_name
    model.backend_name = identity.backend_name if identity is not None else model_name
    model.model_artifacts = identity.artifacts if identity is not None else None
    model.demucs = identity.demucs if identity is not None else None
    model._identity_record = identity
    model.model_name = model.model_display_label
    model.process_method = identity.arch if identity is not None else selected_process_method
    model.model_status = (
        False if model.model_name == CHOOSE_MODEL or model.model_name == NO_MODEL else True
    )
    # Always defined: hash / path lookup may leave this unset for missing files.
    model.model_data: Any = None
    model.primary_stem: str | None = None
    model.secondary_stem: str | None = None
    model.primary_stem_native: str | None = None
    model.is_ensemble_mode = False
    model.ensemble_primary_stem = None
    model.ensemble_secondary_stem = None
    model.ensemble_pair_roles: tuple[object, ...] = ()
    model.primary_model_primary_stem = primary_model_primary_stem
    model.is_secondary_model = True if is_vocal_split_model else is_secondary_model
    model.secondary_model = None
    model.secondary_model_scale = None
    model.demucs_4_stem_added_count = 0
    model.is_demucs_4_stem_secondaries = False
    model.is_4_stem_ensemble = False
    model.pre_proc_model = None
    model.pre_proc_model_activated = False
    model.is_pre_proc_model = is_pre_proc_model
    model.is_dry_check = is_dry_check
    model.model_samplerate: Any = 44100
    model.model_capacity: Any = (32, 128)
    model.is_vr_51_model = False
    model.is_demucs_pre_proc_model_inst_mix = False
    model.secondary_model_4_stem = []
    model.secondary_model_4_stem_scale = []
    model.secondary_model_4_stem_names = []
    model.secondary_model_4_stem_model_names_list = []
    model.all_models = []
    model.secondary_model_other = None
    model.secondary_model_scale_other = None
    model.secondary_model_bass = None
    model.secondary_model_scale_bass = None
    model.secondary_model_drums = None
    model.secondary_model_scale_drums = None
    model.is_multi_stem_ensemble = False
    model.is_karaoke = False
    model.is_karaoke_curated = False
    model.is_bv_model = False
    model.bv_model_rebalance = 0
    model.is_sec_bv_rebalance = False
    model.is_change_def = is_change_def
    model.model_hash_dir = None
    model.is_get_hash_dir_only = is_get_hash_dir_only
    model.is_secondary_model_activated = False
    model.vocal_split_model = None
    model.is_vocal_split_model = is_vocal_split_model
    model.is_vocal_split_model_activated = False
    model.is_save_inst_vocal_splitter = process.save_inst_vocal_splitter
    # Computed at the end of __init__ once the primary/secondary stems are
    # resolved (UVR reads them from the live stem-only labels instead).
    model.is_inst_only_voc_splitter = False
    model.is_save_vocal_only = False
    model._is_secondary_model_param = is_secondary_model


def resolve_identity(model: ModelConfig, inputs: ModelBuildInputs) -> None:
    model_name = inputs.model_name
    selected_process_method = inputs.selected_process_method
    is_secondary_model = inputs.is_secondary_model
    is_pre_proc_model = inputs.is_pre_proc_model
    identity = inputs.identity
    process = inputs.settings.process
    demucs = inputs.settings.demucs
    ensemble = inputs.settings.ensemble

    if selected_process_method == ENSEMBLE_MODE:
        if identity is not None:
            model.process_method = identity.arch
            model.model_and_process_tag = identity.id
        else:
            model.process_method, separator, model.model_name = model_name.partition(
                ENSEMBLE_PARTITION
            )
            model.model_and_process_tag = model_name
            if not separator:
                model.model_status = False
        model.ensemble_primary_stem, model.ensemble_secondary_stem = model.return_ensemble_stems()
        is_not_secondary_or_pre_proc = not is_secondary_model and not is_pre_proc_model
        model.is_ensemble_mode = is_not_secondary_or_pre_proc

        from core.stem_pairs import normalize_stem_pair_id

        ensemble_pair_id = normalize_stem_pair_id(ensemble.main_stem)
        if ensemble_pair_id == "mode.four_stem":
            model.is_4_stem_ensemble = model.is_ensemble_mode
        elif ensemble_pair_id == "mode.multi_stem" and process.method == ENSEMBLE_MODE:
            model.is_multi_stem_ensemble = True

        is_not_vocal_stem = model.ensemble_primary_stem != VOCAL_STEM
        model.pre_proc_model_activated = (
            demucs.is_pre_proc_model_activate if is_not_vocal_stem else False
        )
