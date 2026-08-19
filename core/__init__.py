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

from .model_repository import (
    ModelRepository,
)
from .ensemble_service import (
    EnsembleService,
    ResolvedEnsemblePreset,
    canonical_saved_ensemble_name,
    delete_ensemble,
    list_saved_ensembles,
    load_ensemble,
    save_ensemble,
)
from .model_config import ModelConfig, assemble_model
from .audio_tools import AudioToolRunner
from .gpu import available_cuda_devices, list_gpu_devices
from .ensembler import Ensembler
from .job_callbacks import JobCallbacks
from .job_runner import JobRunner
from .paths import DATA_DIR, ENSEMBLE_CACHE_DIR, ensure_data_dir
from .process_data import ProcessData
from .settings import Settings
from .model_identity import ModelId, ModelIdentityService, ModelRecord
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
from .audio_plan import AudioJobResolver, AudioJobSpec, PlannedAudioUnit, ResolvedAudioJob
from .blocking_runner import BlockingRunner, RunResult, run_blocking
from .model_catalogue import CatalogEntryId, ModelCatalogueService, ModelCatalogueRecord
from .model_registry import ModelRegistryService
from .settings.job_resolution import SettingsLayer, SettingsResolver
from .stems import StemRoute, StemRouteKind, StemSelection, StemSelectionStatus

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
