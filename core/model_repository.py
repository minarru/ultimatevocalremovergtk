"""Checkpoint discovery, hash maps, and list/checklist identities.

Per-run :class:`~core.model_config.ModelConfig` assembly lives in
:mod:`core.model_config`. Nested secondary / vocal-split / Demucs pre-process
factories live in :mod:`core.model_config.determine`. MDX-C yaml helpers and
hash-JSON IO live in :mod:`core.model_data`. Saved-ensemble JSON persistence
lives in :mod:`core.ensemble_service`.
Nothing here imports ``tkinter``.
"""

import json
import os
import threading
import typing
from typing import TYPE_CHECKING, AbstractSet, Any, Callable, Dict, List, Optional, Tuple

from bundled.constants import *  # mirrors UVR.py's flat constant namespace

from . import paths
from .demucs_models import (
    demucs_yaml_bag_member_sigs,
    is_demucs_bag_member_weight,
)
from .model_data import load_model_hash_data
from .model_display import (
    map_basenames_to_display,
)
from .model_stem_manifest import resolve_model_stem_semantics
from .settings import Settings
from .stem_roles import StemProcessingContext, StemReviewStatus

if TYPE_CHECKING:
    from .model_identity import IdentityIndex


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
        self._model_hash_table_provider: Optional[Callable[[], typing.Mapping[str, Any]]] = None
        # Phase 3 hook: later phases set this to a callable that prompts the user
        # for parameters of an unrecognized model. Returning ``None`` (the
        # default) simply marks such models as unavailable.
        self.on_unrecognized_model: Optional[Callable[["ModelConfig"], Any]] = None
        self._stem_check_cache = None
        self._karaoke_cache: Optional[Tuple[Tuple[str, ...], List[str]]] = None
        self._models_changed_subscribers: List[Callable[[], None]] = []
        self._models_changed_lock = threading.Lock()
        self._notifying_models_changed = False
        self._presentation_changed_subscribers: List[Callable[[], None]] = []
        self._presentation_changed_lock = threading.Lock()
        self._notifying_presentation_changed = False
        self._inventory_lock = threading.RLock()
        self._inventory_generation = 0
        # Owned here, not on ModelIdentityService: services are built per call
        # site, so a per-service cache never hits. Keyed on the same
        # generation/catalogue/naming triple the service computes.
        self._identity_cache_key: Optional[Tuple[int, str, int]] = None
        self._identity_cache: Optional["IdentityIndex"] = None
        self._naming_revision = 0
        self._catalogue = catalogue
        self.reload_mappers()
        # Catalogue refinements are presentation deltas: they change the label a
        # record projects, never which files are installed. Subscribing here is
        # what turns a late catalogue arrival into a repaint.
        subscribe_delta = getattr(catalogue, "subscribe_delta", None)
        if callable(subscribe_delta):
            subscribe_delta(self._on_catalogue_delta)

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
        if not callable(digest):
            return ""
        value = digest()
        return value if isinstance(value, str) else ""

    def bind_model_hash_table(self, provider: Callable[[], typing.Mapping[str, Any]]) -> None:
        """Bind the persisted stat-guarded hash table owned by the caller.

        The repository keeps only the flattened trusted projection. Retaining
        the provider lets model invalidation rebuild that projection with
        fresh stat checks instead of forcing checkpoint hashing.
        """
        with self._inventory_lock:
            self._model_hash_table_provider = provider
            self._rehydrate_model_hash_table()
            self._identity_cache_key = None
            self._identity_cache = None

    def _rehydrate_model_hash_table(self) -> None:
        provider = self._model_hash_table_provider
        self.model_hash_table.clear()
        if provider is None:
            return
        from .model_hash_cache import flatten_trusted, snapshot_table

        persisted = snapshot_table(provider())
        self.model_hash_table.update(flatten_trusted(persisted))

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

    def _on_catalogue_delta(self, delta: Any) -> None:
        """Translate a typed catalogue delta into a presentation refresh.

        Only source and identity deltas move model labels: ``SOURCES_CHANGED``
        can introduce a friendlier display, and ``IDENTITY_REFINED`` can make an
        installed record gain or lose the exact catalogue association it
        projects from. ``METADATA_CHANGED`` carries stem subtitles, which are
        not model labels.

        Deliberately does not read ``coordinator.snapshot()``: the coordinator
        has already published, and pulling here would remesh sources from a
        notification callback. The next identity read consumes the new snapshot.

        Release is owned by the coordinator: :meth:`CatalogueCoordinator.close`
        clears its subscriber list, and the repository has no disposal hook of
        its own to add an unused ``close()`` API to.
        """
        from .catalogue_types import DeltaKind

        kind = getattr(delta, "kind", None)
        if kind not in (DeltaKind.SOURCES_CHANGED, DeltaKind.IDENTITY_REFINED):
            return
        self.invalidate_model_presentation(reload_mappers=False)

    def subscribe_model_presentation_changed(self, callback: Callable[[], None]) -> None:
        """Call ``callback`` after :meth:`invalidate_model_presentation`.

        Presentation-only: labels or catalogue associations changed while the
        set of installed files, resolved plans and eligibility caches all stayed
        valid. Fired from whichever thread invalidated, exactly like
        ``models_changed``, so listeners marshal to their own loop themselves.
        """
        with self._presentation_changed_lock:
            if callback not in self._presentation_changed_subscribers:
                self._presentation_changed_subscribers.append(callback)

    def unsubscribe_model_presentation_changed(self, callback: Callable[[], None]) -> None:
        with self._presentation_changed_lock:
            try:
                self._presentation_changed_subscribers.remove(callback)
            except ValueError:
                pass

    def _notify_model_presentation_changed(self) -> None:
        if self._notifying_presentation_changed:
            return
        with self._presentation_changed_lock:
            callbacks = list(self._presentation_changed_subscribers)
        self._notifying_presentation_changed = True
        try:
            for callback in callbacks:
                try:
                    callback()
                except Exception:
                    from .debug_log import debug

                    debug("model", "model_presentation_changed subscriber raised")
        finally:
            self._notifying_presentation_changed = False

    def invalidate_model_presentation(self, *, reload_mappers: bool = False) -> None:
        """Labels changed; the files on disk did not.

        Drops only the identity/display projection cache. Inventory generation,
        hash maps, dry-check and karaoke pools all survive, so a resolved plan
        stays effective and no checkpoint is rehashed.
        """
        from .debug_log import debug

        with self._inventory_lock:
            debug("model", f"invalidate_model_presentation mappers={reload_mappers}")
            if reload_mappers:
                self._reload_name_mappers()
            self._identity_cache_key = None
            self._identity_cache = None
        self._notify_model_presentation_changed()

    def _reload_hash_mappers(self) -> None:
        """Execution data: checkpoint hash -> model parameters."""
        for attr, path in (
            ("vr_hash_MAPPER", paths.VR_HASH_JSON),
            ("mdx_hash_MAPPER", paths.MDX_HASH_JSON),
        ):
            try:
                setattr(self, attr, load_model_hash_data(path))
            except (FileNotFoundError, ValueError):
                setattr(self, attr, {})

    def _reload_name_mappers(self) -> None:
        """Presentation data: on-disk basename -> friendly label.

        Owns ``naming_revision`` because that token keys display projections
        only. A presentation refresh reloads these without touching hash maps.
        """
        from .name_mapper import load_presentation_name_mapper

        for attr, path in (
            ("mdx_name_select_MAPPER", paths.MDX_MODEL_NAME_SELECT),
            ("demucs_name_select_MAPPER", paths.DEMUCS_MODEL_NAME_SELECT),
        ):
            setattr(self, attr, load_presentation_name_mapper(path))
        self._naming_revision += 1

    def reload_mappers(self) -> None:
        from .debug_log import debug

        debug("model", "reload_mappers")
        self._reload_hash_mappers()
        self._reload_name_mappers()

    def list_vr_models(self) -> List[str]:
        return _list_models(paths.VR_MODELS_DIR, (".pth",))

    def list_mdx_models(self) -> List[str]:
        return _list_models(paths.MDX_MODELS_DIR, (".onnx", ".ckpt"))

    def list_demucs_models(self) -> List[str]:
        models: List[str] = []
        bag_sigs = demucs_yaml_bag_member_sigs(paths.DEMUCS_NEWER_REPO_DIR)
        for directory in (paths.DEMUCS_NEWER_REPO_DIR, paths.DEMUCS_MODELS_DIR):
            for name in _list_model_files(directory, (".th", ".th.gz", ".ckpt", ".yaml", ".yml")):
                if directory == paths.DEMUCS_MODELS_DIR and name.lower().endswith(".ckpt"):
                    continue
                stem = _artifact_stem(name)
                if directory == paths.DEMUCS_NEWER_REPO_DIR and is_demucs_bag_member_weight(
                    stem, bag_sigs
                ):
                    continue
                models.append(stem)
        seen, unique = set(), []
        for name in models:
            if name not in seen:
                seen.add(name)
                unique.append(name)
        return unique

    def _model_artifact_files(self, family: str) -> List[str]:
        """Return installed artifact filenames without hashing their contents."""
        if family == "vr":
            return _list_model_files(paths.VR_MODELS_DIR, (".pth",))
        if family == "mdx":
            return _list_model_files(paths.MDX_MODELS_DIR, (".onnx", ".ckpt", ".yaml", ".yml"))
        if family == "apollo":
            return _list_model_files(paths.APOLLO_MODELS_DIR, (".ckpt", ".bin"))
        if family != "demucs":
            return []
        newer = _list_model_files(
            paths.DEMUCS_NEWER_REPO_DIR, (".th", ".th.gz", ".ckpt", ".yaml", ".yml")
        )
        legacy = [
            name
            for name in _list_model_files(
                paths.DEMUCS_MODELS_DIR, (".th", ".th.gz", ".yaml", ".yml")
            )
            if not name.lower().endswith(".ckpt")
        ]
        return newer + [name for name in legacy if name not in newer]

    def _model_artifact_path(self, family: str, filename: str) -> str:
        directories = {
            "vr": (paths.VR_MODELS_DIR,),
            "mdx": (paths.MDX_MODELS_DIR,),
            "demucs": (paths.DEMUCS_NEWER_REPO_DIR, paths.DEMUCS_MODELS_DIR),
            "apollo": (paths.APOLLO_MODELS_DIR,),
        }
        for directory in directories.get(family, ()):
            candidate = os.path.join(directory, filename)
            if os.path.isfile(candidate):
                return candidate
        return os.path.join(directories.get(family, ("",))[0], filename)

    # -- Model tags / stem filtering (ported from UVR's model menus) -----------

    def list_vr_model_tags(self) -> List[str]:
        return _canonical_model_tags("vr", self.list_vr_models(), VR_ARCH_TYPE, self)

    def list_mdx_model_tags(self) -> List[str]:
        return _canonical_model_tags("mdx", self.list_mdx_models(), MDX_ARCH_TYPE, self)

    def mdx_catalogue_display_index(self, *, allow_network: bool = False) -> Dict[str, str]:
        coordinator = self._catalogue
        if coordinator is not None:
            snapshot = coordinator.ensure(allow_network=allow_network)
            return dict(snapshot.display_index_mdx)
        from .model_display import load_mdx_catalog_display_index

        return load_mdx_catalog_display_index(allow_network=allow_network)

    def vr_catalogue_display_index(self, *, allow_network: bool = False) -> Dict[str, str]:
        coordinator = self._catalogue
        if coordinator is not None:
            snapshot = coordinator.ensure(allow_network=allow_network)
            return dict(snapshot.display_index_vr)
        from .model_display import load_vr_catalog_display_index

        return load_vr_catalog_display_index(allow_network=allow_network)

    def demucs_catalogue_display_index(self, *, allow_network: bool = False) -> Dict[str, str]:
        coordinator = self._catalogue
        if coordinator is not None:
            snapshot = coordinator.ensure(allow_network=allow_network)
            return dict(snapshot.display_index_demucs)
        from .model_display import load_demucs_catalog_display_index

        return load_demucs_catalog_display_index(allow_network=allow_network)

    def list_demucs_model_tags(self) -> List[str]:
        return _canonical_model_tags("demucs", self.list_demucs_models(), DEMUCS_ARCH_TYPE, self)

    def all_model_tags(self) -> List[str]:
        return (
            self.list_vr_model_tags() + self.list_mdx_model_tags() + self.list_demucs_model_tags()
        )

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
        identities = self._identity_index()
        model_data: List[ModelConfig] = []
        for tag in key[0]:
            model = _dry_check_config(settings, self, tag, identities)
            if model is not None:
                model_data.append(model)
        self._stem_check_cache = (key, model_data)
        return model_data

    def _identity_index(self) -> "IdentityIndex":
        """The identity index for this repository's current inventory.

        Resolved once per pool loop rather than per tag: the pools below walk
        whole tag lists, and this is the only lookup surface they need.
        """
        from .model_identity import ModelIdentityService

        return ModelIdentityService(self).index

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
        from .debug_log import log_event

        with self._inventory_lock:
            self._inventory_generation += 1
            log_event(
                "model",
                "model_inventory_invalidated",
                generation=self._inventory_generation,
            )
            self._stem_check_cache = None
            self._karaoke_cache = None
            self._identity_cache_key = None
            self._identity_cache = None
            self._rehydrate_model_hash_table()
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
        identities = self._identity_index()
        for tag in tags:
            model = _dry_check_config(settings, self, tag, identities)
            if (
                model is not None
                and model.model_status
                and (model.is_karaoke or model.is_bv_model)
                and _has_reviewed_vocal_split_context(model)
            ):
                model_list.append(_checklist_id(model))
        self._karaoke_cache = (tags, model_list)
        return list(model_list)

    def ensemble_model_list(self, settings: Settings, ensemble_main_stem: Any) -> List[str]:
        """Return installed models with exact reviewed pair-role coverage.

        Pair eligibility is deliberately stricter than a display or native
        spelling comparison: a model must resolve to a reviewed full-mix
        declaration with both role IDs from the requested definition.
        """
        from core.stem_pairs import normalize_stem_pair_id, stem_pair_definition
        from core.stem_roles import StemRoleId

        pair_id = normalize_stem_pair_id(ensemble_main_stem)
        definition = stem_pair_definition(pair_id)
        if definition is not None:
            return [
                _checklist_id(model)
                for model in self.stem_check(settings)
                if _has_reviewed_full_mix_roles(model, definition.roles)
            ]
        if pair_id == "mode.multi_stem":
            return [_checklist_id(model) for model in self.stem_check(settings)]
        if pair_id == "mode.four_stem":
            roles = (
                StemRoleId("instrument.bass"),
                StemRoleId("instrument.drums"),
                StemRoleId("residual.other"),
                StemRoleId("vocal.vocals"),
            )
            return [
                _checklist_id(model)
                for model in self.stem_check(settings)
                if _has_reviewed_full_mix_roles(model, roles)
            ]
        return []

    def resolve_model_dry(self, settings: Settings, process_method: str, model_name: str):
        """Resolve ``model_name`` to a dry-check :class:`ModelConfig` (or ``None``).

        Lets the UI inspect a selected model (its stems, MDX-C type, ...) without
        committing to a run. Returns ``None`` when the model can't be resolved
        without prompting. Callers reuse the single returned object instead of
        rebuilding ``ModelConfig`` (which hashes the model file) more than once.
        """
        try:
            if process_method == VR_ARCH_PM:
                process_method = VR_ARCH_TYPE
            identity = None
            if str(model_name or "").partition(":")[0].casefold() in {"vr", "mdx", "demucs"}:
                from .model_identity import ModelIdentityService

                identity = ModelIdentityService(self).lookup(model_name)
                model_name = identity.display
            if identity is None:
                return ModelConfig(settings, self, model_name, process_method, is_dry_check=True)
            return ModelConfig(
                settings,
                self,
                model_name,
                process_method,
                is_dry_check=True,
                identity=identity,
            )
        except (FileNotFoundError, ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
            from .debug_log import debug

            debug(
                "model",
                f"resolve_model_dry failed model={model_name!r} error={type(exc).__name__}: {exc}",
            )
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


def _dry_check_config(
    settings: Settings,
    repo: "ModelRepository",
    tag: str,
    identities: "IdentityIndex",
) -> Optional["ModelConfig"]:
    """Build the dry-check :class:`ModelConfig` for one canonical model tag.

    Dry-check pools are canonical ``family:basename`` IDs, which the legacy
    ``"Arch: Display"`` parser in :class:`ModelConfig` cannot split -- it would
    leave every installed model with ``model_status=False``. Resolve the record
    here and hand it over as ``identity``. An unknown or collided ID falls
    through to the legacy path, which marks the config unavailable: the right
    outcome for a model that cannot be addressed unambiguously.
    """
    try:
        identity = None
        try:
            identity = identities.lookup(tag)
        except ValueError as exc:
            from .debug_log import debug

            debug("model", f"dry-check identity unresolved tag={tag!r}: {exc}")
        return ModelConfig(settings, repo, tag, is_dry_check=True, identity=identity)
    except (FileNotFoundError, ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        from .debug_log import debug

        debug(
            "model",
            f"dry-check failed tag={tag!r} error={type(exc).__name__}: {exc}",
        )
        return None


def _canonical_model_tags(
    family: str, basenames: List[str], arch: str, repo: "ModelRepository"
) -> List[str]:
    """Installed basenames → ``family:basename``, sorted by display label."""
    from .model_identity import ModelId

    displays = map_basenames_to_display(basenames, arch, repo)
    pairs = sorted(zip(displays, basenames, strict=False), key=lambda item: str(item[0]).casefold())
    return [str(ModelId(family, basename)) for _display, basename in pairs]


def _checklist_id(model: Any) -> str:
    """Canonical row key for a dry-check config (``family:basename``)."""
    from .model_identity import FAMILY_BY_ARCH, ModelId

    # The config carries its resolved record's id since the dry-check pools
    # started resolving identities; use it rather than re-deriving one from a
    # filename. ``os.path.splitext`` on a basename such as
    # ``mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956`` strips ``.1956``
    # and produces an id no record answers to.
    canonical = str(getattr(model, "canonical_id", "") or "")
    if canonical:
        return canonical
    family = FAMILY_BY_ARCH.get(getattr(model, "process_method", None) or "")
    basename = getattr(model, "model_basename", None)
    if family and basename:
        stem = _artifact_stem(str(basename))
        if stem and ":" not in stem:
            return str(ModelId(family, stem))
    tag = getattr(model, "model_and_process_tag", None)
    return str(tag or "")


def _has_reviewed_vocal_split_context(model: Any) -> bool:
    """Require exact reviewed splitter semantics for one dry-check model."""
    native_stems: tuple[str, ...] = ()
    for attribute in ("mdx_model_stems", "demucs_source_list"):
        value = getattr(model, attribute, ())
        if isinstance(value, (list, tuple)) and value:
            native_stems = tuple(str(item) for item in value if item)
            if native_stems:
                break
    if not native_stems:
        native_stems = tuple(
            dict.fromkeys(
                str(item)
                for item in (
                    getattr(model, "primary_stem_native", None)
                    or getattr(model, "primary_stem", None),
                    getattr(model, "secondary_stem", None),
                )
                if item
            )
        )
    model_id = _checklist_id(model)
    if not model_id or not native_stems:
        return False
    semantics = resolve_model_stem_semantics(
        model_id,
        native_stems=native_stems,
        backend_primary=str(
            getattr(model, "primary_stem_native", None) or getattr(model, "primary_stem", "") or ""
        ),
        backend_target=str(getattr(model, "target_instrument", "") or ""),
        context=StemProcessingContext.VOCAL_SPLIT,
    )
    return semantics.status is StemReviewStatus.REVIEWED


def _has_reviewed_full_mix_roles(model: Any, required_roles: typing.Iterable[Any]) -> bool:
    """Require exact reviewed full-mix roles for a semantic ensemble pair."""
    native_stems: tuple[str, ...] = ()
    for attribute in ("mdx_model_stems", "demucs_source_list"):
        value = getattr(model, attribute, ())
        if isinstance(value, (list, tuple)) and value:
            native_stems = tuple(str(item) for item in value if item)
            if native_stems:
                break
    if not native_stems:
        native_stems = tuple(
            dict.fromkeys(
                str(item)
                for item in (
                    getattr(model, "primary_stem_native", None)
                    or getattr(model, "primary_stem", None),
                    getattr(model, "secondary_stem", None),
                )
                if item
            )
        )
    model_id = _checklist_id(model)
    if not model_id or not native_stems:
        return False
    semantics = resolve_model_stem_semantics(
        model_id,
        native_stems=native_stems,
        backend_primary=str(
            getattr(model, "primary_stem_native", None) or getattr(model, "primary_stem", "") or ""
        ),
        backend_target=str(getattr(model, "target_instrument", "") or ""),
        context=StemProcessingContext.FULL_MIX,
    )
    if semantics.status is not StemReviewStatus.REVIEWED:
        return False
    available_roles = {output.role for output in semantics.outputs}
    return set(required_roles).issubset(available_roles)


def _list_models(directory: str, extensions: typing.Any) -> List[str]:
    return sorted(_artifact_stem(name) for name in _list_model_files(directory, extensions))


def _artifact_stem(filename: str) -> str:
    from .model_inventory import artifact_stem

    return artifact_stem(filename)


def _list_model_files(directory: str, extensions: typing.Any) -> List[str]:
    if not os.path.isdir(directory):
        return []
    names = []
    for entry in os.listdir(directory):
        full = os.path.join(directory, entry)
        if os.path.isfile(full) and entry.lower().endswith(tuple(extensions)):
            names.append(entry)
    return sorted(names)


from .model_config.config import ModelConfig  # noqa: E402 - avoids import cycle
