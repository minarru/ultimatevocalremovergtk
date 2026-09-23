"""Tk-free backend facade for Ultimate Vocal Remover (GTK4 rewrite).

``core`` decouples UVR's audio backend from Tkinter so it can be driven by the
GTK4/libadwaita UI (``ui``) or any other front end. It exposes:

* :class:`Settings` - typed settings persisted as ``settings.json`` (legacy
  ``data.pkl`` is imported once).
* :class:`ModelConfig` / :func:`assemble_model` - typed per-run config assembly.
* :class:`ProcessData` - typed payload passed to separation engines.
* :class:`ModelRepository` - model discovery and MD5 hash/model-data resolution.
* :class:`JobRunner` / :class:`JobCallbacks` - the ``KThread`` separation worker.

Importing this package must never import ``tkinter``; heavy ML dependencies
(``torch``, ``engines``) are imported lazily inside the methods that use them.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .audio_plan import AudioJobResolver, AudioJobSpec, PlannedAudioUnit, ResolvedAudioJob
    from .audio_tools import AudioToolRunner
    from .blocking_runner import BlockingRunner, RunResult, run_blocking
    from .ensemble_service import (
        EnsembleService,
        ResolvedEnsemblePreset,
        canonical_saved_ensemble_name,
        delete_ensemble,
        list_saved_ensembles,
        load_ensemble,
        save_ensemble,
    )
    from .ensembler import Ensembler
    from .gpu import available_cuda_devices, list_gpu_devices
    from .job_callbacks import JobCallbacks
    from .job_plan import (
        Diagnostic,
        JobResolver,
        JobSpec,
        ModelDescriptor,
        PlannedInput,
        PlannedOutput,
        Provenance,
        ResolvedJob,
        ValidationLevel,
    )
    from .job_runner import JobRunner
    from .model_catalogue import CatalogEntryId, ModelCatalogueRecord, ModelCatalogueService
    from .model_config import ModelConfig, assemble_model
    from .model_identity import (
        CatalogueRef,
        DemucsSpec,
        MdxSpec,
        ModelArtifacts,
        ModelId,
        ModelIdentityService,
        ModelRecord,
    )
    from .model_registry import ModelRegistryService
    from .model_repository import (
        ModelRepository,
    )
    from .paths import DATA_DIR, ENSEMBLE_CACHE_DIR, ensure_data_dir
    from .process_data import ProcessData
    from .settings import Settings
    from .settings.job_resolution import SettingsLayer, SettingsResolver
    from .stems import StemRoute, StemRouteKind, StemSelection, StemSelectionStatus

_EXPORTS: dict[str, tuple[str, str]] = {
    'Settings': ('.settings', 'Settings'),
    'ModelConfig': ('.model_config', 'ModelConfig'),
    'ModelRepository': ('.model_repository', 'ModelRepository'),
    'assemble_model': ('.model_config', 'assemble_model'),
    'ProcessData': ('.process_data', 'ProcessData'),
    'JobRunner': ('.job_runner', 'JobRunner'),
    'JobCallbacks': ('.job_callbacks', 'JobCallbacks'),
    'AudioToolRunner': ('.audio_tools', 'AudioToolRunner'),
    'Ensembler': ('.ensembler', 'Ensembler'),
    'ENSEMBLE_CACHE_DIR': ('.paths', 'ENSEMBLE_CACHE_DIR'),
    'canonical_saved_ensemble_name': ('.ensemble_service', 'canonical_saved_ensemble_name'),
    'list_saved_ensembles': ('.ensemble_service', 'list_saved_ensembles'),
    'save_ensemble': ('.ensemble_service', 'save_ensemble'),
    'load_ensemble': ('.ensemble_service', 'load_ensemble'),
    'delete_ensemble': ('.ensemble_service', 'delete_ensemble'),
    'ensure_data_dir': ('.paths', 'ensure_data_dir'),
    'DATA_DIR': ('.paths', 'DATA_DIR'),
    'available_cuda_devices': ('.gpu', 'available_cuda_devices'),
    'list_gpu_devices': ('.gpu', 'list_gpu_devices'),
    'ModelId': ('.model_identity', 'ModelId'),
    'ModelArtifacts': ('.model_identity', 'ModelArtifacts'),
    'DemucsSpec': ('.model_identity', 'DemucsSpec'),
    'MdxSpec': ('.model_identity', 'MdxSpec'),
    'CatalogueRef': ('.model_identity', 'CatalogueRef'),
    'ModelRecord': ('.model_identity', 'ModelRecord'),
    'ModelIdentityService': ('.model_identity', 'ModelIdentityService'),
    'JobSpec': ('.job_plan', 'JobSpec'),
    'JobResolver': ('.job_plan', 'JobResolver'),
    'ResolvedJob': ('.job_plan', 'ResolvedJob'),
    'ValidationLevel': ('.job_plan', 'ValidationLevel'),
    'Provenance': ('.job_plan', 'Provenance'),
    'Diagnostic': ('.job_plan', 'Diagnostic'),
    'ModelDescriptor': ('.job_plan', 'ModelDescriptor'),
    'PlannedInput': ('.job_plan', 'PlannedInput'),
    'PlannedOutput': ('.job_plan', 'PlannedOutput'),
    'AudioJobSpec': ('.audio_plan', 'AudioJobSpec'),
    'AudioJobResolver': ('.audio_plan', 'AudioJobResolver'),
    'ResolvedAudioJob': ('.audio_plan', 'ResolvedAudioJob'),
    'PlannedAudioUnit': ('.audio_plan', 'PlannedAudioUnit'),
    'BlockingRunner': ('.blocking_runner', 'BlockingRunner'),
    'RunResult': ('.blocking_runner', 'RunResult'),
    'run_blocking': ('.blocking_runner', 'run_blocking'),
    'SettingsLayer': ('.settings.job_resolution', 'SettingsLayer'),
    'SettingsResolver': ('.settings.job_resolution', 'SettingsResolver'),
    'StemRoute': ('.stems', 'StemRoute'),
    'StemRouteKind': ('.stems', 'StemRouteKind'),
    'StemSelection': ('.stems', 'StemSelection'),
    'StemSelectionStatus': ('.stems', 'StemSelectionStatus'),
    'EnsembleService': ('.ensemble_service', 'EnsembleService'),
    'ResolvedEnsemblePreset': ('.ensemble_service', 'ResolvedEnsemblePreset'),
    'CatalogEntryId': ('.model_catalogue', 'CatalogEntryId'),
    'ModelCatalogueRecord': ('.model_catalogue', 'ModelCatalogueRecord'),
    'ModelCatalogueService': ('.model_catalogue', 'ModelCatalogueService'),
    'ModelRegistryService': ('.model_registry', 'ModelRegistryService'),
}


def __getattr__(name: str) -> Any:
    try:
        module, attribute = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(import_module(module, __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "Settings",
    "ModelConfig",
    "ModelRepository",
    "assemble_model",
    "ProcessData",
    "JobRunner",
    "JobCallbacks",
    "AudioToolRunner",
    "Ensembler",
    "ENSEMBLE_CACHE_DIR",
    "canonical_saved_ensemble_name",
    "list_saved_ensembles",
    "save_ensemble",
    "load_ensemble",
    "delete_ensemble",
    "ensure_data_dir",
    "DATA_DIR",
    "available_cuda_devices",
    "list_gpu_devices",
    "ModelId",
    "ModelArtifacts",
    "DemucsSpec",
    "MdxSpec",
    "CatalogueRef",
    "ModelRecord",
    "ModelIdentityService",
    "JobSpec",
    "JobResolver",
    "ResolvedJob",
    "ValidationLevel",
    "Provenance",
    "Diagnostic",
    "ModelDescriptor",
    "PlannedInput",
    "PlannedOutput",
    "AudioJobSpec",
    "AudioJobResolver",
    "ResolvedAudioJob",
    "PlannedAudioUnit",
    "BlockingRunner",
    "RunResult",
    "run_blocking",
    "SettingsLayer",
    "SettingsResolver",
    "StemRoute",
    "StemRouteKind",
    "StemSelection",
    "StemSelectionStatus",
    "EnsembleService",
    "ResolvedEnsemblePreset",
    "CatalogEntryId",
    "ModelCatalogueRecord",
    "ModelCatalogueService",
    "ModelRegistryService",
]
