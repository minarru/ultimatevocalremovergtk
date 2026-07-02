"""Tk-free backend facade for Ultimate Vocal Remover (GTK4 rewrite).

``uvr_core`` decouples UVR's audio backend from Tkinter so it can be driven by the
GTK4/libadwaita UI (``uvr_gtk``) or any other front end. It exposes:

* :class:`SettingsModel` - the flat ``DEFAULT_DATA`` schema with pickle persistence.
* :class:`ModelData` / :func:`assemble_model_data` - Tk-free per-run config assembly.
* :class:`ModelRepository` - model discovery and MD5 hash/model-data resolution.
* :class:`JobRunner` / :class:`JobCallbacks` - the ``KThread`` separation worker.

Importing this package must never import ``tkinter``; heavy ML dependencies
(``torch``, ``separate.py``) are imported lazily inside the methods that use them.
"""

from .gpu import available_cuda_devices
from .job_runner import Ensembler, JobCallbacks, JobRunner
from .paths import DATA_DIR, ensure_data_dir
from .model_data import (
    ENSEMBLE_CACHE_DIR,
    ModelData,
    ModelRepository,
    assemble_model_data,
    delete_ensemble,
    list_saved_ensembles,
    load_ensemble,
    save_ensemble,
)
from .settings import SettingsModel

__all__ = [
    "SettingsModel",
    "ModelData",
    "ModelRepository",
    "assemble_model_data",
    "JobRunner",
    "JobCallbacks",
    "Ensembler",
    "ENSEMBLE_CACHE_DIR",
    "list_saved_ensembles",
    "save_ensemble",
    "load_ensemble",
    "delete_ensemble",
    "ensure_data_dir",
    "DATA_DIR",
    "available_cuda_devices",
]
