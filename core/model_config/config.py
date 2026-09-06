"""Public typed model configuration."""

from __future__ import annotations

import json
import os
import typing
from typing import TYPE_CHECKING, Any, Mapping, Optional, cast

from bundled.constants import *  # mirrors UVR.py's flat constant namespace

from .. import paths
from ..demucs_models import resolve_demucs_model_file
from ..mdx_c_registry import compute_checkpoint_hash, try_register_from_catalog
from ..model_stem_semantics import resolve_karaoke_confidence
from ..settings import Settings

if TYPE_CHECKING:
    from ..model_identity import ModelRecord
    from ..model_repository import ModelRepository


from .builders.chains import build_secondary_chain
from .builders.demucs import build_demucs_options
from .builders.inputs import ModelBuildInputs
from .builders.mdx import build_mdx_options
from .builders.shared import initialize_shared_options, resolve_identity
from .builders.vr import build_vr_options
from .compat import (
    CommonRunOptionsLegacyOptions,
    DemucsOptionsLegacyOptions,
    DeviceOptionsLegacyOptions,
    EnsembleMemberFlagsLegacyOptions,
    ExportOptionsLegacyOptions,
    MDXOptionsLegacyOptions,
    ModelIdentityLegacyOptions,
    SecondaryChainLegacyOptions,
    StemRoutingLegacyOptions,
    VROptionsLegacyOptions,
)


class ModelConfig(
    ModelIdentityLegacyOptions,
    ExportOptionsLegacyOptions,
    DeviceOptionsLegacyOptions,
    EnsembleMemberFlagsLegacyOptions,
    StemRoutingLegacyOptions,
    SecondaryChainLegacyOptions,
    VROptionsLegacyOptions,
    MDXOptionsLegacyOptions,
    DemucsOptionsLegacyOptions,
    CommonRunOptionsLegacyOptions,
):
    """Configuration consumed by separation engines.

    The inherited flat attributes are the stable duck-typed engine API. New
    callers can use the typed nested groups populated by the implementation:
    ``identity``, ``export_options``, ``device_options``, ``ensemble_flags``,
    ``stem_routing``, ``secondary_chain``, and the architecture option group.
    """

    model_data: Any
    demucs: Any
    _identity_record: ModelRecord | None
    _is_secondary_model_param: bool

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
        inputs = ModelBuildInputs(
            settings=settings,
            repo=repo,
            model_name=model_name,
            selected_process_method=selected_process_method,
            is_secondary_model=is_secondary_model,
            primary_model_primary_stem=primary_model_primary_stem,
            is_pre_proc_model=is_pre_proc_model,
            is_dry_check=is_dry_check,
            is_change_def=is_change_def,
            is_get_hash_dir_only=is_get_hash_dir_only,
            is_vocal_split_model=is_vocal_split_model,
            identity=identity,
            model_dependencies=model_dependencies,
        )
        self.settings = settings
        self.repo: Any = repo
        self.model_dependencies = model_dependencies
        initialize_shared_options(self, inputs)
        resolve_identity(self, inputs)

        if self.process_method == VR_ARCH_TYPE:
            build_vr_options(self, inputs)

        if self.process_method == MDX_ARCH_TYPE:
            build_mdx_options(self, inputs)

        if self.process_method == DEMUCS_ARCH_TYPE:
            build_demucs_options(self, inputs)

        if self.model_status:
            self.model_basename = os.path.splitext(os.path.basename(self.model_path))[0]
        else:
            self.model_basename = None

        if self.process_method == MDX_ARCH_TYPE and self.model_data:
            self.apply_karaoke_metadata(str(self.model_data.get("config_yaml") or ""))
            self._reconcile_mdx_runtime_contract()

        self.pre_proc_model_activated = (
            self.pre_proc_model_activated if not self.is_secondary_model else False
        )

        # -- Secondary model resolution (ported from UVR.py L686-L715) ----------
        build_secondary_chain(self, inputs)

        if self.is_vocal_split_model and self.model_status:
            self.is_secondary_model_activated = False

        self._apply_stem_focus()

        # Derive the vocal-splitter "save only" flags now that stems are known.
        self.is_inst_only_voc_splitter = self.check_only_selection_stem(INST_STEM_ONLY)
        self.is_save_vocal_only = self.check_only_selection_stem(IS_SAVE_VOC_ONLY)

        self.vocal_splitter_model_data()

    def _apply_stem_focus(self) -> None:
        """Honor ``process.stem_focus`` as the exclusive-pick (GTK and CLI).

        Fills ``available_stem_routes`` / ``selected_stem_routes`` and records
        whether the latter came from an explicit focus or MDX subset sidecar.
        Native yaml keys and exclusive-save flags stay as assembled from
        settings; engines read the routes. Vocal splitters still receive a
        selection, but :func:`~core.stems.run_export_routes` writes the full
        inventory.

        CLI ``--stems primary|secondary`` stores positional sentinels in
        ``stem_focus``. Those prefer the explicitly declared logical route and
        otherwise retain the backend primary/secondary match so engines export
        that one route. A multi-stem MDX-C custom subset still lives in
        ``mdxnet_stems_selected`` (natives) and is applied after that. Do not
        fold subset names into ``stem_focus``.

        Resolution is **per-config only**: assembling a model must never write
        back into ``self.settings``. One ``Settings`` assembles many configs
        (ensemble members, secondaries, pre-process), and in the GUI it is the
        live persisted object that read-only callers such as
        ``estimate_workload`` also assemble from.
        """
        from core.stems import (
            FOCUS_PRIMARY,
            StemSelectionStatus,
            logical_primary_route,
            logical_secondary_route,
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
        selected_stem_routes_explicit = bool(focus.strip())
        positional = positional_stem_focus(focus)
        selection_matched = False
        if positional:
            logical = (
                logical_primary_route(routes)
                if positional == FOCUS_PRIMARY
                else logical_secondary_route(routes)
            )
            if logical is not None:
                matched = (logical,)
            else:
                target = self.primary_stem if positional == FOCUS_PRIMARY else self.secondary_stem
                matched = tuple(
                    route for route in routes if route_matches_stem(route, target, self)
                )
            selected = (
                matched[:1]
                if matched
                else (
                    tuple(route for route in routes if route.selected_by_default) or tuple(routes)
                )
            )
        else:
            selection = select_stem_routes(routes, focus)
            selection_matched = selection.status is StemSelectionStatus.MATCHED
            if selection.status is StemSelectionStatus.UNMATCHED:
                selected = tuple(route for route in routes if route.selected_by_default) or tuple(
                    routes
                )
            else:
                selected = selection.routes

            if selection.status is StemSelectionStatus.EMPTY:
                mdx_stems = tuple(
                    str(stem) for stem in (getattr(self, "mdx_model_stems", None) or ()) if stem
                )
                sidecar = tuple(
                    str(stem)
                    for stem in (getattr(self, "mdxnet_stems_selected", None) or ())
                    if stem
                )
                if len(mdx_stems) > 2 and sidecar:
                    matched = routes_matching_stems(routes, sidecar, self)
                    selected = matched
                    selected_stem_routes_explicit = True

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
                elif not (
                    selection_matched and all(route.role in pair.roles for route in selected)
                ):
                    selected = pair_routes

        self.selected_stem_routes = selected
        self.selected_stem_routes_explicit = selected_stem_routes_explicit

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
            self.is_secondary_model_activated = (
                False if self.secondary_model.model_basename == self.model_basename else True
            )

    def return_ensemble_stems(self, is_primary: typing.Any = False):
        """Return registry labels for the selected exact reviewed role pair."""
        from core.model_stem_manifest import load_bundled_stem_semantics
        from core.stem_pairs import normalize_stem_pair_id, stem_pair_definition

        pair = stem_pair_definition(normalize_stem_pair_id(self.settings.ensemble.main_stem))
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
            secondary_definition = (
                registry.roles.get(pair_roles[1]) if len(pair_roles) == 2 else None
            )
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
            secondary_bucket = bucket_for_model_stem(str(secondary_for_label or ""), **ctx)
            primary_is_vocals = primary_bucket in vocal_buckets
            secondary_is_vocals = secondary_bucket in vocal_buckets
            primary_is_inst = primary_bucket in inst_buckets
            secondary_is_inst = secondary_bucket in inst_buckets

        if checktype == VOCAL_STEM_ONLY:
            return not (
                (not primary_is_vocals and stem_primary_bool)
                or (not secondary_is_vocals and stem_secondary_bool)
            )
        elif checktype == INST_STEM_ONLY:
            return (
                primary_is_inst and stem_primary_bool and is_save_inst_splitter and has_voc_splitter
            ) or (
                secondary_is_inst
                and stem_secondary_bool
                and is_save_inst_splitter
                and has_voc_splitter
            )
        elif checktype == IS_SAVE_VOC_ONLY:
            return (primary_is_vocals and stem_primary_bool) or (
                secondary_is_vocals and stem_secondary_bool
            )
        elif checktype == IS_SAVE_INST_ONLY:
            return (primary_is_inst and stem_primary_bool) or (
                secondary_is_inst and stem_secondary_bool
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

    def _reconcile_mdx_runtime_contract(self) -> None:
        """Validate installed hash/config output keys without replacing them."""
        from ..mdx_runtime_contract import reconcile_mdx_runtime_signature

        observed = tuple(str(stem) for stem in self.mdx_model_stems if stem)
        if not observed:
            observed = tuple(
                str(stem)
                for stem in (self.primary_stem_native or self.primary_stem, self.secondary_stem)
                if stem
            )
        config = getattr(self, "mdx_c_configs", None)
        training = getattr(config, "training", None)
        if training is None and isinstance(config, Mapping):
            training = config.get("training")
        training_instruments = getattr(training, "instruments", None)
        if training_instruments is None and isinstance(training, Mapping):
            training_instruments = training.get("instruments")
        target_instrument = getattr(training, "target_instrument", None)
        if target_instrument is None and isinstance(training, Mapping):
            target_instrument = training.get("target_instrument")
        self.mdx_runtime_reconciliation = reconcile_mdx_runtime_signature(
            self.canonical_id,
            observed_native_stems=observed,
            config_yaml=getattr(self, "mdx_config_yaml", ""),
            config_sha256=getattr(self, "mdx_config_sha256", ""),
            training_instruments=tuple(training_instruments or ()),
            target_instrument=str(target_instrument or ""),
            observed_primary_native=str(self.primary_stem_native or self.primary_stem or ""),
            artifact_digest=str(getattr(self, "model_hash", "") or ""),
            hash_record_source=str(getattr(self, "mdx_hash_record_source", "") or ""),
            source="installed",
        )

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
            self.model_path = os.path.join(demucs_model_dir, artifacts.primary_filename)
            return
        backend_name = getattr(self, "backend_name", self.model_name)
        for file_name, display in self.repo.demucs_name_select_MAPPER.items():
            if (
                backend_name in {file_name, os.path.splitext(file_name)[0]}
                or self.model_name == display
            ):
                self.model_path = os.path.join(demucs_model_dir, file_name)
                return
        self.model_path = resolve_demucs_model_file(backend_name, demucs_version)

    def get_demucs_model_data(self):
        from .builders.demucs import resolve_demucs_layout

        resolve_demucs_layout(self)

    def get_model_data(self, model_hash_dir: typing.Any, hash_mapper: dict):
        mapped = None
        self.mdx_hash_record_source = ""
        if self.model_hash in hash_mapper:
            mapped = dict(hash_mapper[self.model_hash])
            if self.process_method == MDX_ARCH_TYPE:
                from ..mdx_runtime_contract import reviewed_mdx_hash_record_source

                self.mdx_hash_record_source = reviewed_mdx_hash_record_source(str(self.model_hash))
        else:
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

        if self.process_method == MDX_ARCH_TYPE and self.is_mdx_ckpt and self.model_path:
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

    @property
    def vr_options(self):
        return self._vr_options if self.process_method == VR_ARCH_TYPE else None

    @property
    def mdx_options(self):
        return self._mdx_options if self.process_method == MDX_ARCH_TYPE else None

    @property
    def demucs_options(self):
        return self._demucs_options if self.process_method == DEMUCS_ARCH_TYPE else None
