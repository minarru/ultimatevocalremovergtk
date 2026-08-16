"""Model repository and implementation for typed model configuration.

This rebuilds the per-run model configuration that the ``separate.py`` engines
consume, but reads every value from a :class:`~core.settings.Settings`
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
import typing

import json
import os
import re
import threading
import tempfile
from typing import AbstractSet, Any, Callable, Dict, List, Optional, Sequence, Tuple, cast

from bundled.constants import *  # noqa: F401,F403 - mirrors UVR.py's flat constant namespace

from . import paths
from .mdx_config_fetch import ensure_mdx_c_config
from .demucs_models import (
    demucs_yaml_bag_member_sigs,
    is_demucs_bag_member_weight,
    resolve_demucs_model_file,
)
from .mdx_c_registry import compute_checkpoint_hash, try_register_from_catalog
from .model_stem_semantics import is_vocal_target, resolve_karaoke_confidence
from .model_display import (
    display_name_for_basename,
    map_basenames_to_display,
    resolve_mdx_model_basename,
    resolve_vr_model_basename,
)
from .audio_io import resolve_wav_type_set
from .settings import Settings
from .settings.coerce import enum_value

_MDX_C_YAML_LOADER = None


def load_mdx_c_config(path: str) -> dict:
    """Load a bundled MDX-C / Roformer yaml config.

    Shipped configs use ``!!python/tuple`` for a few list fields; this extends
    :class:`yaml.SafeLoader` with only that tag so we avoid ``FullLoader`` while
    still parsing the trusted local files under ``mdx_c_configs/``. It also
    widens the float resolver: PyYAML's default one requires a ``.`` in the
    mantissa, so a bare-exponent value like ``1e-3`` (no shipped config uses
    this, but externally-sourced yamls — e.g. vendored Demucs's own configs —
    commonly do) silently loads as the string ``"1e-3"`` instead of ``0.001``.
    """
    import re

    import yaml

    global _MDX_C_YAML_LOADER
    if _MDX_C_YAML_LOADER is None:

        class MdxCYamlLoader(yaml.SafeLoader):
            pass

        def _construct_python_tuple(loader: typing.Any, node: typing.Any):
            return tuple(loader.construct_sequence(node))

        yaml.add_constructor(
            "tag:yaml.org,2002:python/tuple",
            _construct_python_tuple,
            Loader=MdxCYamlLoader,
        )
        MdxCYamlLoader.add_implicit_resolver(
            "tag:yaml.org,2002:float",
            re.compile(
                r"""^(?:
                 [-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+]?[0-9]+)?
                |[-+]?(?:[0-9][0-9_]*)(?:[eE][-+]?[0-9]+)
                |\.[0-9_]+(?:[eE][-+][0-9]+)?
                |[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*
                |[-+]?\.(?:inf|Inf|INF)
                |\.(?:nan|NaN|NAN))$""",
                re.VERBOSE,
            ),
            list("-+0123456789."),
        )
        _MDX_C_YAML_LOADER = MdxCYamlLoader

    with open(path) as config_file:
        return yaml.load(config_file, Loader=_MDX_C_YAML_LOADER)


def _mdx_c_training(config: typing.Any) -> Any:
    """Return the ``training`` section from an MDX-C yaml config object."""
    training = getattr(config, "training", None)
    if training is None and isinstance(config, dict):
        training = config.get("training")
    return training


def _mdx_c_primary_for_select(instruments: list, stem_select: Any) -> Any:
    """Pick a primary stem that actually exists on a multi-stem MDX-C model."""
    if stem_select and stem_select != ALL_STEMS:
        if stem_select in instruments:
            return stem_select
        from .model_stem_semantics import resolve_stem_dict_key

        # Treat instruments as a key set so Title Case UI picks match yaml case.
        matched = resolve_stem_dict_key({str(s): s for s in instruments}, str(stem_select))
        if matched is not None:
            return matched
    for stem in instruments:
        if is_vocal_target(str(stem)):
            return stem
    return instruments[0] if instruments else stem_select


def _mdx_c_secondary_for_pair(instruments: list, primary: Any, mapped: Any) -> Any:
    """Complement stem for a 2-stem MDX-C model.

    ``secondary_stem`` only knows UVR's pair table, so a model trained on any
    other pair (``center``/``wide``) gets the synthetic ``No <stem>`` label
    back. A 2-stem model *emits* its complement, so that label names nothing in
    the demixed sources and export dies with a ``KeyError``. Use the model's own
    other instrument instead. Real pair labels (``Instrumental``) and models that
    genuinely emit a ``No <stem>`` stem are left alone.
    """
    if not instruments or not str(mapped).startswith(NO_STEM):
        return mapped

    from .model_stem_semantics import resolve_stem_dict_key

    if resolve_stem_dict_key({str(s): s for s in instruments}, str(mapped)) is not None:
        return mapped
    others = [stem for stem in instruments if str(stem) != str(primary)]
    return others[0] if others else mapped


def load_model_hash_data(dictionary: str) -> dict:
    """Load one of the model-data / name-mapper JSON files."""
    with open(dictionary, "r") as d:
        return json.load(d)


class ModelRepository:
    """Holds the model-data mappers and the path->hash cache.

    Mirrors the ``vr_hash_MAPPER`` / ``mdx_hash_MAPPER`` / ``*_name_select_MAPPER``
    attributes and the ``model_hash_table`` that live on ``MainWindow``. Created
    once and shared by every :class:`ModelConfig` built for a run.
    """

    def __init__(self):
        self.vr_hash_MAPPER: dict = {}
        self.mdx_hash_MAPPER: dict = {}
        self.mdx_name_select_MAPPER: dict = {}
        self.demucs_name_select_MAPPER: dict = {}
        # AppContext seeds this ephemeral cache from trusted persisted entries.
        self.model_hash_table: Dict[str, str] = {}
        # Phase 3 hook: later phases set this to a callable that prompts the user
        # for parameters of an unrecognized model. Returning ``None`` (the
        # default) simply marks such models as unavailable.
        self.on_unrecognized_model: Optional[Callable[["ModelConfig"], Any]] = None
        self._stem_check_cache = None
        self._karaoke_cache: Optional[Tuple[Tuple[str, ...], List[str]]] = None
        self._models_changed_subscribers: List[Callable[[], None]] = []
        self._models_changed_lock = threading.Lock()
        self._notifying_models_changed = False
        self._inventory_generation = 0
        self.reload_mappers()

    @property
    def inventory_generation(self) -> int:
        """Monotonic token invalidating previously resolved effective plans."""
        return self._inventory_generation

    # -- Change notification ----------------------------------------------------

    def subscribe_models_changed(self, callback: Callable[[], None]) -> None:
        """Call ``callback`` after :meth:`invalidate_models`.

        Fired from whichever thread invalidated — usually the download worker —
        so listeners must marshal to their own loop before touching widgets.
        Mirrors ``catalogue_stem_cache.subscribe`` and
        ``DownloadManager.subscribe_catalogue_changed``.
        """
        with self._models_changed_lock:
            if callback not in self._models_changed_subscribers:
                self._models_changed_subscribers.append(callback)

    def unsubscribe_models_changed(self, callback: Callable[[], None]) -> None:
        with self._models_changed_lock:
            try:
                self._models_changed_subscribers.remove(callback)
            except ValueError:
                pass

    def _notify_models_changed(self) -> None:
        # A subscriber that invalidates again (e.g. a refresh that registers a
        # newly recognized model) would otherwise renotify itself forever.
        if self._notifying_models_changed:
            return
        with self._models_changed_lock:
            callbacks = list(self._models_changed_subscribers)
        self._notifying_models_changed = True
        try:
            for callback in callbacks:
                try:
                    callback()
                except Exception:
                    from .debug_log import debug

                    debug("model", "models_changed subscriber raised")
        finally:
            self._notifying_models_changed = False

    def reload_mappers(self) -> None:
        from .debug_log import debug
        from .model_display import clear_display_cache

        debug("model", "reload_mappers")
        clear_display_cache()
        for attr, path in (
            ("vr_hash_MAPPER", paths.VR_HASH_JSON),
            ("mdx_hash_MAPPER", paths.MDX_HASH_JSON),
        ):
            try:
                setattr(self, attr, load_model_hash_data(path))
            except (FileNotFoundError, ValueError):
                setattr(self, attr, {})

        # Name mappers are mirror + local overlay, not a single file.
        from .name_mapper import load_name_mapper

        for attr, path in (
            ("mdx_name_select_MAPPER", paths.MDX_MODEL_NAME_SELECT),
            ("demucs_name_select_MAPPER", paths.DEMUCS_MODEL_NAME_SELECT),
        ):
            setattr(self, attr, load_name_mapper(path))

    def list_vr_models(self) -> List[str]:
        return _list_models(paths.VR_MODELS_DIR, (".pth",))

    def list_mdx_models(self) -> List[str]:
        return _list_models(paths.MDX_MODELS_DIR, (".onnx", ".ckpt"))

    def list_demucs_models(self) -> List[str]:
        models: List[str] = []
        bag_sigs = demucs_yaml_bag_member_sigs(paths.DEMUCS_NEWER_REPO_DIR)
        for directory in (paths.DEMUCS_NEWER_REPO_DIR, paths.DEMUCS_MODELS_DIR):
            for name in _list_models(directory, (".th", ".ckpt", ".yaml", ".gz")):
                if (
                    directory == paths.DEMUCS_NEWER_REPO_DIR
                    and is_demucs_bag_member_weight(name, bag_sigs)
                ):
                    continue
                models.append(name)
        seen, unique = set(), []
        for name in models:
            if name not in seen:
                seen.add(name)
                unique.append(name)
        return unique

    # -- Model tags / stem filtering (ported from UVR's model menus) -----------

    def list_vr_model_tags(self) -> List[str]:
        names = sorted(
            map_basenames_to_display(self.list_vr_models(), VR_ARCH_TYPE, self)
        )
        return [f"{VR_ARCH_TYPE}{ENSEMBLE_PARTITION}{name}" for name in names]

    def list_mdx_model_tags(self) -> List[str]:
        names = sorted(
            map_basenames_to_display(self.list_mdx_models(), MDX_ARCH_TYPE, self)
        )
        return [f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}{name}" for name in names]

    def mdx_catalogue_display_index(self, *, allow_network: bool = False) -> Dict[str, str]:
        from .model_display import load_mdx_catalog_display_index

        return load_mdx_catalog_display_index(allow_network=allow_network)

    def vr_catalogue_display_index(self, *, allow_network: bool = False) -> Dict[str, str]:
        from .model_display import load_vr_catalog_display_index

        return load_vr_catalog_display_index(allow_network=allow_network)

    def demucs_catalogue_display_index(self, *, allow_network: bool = False) -> Dict[str, str]:
        from .model_display import load_demucs_catalog_display_index

        return load_demucs_catalog_display_index(allow_network=allow_network)

    def list_demucs_model_tags(self) -> List[str]:
        names = sorted(
            map_basenames_to_display(self.list_demucs_models(), DEMUCS_ARCH_TYPE, self)
        )
        return [f"{DEMUCS_ARCH_TYPE}{ENSEMBLE_PARTITION}{name}" for name in names]

    def all_model_tags(self) -> List[str]:
        return self.list_vr_model_tags() + self.list_mdx_model_tags() + self.list_demucs_model_tags()

    def default_change_model_tags(self) -> List[str]:
        """VR + MDX model tags - the pool UVR exposes in change-model-defaults."""
        return self.list_vr_model_tags() + self.list_mdx_model_tags()

    def stem_check(self, settings: Settings) -> List["ModelConfig"]:
        """Build a cached dry-check ``ModelConfig`` for every discovered model.

        Equivalent to ``assemble_model(arch_type=ENSEMBLE_STEM_CHECK)``;
        each model's hash/params are resolved so callers can filter by stem. The
        result is cached against the current model set so the (file-hashing) work
        only happens once per change.
        """
        # Keyed on the model set plus ``mdx.stems`` -- and deliberately nothing
        # else. That one field is the only setting that reaches a dry-check
        # filter (``mdxnet_stem_select`` -> ``_mdx_c_primary_for_select``, see
        # ``primary_stem`` below); the Demucs analogue is guarded by
        # ``is_ensemble_mode``, which is always False on this path. Do not widen
        # this to a full Settings fingerprint: every unrelated settings edit
        # would then re-hash every checkpoint.
        key = (tuple(self.all_model_tags()), str(settings.mdx.stems))
        if self._stem_check_cache is not None and self._stem_check_cache[0] == key:
            return self._stem_check_cache[1]
        model_data: List[ModelConfig] = [
            ModelConfig(settings, self, tag, is_dry_check=True) for tag in key[0]
        ]
        self._stem_check_cache = (key, model_data)
        return model_data

    def invalidate_stem_check(self) -> None:
        """Drop the dry-check pools only.

        Narrow primitive: use it when the *filters* changed but the files on
        disk did not. When model files were added, removed or rewritten, call
        :meth:`invalidate_models` instead -- the mappers and display caches are
        derived from those files too.
        """
        from .debug_log import debug

        debug("model", "invalidate_stem_check")
        self._stem_check_cache = None
        self._karaoke_cache = None

    def invalidate_models(self) -> None:
        """The set of model files on disk changed: drop every derived cache.

        The single entry point for that event. ``reload_mappers`` already
        chains ``clear_display_cache`` -> ``invalidate_catalogue_merge``, so
        this covers the dry-check pools, the ephemeral hash cache, the hash and
        name mappers, and the display/catalogue merges together.

        Clearing ``model_hash_table`` is cheap despite appearances: every entry
        it holds is also in the persistent stat-guarded table, so refilling
        costs an ``os.stat`` per checkpoint rather than an md5.
        """
        from .debug_log import debug

        self._inventory_generation += 1
        debug("model", f"invalidate_models generation={self._inventory_generation}")
        self._stem_check_cache = None
        self._karaoke_cache = None
        self.model_hash_table.clear()
        self.reload_mappers()
        self._notify_models_changed()

    def model_list(
        self,
        settings: Settings,
        primary_stem: str,
        secondary_stem: str,
        is_4_stem_check: bool = False,
        is_no_demucs: bool = False,
        *,
        wanted_buckets: Optional[AbstractSet[Any]] = None,
    ) -> List[str]:
        """Tk-free port of ``MainWindow.model_list`` (secondary-model filtering).

        Stem comparison goes through :func:`core.stems.bucket_for_model_stem`.
        ``wanted_buckets`` accepts :class:`~core.stems.StemBucket` members or
        their ``.value`` strings (pair requests must not be re-derived from
        slash-split display halves).
        """
        from core.stems import StemBucket, bucket_for_model_stem, model_stem_count

        stem_check = self.stem_check(settings)

        def _as_bucket_value(item: Any) -> str:
            if isinstance(item, StemBucket):
                return item.value
            return str(item)

        if wanted_buckets is None:
            wanted = {
                bucket_for_model_stem(primary_stem, stem_count=1).value,
                bucket_for_model_stem(secondary_stem, stem_count=1).value,
            }
        else:
            wanted = {_as_bucket_value(item) for item in wanted_buckets}
        wanted.discard(StemBucket.UNKNOWN.value)

        def bucket_of(model: "ModelConfig", stem: str) -> str:
            return bucket_for_model_stem(
                stem,
                stem_count=model_stem_count(model),
                is_karaoke=bool(getattr(model, "is_karaoke", False)),
                is_bv=bool(getattr(model, "is_bv_model", False)),
            ).value

        def matches_stem(model: "ModelConfig") -> bool:
            if not wanted:
                return False
            primary_match = bucket_of(model, str(model.primary_stem or "")) in wanted
            mdx_match = any(bucket_of(model, stem) in wanted for stem in model.mdx_model_stems)
            if is_no_demucs:
                return primary_match or (mdx_match and model.mdx_stem_count <= 2)
            return primary_match or mdx_match

        def demucs_match(model: "ModelConfig") -> bool:
            return any(
                bucket_for_model_stem(stem, stem_count=4).value in wanted
                for stem in model.demucs_source_list
            )

        result: List[str] = []
        for model in stem_check:
            if is_4_stem_check and (model.demucs_stem_count == 4 or model.mdx_stem_count == 4):
                result.append(model.model_and_process_tag)
            elif matches_stem(model) or (not is_no_demucs and demucs_match(model)):
                result.append(model.model_and_process_tag)
        return result

    def karaoke_model_list(self, settings: Settings) -> List[str]:
        """Build the dry-check vocal-split model pool."""
        tags = tuple(self.default_change_model_tags())
        if self._karaoke_cache is not None and self._karaoke_cache[0] == tags:
            return list(self._karaoke_cache[1])
        model_list: List[str] = []
        for tag in tags:
            model = ModelConfig(settings, self, tag, is_dry_check=True)
            if model.model_status and (model.is_karaoke or model.is_bv_model):
                model_list.append(model.model_and_process_tag)
        self._karaoke_cache = (tags, model_list)
        return list(model_list)

    def ensemble_model_list(
        self, settings: Settings, ensemble_main_stem: Any
    ) -> List[str]:
        """Models compatible with the chosen ensemble main-stem pair.

        Accepts :class:`~core.stems.EnsemblePair` or its stable id. Legacy
        display pair strings coerce to :attr:`~core.stems.EnsemblePair.CHOOSE`
        and yield an empty list.
        """
        from core.stems import EnsemblePair, StemBucket, coerce_ensemble_pair

        pair = (
            ensemble_main_stem
            if isinstance(ensemble_main_stem, EnsemblePair)
            else coerce_ensemble_pair(ensemble_main_stem)
        )
        if pair is EnsemblePair.CHOOSE:
            return []
        if pair is EnsemblePair.MULTI_STEM:
            return [model.model_and_process_tag for model in self.stem_check(settings)]
        if pair is EnsemblePair.FOUR_STEM:
            return self.model_list(
                settings, PRIMARY_STEM, SECONDARY_STEM, is_4_stem_check=True
            )
        primary, secondary = pair.buckets()
        primary_ui, secondary_ui = pair.stem_halves()
        wanted = {primary, secondary}
        wanted.discard(StemBucket.UNKNOWN)
        return self.model_list(
            settings,
            primary_ui,
            secondary_ui,
            wanted_buckets=wanted,
        )

    def resolve_model_dry(self, settings: Settings, process_method: str, model_name: str):
        """Resolve ``model_name`` to a dry-check :class:`ModelConfig` (or ``None``).

        Lets the UI inspect a selected model (its stems, MDX-C type, ...) without
        committing to a run. Returns ``None`` when the model can't be resolved
        without prompting. Callers reuse the single returned object instead of
        rebuilding ``ModelConfig`` (which hashes the model file) more than once.
        """
        try:
            if str(model_name or "").partition(":")[0].casefold() in {"vr", "mdx", "demucs"}:
                from .model_identity import ModelIdentityService

                family = {
                    VR_ARCH_TYPE: "vr", VR_ARCH_PM: "vr",
                    MDX_ARCH_TYPE: "mdx", DEMUCS_ARCH_TYPE: "demucs",
                }.get(process_method)
                model_name = ModelIdentityService(self).engine_value(
                    model_name, family=family
                )
            return ModelConfig(settings, self, model_name, process_method, is_dry_check=True)
        except (FileNotFoundError, ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
            from .debug_log import debug

            debug("model", f"resolve_model_dry failed model={model_name!r} error={type(exc).__name__}: {exc}")
            return None

    def stem_labels_for_model(self, settings: Settings, process_method: str, model_name: str):
        """Return ``(primary_stem, secondary_stem)`` for the selected model.

        Used to label the per-model stem-only toggles; returns ``(None, None)``
        when the model can't be resolved without prompting.
        """
        model = self.resolve_model_dry(settings, process_method, model_name)
        if model is None:
            return None, None
        return model.primary_stem, model.secondary_stem


def _list_models(directory: str, extensions: typing.Any) -> List[str]:
    if not os.path.isdir(directory):
        return []
    names = []
    for entry in os.listdir(directory):
        full = os.path.join(directory, entry)
        if os.path.isfile(full) and entry.lower().endswith(tuple(extensions)):
            names.append(os.path.splitext(entry)[0])
    return sorted(names)


class _ModelConfigImplementation:
    """Private implementation retained while repository logic is extracted.

    The public :class:`core.model_config.ModelConfig` subclasses this during the
    compatibility window. Keeping the proven resolution logic here avoids
    duplicating it while ``ModelRepository`` remains in this module.
    """

    def __init__(
        self,
        settings: Settings,
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
        self.repo: Any = repo
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
        self.is_primary_stem_only = process.primary_stem_only
        self.is_secondary_stem_only = process.secondary_stem_only
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
        self.model_name = model_name
        self.process_method = selected_process_method
        self.model_status = False if self.model_name == CHOOSE_MODEL or self.model_name == NO_MODEL else True
        # Always defined: hash / path lookup may leave this unset for missing files.
        self.model_data: Any = None
        self.primary_stem: str | None = None
        self.secondary_stem: str | None = None
        self.primary_stem_native: str | None = None
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
            # The ensemble member tag is ``"<arch>: <model name>"``; split it back
            # into the member's real process method + model name (UVR L553-567).
            self.process_method, _, self.model_name = model_name.partition(ENSEMBLE_PARTITION)
            self.model_and_process_tag = model_name
            self.ensemble_primary_stem, self.ensemble_secondary_stem = self.return_ensemble_stems()
            is_not_secondary_or_pre_proc = not is_secondary_model and not is_pre_proc_model
            self.is_ensemble_mode = is_not_secondary_or_pre_proc

            from core.stems import EnsemblePair, coerce_ensemble_pair

            ensemble_pair = coerce_ensemble_pair(ensemble.main_stem)
            if ensemble_pair is EnsemblePair.FOUR_STEM:
                self.is_4_stem_ensemble = self.is_ensemble_mode
            elif (
                ensemble_pair is EnsemblePair.MULTI_STEM
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
                                    # Odd yaml: target ``other`` is a clean
                                    # instrumental extractor; complement is the
                                    # acapella (all vocals), not ``No other``.
                                    if str(target).casefold() == "other":
                                        self.primary_stem_native = str(target)
                                        self.primary_stem = INST_STEM
                                        self.secondary_stem = VOCAL_STEM
                                    else:
                                        self.primary_stem = target
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
            self.margin_demucs = int(demucs.margin_demucs)
            self.chunks_demucs = 0
            self.shifts = int(demucs.shifts)
            self.is_split_mode = demucs.is_split_mode
            # Engine ``demucs_segments`` expects the legacy ``Default`` label.
            self.segment = (
                DEF_OPT if demucs.segment is None else str(demucs.segment)
            )
            self.is_chunk_demucs = demucs.is_chunk_demucs
            self.is_primary_stem_only = (
                process.primary_stem_only
                if self.is_ensemble_mode
                else demucs.is_primary_stem_only
            )
            self.is_secondary_stem_only = (
                process.secondary_stem_only
                if self.is_ensemble_mode
                else demucs.is_secondary_stem_only
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

        self.is_primary_model_primary_stem_only = is_primary_model_primary_stem_only
        self.is_primary_model_secondary_stem_only = is_primary_model_secondary_stem_only

        # -- Secondary model resolution (ported from UVR.py L686-L715) ----------
        is_secondary_activated_and_status = self.is_secondary_model_activated and self.model_status
        is_demucs = self.process_method == DEMUCS_ARCH_TYPE
        is_all_stems = demucs.stems == ALL_STEMS
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
                self.is_demucs_pre_proc_model_inst_mix = (
                    demucs.is_pre_proc_model_inst_mix if self.pre_proc_model else False
                )

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
        self._sync_option_groups()

    # -- Secondary / vocal-split / pre-process resolution -----------------------
    # Faithful Tk-free ports of ``MainWindow.process_determine_*`` /
    # ``vocal_splitter_model_data`` / ``secondary_model_data`` reading the same
        # flat settings keys instead of Tk variables.

    def vocal_splitter_model_data(self):
        self.vocal_split_model = None
        self.is_vocal_split_model_activated = False
        if not self.is_secondary_model and self.model_status:
            self.vocal_split_model = process_determine_vocal_split_model(self.settings, self.repo)
            self.is_vocal_split_model_activated = True if self.vocal_split_model else False
            if self.vocal_split_model and self.vocal_split_model.bv_model_rebalance:
                self.is_sec_bv_rebalance = True

    def secondary_model_data(self, primary_stem: typing.Any):
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

    def return_ensemble_stems(self, is_primary: typing.Any = False):
        """Return UI stem-half labels for the chosen :class:`~core.stems.EnsemblePair`.

        These are Save-stems / stem-only labels, not filename combine tags
        (:meth:`~core.stems.EnsemblePair.buckets` / ``filename_tag``).
        """
        from core.stems import coerce_ensemble_pair

        primary, secondary = coerce_ensemble_pair(
            self.settings.ensemble.main_stem
        ).stem_halves()
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
            stem_primary_bool = self.settings.demucs.is_primary_stem_only
            stem_secondary_bool = self.settings.demucs.is_secondary_stem_only
        else:
            stem_primary_bool = self.settings.process.primary_stem_only
            stem_secondary_bool = self.settings.process.secondary_stem_only

        is_save_inst_splitter = self.settings.process.save_inst_vocal_splitter
        has_voc_splitter = self.settings.process.vocal_splitter != NO_MODEL

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
        resolved_name = resolve_vr_model_basename(
            self.model_name,
            catalogue_index=self.repo.vr_catalogue_display_index(),
        )
        self.model_path = os.path.join(paths.VR_MODELS_DIR, f"{resolved_name}.pth")

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
                elif file_name.endswith(ONNX):
                    # Mapper keys auto-registered from download jobs already
                    # include the extension (unlike bundled catalogue keys),
                    # so appending it again would look up "name.onnx.onnx".
                    ext = ""
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
                return
        self.model_path = resolve_demucs_model_file(self.model_name, self.demucs_version)

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
        from .model_hash_cache import is_stale, lookup_trusted, remember

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
        from .model_config.base import (
            DeviceOptions,
            EnsembleMemberFlags,
            ExportOptions,
            ModelIdentity,
            SecondaryChain,
            StemRouting,
        )
        from .model_config.demucs import DemucsOptions
        from .model_config.mdx import MDXOptions
        from .model_config.vr import VROptions

        self.identity = ModelIdentity(
            model_name=self.model_name,
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
            is_primary_stem_only=bool(self.is_primary_stem_only),
            is_secondary_stem_only=bool(self.is_secondary_stem_only),
            mdx_model_stems=tuple(self.mdx_model_stems),
            demucs_source_list=tuple(self.demucs_source_list),
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
                margin_demucs=self.margin_demucs,
                chunks_demucs=self.chunks_demucs,
                shifts=self.shifts,
                is_split_mode=bool(self.is_split_mode),
                segment=self.segment,
                is_chunk_demucs=bool(self.is_chunk_demucs),
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

_SECONDARY_PREFIX_BY_METHOD = {
    VR_ARCH_TYPE: "vr",
    MDX_ARCH_TYPE: "mdx",
    DEMUCS_ARCH_TYPE: "demucs",
}


def _secondary_slot_for_stem(main_model_primary_stem: str) -> Optional[str]:
    """Return the nested secondary-model slot for a primary stem."""
    if main_model_primary_stem in (VOCAL_STEM, INST_STEM):
        return "voc_inst"
    elif main_model_primary_stem in (OTHER_STEM, NO_OTHER_STEM):
        return "other"
    elif main_model_primary_stem in (DRUM_STEM, NO_DRUM_STEM):
        return "drums"
    elif main_model_primary_stem in (BASS_STEM, NO_BASS_STEM):
        return "bass"
    return None


def process_determine_secondary_model(
    settings: Settings,
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

    slot = _secondary_slot_for_stem(main_model_primary_stem)
    section = getattr(settings, prefix)
    secondary_model_name = (
        getattr(section, f"{slot}_secondary_model") if slot else NO_MODEL
    )
    secondary_model_scale = (
        getattr(section, f"{slot}_secondary_model_scale") if slot else None
    )
    if secondary_model_scale:
        secondary_model_scale = float(secondary_model_scale)

    secondary_model = None
    if secondary_model_name and secondary_model_name != NO_MODEL:
        secondary_model = ModelConfig(
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


def process_determine_demucs_pre_proc_model(settings: Settings, repo: ModelRepository, primary_stem: typing.Any=None):
    """Tk-free port of ``MainWindow.process_determine_demucs_pre_proc_model``."""
    pre_proc_name = settings.demucs.pre_proc_model
    if pre_proc_name != NO_MODEL and settings.demucs.is_pre_proc_model_activate:
        pre_proc_model = ModelConfig(
            settings,
            repo,
            pre_proc_name,
            primary_model_primary_stem=primary_stem,
            is_pre_proc_model=True,
        )
        if pre_proc_model.model_status:
            return pre_proc_model
    return None


def process_determine_vocal_split_model(settings: Settings, repo: ModelRepository):
    """Tk-free port of ``MainWindow.process_determine_vocal_split_model``."""
    split_name = settings.process.vocal_splitter
    if split_name != NO_MODEL and settings.process.vocal_splitter_enabled:
        vocal_splitter_model = ModelConfig(settings, repo, split_name, is_vocal_split_model=True)
        if vocal_splitter_model.model_status:
            return vocal_splitter_model
    return None


from .model_config.config import ModelConfig


# -- Saved ensembles (UVR persists these as JSON in ``ensembles/``) -----------

ENSEMBLE_CACHE_DIR = paths.ENSEMBLE_CACHE_DIR


_ENSEMBLE_NAME_RE = re.compile(r"^[A-Za-z0-9 _-]{1,25}$")


def canonical_saved_ensemble_name(name: str) -> str:
    """Validate and canonicalize a user-supplied saved-ensemble name."""
    value = name.strip()
    if not value or not _ENSEMBLE_NAME_RE.fullmatch(value):
        raise ValueError(
            "Ensemble names may contain only letters, numbers, spaces, "
            "underscores, and hyphens (maximum 25 characters)."
        )
    if value.startswith("-") or value.endswith("-"):
        raise ValueError("Ensemble names cannot start or end with a hyphen.")
    return value.replace(" ", "_")


def _saved_ensemble_path(name: str) -> str:
    canonical = canonical_saved_ensemble_name(name)
    root = os.path.abspath(ENSEMBLE_CACHE_DIR)
    path = os.path.abspath(os.path.join(root, f"{canonical}.json"))
    if os.path.commonpath((root, path)) != root:
        raise ValueError("Ensemble path escapes the ensemble cache")
    return path


def list_saved_ensembles() -> List[str]:
    """Return the names of every saved ensemble (UVR's ``last_found_ensembles``)."""
    if not os.path.isdir(ENSEMBLE_CACHE_DIR):
        return []
    names = []
    for entry in os.listdir(ENSEMBLE_CACHE_DIR):
        if not entry.lower().endswith(".json"):
            continue
        stem = os.path.splitext(entry)[0]
        try:
            canonical = canonical_saved_ensemble_name(stem)
        except ValueError:
            continue
        if canonical == stem:
            names.append(canonical)
    return sorted(names)


def save_ensemble(
    name: str, ensemble_main_stem: Any, ensemble_type: str, selected_models: typing.Any,
    *, wav_ensemble: bool = False, save_all_outputs: bool = True,
    identity_schema_version: int = 2,
) -> str:
    """Persist an ensemble (``ensemble_main_stem`` is an :class:`~core.stems.EnsemblePair` id)."""
    from core.stems import EnsemblePair, coerce_ensemble_pair

    pair = (
        ensemble_main_stem
        if isinstance(ensemble_main_stem, EnsemblePair)
        else coerce_ensemble_pair(ensemble_main_stem)
    )
    saved_data = {
        "ensemble_main_stem": pair.value,
        "ensemble_type": ensemble_type,
        "selected_models": list(selected_models),
        "is_wav_ensemble": bool(wav_ensemble),
        "save_all_outputs": bool(save_all_outputs),
        "identity_schema_version": identity_schema_version,
    }
    path = _saved_ensemble_path(name)
    os.makedirs(ENSEMBLE_CACHE_DIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=ENSEMBLE_CACHE_DIR
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as outfile:
            json.dump(saved_data, outfile, indent=4)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
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
