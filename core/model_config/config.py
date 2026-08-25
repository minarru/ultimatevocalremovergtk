"""Public typed model configuration."""

from __future__ import annotations

import json
import os
import typing
from typing import TYPE_CHECKING, Any, Mapping, Optional, Sequence, cast

from bundled.constants import *  # noqa: F401,F403 - mirrors UVR.py's flat constant namespace

from .. import paths
from ..audio_io import resolve_wav_type_set
from ..demucs_models import resolve_demucs_model_file
from ..mdx_c_registry import compute_checkpoint_hash, try_register_from_catalog
from ..mdx_config_fetch import ensure_mdx_c_config
from ..model_stem_semantics import resolve_karaoke_confidence
from ..settings import Settings
from ..settings.coerce import enum_value

if TYPE_CHECKING:
    from ..model_identity import ModelRecord
    from ..model_repository import ModelRepository


class ModelConfig:
    """Configuration consumed by separation engines.

    The inherited flat attributes are the stable duck-typed engine API. New
    callers can use the typed nested groups populated by the implementation:
    ``identity``, ``export_options``, ``device_options``, ``ensemble_flags``,
    ``stem_routing``, ``secondary_chain``, and the architecture option group.
    """

    def __init__(
        self,
        settings: Settings,
        repo: "ModelRepository",
        model_name: str,
        selected_process_method: str = ENSEMBLE_MODE,
        is_secondary_model: bool = False,
        primary_model_primary_stem: Optional[str] = None,
        is_pre_proc_model: bool = False,
        is_dry_check: bool = False,
        is_change_def: bool = False,
        is_get_hash_dir_only: bool = False,
        is_vocal_split_model: bool = False,
        identity: "ModelRecord | None" = None,
        model_dependencies: Mapping[str, "ModelRecord"] | None = None,
    ):
        self.settings = settings
        self.repo: Any = repo
        self.model_dependencies = model_dependencies
        from ..model_data import (
            _mdx_c_primary_for_select,
            _mdx_c_secondary_for_pair,
            _mdx_c_training,
            load_mdx_c_config,
        )
        from .determine import process_determine_demucs_pre_proc_model

        process = settings.process
        vr = settings.vr
        mdx = settings.mdx
        demucs = settings.demucs
        ensemble = settings.ensemble

        device_set = process.device or DEFAULT
        self.DENOISER_MODEL = paths.DENOISER_MODEL_PATH
        self.DEVERBER_MODEL = paths.DEVERBER_MODEL_PATH
        self.is_deverb_vocals = (
            process.deverb_vocals
            if os.path.isfile(paths.DEVERBER_MODEL_PATH)
            else False
        )
        self.deverb_vocal_opt = DEVERB_MAPPER[enum_value(process.deverb_vocal_opt)]
        denoise_opt = enum_value(mdx.denoise_option)
        self.is_denoise_model = bool(
            denoise_opt == DENOISE_M
            and os.path.isfile(paths.DENOISER_MODEL_PATH)
        )
        self.is_gpu_conversion = bool(process.use_gpu)
        self.use_gpu = self.is_gpu_conversion
        self.is_normalization = process.normalization
        self.is_match_mix_level = bool(process.match_mix_level)
        self.is_prevent_export_clipping = bool(process.prevent_export_clipping)
        try:
            self.amplification_threshold = float(
                process.amplification_threshold or 0.0
            )
        except (TypeError, ValueError):
            self.amplification_threshold = 0.0
        self.is_use_directml = bool(process.use_directml)
        self.is_denoise = denoise_opt != DENOISE_NONE
        self.is_mdx_c_seg_def = mdx.is_mdx_c_seg_def
        self.mdx_batch_size = (
            1 if mdx.batch_size is None else int(mdx.batch_size)
        )
        self.mdxnet_stem_select = mdx.stems
        self.mdxnet_stems_selected = mdx.stems_selected or []
        self.overlap = float(demucs.overlap)
        self.overlap_mdx = (
            0.25 if mdx.overlap_mdx is None else float(mdx.overlap_mdx)
        )
        self.overlap_mdx23 = int(mdx.overlap_mdx23)
        self.semitone_shift = float(process.semitone_shift)
        self.is_pitch_change = False if self.semitone_shift == 0 else True
        self.is_match_frequency_pitch = mdx.is_match_frequency_pitch
        self.is_mdx_ckpt = False
        self.is_mdx_c = False
        # Roformer models are MDX-C-style nets selected by their yaml config
        # (``is_roformer`` in the model-data JSON); ``is_target_instrument`` marks
        # a config that defines a single ``training.target_instrument``.
        self.is_roformer = False
        self.is_target_instrument = False
        self.model_type: str = ""
        self.is_mdx_combine_stems = mdx.is_mdx23_combine_stems
        self.is_mdx_include_stem_complement = mdx.is_mdx_include_stem_complement
        self.mdx_c_configs: Any = None
        self.mdx_model_stems: list[str] = []
        self.mdx_dim_f_set: int | None = None
        self.mdx_dim_t_set: int | None = None
        self.mdx_stem_count = 1
        self.compensate: float | None = None
        self.mdx_n_fft_scale_set: int | None = None
        self.wav_type_set = resolve_wav_type_set(settings)
        self.device_set = (
            device_set.split(":")[-1].strip() if ":" in device_set else device_set
        )
        self.mp3_bit_set = enum_value(process.mp3_bitrate)
        self.flac_bit_set = enum_value(process.flac_bit_depth)
        self.save_format = process.save_format.value
        self.is_invert_spec = mdx.is_invert_spec
        self.is_mixer_mode = False
        self.demucs_stems = demucs.stems
        self.is_demucs_combine_stems = demucs.is_demucs_combine_stems
        self.demucs_source_list: Sequence[str] = []
        self.demucs_source_map: dict[str, int] = {}
        self.demucs_stem_count = 0
        self.mixer_path = paths.MDX_MIXER_PATH
        self.canonical_id = identity.id if identity is not None else ""
        self.stem_semantics = None
        self.model_display_label = (
            identity.display if identity is not None else model_name
        )
        self.backend_name = (
            identity.backend_name if identity is not None else model_name
        )
        self.model_artifacts = (
            identity.artifacts if identity is not None else None
        )
        self.demucs = identity.demucs if identity is not None else None
        self._identity_record = identity
        self.model_name = self.model_display_label
        self.process_method = (
            identity.arch if identity is not None else selected_process_method
        )
        self.model_status = False if self.model_name == CHOOSE_MODEL or self.model_name == NO_MODEL else True
        # Always defined: hash / path lookup may leave this unset for missing files.
        self.model_data: Any = None
        self.primary_stem: str | None = None
        self.secondary_stem: str | None = None
        self.primary_stem_native: str | None = None
        self.is_ensemble_mode = False
        self.ensemble_primary_stem = None
        self.ensemble_secondary_stem = None
        self.ensemble_pair_roles: tuple[object, ...] = ()
        self.primary_model_primary_stem = primary_model_primary_stem
        self.is_secondary_model = True if is_vocal_split_model else is_secondary_model
        self.secondary_model = None
        self.secondary_model_scale = None
        self.demucs_4_stem_added_count = 0
        self.is_demucs_4_stem_secondaries = False
        self.is_4_stem_ensemble = False
        self.pre_proc_model = None
        self.pre_proc_model_activated = False
        self.is_pre_proc_model = is_pre_proc_model
        self.is_dry_check = is_dry_check
        self.model_samplerate: Any = 44100
        self.model_capacity: Any = (32, 128)
        self.is_vr_51_model = False
        self.is_demucs_pre_proc_model_inst_mix = False
        self.secondary_model_4_stem = []
        self.secondary_model_4_stem_scale = []
        self.secondary_model_4_stem_names = []
        self.secondary_model_4_stem_model_names_list = []
        self.all_models = []
        self.secondary_model_other = None
        self.secondary_model_scale_other = None
        self.secondary_model_bass = None
        self.secondary_model_scale_bass = None
        self.secondary_model_drums = None
        self.secondary_model_scale_drums = None
        self.is_multi_stem_ensemble = False
        self.is_karaoke = False
        self.is_karaoke_curated = False
        self.is_bv_model = False
        self.bv_model_rebalance = 0
        self.is_sec_bv_rebalance = False
        self.is_change_def = is_change_def
        self.model_hash_dir = None
        self.is_get_hash_dir_only = is_get_hash_dir_only
        self.is_secondary_model_activated = False
        self.vocal_split_model = None
        self.is_vocal_split_model = is_vocal_split_model
        self.is_vocal_split_model_activated = False
        self.is_save_inst_vocal_splitter = process.save_inst_vocal_splitter
        # Computed at the end of __init__ once the primary/secondary stems are
        # resolved (UVR reads them from the live stem-only labels instead).
        self.is_inst_only_voc_splitter = False
        self.is_save_vocal_only = False
        self._is_secondary_model_param = is_secondary_model

        if selected_process_method == ENSEMBLE_MODE:
            if identity is not None:
                self.process_method = identity.arch
                self.model_and_process_tag = identity.id
            else:
                self.process_method, separator, self.model_name = model_name.partition(
                    ENSEMBLE_PARTITION
                )
                self.model_and_process_tag = model_name
                if not separator:
                    self.model_status = False
            self.ensemble_primary_stem, self.ensemble_secondary_stem = self.return_ensemble_stems()
            is_not_secondary_or_pre_proc = not is_secondary_model and not is_pre_proc_model
            self.is_ensemble_mode = is_not_secondary_or_pre_proc

            from core.stem_pairs import normalize_stem_pair_id

            ensemble_pair_id = normalize_stem_pair_id(ensemble.main_stem)
            if ensemble_pair_id == "mode.four_stem":
                self.is_4_stem_ensemble = self.is_ensemble_mode
            elif (
                ensemble_pair_id == "mode.multi_stem"
                and process.method == ENSEMBLE_MODE
            ):
                self.is_multi_stem_ensemble = True

            is_not_vocal_stem = self.ensemble_primary_stem != VOCAL_STEM
            self.pre_proc_model_activated = (
                demucs.is_pre_proc_model_activate if is_not_vocal_stem else False
            )

        if self.process_method == VR_ARCH_TYPE:
            self.is_secondary_model_activated = (
                vr.is_secondary_model_activate if not is_secondary_model else False
            )
            self.aggression_setting = float(int(vr.aggression_setting) / 100)
            self.is_tta = vr.is_tta
            self.is_post_process = vr.is_post_process
            self.window_size = int(vr.window_size)
            self.batch_size = (
                1 if vr.batch_size is None else int(vr.batch_size)
            )
            self.crop_size = int(vr.crop_size)
            self.is_high_end_process = (
                "mirroring" if vr.is_high_end_process else "None"
            )
            self.post_process_threshold = float(vr.post_process_threshold)
            self.model_capacity = 32, 128
            self.get_vr_model_path()
            self.get_model_hash()
            if self.model_hash:
                self.model_hash_dir = os.path.join(paths.VR_HASH_DIR, f"{self.model_hash}.json")
                if self.is_change_def:
                    self.model_data = self.change_model_data()
                else:
                    self.model_data = self.get_model_data(paths.VR_HASH_DIR, repo.vr_hash_MAPPER) if self.model_hash != WOOD_INST_MODEL_HASH else WOOD_INST_PARAMS
                if self.model_data:
                    from ml.vr_network.model_param_init import ModelParameters
                    vr_model_param = os.path.join(paths.VR_PARAM_DIR, "{}.json".format(self.model_data["vr_model_param"]))
                    self.primary_stem = self.model_data["primary_stem"]
                    self.secondary_stem = secondary_stem(str(self.primary_stem or ""))
                    self.vr_model_param = ModelParameters(vr_model_param)
                    self.model_samplerate = self.vr_model_param.param["sr"]
                    self.primary_stem_native = self.primary_stem
                    if "nout" in self.model_data.keys() and "nout_lstm" in self.model_data.keys():
                        self.model_capacity = self.model_data["nout"], self.model_data["nout_lstm"]
                        self.is_vr_51_model = True
                    self.check_if_karaokee_model()
                else:
                    self.model_status = False

        if self.process_method == MDX_ARCH_TYPE:
            self.is_secondary_model_activated = (
                mdx.is_secondary_model_activate if not is_secondary_model else False
            )
            self.margin = int(mdx.margin)
            self.chunks = 0
            self.mdx_segment_size = int(mdx.segment_size)
            self.get_mdx_model_path()
            self.get_model_hash()
            if self.model_hash:
                self.model_hash_dir = os.path.join(paths.MDX_HASH_DIR, f"{self.model_hash}.json")
                if self.is_change_def:
                    self.model_data = self.change_model_data()
                else:
                    self.model_data = self.get_model_data(paths.MDX_HASH_DIR, repo.mdx_hash_MAPPER)
                if self.model_data:
                    if "is_roformer" in self.model_data:
                        self.is_roformer = self.model_data["is_roformer"]
                    if "model_type" in self.model_data:
                        self.model_type = str(self.model_data["model_type"])
                    if "config_yaml" in self.model_data:
                        self.is_mdx_c = True
                        config_name = self.model_data["config_yaml"]
                        config_path = os.path.join(paths.MDX_C_CONFIG_PATH, config_name)
                        if not os.path.isfile(config_path):
                            ensure_mdx_c_config(config_name)
                        if os.path.isfile(config_path):
                            try:
                                from ml_collections import ConfigDict

                                config = ConfigDict(load_mdx_c_config(config_path))
                            except ImportError:
                                # yaml / ml_collections are part of the (lazy) ML
                                # stack; without them an MDX-C model can't be
                                # configured, so treat it as unavailable here.
                                config = None
                            except Exception as exc:
                                from ..debug_log import debug

                                debug(
                                    "model",
                                    f"mdx_c_config load failed file={os.path.basename(config_path)} "
                                    f"error={type(exc).__name__}: {exc}",
                                )
                                config = None
                            if config is None:
                                self.model_status = False
                            else:
                                self.mdx_c_configs = config
                                training = _mdx_c_training(self.mdx_c_configs)
                                target_instrument = (
                                    getattr(training, "target_instrument", None)
                                    if training is not None
                                    else None
                                )
                                if target_instrument:
                                    self.is_target_instrument = True
                                    target = target_instrument
                                    self.mdx_model_stems = [target]
                                    # Odd yaml: target ``other`` is a clean
                                    # instrumental extractor; complement is the
                                    # acapella (all vocals), not ``No other``.
                                    if str(target).casefold() == "other":
                                        self.primary_stem_native = str(target)
                                        self.primary_stem = INST_STEM
                                        self.secondary_stem = VOCAL_STEM
                                    else:
                                        self.primary_stem = target
                                        self.primary_stem_native = str(target)
                                        self.secondary_stem = secondary_stem(
                                            str(self.primary_stem or "")
                                        )
                                    if self.is_roformer and self.is_ensemble_mode and target in (VOCAL_STEM, INST_STEM):
                                        self.mdxnet_stem_select = self.ensemble_primary_stem
                                elif training is not None:
                                    instruments = getattr(training, "instruments", None) or []
                                    self.mdx_model_stems = list(instruments)
                                    self.mdx_stem_count = len(self.mdx_model_stems)
                                    if self.mdx_stem_count == 2:
                                        self.primary_stem = self.mdx_model_stems[0]
                                    else:
                                        # ``mdx.stems`` is a global UI choice (often
                                        # Instrumental/Vocals). 4-stem models only
                                        # expose drums/bass/other/vocals — keep the
                                        # selection when it exists, otherwise fall
                                        # back so export never KeyErrors.
                                        self.primary_stem = _mdx_c_primary_for_select(
                                            self.mdx_model_stems,
                                            self.mdxnet_stem_select,
                                        )
                                    self.primary_stem_native = str(self.primary_stem or "")
                                    if self.is_ensemble_mode:
                                        self.mdxnet_stem_select = self.ensemble_primary_stem
                                    self.secondary_stem = secondary_stem(
                                        str(self.primary_stem or "")
                                    )
                                    if self.mdx_stem_count == 2:
                                        self.secondary_stem = _mdx_c_secondary_for_pair(
                                            self.mdx_model_stems,
                                            self.primary_stem,
                                            self.secondary_stem,
                                        )
                                else:
                                    self.secondary_stem = secondary_stem(
                                        str(self.primary_stem or "")
                                    )
                        else:
                            self.model_status = False
                    else:
                        self.compensate = (
                            self.model_data["compensate"]
                            if mdx.compensate is None
                            else float(mdx.compensate)
                        )
                        self.mdx_dim_f_set = self.model_data["mdx_dim_f_set"]
                        self.mdx_dim_t_set = self.model_data["mdx_dim_t_set"]
                        self.mdx_n_fft_scale_set = self.model_data["mdx_n_fft_scale_set"]
                        self.primary_stem = self.model_data["primary_stem"]
                        self.primary_stem_native = self.model_data["primary_stem"]
                        self.secondary_stem = secondary_stem(str(self.primary_stem or ""))
                else:
                    self.model_status = False

        if self.process_method == DEMUCS_ARCH_TYPE:
            self.is_secondary_model_activated = (
                demucs.is_secondary_model_activate if not is_secondary_model else False
            )
            if not self.is_ensemble_mode:
                self.pre_proc_model_activated = (
                    demucs.is_pre_proc_model_activate
                    if demucs.stems not in [VOCAL_STEM, INST_STEM]
                    else False
                )
            self.shifts = int(demucs.shifts)
            self.is_split_mode = demucs.is_split_mode
            # Engine ``demucs_segments`` expects the legacy ``Default`` label.
            self.segment = (
                DEF_OPT if demucs.segment is None else str(demucs.segment)
            )
            self.get_demucs_model_data()
            self.get_demucs_model_path()

        if self.model_status:
            self.model_basename = os.path.splitext(os.path.basename(self.model_path))[0]
        else:
            self.model_basename = None

        if self.process_method == MDX_ARCH_TYPE and self.model_data:
            self.apply_karaoke_metadata(
                str(self.model_data.get("config_yaml") or "")
            )

        self.pre_proc_model_activated = self.pre_proc_model_activated if not self.is_secondary_model else False

        # -- Secondary model resolution (ported from UVR.py L686-L715) ----------
        is_secondary_activated_and_status = self.is_secondary_model_activated and self.model_status
        is_demucs = self.process_method == DEMUCS_ARCH_TYPE
        is_all_stems = demucs.stems == ALL_STEMS
        # The four per-stem Demucs secondary slots only exist on a model that
        # actually emits four (or six) sources. ``active_model_paths`` widens to
        # them on exactly that condition (``4_stem``/``6_stem`` layout), so a
        # 2-source model here would resolve slots planning never declared.
        is_valid_ensemble = (
            not self.is_ensemble_mode
            and is_all_stems
            and is_demucs
            and self.demucs_stem_count >= 4
        )
        is_multi_stem_ensemble_demucs = self.is_multi_stem_ensemble and is_demucs

        if is_secondary_activated_and_status:
            if is_valid_ensemble or self.is_4_stem_ensemble or is_multi_stem_ensemble_demucs:
                for key in DEMUCS_4_SOURCE_LIST:
                    self.secondary_model_data(key)
                    self.secondary_model_4_stem.append(self.secondary_model)
                    self.secondary_model_4_stem_scale.append(self.secondary_model_scale)
                    self.secondary_model_4_stem_names.append(key)
                self.demucs_4_stem_added_count = sum(i is not None for i in self.secondary_model_4_stem)
                self.is_secondary_model_activated = any(i is not None for i in self.secondary_model_4_stem)
                self.demucs_4_stem_added_count -= 1 if self.is_secondary_model_activated else 0
                if self.is_secondary_model_activated:
                    self.secondary_model_4_stem_model_names_list = [
                        (
                            getattr(i, "backend_name", None)
                            or getattr(i, "model_basename", None)
                        )
                        if i is not None
                        else None
                        for i in self.secondary_model_4_stem
                    ]
                    self.is_demucs_4_stem_secondaries = True
            else:
                primary_stem = self.ensemble_primary_stem if self.is_ensemble_mode and is_demucs else self.primary_stem
                self.secondary_model_data(primary_stem)

        if self.process_method == DEMUCS_ARCH_TYPE and not is_secondary_model:
            if self.demucs_stem_count >= 3 and self.pre_proc_model_activated:
                self.pre_proc_model = process_determine_demucs_pre_proc_model(
                    self.settings, self.repo, self.primary_stem,
                    self.model_dependencies,
                )
                self.pre_proc_model_activated = True if self.pre_proc_model else False
                self.is_demucs_pre_proc_model_inst_mix = (
                    demucs.is_pre_proc_model_inst_mix if self.pre_proc_model else False
                )

        if self.is_vocal_split_model and self.model_status:
            self.is_secondary_model_activated = False

        self._apply_stem_focus()

        # Derive the vocal-splitter "save only" flags now that stems are known.
        self.is_inst_only_voc_splitter = self.check_only_selection_stem(INST_STEM_ONLY)
        self.is_save_vocal_only = self.check_only_selection_stem(IS_SAVE_VOC_ONLY)

        self.vocal_splitter_model_data()
        self._sync_option_groups()

    def _apply_stem_focus(self) -> None:
        """Honor ``process.stem_focus`` as the exclusive-pick (GTK and CLI).

        Fills ``available_stem_routes`` / ``selected_stem_routes`` only.
        Native yaml keys and exclusive-save flags stay as assembled from
        settings; engines read the routes. Vocal splitters still receive a
        selection, but :func:`~core.stems.run_export_routes` writes the full
        inventory.

        CLI ``--stems primary|secondary`` stores positional sentinels in
        ``stem_focus``. Those pick the primary/secondary native (or derived
        complement) here so engines export that one route. A multi-stem MDX-C
        custom subset still lives in ``mdxnet_stems_selected`` (natives) and
        is applied after that. Do not fold subset names into ``stem_focus``.

        Resolution is **per-config only**: assembling a model must never write
        back into ``self.settings``. One ``Settings`` assembles many configs
        (ensemble members, secondaries, pre-process), and in the GUI it is the
        live persisted object that read-only callers such as
        ``estimate_workload`` also assemble from.
        """
        from core.stems import (
            FOCUS_PRIMARY,
            StemSelectionStatus,
            model_stem_routes,
            positional_stem_focus,
            route_matches_stem,
            routes_for_ensemble_pair,
            routes_matching_stems,
            select_stem_routes,
        )

        focus = str(getattr(self.settings.process, "stem_focus", "") or "")
        routes = model_stem_routes(self)
        self.available_stem_routes = routes
        positional = positional_stem_focus(focus)
        selection_matched = False
        if positional:
            logical = tuple(route for route in routes if route.logical_primary)
            if positional == FOCUS_PRIMARY and len(logical) == 1:
                matched = logical
            elif positional != FOCUS_PRIMARY and len(routes) == 2 and len(logical) == 1:
                matched = tuple(route for route in routes if not route.logical_primary)
            else:
                target = (
                    self.primary_stem if positional == FOCUS_PRIMARY else self.secondary_stem
                )
                matched = tuple(
                    route
                    for route in routes
                    if route_matches_stem(route, target, self)
                )
            selected = matched[:1] if matched else (
                tuple(route for route in routes if route.selected_by_default)
                or tuple(routes)
            )
        else:
            selection = select_stem_routes(routes, focus)
            selection_matched = selection.status is StemSelectionStatus.MATCHED
            if selection.status is StemSelectionStatus.UNMATCHED:
                selected = tuple(
                    route for route in routes if route.selected_by_default
                ) or tuple(routes)
            else:
                selected = selection.routes

            if selection.status is StemSelectionStatus.EMPTY:
                mdx_stems = tuple(
                    str(stem)
                    for stem in (getattr(self, "mdx_model_stems", None) or ())
                    if stem
                )
                sidecar = tuple(
                    str(stem)
                    for stem in (getattr(self, "mdxnet_stems_selected", None) or ())
                    if stem
                )
                if len(mdx_stems) > 2 and sidecar:
                    native_concepts = {
                        route.concept
                        for route in routes
                        if route.native is not None
                    }
                    matched = routes_matching_stems(routes, sidecar, self)
                    matched_concepts = {route.concept for route in matched}
                    if matched and matched_concepts < native_concepts:
                        selected = matched

        # Dual-stem ensemble members default to the pair, not a 4-stem model's
        # full native inventory. Four/multi-stem members keep the selection for
        # final combine; ``run_export_routes`` emits the full inventory.
        if not self.is_vocal_split_model and bool(getattr(self, "is_ensemble_mode", False)):
            from core.stem_pairs import normalize_stem_pair_id, stem_pair_definition

            pair_id = normalize_stem_pair_id(self.settings.ensemble.main_stem)
            pair = stem_pair_definition(pair_id)
            if pair is not None:
                pair_routes = routes_for_ensemble_pair(routes, pair)
                if not pair_routes:
                    selected = ()
                elif not selection_matched:
                    selected = pair_routes

        self.selected_stem_routes = selected

    def _exclusive_sides_from_routes(self) -> tuple[bool, bool]:
        """``(primary_only, secondary_only)`` from a single selected route.

        Native subset picks (bass on a 4-stem MDX-C model) are not a dual-stem
        exclusive, so both sides stay false — matching the old assemble overlay.
        """
        from core.stems import route_matches_stem

        selected = tuple(getattr(self, "selected_stem_routes", ()) or ())
        if len(selected) != 1:
            return False, False
        route = selected[0]
        if route_matches_stem(route, self.primary_stem, self):
            return True, False
        if route_matches_stem(route, self.secondary_stem, self):
            return False, True
        return False, False

    # -- Secondary / vocal-split / pre-process resolution -----------------------
    # Faithful Tk-free ports of ``MainWindow.process_determine_*`` /
    # ``vocal_splitter_model_data`` / ``secondary_model_data`` reading the same
        # flat settings keys instead of Tk variables.

    def vocal_splitter_model_data(self):
        from .determine import process_determine_vocal_split_model

        self.vocal_split_model = None
        self.is_vocal_split_model_activated = False
        if not self.is_secondary_model and self.model_status:
            self.vocal_split_model = process_determine_vocal_split_model(
                self.settings, self.repo, self.model_dependencies
            )
            self.is_vocal_split_model_activated = True if self.vocal_split_model else False
            if self.vocal_split_model and self.vocal_split_model.bv_model_rebalance:
                self.is_sec_bv_rebalance = True

    def secondary_model_data(self, primary_stem: typing.Any):
        from .determine import process_determine_secondary_model

        secondary_model, secondary_model_scale = process_determine_secondary_model(
            self.settings,
            self.repo,
            self.process_method,
            primary_stem,
            self.model_dependencies,
        )
        self.secondary_model = secondary_model
        self.secondary_model_scale = secondary_model_scale
        self.is_secondary_model_activated = False if not secondary_model else True
        if self.secondary_model:
            self.is_secondary_model_activated = False if self.secondary_model.model_basename == self.model_basename else True

    def return_ensemble_stems(self, is_primary: typing.Any = False):
        """Return registry labels for the selected exact reviewed role pair."""
        from core.model_stem_manifest import load_bundled_stem_semantics
        from core.stem_pairs import normalize_stem_pair_id, stem_pair_definition

        pair = stem_pair_definition(
            normalize_stem_pair_id(self.settings.ensemble.main_stem)
        )
        if pair is None:
            self.ensemble_pair_roles = ()
            primary, secondary = "", ""
        else:
            registry = load_bundled_stem_semantics()
            primary_definition = registry.roles.get(pair.roles[0])
            secondary_definition = registry.roles.get(pair.roles[1])
            if primary_definition is None or secondary_definition is None:
                self.ensemble_pair_roles = ()
                primary, secondary = "", ""
            else:
                self.ensemble_pair_roles = pair.roles
                primary = primary_definition.display
                secondary = secondary_definition.display
        if is_primary:
            return primary
        return primary, secondary

    def check_only_selection_stem(self, checktype: typing.Any):
        """Port of ``MainWindow.check_only_selection_stem``.

        UVR reads the live stem-only checkbox labels (set by
        ``update_stem_checkbox_labels`` to ``f"{stem} Only"``); the Tk-free port
        derives the same labels from the model's resolved primary/secondary
        stems instead.
        """
        chosen_method = self.settings.process.method
        # In ensemble mode the stem-only labels follow the chosen ensemble pair
        # (UVR's ``update_stem_checkbox_labels``), not the member model's stems.
        if chosen_method == ENSEMBLE_MODE:
            primary_for_label = self.ensemble_primary_stem
            secondary_for_label = self.ensemble_secondary_stem
        else:
            primary_for_label = self.primary_stem
            secondary_for_label = self.secondary_stem

        # A single selected route that names this pair's primary/secondary is
        # the exclusive pick (CLI ``--stems vocals`` included). Native subset
        # picks such as bass do not count — see ``_exclusive_sides_from_routes``.
        from core.stems import route_matches_stem

        selected = tuple(getattr(self, "selected_stem_routes", ()) or ())
        stem_primary_bool = False
        stem_secondary_bool = False
        if len(selected) == 1:
            route = selected[0]
            pair_roles = tuple(getattr(self, "ensemble_pair_roles", ()) or ())
            if chosen_method == ENSEMBLE_MODE and len(pair_roles) == 2:
                stem_primary_bool = route.role == pair_roles[0]
                stem_secondary_bool = route.role == pair_roles[1]
            else:
                stem_primary_bool = route_matches_stem(route, primary_for_label, self)
                stem_secondary_bool = (not stem_primary_bool) and route_matches_stem(
                    route, secondary_for_label, self
                )

        is_save_inst_splitter = self.settings.process.save_inst_vocal_splitter
        has_voc_splitter = (
            self.settings.process.vocal_splitter_enabled
            and self.settings.process.vocal_splitter != NO_MODEL
        )

        if chosen_method == ENSEMBLE_MODE:
            from core.model_stem_manifest import load_bundled_stem_semantics

            pair_roles = tuple(getattr(self, "ensemble_pair_roles", ()) or ())
            registry = load_bundled_stem_semantics()
            primary_definition = registry.roles.get(pair_roles[0]) if len(pair_roles) == 2 else None
            secondary_definition = registry.roles.get(pair_roles[1]) if len(pair_roles) == 2 else None
            primary_is_vocals = bool(
                primary_definition is not None and primary_definition.family.value == "vocal"
            )
            secondary_is_vocals = bool(
                secondary_definition is not None and secondary_definition.family.value == "vocal"
            )
            primary_is_inst = bool(
                primary_definition is not None and primary_definition.family.value == "mix"
            )
            secondary_is_inst = bool(
                secondary_definition is not None and secondary_definition.family.value == "mix"
            )
        else:
            from core.stems import StemBucket, bucket_for_model_stem, stem_context

            vocal_buckets = {
                StemBucket.VOCALS,
                StemBucket.LEAD_VOCALS,
                StemBucket.BACKING_VOCALS,
            }
            inst_buckets = {
                StemBucket.INSTRUMENTAL,
                StemBucket.INST_WITH_BV,
                StemBucket.INST_WITH_LEAD,
            }
            ctx = stem_context(self)
            primary_bucket = bucket_for_model_stem(str(primary_for_label or ""), **ctx)
            secondary_bucket = bucket_for_model_stem(
                str(secondary_for_label or ""), **ctx
            )
            primary_is_vocals = primary_bucket in vocal_buckets
            secondary_is_vocals = secondary_bucket in vocal_buckets
            primary_is_inst = primary_bucket in inst_buckets
            secondary_is_inst = secondary_bucket in inst_buckets

        if checktype == VOCAL_STEM_ONLY:
            return not (
                (not primary_is_vocals and stem_primary_bool) or
                (not secondary_is_vocals and stem_secondary_bool)
            )
        elif checktype == INST_STEM_ONLY:
            return (
                (primary_is_inst and stem_primary_bool and is_save_inst_splitter and has_voc_splitter) or
                (secondary_is_inst and stem_secondary_bool and is_save_inst_splitter and has_voc_splitter)
            )
        elif checktype == IS_SAVE_VOC_ONLY:
            return (
                (primary_is_vocals and stem_primary_bool) or
                (secondary_is_vocals and stem_secondary_bool)
            )
        elif checktype == IS_SAVE_INST_ONLY:
            return (
                (primary_is_inst and stem_primary_bool) or
                (secondary_is_inst and stem_secondary_bool)
            )
        return False

    def check_if_karaokee_model(self):
        if not self.model_data:
            return
        if IS_KARAOKEE in self.model_data.keys():
            self.is_karaoke = bool(self.model_data[IS_KARAOKEE])
            self.is_karaoke_curated = True
        elif "is_karaokee" in self.model_data:
            self.is_karaoke = bool(self.model_data["is_karaokee"])
            self.is_karaoke_curated = True
        if IS_BV_MODEL in self.model_data.keys():
            self.is_bv_model = self.model_data[IS_BV_MODEL]
        if IS_BV_MODEL_REBAL in self.model_data.keys() and self.is_bv_model:
            self.bv_model_rebalance = self.model_data[IS_BV_MODEL_REBAL]

    def apply_karaoke_metadata(self, config_yaml: str = "") -> None:
        """Set ``is_karaoke``/``is_karaoke_curated`` from hash JSON and
        catalogue/config name hints."""
        self.check_if_karaokee_model()
        if getattr(self, "is_karaoke_curated", False):
            return
        weight_basename = getattr(self, "model_basename", None)
        if not weight_basename:
            model_path = getattr(self, "model_path", None) or ""
            if model_path:
                weight_basename = os.path.splitext(os.path.basename(model_path))[0]
        is_karaoke, is_curated = resolve_karaoke_confidence(
            model_data=self.model_data,
            model_name=str(self.model_name or ""),
            config_yaml=config_yaml,
            weight_basename=str(weight_basename or ""),
        )
        self.is_karaoke = is_karaoke
        self.is_karaoke_curated = is_curated

    def get_vr_model_path(self) -> None:
        artifacts = getattr(self, "model_artifacts", None)
        primary = (
            artifacts.primary_filename
            if artifacts is not None
            else getattr(self, "backend_name", self.model_name)
        )
        filename = primary if primary.casefold().endswith(".pth") else f"{primary}.pth"
        self.model_path = os.path.join(paths.VR_MODELS_DIR, filename)

    def get_mdx_model_path(self):
        artifacts = getattr(self, "model_artifacts", None)
        if artifacts is not None:
            filename = artifacts.primary_filename
            self.is_mdx_ckpt = filename.casefold().endswith(CKPT)
            self.model_path = os.path.join(paths.MDX_MODELS_DIR, filename)
        else:
            filename = getattr(self, "backend_name", self.model_name)
            for file_name, chosen_mdx_model in self.repo.mdx_name_select_MAPPER.items():
                if filename == file_name or self.model_name == chosen_mdx_model:
                    filename = file_name
                    break
            if filename.casefold().endswith(CKPT):
                self.is_mdx_ckpt = True
                self.model_path = os.path.join(paths.MDX_MODELS_DIR, filename)
                self.mixer_path = os.path.join(paths.MDX_MODELS_DIR, "mixer_val.ckpt")
                return
            if filename.casefold().endswith(ONNX):
                self.model_path = os.path.join(paths.MDX_MODELS_DIR, filename)
                self.mixer_path = os.path.join(paths.MDX_MODELS_DIR, "mixer_val.ckpt")
                return
            base_path = os.path.join(paths.MDX_MODELS_DIR, filename)
            ckpt_path = f"{base_path}{CKPT}"
            onnx_path = f"{base_path}{ONNX}"
            if os.path.isfile(ckpt_path):
                self.model_path = ckpt_path
                self.is_mdx_ckpt = True
            elif os.path.isfile(onnx_path):
                self.model_path = onnx_path
            else:
                self.model_path = onnx_path
        self.mixer_path = os.path.join(paths.MDX_MODELS_DIR, "mixer_val.ckpt")

    def get_demucs_model_path(self):
        record = getattr(self, "_identity_record", None)
        spec = record.demucs if record is not None else None
        demucs_version = spec.version if spec is not None else self.demucs_version
        demucs_newer = demucs_version in {DEMUCS_V3, DEMUCS_V4}
        demucs_model_dir = paths.DEMUCS_NEWER_REPO_DIR if demucs_newer else paths.DEMUCS_MODELS_DIR
        artifacts = getattr(self, "model_artifacts", None)
        if artifacts is not None:
            self.model_path = os.path.join(
                demucs_model_dir, artifacts.primary_filename
            )
            return
        backend_name = getattr(self, "backend_name", self.model_name)
        for file_name, display in self.repo.demucs_name_select_MAPPER.items():
            if backend_name in {file_name, os.path.splitext(file_name)[0]} or self.model_name == display:
                self.model_path = os.path.join(demucs_model_dir, file_name)
                return
        self.model_path = resolve_demucs_model_file(backend_name, demucs_version)

    def get_demucs_model_data(self):
        spec = self.demucs if getattr(self, "demucs", None) is not None else None
        if spec is None:
            raise ValueError(
                f"{self.canonical_id} is missing Demucs version/layout metadata"
            )
        self.demucs_version = {
            "v1": DEMUCS_V1,
            "v2": DEMUCS_V2,
            "v3": DEMUCS_V3,
            "v4": DEMUCS_V4,
        }[spec.version]
        if spec.source_layout == "2_stem":
            self.demucs_source_list, self.demucs_source_map, self.demucs_stem_count = (
                DEMUCS_2_SOURCE,
                DEMUCS_2_SOURCE_MAPPER,
                2,
            )
        elif spec.source_layout == "6_stem":
            self.demucs_source_list, self.demucs_source_map, self.demucs_stem_count = (
                DEMUCS_6_SOURCE,
                DEMUCS_6_SOURCE_MAPPER,
                6,
            )
        else:
            self.demucs_source_list, self.demucs_source_map, self.demucs_stem_count = (
                DEMUCS_4_SOURCE,
                DEMUCS_4_SOURCE_MAPPER,
                4,
            )
        if not self.is_ensemble_mode:
            self.primary_stem = PRIMARY_STEM if self.demucs_stems == ALL_STEMS else self.demucs_stems
            self.secondary_stem = secondary_stem(str(self.primary_stem or ""))

    def get_model_data(self, model_hash_dir: typing.Any, hash_mapper: dict):
        mapped = None
        for model_hash, model_settings in hash_mapper.items():
            if self.model_hash in model_hash:
                mapped = dict(model_settings)
                break

        model_settings_json = os.path.join(model_hash_dir, f"{self.model_hash}.json")
        if os.path.isfile(model_settings_json):
            with open(model_settings_json, "r") as json_file:
                local = json.load(json_file)
            if not isinstance(local, dict):
                local = {}
            if mapped:
                merged = dict(mapped)
                merged.update(local)
                return merged
            return local

        if mapped:
            return mapped

        if (
            self.process_method == MDX_ARCH_TYPE
            and self.is_mdx_ckpt
            and self.model_path
        ):
            params = try_register_from_catalog(self.model_path, self.model_hash)
            if params:
                return params

        return self.get_model_data_from_popup()

    def change_model_data(self):
        """Port of the legacy change-model-defaults flow."""
        if self.is_get_hash_dir_only:
            return None
        return self.get_model_data_from_popup()

    def get_model_data_from_popup(self):
        """Resolve unknown model parameters via the front-end hook.

        Dry checks never prompt, and the GTK layer installs
        :attr:`ModelRepository.on_unrecognized_model`
        to present the parameter dialog and persist the result.
        """
        if self.is_dry_check:
            return None
        if callable(self.repo.on_unrecognized_model):
            return self.repo.on_unrecognized_model(cast(Any, self))
        return None

    def get_model_hash(self) -> None:
        from ..model_hash_cache import is_stale, lookup_trusted, remember

        self.model_hash = None
        if not os.path.isfile(self.model_path):
            self.model_status = False
            return
        path = self.model_path
        cache = self.repo.model_hash_table
        trusted = lookup_trusted(self.settings.process.model_hash_table, path)
        if trusted:
            self.model_hash = trusted
            cache[path] = trusted
            return
        # Only the persistent table is stat-guarded. When it reports the file
        # changed, the unguarded in-memory copy below is stale by definition --
        # drop it, or a checkpoint replaced at the same path keeps resolving to
        # the previous model's params for the rest of the session.
        if is_stale(self.settings.process.model_hash_table, path):
            cache.pop(path, None)
        cached = cache.get(path)
        if cached:
            self.model_hash = cached
            return
        self.model_hash = compute_checkpoint_hash(path)
        if self.model_hash:
            cache[path] = self.model_hash
            remember(self.settings.process.model_hash_table, path, self.model_hash)

    def _sync_option_groups(self) -> None:
        """Snapshot flat compatibility attributes into typed option groups."""
        from .base import (
            DeviceOptions,
            EnsembleMemberFlags,
            ExportOptions,
            ModelIdentity,
            SecondaryChain,
            StemRouting,
        )
        from .demucs import DemucsOptions
        from .mdx import MDXOptions
        from .vr import VROptions

        self.identity = ModelIdentity(
            model_name=self.model_name,
            canonical_id=self.canonical_id,
            model_display_label=self.model_display_label,
            backend_name=self.backend_name,
            model_artifacts=self.model_artifacts,
            process_method=self.process_method,
            model_path=getattr(self, "model_path", None),
            model_basename=self.model_basename,
            model_hash=getattr(self, "model_hash", None),
            model_status=bool(self.model_status),
            model_and_process_tag=getattr(self, "model_and_process_tag", None),
        )
        self.export_options = ExportOptions(
            wav_type_set=self.wav_type_set,
            mp3_bit_set=self.mp3_bit_set,
            flac_bit_set=self.flac_bit_set,
            save_format=self.save_format,
            is_normalization=bool(self.is_normalization),
            is_match_mix_level=bool(self.is_match_mix_level),
            is_prevent_export_clipping=bool(self.is_prevent_export_clipping),
            amplification_threshold=self.amplification_threshold,
        )
        self.device_options = DeviceOptions(
            use_gpu=bool(self.use_gpu),
            device_set=self.device_set,
            is_use_directml=bool(self.is_use_directml),
        )
        self.ensemble_flags = EnsembleMemberFlags(
            is_ensemble_mode=bool(self.is_ensemble_mode),
            is_4_stem_ensemble=bool(self.is_4_stem_ensemble),
            is_multi_stem_ensemble=bool(self.is_multi_stem_ensemble),
            ensemble_primary_stem=self.ensemble_primary_stem,
            ensemble_secondary_stem=self.ensemble_secondary_stem,
        )
        self.stem_routing = StemRouting(
            primary_stem=self.primary_stem,
            secondary_stem=self.secondary_stem,
            primary_stem_native=self.primary_stem_native,
            primary_model_primary_stem=self.primary_model_primary_stem,
            mdx_model_stems=tuple(self.mdx_model_stems),
            demucs_source_list=tuple(self.demucs_source_list),
            available_routes=tuple(
                getattr(self, "available_stem_routes", ())
            ),
            selected_routes=tuple(
                getattr(self, "selected_stem_routes", ())
            ),
            semantics=self.stem_semantics,
        )
        self.secondary_chain = SecondaryChain(
            secondary_model=self.secondary_model,
            secondary_model_scale=self.secondary_model_scale,
            secondary_model_4_stem=tuple(self.secondary_model_4_stem),
            secondary_model_4_stem_scale=tuple(self.secondary_model_4_stem_scale),
            pre_proc_model=self.pre_proc_model,
            vocal_split_model=self.vocal_split_model,
            is_secondary_model_activated=bool(self.is_secondary_model_activated),
            pre_proc_model_activated=bool(self.pre_proc_model_activated),
            is_vocal_split_model_activated=bool(
                self.is_vocal_split_model_activated
            ),
        )
        self.vr_options = (
            VROptions(
                aggression_setting=self.aggression_setting,
                is_tta=bool(self.is_tta),
                is_post_process=bool(self.is_post_process),
                window_size=self.window_size,
                batch_size=self.batch_size,
                crop_size=self.crop_size,
                is_high_end_process=self.is_high_end_process,
                post_process_threshold=self.post_process_threshold,
                model_capacity=self.model_capacity,
                model_samplerate=self.model_samplerate,
                vr_model_param=getattr(self, "vr_model_param", None),
                is_vr_51_model=bool(self.is_vr_51_model),
            )
            if self.process_method == VR_ARCH_TYPE
            else None
        )
        self.mdx_options = (
            MDXOptions(
                margin=self.margin,
                chunks=self.chunks,
                mdx_segment_size=self.mdx_segment_size,
                mdx_batch_size=self.mdx_batch_size,
                mdxnet_stem_select=self.mdxnet_stem_select,
                mdxnet_stems_selected=tuple(self.mdxnet_stems_selected),
                overlap_mdx=self.overlap_mdx,
                overlap_mdx23=self.overlap_mdx23,
                is_mdx_ckpt=bool(self.is_mdx_ckpt),
                is_mdx_c=bool(self.is_mdx_c),
                is_roformer=bool(self.is_roformer),
                is_target_instrument=bool(self.is_target_instrument),
                model_type=self.model_type,
                mdx_c_configs=self.mdx_c_configs,
                mdx_model_stems=tuple(self.mdx_model_stems),
                mdx_stem_count=self.mdx_stem_count,
                compensate=self.compensate,
                mdx_dim_f_set=self.mdx_dim_f_set,
                mdx_dim_t_set=self.mdx_dim_t_set,
                mdx_n_fft_scale_set=self.mdx_n_fft_scale_set,
            )
            if self.process_method == MDX_ARCH_TYPE
            else None
        )
        self.demucs_options = (
            DemucsOptions(
                shifts=self.shifts,
                is_split_mode=bool(self.is_split_mode),
                segment=self.segment,
                demucs_stems=self.demucs_stems,
                is_demucs_combine_stems=bool(self.is_demucs_combine_stems),
                demucs_source_list=tuple(self.demucs_source_list),
                demucs_source_map=getattr(self, "demucs_source_map", None),
                demucs_stem_count=self.demucs_stem_count,
                demucs_version=getattr(self, "demucs_version", None),
            )
            if self.process_method == DEMUCS_ARCH_TYPE
            else None
        )
