"""Checkpoint discovery, hash maps, and list/checklist identities.

Per-run :class:`~core.model_config.ModelConfig` assembly lives in
:mod:`core.model_config`. Nested secondary / vocal-split / Demucs pre-process
factories live in :mod:`core.model_config.determine`. MDX-C yaml helpers and
hash-JSON IO live in :mod:`core.model_data`. Saved-ensemble JSON persistence
lives in :mod:`core.ensemble_service`.
Nothing here imports ``tkinter``.
"""
import typing

import json
import os
import threading
from typing import AbstractSet, Any, Callable, Dict, List, Optional, Tuple

from bundled.constants import *  # noqa: F401,F403 - mirrors UVR.py's flat constant namespace

from . import paths
from .demucs_models import (
    demucs_yaml_bag_member_sigs,
    is_demucs_bag_member_weight,
)
from .model_data import load_model_hash_data
from .model_display import (
    map_basenames_to_display,
)
from .settings import Settings


class ModelRepository:
    """Holds the model-data mappers and the path->hash cache.

    Mirrors the ``vr_hash_MAPPER`` / ``mdx_hash_MAPPER`` / ``*_name_select_MAPPER``
    attributes and the ``model_hash_table`` that live on ``MainWindow``. Created
    once and shared by every :class:`ModelConfig` built for a run.
    """

    def __init__(self, *, catalogue: Any = None):
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
        self._naming_revision = 0
        self._catalogue = catalogue
        self.reload_mappers()

    @property
    def inventory_generation(self) -> int:
        """Monotonic token invalidating previously resolved effective plans."""
        return self._inventory_generation

    @property
    def naming_revision(self) -> int:
        return self._naming_revision

    @property
    def catalogue(self) -> Any:
        return self._catalogue

    @property
    def catalogue_revision(self) -> str:
        coordinator = self._catalogue
        if coordinator is None:
            return ""
        snapshot = getattr(coordinator, "_latest", None)
        revision = getattr(snapshot, "revision", None)
        digest = getattr(revision, "digest", None)
        return digest() if callable(digest) else ""

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

        debug("model", "reload_mappers")
        self._naming_revision += 1
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
        return _canonical_model_tags("vr", self.list_vr_models(), VR_ARCH_TYPE, self)

    def list_mdx_model_tags(self) -> List[str]:
        return _canonical_model_tags("mdx", self.list_mdx_models(), MDX_ARCH_TYPE, self)

    def mdx_catalogue_display_index(self, *, allow_network: bool = False) -> Dict[str, str]:
        coordinator = self._catalogue
        if coordinator is not None:
            snapshot = coordinator.ensure(vip=True, allow_network=allow_network)
            return dict(snapshot.display_index_mdx)
        from .model_display import load_mdx_catalog_display_index

        return load_mdx_catalog_display_index(allow_network=allow_network)

    def vr_catalogue_display_index(self, *, allow_network: bool = False) -> Dict[str, str]:
        coordinator = self._catalogue
        if coordinator is not None:
            snapshot = coordinator.ensure(vip=True, allow_network=allow_network)
            return dict(snapshot.display_index_vr)
        from .model_display import load_vr_catalog_display_index

        return load_vr_catalog_display_index(allow_network=allow_network)

    def demucs_catalogue_display_index(self, *, allow_network: bool = False) -> Dict[str, str]:
        coordinator = self._catalogue
        if coordinator is not None:
            snapshot = coordinator.ensure(vip=True, allow_network=allow_network)
            return dict(snapshot.display_index_demucs)
        from .model_display import load_demucs_catalog_display_index

        return load_demucs_catalog_display_index(allow_network=allow_network)

    def list_demucs_model_tags(self) -> List[str]:
        return _canonical_model_tags(
            "demucs", self.list_demucs_models(), DEMUCS_ARCH_TYPE, self
        )

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

        The single entry point for that event. ``reload_mappers`` increments
        the naming revision without remeshing catalogue sources. Display
        indexes come from the coordinator snapshot when one is injected.

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
                result.append(_checklist_id(model))
            elif matches_stem(model) or (not is_no_demucs and demucs_match(model)):
                result.append(_checklist_id(model))
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
                model_list.append(_checklist_id(model))
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
            return [_checklist_id(model) for model in self.stem_check(settings)]
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


def _canonical_model_tags(
    family: str, basenames: List[str], arch: str, repo: "ModelRepository"
) -> List[str]:
    """Installed basenames → ``family:basename``, sorted by display label."""
    from .model_identity import ModelId

    displays = map_basenames_to_display(basenames, arch, repo)
    pairs = sorted(zip(displays, basenames), key=lambda item: str(item[0]).casefold())
    return [str(ModelId(family, basename)) for _display, basename in pairs]


def _checklist_id(model: Any) -> str:
    """Canonical row key for a dry-check config (``family:basename``)."""
    from .model_identity import FAMILY_BY_ARCH, ModelId

    family = FAMILY_BY_ARCH.get(getattr(model, "process_method", None) or "")
    basename = getattr(model, "model_basename", None)
    if family and basename:
        stem = os.path.splitext(str(basename))[0]
        if stem and ":" not in stem:
            return str(ModelId(family, stem))
    tag = getattr(model, "model_and_process_tag", None)
    return str(tag or "")


def _list_models(directory: str, extensions: typing.Any) -> List[str]:
    if not os.path.isdir(directory):
        return []
    names = []
    for entry in os.listdir(directory):
        full = os.path.join(directory, entry)
        if os.path.isfile(full) and entry.lower().endswith(tuple(extensions)):
            names.append(os.path.splitext(entry)[0])
    return sorted(names)


from .model_config.config import ModelConfig

