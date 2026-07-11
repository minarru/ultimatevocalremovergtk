"""Tk-free port of ``UVR.py``'s ``ModelData`` / ``assemble_model_data``.

This rebuilds the per-run model configuration that the ``separate.py`` engines
consume, but reads every value from a :class:`~core.settings.SettingsModel`
instead of Tkinter variables and the root window. The MD5 model-discovery logic
is preserved verbatim.

The **primary single-model** path for all four architectures (VR, MDX-Net,
MDX-C, Demucs) plus the secondary-model, vocal-splitter and Demucs pre-process
machinery is fully ported. Ensemble assembly (``ENSEMBLE_MODE`` /
``ENSEMBLE_CHECK``, the ensemble main-stem pairing and the saved-ensemble JSON
store) is ported here too; the combination of the per-model outputs is performed
by the ``Ensembler`` in :mod:`core.job_runner`. Nothing here imports
``tkinter``.
"""

import json
import os
from typing import Any, Callable, Dict, List, Optional

from bundled.constants import *  # noqa: F401,F403 - mirrors UVR.py's flat constant namespace

from . import paths
from .mdx_config_fetch import ensure_mdx_c_config
from .mdx_c_registry import compute_checkpoint_hash, display_name_for_basename, resolve_mdx_model_basename, try_register_from_catalog
from .audio_io import resolve_wav_type_set
from .settings import SettingsModel

_MDX_C_YAML_LOADER = None


def load_mdx_c_config(path: str) -> dict:
    """Load a bundled MDX-C / Roformer yaml config.

    Shipped configs use ``!!python/tuple`` for a few list fields; this extends
    :class:`yaml.SafeLoader` with only that tag so we avoid ``FullLoader`` while
    still parsing the trusted local files under ``mdx_c_configs/``.
    """
    import yaml

    global _MDX_C_YAML_LOADER
    if _MDX_C_YAML_LOADER is None:

        class MdxCYamlLoader(yaml.SafeLoader):
            pass

        def _construct_python_tuple(loader, node):
            return tuple(loader.construct_sequence(node))

        yaml.add_constructor(
            "tag:yaml.org,2002:python/tuple",
            _construct_python_tuple,
            Loader=MdxCYamlLoader,
        )
        _MDX_C_YAML_LOADER = MdxCYamlLoader

    with open(path) as config_file:
        return yaml.load(config_file, Loader=_MDX_C_YAML_LOADER)


def _mdx_c_training(config) -> Any:
    """Return the ``training`` section from an MDX-C yaml config object."""
    training = getattr(config, "training", None)
    if training is None and isinstance(config, dict):
        training = config.get("training")
    return training


def load_model_hash_data(dictionary: str) -> dict:
    """Load one of the model-data / name-mapper JSON files."""
    with open(dictionary, "r") as d:
        return json.load(d)


class ModelRepository:
    """Holds the model-data mappers and the path->hash cache.

    Mirrors the ``vr_hash_MAPPER`` / ``mdx_hash_MAPPER`` / ``*_name_select_MAPPER``
    attributes and the ``model_hash_table`` that live on ``MainWindow``. Created
    once and shared by every :class:`ModelData` built for a run.
    """

    def __init__(self):
        self.vr_hash_MAPPER: dict = {}
        self.mdx_hash_MAPPER: dict = {}
        self.mdx_name_select_MAPPER: dict = {}
        self.demucs_name_select_MAPPER: dict = {}
        self.model_hash_table: Dict[str, str] = {}
        # Phase 3 hook: later phases set this to a callable that prompts the user
        # for parameters of an unrecognized model. Returning ``None`` (the
        # default) simply marks such models as unavailable.
        self.on_unrecognized_model: Optional[Callable[["ModelData"], Any]] = None
        self._stem_check_cache = None
        self.reload_mappers()

    def reload_mappers(self) -> None:
        from .debug_log import debug

        debug("model", "reload_mappers")
        for attr, path in (
            ("vr_hash_MAPPER", paths.VR_HASH_JSON),
            ("mdx_hash_MAPPER", paths.MDX_HASH_JSON),
            ("mdx_name_select_MAPPER", paths.MDX_MODEL_NAME_SELECT),
            ("demucs_name_select_MAPPER", paths.DEMUCS_MODEL_NAME_SELECT),
        ):
            try:
                setattr(self, attr, load_model_hash_data(path))
            except (FileNotFoundError, ValueError):
                setattr(self, attr, {})

    def list_vr_models(self) -> List[str]:
        return _list_models(paths.VR_MODELS_DIR, (".pth",))

    def list_mdx_models(self) -> List[str]:
        return _list_models(paths.MDX_MODELS_DIR, (".onnx", ".ckpt"))

    def list_demucs_models(self) -> List[str]:
        models: List[str] = []
        for directory in (paths.DEMUCS_NEWER_REPO_DIR, paths.DEMUCS_MODELS_DIR):
            models.extend(_list_models(directory, (".th", ".ckpt", ".yaml", ".gz")))
        seen, unique = set(), []
        for name in models:
            if name not in seen:
                seen.add(name)
                unique.append(name)
        return unique

    # -- Model tags / stem filtering (ported from UVR's model menus) -----------

    def list_vr_model_tags(self) -> List[str]:
        names = sorted(self.list_vr_models())
        return [f"{VR_ARCH_TYPE}{ENSEMBLE_PARTITION}{name}" for name in names]

    def list_mdx_model_tags(self) -> List[str]:
        catalogue_names = self.mdx_catalogue_display_index()
        names = sorted(
            display_name_for_basename(
                name,
                self.mdx_name_select_MAPPER,
                catalogue_index=catalogue_names,
            )
            for name in self.list_mdx_models()
        )
        return [f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}{name}" for name in names]

    def mdx_catalogue_display_index(self) -> Dict[str, str]:
        from .mdx_c_registry import load_mdx_catalog_display_index

        return load_mdx_catalog_display_index()

    def list_demucs_model_tags(self) -> List[str]:
        names = sorted(_apply_name_mapper(self.list_demucs_models(), self.demucs_name_select_MAPPER))
        return [f"{DEMUCS_ARCH_TYPE}{ENSEMBLE_PARTITION}{name}" for name in names]

    def all_model_tags(self) -> List[str]:
        return self.list_vr_model_tags() + self.list_mdx_model_tags() + self.list_demucs_model_tags()

    def default_change_model_tags(self) -> List[str]:
        """VR + MDX model tags - the pool UVR exposes in change-model-defaults."""
        return self.list_vr_model_tags() + self.list_mdx_model_tags()

    def stem_check(self, settings: "SettingsModel") -> List["ModelData"]:
        """Build a (cached) dry-check ``ModelData`` for every discovered model.

        Equivalent to ``assemble_model_data(arch_type=ENSEMBLE_STEM_CHECK)``;
        each model's hash/params are resolved so callers can filter by stem. The
        result is cached against the current model set so the (file-hashing) work
        only happens once per change.
        """
        tags = tuple(self.all_model_tags())
        if self._stem_check_cache is not None and self._stem_check_cache[0] == tags:
            return self._stem_check_cache[1]
        model_data: List[ModelData] = [
            ModelData(settings, self, tag, is_dry_check=True) for tag in tags
        ]
        self._stem_check_cache = (tags, model_data)
        return model_data

    def invalidate_stem_check(self) -> None:
        from .debug_log import debug

        debug("model", "invalidate_stem_check")
        self._stem_check_cache = None

    def model_list(
        self,
        settings: "SettingsModel",
        primary_stem: str,
        secondary_stem: str,
        is_4_stem_check: bool = False,
        is_no_demucs: bool = False,
    ) -> List[str]:
        """Tk-free port of ``MainWindow.model_list`` (secondary-model filtering)."""
        stem_check = self.stem_check(settings)

        def matches_stem(model: "ModelData") -> bool:
            primary_match = model.primary_stem in {primary_stem, secondary_stem}
            mdx_stem_match = primary_stem in model.mdx_model_stems and model.mdx_stem_count <= 2
            return (primary_match or mdx_stem_match) if is_no_demucs else (primary_match or primary_stem in model.mdx_model_stems)

        result: List[str] = []
        for model in stem_check:
            if is_4_stem_check and (model.demucs_stem_count == 4 or model.mdx_stem_count == 4):
                result.append(model.model_and_process_tag)
            elif matches_stem(model) or (not is_no_demucs and primary_stem.lower() in model.demucs_source_list):
                result.append(model.model_and_process_tag)
        return result

    def karaoke_model_list(self, settings: "SettingsModel") -> List[str]:
        """Port of ``assemble_model_data(arch_type=KARAOKEE_CHECK)`` - vocal-split pool."""
        model_list: List[str] = []
        for tag in self.default_change_model_tags():
            model = ModelData(settings, self, tag, is_dry_check=True)
            if model.model_status and (model.is_karaoke or model.is_bv_model):
                model_list.append(model.model_and_process_tag)
        return model_list

    def ensemble_model_list(self, settings: "SettingsModel", ensemble_main_stem: str) -> List[str]:
        """Models compatible with the chosen ensemble main-stem pair.

        Port of ``selection_action_ensemble_stems``'s call to ``model_list``:
        a specific pair filters to models that produce that stem; the 4-stem
        ensemble keeps only 4-source models; the multi-stem ensemble keeps every
        model. Returns the ``"<arch>: <model>"`` tags used as ensemble members.
        """
        if ensemble_main_stem in (CHOOSE_STEM_PAIR, "", None):
            return []
        if ensemble_main_stem == MULTI_STEM_ENSEMBLE:
            return [model.model_and_process_tag for model in self.stem_check(settings)]
        if ensemble_main_stem == FOUR_STEM_ENSEMBLE:
            return self.model_list(settings, PRIMARY_STEM, SECONDARY_STEM, is_4_stem_check=True)
        stems = ensemble_main_stem.partition("/")
        return self.model_list(settings, stems[0], stems[2])

    def resolve_model_dry(self, settings: "SettingsModel", process_method: str, model_name: str):
        """Resolve ``model_name`` to a dry-check :class:`ModelData` (or ``None``).

        Lets the UI inspect a selected model (its stems, MDX-C type, ...) without
        committing to a run. Returns ``None`` when the model can't be resolved
        without prompting. Callers reuse the single returned object instead of
        rebuilding ``ModelData`` (which hashes the model file) more than once.
        """
        try:
            return ModelData(settings, self, model_name, process_method, is_dry_check=True)
        except (FileNotFoundError, ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
            from .debug_log import debug

            debug("model", f"resolve_model_dry failed model={model_name!r} error={type(exc).__name__}: {exc}")
            return None

    def stem_labels_for_model(self, settings: "SettingsModel", process_method: str, model_name: str):
        """Return ``(primary_stem, secondary_stem)`` for the selected model.

        Used to label the per-model stem-only toggles; returns ``(None, None)``
        when the model can't be resolved without prompting.
        """
        model = self.resolve_model_dry(settings, process_method, model_name)
        if model is None:
            return None, None
        return model.primary_stem, model.secondary_stem


def _apply_name_mapper(names, name_mapper) -> List[str]:
    """Map on-disk file names to display names (UVR's ``fix_name``)."""
    if not name_mapper:
        return list(names)
    mapped = []
    for name in names:
        replacement = next(
            (new_name for old_name, new_name in name_mapper.items() if name in old_name),
            name,
        )
        mapped.append(replacement)
    return mapped


def _list_models(directory: str, extensions) -> List[str]:
    if not os.path.isdir(directory):
        return []
    names = []
    for entry in os.listdir(directory):
        full = os.path.join(directory, entry)
        if os.path.isfile(full) and entry.lower().endswith(tuple(extensions)):
            names.append(os.path.splitext(entry)[0])
    return sorted(names)


class ModelData:
    """Tk-free equivalent of ``UVR.py``'s ``ModelData`` for a single model."""

    def __init__(
        self,
        settings: SettingsModel,
        repo: ModelRepository,
        model_name: str,
        selected_process_method: str = ENSEMBLE_MODE,
        is_secondary_model: bool = False,
        primary_model_primary_stem: Optional[str] = None,
        is_primary_model_primary_stem_only: bool = False,
        is_primary_model_secondary_stem_only: bool = False,
        is_pre_proc_model: bool = False,
        is_dry_check: bool = False,
        is_change_def: bool = False,
        is_get_hash_dir_only: bool = False,
        is_vocal_split_model: bool = False,
    ):
        self.settings = settings
        self.repo = repo

        device_set = settings.get("device_set")
        self.DENOISER_MODEL = paths.DENOISER_MODEL_PATH
        self.DEVERBER_MODEL = paths.DEVERBER_MODEL_PATH
        self.is_deverb_vocals = settings.get("is_deverb_vocals") if os.path.isfile(paths.DEVERBER_MODEL_PATH) else False
        self.deverb_vocal_opt = DEVERB_MAPPER[settings.get("deverb_vocal_opt")]
        self.is_denoise_model = True if settings.get("denoise_option") == DENOISE_M and os.path.isfile(paths.DENOISER_MODEL_PATH) else False
        self.is_gpu_conversion = 0 if settings.get("is_gpu_conversion") else -1
        self.is_normalization = settings.get("is_normalization")
        self.is_use_directml = bool(settings.get("is_use_directml"))
        self.is_primary_stem_only = settings.get("is_primary_stem_only")
        self.is_secondary_stem_only = settings.get("is_secondary_stem_only")
        self.is_denoise = True if settings.get("denoise_option") != DENOISE_NONE else False
        self.is_mdx_c_seg_def = settings.get("is_mdx_c_seg_def")
        self.mdx_batch_size = 1 if settings.get("mdx_batch_size") == DEF_OPT else int(settings.get("mdx_batch_size"))
        self.mdxnet_stem_select = settings.get("mdx_stems")
        self.mdxnet_stems_selected = settings.get("mdx_stems_selected") or []
        self.overlap = float(settings.get("overlap")) if settings.get("overlap") != DEFAULT else 0.25
        overlap_mdx_val = settings.get("overlap_mdx")
        self.overlap_mdx = float(overlap_mdx_val) if overlap_mdx_val != DEFAULT else 0.25
        self.overlap_mdx23 = int(float(settings.get("overlap_mdx23")))
        self.semitone_shift = float(settings.get("semitone_shift"))
        self.is_pitch_change = False if self.semitone_shift == 0 else True
        self.is_match_frequency_pitch = settings.get("is_match_frequency_pitch")
        self.is_mdx_ckpt = False
        self.is_mdx_c = False
        # Roformer models are MDX-C-style nets selected by their yaml config
        # (``is_roformer`` in the model-data JSON); ``is_target_instrument`` marks
        # a config that defines a single ``training.target_instrument``.
        self.is_roformer = False
        self.is_target_instrument = False
        self.model_type = ""
        self.is_mdx_combine_stems = settings.get("is_mdx23_combine_stems")
        self.is_mdx_include_stem_complement = settings.get("is_mdx_include_stem_complement")
        self.mdx_c_configs = None
        self.mdx_model_stems = []
        self.mdx_dim_f_set = None
        self.mdx_dim_t_set = None
        self.mdx_stem_count = 1
        self.compensate = None
        self.mdx_n_fft_scale_set = None
        self.wav_type_set = resolve_wav_type_set(settings)
        self.device_set = device_set.split(":")[-1].strip() if ":" in device_set else device_set
        self.mp3_bit_set = settings.get("mp3_bit_set")
        self.flac_bit_set = settings.get("flac_bit_set", "16-bit")
        self.save_format = settings.get("save_format")
        self.is_invert_spec = settings.get("is_invert_spec")
        self.is_mixer_mode = False
        self.demucs_stems = settings.get("demucs_stems")
        self.is_demucs_combine_stems = settings.get("is_demucs_combine_stems")
        self.demucs_source_list = []
        self.demucs_stem_count = 0
        self.mixer_path = paths.MDX_MIXER_PATH
        self.model_name = model_name
        self.process_method = selected_process_method
        self.model_status = False if self.model_name == CHOOSE_MODEL or self.model_name == NO_MODEL else True
        self.primary_stem = None
        self.secondary_stem = None
        self.primary_stem_native = None
        self.is_ensemble_mode = False
        self.ensemble_primary_stem = None
        self.ensemble_secondary_stem = None
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
        self.model_samplerate = 44100
        self.model_capacity = 32, 128
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
        self.is_save_inst_vocal_splitter = settings.get("is_save_inst_set_vocal_splitter")
        # Computed at the end of __init__ once the primary/secondary stems are
        # resolved (UVR reads them from the live stem-only labels instead).
        self.is_inst_only_voc_splitter = False
        self.is_save_vocal_only = False
        self._is_secondary_model_param = is_secondary_model

        if selected_process_method == ENSEMBLE_MODE:
            # The ensemble member tag is ``"<arch>: <model name>"``; split it back
            # into the member's real process method + model name (UVR L553-567).
            self.process_method, _, self.model_name = model_name.partition(ENSEMBLE_PARTITION)
            self.model_and_process_tag = model_name
            self.ensemble_primary_stem, self.ensemble_secondary_stem = self.return_ensemble_stems()
            is_not_secondary_or_pre_proc = not is_secondary_model and not is_pre_proc_model
            self.is_ensemble_mode = is_not_secondary_or_pre_proc

            ensemble_main_stem = settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR)
            if ensemble_main_stem == FOUR_STEM_ENSEMBLE:
                self.is_4_stem_ensemble = self.is_ensemble_mode
            elif ensemble_main_stem == MULTI_STEM_ENSEMBLE and settings.get("chosen_process_method") == ENSEMBLE_MODE:
                self.is_multi_stem_ensemble = True

            is_not_vocal_stem = self.ensemble_primary_stem != VOCAL_STEM
            self.pre_proc_model_activated = settings.get("is_demucs_pre_proc_model_activate") if is_not_vocal_stem else False

        if self.process_method == VR_ARCH_TYPE:
            self.is_secondary_model_activated = settings.get("vr_is_secondary_model_activate") if not is_secondary_model else False
            self.aggression_setting = float(int(settings.get("aggression_setting")) / 100)
            self.is_tta = settings.get("is_tta")
            self.is_post_process = settings.get("is_post_process")
            self.window_size = int(settings.get("window_size"))
            self.batch_size = 1 if settings.get("batch_size") == DEF_OPT else int(settings.get("batch_size"))
            self.crop_size = int(settings.get("crop_size"))
            self.is_high_end_process = "mirroring" if settings.get("is_high_end_process") else "None"
            self.post_process_threshold = float(settings.get("post_process_threshold"))
            self.model_capacity = 32, 128
            self.model_path = os.path.join(paths.VR_MODELS_DIR, f"{self.model_name}.pth")
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
            self.is_secondary_model_activated = settings.get("mdx_is_secondary_model_activate") if not is_secondary_model else False
            self.margin = int(settings.get("margin"))
            self.chunks = 0
            self.mdx_segment_size = int(settings.get("mdx_segment_size"))
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
                                from .debug_log import debug

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
                                    self.primary_stem = target
                                    if self.is_roformer and self.is_ensemble_mode and target in (VOCAL_STEM, INST_STEM):
                                        self.mdxnet_stem_select = self.ensemble_primary_stem
                                elif training is not None:
                                    instruments = getattr(training, "instruments", None) or []
                                    self.mdx_model_stems = list(instruments)
                                    self.mdx_stem_count = len(self.mdx_model_stems)
                                    if self.mdx_stem_count == 2:
                                        self.primary_stem = self.mdx_model_stems[0]
                                    else:
                                        self.primary_stem = self.mdxnet_stem_select
                                    if self.is_ensemble_mode:
                                        self.mdxnet_stem_select = self.ensemble_primary_stem
                        else:
                            self.model_status = False
                    else:
                        self.compensate = self.model_data["compensate"] if settings.get("compensate") == AUTO_SELECT else float(settings.get("compensate"))
                        self.mdx_dim_f_set = self.model_data["mdx_dim_f_set"]
                        self.mdx_dim_t_set = self.model_data["mdx_dim_t_set"]
                        self.mdx_n_fft_scale_set = self.model_data["mdx_n_fft_scale_set"]
                        self.primary_stem = self.model_data["primary_stem"]
                        self.primary_stem_native = self.model_data["primary_stem"]
                        self.check_if_karaokee_model()
                    self.secondary_stem = secondary_stem(str(self.primary_stem or ""))
                else:
                    self.model_status = False

        if self.process_method == DEMUCS_ARCH_TYPE:
            self.is_secondary_model_activated = settings.get("demucs_is_secondary_model_activate") if not is_secondary_model else False
            if not self.is_ensemble_mode:
                self.pre_proc_model_activated = settings.get("is_demucs_pre_proc_model_activate") if settings.get("demucs_stems") not in [VOCAL_STEM, INST_STEM] else False
            self.margin_demucs = int(settings.get("margin_demucs"))
            self.chunks_demucs = 0
            self.shifts = int(settings.get("shifts"))
            self.is_split_mode = settings.get("is_split_mode")
            self.segment = settings.get("segment")
            self.is_chunk_demucs = settings.get("is_chunk_demucs")
            self.is_primary_stem_only = settings.get("is_primary_stem_only") if self.is_ensemble_mode else settings.get("is_primary_stem_only_Demucs")
            self.is_secondary_stem_only = settings.get("is_secondary_stem_only") if self.is_ensemble_mode else settings.get("is_secondary_stem_only_Demucs")
            self.get_demucs_model_data()
            self.get_demucs_model_path()

        if self.model_status:
            self.model_basename = os.path.splitext(os.path.basename(self.model_path))[0]
        else:
            self.model_basename = None

        self.pre_proc_model_activated = self.pre_proc_model_activated if not self.is_secondary_model else False

        self.is_primary_model_primary_stem_only = is_primary_model_primary_stem_only
        self.is_primary_model_secondary_stem_only = is_primary_model_secondary_stem_only

        # -- Secondary model resolution (ported from UVR.py L686-L715) ----------
        is_secondary_activated_and_status = self.is_secondary_model_activated and self.model_status
        is_demucs = self.process_method == DEMUCS_ARCH_TYPE
        is_all_stems = settings.get("demucs_stems") == ALL_STEMS
        is_valid_ensemble = not self.is_ensemble_mode and is_all_stems and is_demucs
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
                    self.secondary_model_4_stem_model_names_list = [i.model_basename if i is not None else None for i in self.secondary_model_4_stem]
                    self.is_demucs_4_stem_secondaries = True
            else:
                primary_stem = self.ensemble_primary_stem if self.is_ensemble_mode and is_demucs else self.primary_stem
                self.secondary_model_data(primary_stem)

        if self.process_method == DEMUCS_ARCH_TYPE and not is_secondary_model:
            if self.demucs_stem_count >= 3 and self.pre_proc_model_activated:
                self.pre_proc_model = process_determine_demucs_pre_proc_model(self.settings, self.repo, self.primary_stem)
                self.pre_proc_model_activated = True if self.pre_proc_model else False
                self.is_demucs_pre_proc_model_inst_mix = settings.get("is_demucs_pre_proc_model_inst_mix") if self.pre_proc_model else False

        if self.is_vocal_split_model and self.model_status:
            self.is_secondary_model_activated = False
            if self.is_bv_model:
                primary = BV_VOCAL_STEM if self.primary_stem_native == VOCAL_STEM else LEAD_VOCAL_STEM
            else:
                primary = LEAD_VOCAL_STEM if self.primary_stem_native == VOCAL_STEM else BV_VOCAL_STEM
            self.primary_stem, self.secondary_stem = primary, secondary_stem(primary)

        # Derive the vocal-splitter "save only" flags now that stems are known.
        self.is_inst_only_voc_splitter = self.check_only_selection_stem(INST_STEM_ONLY)
        self.is_save_vocal_only = self.check_only_selection_stem(IS_SAVE_VOC_ONLY)

        self.vocal_splitter_model_data()

    # -- Secondary / vocal-split / pre-process resolution -----------------------
    # Faithful Tk-free ports of ``MainWindow.process_determine_*`` /
    # ``vocal_splitter_model_data`` / ``secondary_model_data`` reading the same
    # ``DEFAULT_DATA`` settings keys instead of Tk variables.

    def vocal_splitter_model_data(self):
        self.vocal_split_model = None
        self.is_vocal_split_model_activated = False
        if not self.is_secondary_model and self.model_status:
            self.vocal_split_model = process_determine_vocal_split_model(self.settings, self.repo)
            self.is_vocal_split_model_activated = True if self.vocal_split_model else False
            if self.vocal_split_model and self.vocal_split_model.bv_model_rebalance:
                self.is_sec_bv_rebalance = True

    def secondary_model_data(self, primary_stem):
        secondary_model, secondary_model_scale = process_determine_secondary_model(
            self.settings,
            self.repo,
            self.process_method,
            primary_stem,
            self.is_primary_stem_only,
            self.is_secondary_stem_only,
        )
        self.secondary_model = secondary_model
        self.secondary_model_scale = secondary_model_scale
        self.is_secondary_model_activated = False if not secondary_model else True
        if self.secondary_model:
            self.is_secondary_model_activated = False if self.secondary_model.model_basename == self.model_basename else True

    def return_ensemble_stems(self, is_primary=False):
        """Port of ``MainWindow.return_ensemble_stems``.

        Splits the chosen ensemble main-stem pair (e.g. ``"Vocals/Instrumental"``)
        into its primary/secondary halves, reading the value from the settings
        model instead of ``ensemble_main_stem_var``.
        """
        ensemble_stem = self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR).partition("/")
        if is_primary:
            return ensemble_stem[0]
        return ensemble_stem[0], ensemble_stem[2]

    def check_only_selection_stem(self, checktype):
        """Port of ``MainWindow.check_only_selection_stem``.

        UVR reads the live stem-only checkbox labels (set by
        ``update_stem_checkbox_labels`` to ``f"{stem} Only"``); the Tk-free port
        derives the same labels from the model's resolved primary/secondary
        stems instead.
        """
        chosen_method = self.settings.get("chosen_process_method")
        is_demucs = chosen_method == DEMUCS_ARCH_TYPE

        # In ensemble mode the stem-only labels follow the chosen ensemble pair
        # (UVR's ``update_stem_checkbox_labels``), not the member model's stems.
        if chosen_method == ENSEMBLE_MODE:
            primary_for_label = self.ensemble_primary_stem
            secondary_for_label = self.ensemble_secondary_stem
        else:
            primary_for_label = self.primary_stem
            secondary_for_label = self.secondary_stem

        stem_primary_label = f"{primary_for_label} Only" if primary_for_label else ""
        stem_secondary_label = f"{secondary_for_label} Only" if secondary_for_label else ""
        if is_demucs:
            stem_primary_bool = self.settings.get("is_primary_stem_only_Demucs")
            stem_secondary_bool = self.settings.get("is_secondary_stem_only_Demucs")
        else:
            stem_primary_bool = self.settings.get("is_primary_stem_only")
            stem_secondary_bool = self.settings.get("is_secondary_stem_only")

        is_save_inst_splitter = self.settings.get("is_save_inst_set_vocal_splitter")
        has_voc_splitter = self.settings.get("set_vocal_splitter") != NO_MODEL

        if checktype == VOCAL_STEM_ONLY:
            return not (
                (not VOCAL_STEM_ONLY == stem_primary_label and stem_primary_bool) or
                (not VOCAL_STEM_ONLY in stem_secondary_label and stem_secondary_bool)
            )
        elif checktype == INST_STEM_ONLY:
            return (
                (INST_STEM_ONLY == stem_primary_label and stem_primary_bool and is_save_inst_splitter and has_voc_splitter) or
                (INST_STEM_ONLY == stem_secondary_label and stem_secondary_bool and is_save_inst_splitter and has_voc_splitter)
            )
        elif checktype == IS_SAVE_VOC_ONLY:
            return (
                (VOCAL_STEM_ONLY == stem_primary_label and stem_primary_bool) or
                (VOCAL_STEM_ONLY == stem_secondary_label and stem_secondary_bool)
            )
        elif checktype == IS_SAVE_INST_ONLY:
            return (
                (INST_STEM_ONLY == stem_primary_label and stem_primary_bool) or
                (INST_STEM_ONLY == stem_secondary_label and stem_secondary_bool)
            )
        return False

    def check_if_karaokee_model(self):
        if not self.model_data:
            return
        if IS_KARAOKEE in self.model_data.keys():
            self.is_karaoke = self.model_data[IS_KARAOKEE]
        if IS_BV_MODEL in self.model_data.keys():
            self.is_bv_model = self.model_data[IS_BV_MODEL]
        if IS_BV_MODEL_REBAL in self.model_data.keys() and self.is_bv_model:
            self.bv_model_rebalance = self.model_data[IS_BV_MODEL_REBAL]

    def get_mdx_model_path(self):
        resolved_name = resolve_mdx_model_basename(
            self.model_name,
            self.repo.mdx_name_select_MAPPER,
            catalogue_index=self.repo.mdx_catalogue_display_index(),
        )
        if resolved_name.endswith(CKPT):
            self.is_mdx_ckpt = True
        ext = "" if self.is_mdx_ckpt else ONNX
        for file_name, chosen_mdx_model in self.repo.mdx_name_select_MAPPER.items():
            if resolved_name in file_name or self.model_name in chosen_mdx_model:
                if file_name.endswith(CKPT):
                    ext = ""
                    self.is_mdx_ckpt = True
                self.model_path = os.path.join(paths.MDX_MODELS_DIR, f"{file_name}{ext}")
                break
        else:
            base_path = os.path.join(paths.MDX_MODELS_DIR, resolved_name)
            ckpt_path = f"{base_path}{CKPT}"
            onnx_path = f"{base_path}{ONNX}"
            if os.path.isfile(ckpt_path):
                self.model_path = ckpt_path
                self.is_mdx_ckpt = True
            elif os.path.isfile(onnx_path):
                self.model_path = onnx_path
            else:
                self.model_path = f"{base_path}{ext}"
        self.mixer_path = os.path.join(paths.MDX_MODELS_DIR, "mixer_val.ckpt")

    def get_demucs_model_path(self):
        demucs_newer = self.demucs_version in {DEMUCS_V3, DEMUCS_V4}
        demucs_model_dir = paths.DEMUCS_NEWER_REPO_DIR if demucs_newer else paths.DEMUCS_MODELS_DIR
        for file_name, chosen_model in self.repo.demucs_name_select_MAPPER.items():
            if self.model_name == chosen_model:
                self.model_path = os.path.join(demucs_model_dir, file_name)
                break
        else:
            self.model_path = os.path.join(paths.DEMUCS_NEWER_REPO_DIR, f"{self.model_name}.yaml")

    def get_demucs_model_data(self):
        self.demucs_version = DEMUCS_V4
        for key, value in DEMUCS_VERSION_MAPPER.items():
            if value in self.model_name:
                self.demucs_version = key
        if DEMUCS_UVR_MODEL in self.model_name:
            self.demucs_source_list, self.demucs_source_map, self.demucs_stem_count = DEMUCS_2_SOURCE, DEMUCS_2_SOURCE_MAPPER, 2
        else:
            self.demucs_source_list, self.demucs_source_map, self.demucs_stem_count = DEMUCS_4_SOURCE, DEMUCS_4_SOURCE_MAPPER, 4
        if not self.is_ensemble_mode:
            self.primary_stem = PRIMARY_STEM if self.demucs_stems == ALL_STEMS else self.demucs_stems
            self.secondary_stem = secondary_stem(str(self.primary_stem or ""))

    def get_model_data(self, model_hash_dir, hash_mapper: dict):
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
        """Port of ``ModelData.change_model_data`` (change-model-defaults flow)."""
        if self.is_get_hash_dir_only:
            return None
        return self.get_model_data_from_popup()

    def get_model_data_from_popup(self):
        """Resolve unknown model parameters via the front-end hook.

        Mirrors ``ModelData.get_model_data_from_popup``: dry checks never prompt,
        and the GTK layer installs :attr:`ModelRepository.on_unrecognized_model`
        to present the parameter dialog and persist the result.
        """
        if self.is_dry_check:
            return None
        if callable(self.repo.on_unrecognized_model):
            return self.repo.on_unrecognized_model(self)
        return None

    def get_model_hash(self):
        self.model_hash = None
        if not os.path.isfile(self.model_path):
            self.model_status = False
            return
        cache = self.repo.model_hash_table
        if cache:
            for key, value in cache.items():
                if self.model_path == key:
                    self.model_hash = value
                    break
        if not self.model_hash:
            self.model_hash = compute_checkpoint_hash(self.model_path)
            if self.model_hash:
                cache.update({self.model_path: self.model_hash})


_SECONDARY_PREFIX_BY_METHOD = {
    VR_ARCH_TYPE: "vr",
    MDX_ARCH_TYPE: "mdx",
    DEMUCS_ARCH_TYPE: "demucs",
}


def _secondary_keys_for_stem(prefix: str, main_model_primary_stem: str):
    """Return the (model_key, scale_key) for a primary stem (UVR L6616-6627)."""
    if main_model_primary_stem in (VOCAL_STEM, INST_STEM):
        slot = "voc_inst"
    elif main_model_primary_stem in (OTHER_STEM, NO_OTHER_STEM):
        slot = "other"
    elif main_model_primary_stem in (DRUM_STEM, NO_DRUM_STEM):
        slot = "drums"
    elif main_model_primary_stem in (BASS_STEM, NO_BASS_STEM):
        slot = "bass"
    else:
        return None, None
    return f"{prefix}_{slot}_secondary_model", f"{prefix}_{slot}_secondary_model_scale"


def process_determine_secondary_model(
    settings: SettingsModel,
    repo: ModelRepository,
    process_method: str,
    main_model_primary_stem: str,
    is_primary_stem_only: bool = False,
    is_secondary_stem_only: bool = False,
):
    """Tk-free port of ``MainWindow.process_determine_secondary_model``."""
    prefix = _SECONDARY_PREFIX_BY_METHOD.get(process_method)
    if prefix is None:
        return None, None

    model_key, scale_key = _secondary_keys_for_stem(prefix, main_model_primary_stem)
    secondary_model_name = settings.get(model_key, NO_MODEL) if model_key else NO_MODEL
    secondary_model_scale = settings.get(scale_key) if scale_key else None
    if secondary_model_scale:
        secondary_model_scale = float(secondary_model_scale)

    secondary_model = None
    if secondary_model_name and secondary_model_name != NO_MODEL:
        secondary_model = ModelData(
            settings,
            repo,
            secondary_model_name,
            is_secondary_model=True,
            primary_model_primary_stem=main_model_primary_stem,
            is_primary_model_primary_stem_only=is_primary_stem_only,
            is_primary_model_secondary_stem_only=is_secondary_stem_only,
        )
        if not secondary_model.model_status:
            secondary_model = None

    return secondary_model, secondary_model_scale


def process_determine_demucs_pre_proc_model(settings: SettingsModel, repo: ModelRepository, primary_stem=None):
    """Tk-free port of ``MainWindow.process_determine_demucs_pre_proc_model``."""
    pre_proc_name = settings.get("demucs_pre_proc_model", NO_MODEL)
    if pre_proc_name != NO_MODEL and settings.get("is_demucs_pre_proc_model_activate"):
        pre_proc_model = ModelData(
            settings,
            repo,
            pre_proc_name,
            primary_model_primary_stem=primary_stem,
            is_pre_proc_model=True,
        )
        if pre_proc_model.model_status:
            return pre_proc_model
    return None


def process_determine_vocal_split_model(settings: SettingsModel, repo: ModelRepository):
    """Tk-free port of ``MainWindow.process_determine_vocal_split_model``."""
    split_name = settings.get("set_vocal_splitter", NO_MODEL)
    if split_name != NO_MODEL and settings.get("is_set_vocal_splitter"):
        vocal_splitter_model = ModelData(settings, repo, split_name, is_vocal_split_model=True)
        if vocal_splitter_model.model_status:
            return vocal_splitter_model
    return None


def assemble_model_data(
    settings: SettingsModel,
    repo: ModelRepository,
    model: Optional[str] = None,
    arch_type: str = ENSEMBLE_MODE,
) -> List[ModelData]:
    """Tk-free port of ``MainWindow.assemble_model_data`` (UVR.py L1687).

    Supports the single-model architectures (VR / MDX-Net / MDX-C / Demucs), the
    ensemble run (``ENSEMBLE_MODE`` builds one :class:`ModelData` per selected
    member) and the ensemble single-model check (``ENSEMBLE_CHECK``). The stem /
    karaoke dry-checks are served by :class:`ModelRepository` instead.
    """
    if arch_type == ENSEMBLE_MODE:
        selected = settings.get("selected_models") or []
        models = [ModelData(settings, repo, name) for name in selected]
        valid = [model for model in models if model.model_status]
        skipped = len(models) - len(valid)
        if skipped:
            from .debug_log import debug

            debug(
                "model",
                f"assemble_model_data skipped={skipped} valid={len(valid)} "
                f"({skipped} ensemble member(s) could not be resolved)",
            )
        if len(valid) < 2 and len(selected) >= 2:
            raise ValueError(
                "Too few valid ensemble members; check that selected models are installed."
            )
        from .debug_log import debug

        debug("model", f"assemble_model_data ensemble members={len(valid)}")
        return valid
    if not model:
        raise ValueError(f"assemble_model_data requires a model name for {arch_type}")
    if arch_type == ENSEMBLE_CHECK:
        return [ModelData(settings, repo, model)]
    if arch_type in (VR_ARCH_TYPE, VR_ARCH_PM):
        return [ModelData(settings, repo, model, VR_ARCH_TYPE)]
    if arch_type == MDX_ARCH_TYPE:
        return [ModelData(settings, repo, model, MDX_ARCH_TYPE)]
    if arch_type == DEMUCS_ARCH_TYPE:
        return [ModelData(settings, repo, model, DEMUCS_ARCH_TYPE)]
    raise NotImplementedError(f"assemble_model_data: arch_type '{arch_type}' is not supported")


# -- Saved ensembles (UVR persists these as JSON in ``ensembles/``) -----------

ENSEMBLE_CACHE_DIR = paths.ENSEMBLE_CACHE_DIR


def _saved_ensemble_path(name: str) -> str:
    return os.path.join(ENSEMBLE_CACHE_DIR, f"{name.replace(' ', '_')}.json")


def list_saved_ensembles() -> List[str]:
    """Return the names of every saved ensemble (UVR's ``last_found_ensembles``)."""
    if not os.path.isdir(ENSEMBLE_CACHE_DIR):
        return []
    names = [
        os.path.splitext(entry)[0]
        for entry in os.listdir(ENSEMBLE_CACHE_DIR)
        if entry.lower().endswith(".json")
    ]
    return sorted(names)


def save_ensemble(name: str, ensemble_main_stem: str, ensemble_type: str, selected_models) -> str:
    """Persist an ensemble exactly like ``pop_up_save_ensemble_sub_json_dump``.

    The JSON schema matches UVR's (``ensemble_main_stem`` / ``ensemble_type`` /
    ``selected_models``) so saved ensembles are interchangeable between the Tk
    app and the GTK rewrite. Returns the path written.
    """
    os.makedirs(ENSEMBLE_CACHE_DIR, exist_ok=True)
    saved_data = {
        "ensemble_main_stem": ensemble_main_stem,
        "ensemble_type": ensemble_type,
        "selected_models": list(selected_models),
    }
    path = _saved_ensemble_path(name)
    with open(path, "w") as outfile:
        outfile.write(json.dumps(saved_data, indent=4))
    return path


def load_ensemble(name: str) -> Optional[dict]:
    """Load a saved ensemble's data (``selection_action_chosen_ensemble_load_saved``)."""
    path = _saved_ensemble_path(name)
    if os.path.isfile(path):
        with open(path) as infile:
            return json.load(infile)
    return None


def delete_ensemble(name: str) -> bool:
    """Remove a saved ensemble file (UVR's ``deletion_entry``)."""
    path = _saved_ensemble_path(name)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False
