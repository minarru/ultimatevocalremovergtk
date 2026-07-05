"""Filesystem locations for the Tk-free backend facade.

These mirror the path constants defined inline in ``UVR.py`` so ``core`` can
locate models, model-data caches and the persisted settings file without
importing the Tkinter application module.

Paths are split into two groups so the app can run from a read-only install
(Flatpak ``/app``, AppImage mount) while keeping writable runtime data in a
separate, user-writable location:

* Read-only **bundled data** lives under :data:`bundled/` (constants, changelog,
  download cache JSON).
* Writable **runtime data** resolves relative to :data:`DATA_DIR` (models, model
  data caches, downloaded aux models, temp dirs and the settings pickle).

``DATA_DIR`` resolution order (backward compatible):

1. ``$UVR_DATA_DIR`` if set.
2. Else :data:`BASE_PATH` when it is writable (preserves the historic
   "portable" layout for dev checkouts / tarball installs, so existing
   ``./models`` and ``./data.pkl`` keep working unchanged).
3. Else the OS-default user data dir from :mod:`core.platform` (XDG on Linux,
   ``%LOCALAPPDATA%`` on Windows, ``~/Library/Application Support`` on macOS).
"""

import os
import shutil

from .platform import user_data_dir

BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- Read-only bundled data (never written at runtime) -----------------------
BUNDLED_DATA_DIR = os.path.join(BASE_PATH, "bundled")
CHANGE_LOG_PATH = os.path.join(BUNDLED_DATA_DIR, "change_log.txt")
RELEASE_JSON_PATH = os.path.join(BUNDLED_DATA_DIR, "release.json")
DOWNLOAD_MODEL_CACHE_PATH = os.path.join(BUNDLED_DATA_DIR, "model_manual_download.json")
VR_PARAM_DIR = os.path.join(BASE_PATH, "ml", "vr_network", "modelparams")
MDX_MIXER_PATH = os.path.join(BASE_PATH, "ml", "mixer.ckpt")

# Read-only seed tree shipped inside the install dir. When ``DATA_DIR`` is
# relocated (read-only install), :func:`ensure_data_dir` copies the bundled
# JSON/config seeds from here into the writable tree.
BUNDLED_MODELS_DIR = os.path.join(BASE_PATH, "models")


def _resolve_data_dir() -> str:
    """Resolve the writable runtime-data root (see module docstring)."""
    return user_data_dir(BASE_PATH)


# --- Writable runtime data ---------------------------------------------------
DATA_DIR = _resolve_data_dir()

MODELS_DIR = os.path.join(DATA_DIR, "models")
VR_MODELS_DIR = os.path.join(MODELS_DIR, "VR_Models")
MDX_MODELS_DIR = os.path.join(MODELS_DIR, "MDX_Net_Models")
DEMUCS_MODELS_DIR = os.path.join(MODELS_DIR, "Demucs_Models")
DEMUCS_NEWER_REPO_DIR = os.path.join(DEMUCS_MODELS_DIR, "v3_v4_repo")

VR_HASH_DIR = os.path.join(VR_MODELS_DIR, "model_data")
VR_HASH_JSON = os.path.join(VR_HASH_DIR, "model_data.json")
MDX_HASH_DIR = os.path.join(MDX_MODELS_DIR, "model_data")
MDX_HASH_JSON = os.path.join(MDX_HASH_DIR, "model_data.json")
MDX_C_CONFIG_PATH = os.path.join(MDX_HASH_DIR, "mdx_c_configs")

DEMUCS_MODEL_NAME_SELECT = os.path.join(DEMUCS_MODELS_DIR, "model_data", "model_name_mapper.json")
MDX_MODEL_NAME_SELECT = os.path.join(MDX_MODELS_DIR, "model_data", "model_name_mapper.json")

# Apollo restoration models. Like the other model trees these are writable /
# downloadable, so they live under DATA_DIR. ``model_configs`` holds the per-model
# yaml configs and ``model_data`` holds the md5-keyed ``<hash>.json`` param files.
APOLLO_MODELS_DIR = os.path.join(MODELS_DIR, "Apollo_Models")
APOLLO_CONFIG_PATH = os.path.join(APOLLO_MODELS_DIR, "model_configs")
APOLLO_HASH_DIR = os.path.join(APOLLO_MODELS_DIR, "model_data")
APOLLO_HASH_JSON = os.path.join(APOLLO_HASH_DIR, "model_data.json")

DENOISER_MODEL_PATH = os.path.join(VR_MODELS_DIR, "UVR-DeNoise-Lite.pth")
DEVERBER_MODEL_PATH = os.path.join(VR_MODELS_DIR, "UVR-DeEcho-DeReverb.pth")

SAMPLE_CLIP_PATH = os.path.join(DATA_DIR, "temp_sample_clips")
ENSEMBLE_TEMP_PATH = os.path.join(DATA_DIR, "ensemble_temps")

SETTINGS_DATA_FILE = os.path.join(DATA_DIR, "data.pkl")

# Saved ensembles / settings profiles (JSON). Writable under DATA_DIR.
SETTINGS_CACHE_DIR = os.path.join(DATA_DIR, "profiles")
ENSEMBLE_CACHE_DIR = os.path.join(DATA_DIR, "ensembles")

# Legacy paths from the Tk / early GTK layout (``gui_data/saved_*``).
_LEGACY_SETTINGS_DIRS = (
    os.path.join(BASE_PATH, "gui_data", "saved_settings"),
    os.path.join(DATA_DIR, "gui_data", "saved_settings"),
)
_LEGACY_ENSEMBLE_DIRS = (
    os.path.join(BASE_PATH, "gui_data", "saved_ensembles"),
    os.path.join(DATA_DIR, "gui_data", "saved_ensembles"),
)


def _migrate_legacy_dir(legacy_dir: str, target_dir: str) -> None:
    """Move ``*.json`` from a legacy cache folder into ``target_dir`` once."""
    if not os.path.isdir(legacy_dir):
        return
    os.makedirs(target_dir, exist_ok=True)
    for name in os.listdir(legacy_dir):
        if not name.endswith(".json"):
            continue
        src = os.path.join(legacy_dir, name)
        dst = os.path.join(target_dir, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.move(src, dst)
    try:
        remaining = os.listdir(legacy_dir)
        if not remaining or all(entry.endswith(".txt") for entry in remaining):
            shutil.rmtree(legacy_dir)
    except OSError:
        pass


def _migrate_legacy_data_layout() -> None:
    """One-time move from ``gui_data/saved_*`` to ``profiles/`` / ``ensembles/``."""
    for legacy in _LEGACY_SETTINGS_DIRS:
        _migrate_legacy_dir(legacy, SETTINGS_CACHE_DIR)
    for legacy in _LEGACY_ENSEMBLE_DIRS:
        _migrate_legacy_dir(legacy, ENSEMBLE_CACHE_DIR)
    legacy_gui_data = os.path.join(BASE_PATH, "gui_data")
    if os.path.isdir(legacy_gui_data) and not os.listdir(legacy_gui_data):
        try:
            os.rmdir(legacy_gui_data)
        except OSError:
            pass


def ensure_data_dir() -> None:
    """Create the writable runtime tree and seed bundled data when relocated.

    Idempotent. When ``DATA_DIR == BASE_PATH`` (the common dev/portable case)
    this only ensures the directories exist; ``BUNDLED_MODELS_DIR`` and
    ``MODELS_DIR`` are identical so no seeding/copying onto itself occurs.
    """
    from .debug_log import debug

    os.makedirs(DATA_DIR, exist_ok=True)
    writable = os.access(DATA_DIR, os.W_OK)
    debug(
        "settings",
        f"ensure_data_dir DATA_DIR={DATA_DIR} bundled_relocated={BUNDLED_MODELS_DIR != MODELS_DIR} writable={writable}",
    )
    _migrate_legacy_data_layout()
    for directory in (
        MODELS_DIR,
        VR_MODELS_DIR,
        MDX_MODELS_DIR,
        DEMUCS_MODELS_DIR,
        DEMUCS_NEWER_REPO_DIR,
        VR_HASH_DIR,
        MDX_HASH_DIR,
        MDX_C_CONFIG_PATH,
        APOLLO_MODELS_DIR,
        APOLLO_CONFIG_PATH,
        APOLLO_HASH_DIR,
        os.path.dirname(DEMUCS_MODEL_NAME_SELECT),
        os.path.dirname(MDX_MODEL_NAME_SELECT),
        SAMPLE_CLIP_PATH,
        ENSEMBLE_TEMP_PATH,
        ENSEMBLE_CACHE_DIR,
        SETTINGS_CACHE_DIR,
    ):
        os.makedirs(directory, exist_ok=True)

    # Only seed when the writable tree is relocated away from the bundled one.
    if BUNDLED_MODELS_DIR == MODELS_DIR:
        return

    debug("settings", "ensure_data_dir seeding bundled model data")

    _seed_bundled_file(
        os.path.join(BUNDLED_MODELS_DIR, "VR_Models", "model_data", "model_data.json"),
        VR_HASH_JSON,
    )
    _seed_bundled_file(
        os.path.join(BUNDLED_MODELS_DIR, "MDX_Net_Models", "model_data", "model_data.json"),
        MDX_HASH_JSON,
    )
    _seed_bundled_file(
        os.path.join(BUNDLED_MODELS_DIR, "MDX_Net_Models", "model_data", "model_name_mapper.json"),
        MDX_MODEL_NAME_SELECT,
    )
    _seed_bundled_file(
        os.path.join(BUNDLED_MODELS_DIR, "Demucs_Models", "model_data", "model_name_mapper.json"),
        DEMUCS_MODEL_NAME_SELECT,
    )

    # Seed the bundled MDX-C config YAMLs.
    bundled_mdx_c = os.path.join(BUNDLED_MODELS_DIR, "MDX_Net_Models", "model_data", "mdx_c_configs")
    if os.path.isdir(bundled_mdx_c):
        for name in os.listdir(bundled_mdx_c):
            _seed_bundled_file(
                os.path.join(bundled_mdx_c, name),
                os.path.join(MDX_C_CONFIG_PATH, name),
            )

    # Seed the bundled Apollo per-hash param JSONs and model configs (the model
    # checkpoints themselves are downloaded by the user into Apollo_Models/).
    bundled_apollo_data = os.path.join(BUNDLED_MODELS_DIR, "Apollo_Models", "model_data")
    if os.path.isdir(bundled_apollo_data):
        for name in os.listdir(bundled_apollo_data):
            _seed_bundled_file(
                os.path.join(bundled_apollo_data, name),
                os.path.join(APOLLO_HASH_DIR, name),
            )
    bundled_apollo_configs = os.path.join(BUNDLED_MODELS_DIR, "Apollo_Models", "model_configs")
    if os.path.isdir(bundled_apollo_configs):
        for name in os.listdir(bundled_apollo_configs):
            _seed_bundled_file(
                os.path.join(bundled_apollo_configs, name),
                os.path.join(APOLLO_CONFIG_PATH, name),
            )


def _seed_bundled_file(src: str, dst: str) -> None:
    """Copy a bundled seed file to the writable tree if missing.

    Defensive: skips silently when the bundled source is absent and never
    overwrites an existing writable copy.
    """
    if not os.path.isfile(src):
        return
    if os.path.exists(dst):
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
