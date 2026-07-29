"""Tk-free backend facade for Ultimate Vocal Remover (GTK4 rewrite).

``core`` decouples UVR's audio backend from Tkinter so it can be driven by the
GTK4/libadwaita UI (``ui``) or any other front end. It exposes:

* :class:`SettingsModel` / :class:`~core.settings.Settings` - typed settings
  persisted as ``settings.json`` (legacy ``data.pkl`` is imported once).
* :class:`ModelConfig` / :func:`assemble_model` - typed per-run config assembly.
  ``ModelData`` / ``assemble_model_data`` remain compatibility aliases.
* :class:`ModelRepository` - model discovery and MD5 hash/model-data resolution.
* :class:`JobRunner` / :class:`JobCallbacks` - the ``KThread`` separation worker.

Importing this package must never import ``tkinter``; heavy ML dependencies
(``torch``, ``engines``) are imported lazily inside the methods that use them.
"""

from .model_data import (
    ENSEMBLE_CACHE_DIR,
    ModelConfig,
    ModelData,
    ModelRepository,
    assemble_model,
    assemble_model_data,
    delete_ensemble,
    list_saved_ensembles,
    load_ensemble,
    save_ensemble,
)
from .audio_tools import AudioToolRunner
from .gpu import available_cuda_devices, list_gpu_devices
from .job_runner import Ensembler, JobCallbacks, JobRunner
from .paths import DATA_DIR, ensure_data_dir
from .settings import Settings, SettingsModel

__all__ = [
    "Settings",
    "SettingsModel",
    "ModelConfig",
    "ModelData",
    "ModelRepository",
    "assemble_model",
    "assemble_model_data",
    "JobRunner",
    "JobCallbacks",
    "AudioToolRunner",
    "Ensembler",
    "ENSEMBLE_CACHE_DIR",
    "list_saved_ensembles",
    "save_ensemble",
    "load_ensemble",
    "delete_ensemble",
    "ensure_data_dir",
    "DATA_DIR",
    "available_cuda_devices",
    "list_gpu_devices",
]
