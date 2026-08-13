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

from .model_data import (
    ENSEMBLE_CACHE_DIR,
    ModelRepository,
    canonical_saved_ensemble_name,
    delete_ensemble,
    list_saved_ensembles,
    load_ensemble,
    save_ensemble,
)
from .model_config import ModelConfig, assemble_model
from .audio_tools import AudioToolRunner
from .gpu import available_cuda_devices, list_gpu_devices
from .job_runner import Ensembler, JobCallbacks, JobRunner
from .paths import DATA_DIR, ensure_data_dir
from .process_data import ProcessData
from .settings import Settings

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
]
