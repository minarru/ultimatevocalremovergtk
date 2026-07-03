"""Tk-free backend for the Download Center, model-data refresh and updates.

This is the framework-agnostic port of ``UVR.py``'s "Download Center Methods"
(``online_data_refresh`` / ``download_list_fill`` / ``download_model_select`` /
``download_item`` / ``download_model_settings`` / ``download_validate_code``) and
the VIP-code decryption (``vip_downloads``). It reuses the exact remote URLs and
model-list JSON schema UVR uses (see :mod:`data.constants`), so the GTK
front end downloads the same files into the same model directories.

Everything here is import-safe without ``torch``: only the standard library plus
``cryptography`` (lazy-imported, and only for VIP-code validation) are used.
Network and disk work happens on caller-supplied worker threads; this module
never touches any UI toolkit and reports progress through plain callbacks.
"""

import json
import os
import ssl
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

from data.constants import (
    ALL_TYPES,
    BULLETIN_CHECK,
    DEMUCS_ARCH_TYPE,
    DEMUCS_MODEL_NAME_DATA_LINK,
    DEMUCS_NEWER_ARCH_TYPES,
    DOWNLOAD_CHECKS,
    INFO_UNAVAILABLE_TEXT,
    MDX23_CONFIG_CHECKS,
    MDX_ARCH_TYPE,
    MDX_MODEL_DATA_LINK,
    MDX_MODEL_NAME_DATA_LINK,
    NO_CODE,
    NO_MODEL,
    NO_NEW_MODELS,
    NORMAL_REPO,
    OPERATING_SYSTEM,
    UPDATE_LINUX_REPO,
    UPDATE_MAC_X86_64_REPO,
    UPDATE_REPO,
    VIP_REPO,
    VIP_SELECTION,
    VR_ARCH_TYPE,
    VR_MODEL_DATA_LINK,
)

from . import paths

try:  # The version constants live at the repo root (reused verbatim from UVR).
    from __version__ import PATCH, PATCH_LINUX, PATCH_MAC, VERSION
except Exception:  # pragma: no cover - defensive only
    VERSION = ""
    PATCH = PATCH_LINUX = PATCH_MAC = ""

DOWNLOAD_MODEL_CACHE = paths.DOWNLOAD_MODEL_CACHE_PATH

# Mapper JSON download links paired with their on-disk destinations (the exact
# four files ``download_model_settings`` refreshes).
_MODEL_DATA_URLS = [
    (VR_MODEL_DATA_LINK, paths.VR_HASH_JSON),
    (MDX_MODEL_DATA_LINK, paths.MDX_HASH_JSON),
    (MDX_MODEL_NAME_DATA_LINK, paths.MDX_MODEL_NAME_SELECT),
    (DEMUCS_MODEL_NAME_DATA_LINK, paths.DEMUCS_MODEL_NAME_SELECT),
]


def _current_patch() -> str:
    if OPERATING_SYSTEM == "Darwin":
        return PATCH_MAC
    if OPERATING_SYSTEM == "Linux":
        return PATCH_LINUX
    return PATCH


def _latest_version_key() -> str:
    if OPERATING_SYSTEM == "Darwin":
        return "current_version_mac"
    if OPERATING_SYSTEM == "Linux":
        return "current_version_linux"
    return "current_version"


def _ssl_context() -> ssl.SSLContext:
    """Return a TLS context; set ``UVR_INSECURE_DOWNLOADS=1`` to disable verification."""
    if os.environ.get("UVR_INSECURE_DOWNLOADS") == "1":
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def _urlopen(url: str):
    return urllib.request.urlopen(url, context=_ssl_context())


def vip_downloads(password: str, link_type: Tuple[bytes, bytes] = VIP_REPO) -> str:
    """Decrypt the VIP model repo link with ``password`` (port of UVR's helper).

    Returns the decrypted repo URL on success, or :data:`NO_CODE` when the code
    is wrong or ``cryptography`` is unavailable.
    """
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        import base64

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=link_type[0],
            iterations=390000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(bytes(password, "utf-8")))
        f = Fernet(key)
        return str(f.decrypt(link_type[1]), "UTF-8")
    except Exception:
        return NO_CODE


class DownloadManager:
    """Holds the online model catalogue and performs downloads / update checks.

    A single instance is shared by the Download Center and the update view. All
    network calls are synchronous and meant to be driven from a worker thread;
    callers marshal the supplied callbacks onto the GTK main loop.
    """

    def __init__(self):
        self.online_data: Dict = {}
        self.bulletin_data: str = INFO_UNAVAILABLE_TEXT
        self.is_online: bool = False
        self.decoded_vip_link: str = NO_CODE
        self.latest_version: str = ""

        # VIP-merged, on-disk-aware catalogues (populated by ``refresh``).
        self.vr_download_list: Dict[str, str] = {}
        self.mdx_download_list: Dict[str, object] = {}
        self.demucs_download_list: Dict[str, dict] = {}

    # -- Online refresh ---------------------------------------------------------

    def refresh(self) -> bool:
        """Fetch the catalogue + bulletin. Returns ``True`` when online.

        Mirrors the network half of ``online_data_refresh``: on success the
        download lists and the latest-version string are populated; on any
        failure the manager flips to the offline state.
        """
        try:
            with _urlopen(DOWNLOAD_CHECKS) as response:
                self.online_data = json.load(response)
            self.is_online = True
        except Exception:
            self.is_online = False
            return False

        try:
            with _urlopen(BULLETIN_CHECK) as response:
                bulletin = response.read().decode("utf-8")
            self.bulletin_data = bulletin.replace("~", "\u2022")
        except Exception:
            self.bulletin_data = INFO_UNAVAILABLE_TEXT

        self.latest_version = self.online_data.get(_latest_version_key(), "")
        self._rebuild_catalogues()
        return True

    def _rebuild_catalogues(self) -> None:
        """Build the VIP-merged catalogues from ``online_data`` (no disk filter)."""
        self.vr_download_list = dict(self.online_data.get("vr_download_list", {}))
        self.mdx_download_list = dict(self.online_data.get("mdx_download_list", {}))
        self.mdx_download_list.update(self.online_data.get("mdx23c_download_list", {}))
        # Roformer models (BS-Roformer / Mel-Band Roformer) ship in their own
        # ``roformer_download_list`` but use the same compact
        # ``{selectable: {checkpoint: config_yaml}}`` schema as MDX23-C, so they
        # resolve through the MDX download path. Merge them into the MDX list so
        # they show up under the MDX-Net network in the Download Center.
        self.mdx_download_list.update(self.online_data.get("roformer_download_list", {}))
        self.demucs_download_list = dict(self.online_data.get("demucs_download_list", {}))

        if self.decoded_vip_link != NO_CODE:
            self.vr_download_list.update(self.online_data.get("vr_download_vip_list", {}))
            self.mdx_download_list.update(self.online_data.get("mdx_download_vip_list", {}))
            self.mdx_download_list.update(self.online_data.get("mdx23c_download_vip_list", {}))
            self.mdx_download_list.update(self.online_data.get("roformer_download_vip_list", {}))

    # -- VIP code ---------------------------------------------------------------

    def validate_vip_code(self, code: str) -> bool:
        """Validate a VIP code; on success unlock the VIP models. Port of
        ``download_validate_code``."""
        self.decoded_vip_link = vip_downloads(code or "")
        unlocked = self.decoded_vip_link != NO_CODE
        if unlocked and self.online_data:
            self._rebuild_catalogues()
        return unlocked

    # -- Download lists ---------------------------------------------------------

    def available_downloads(self, model_type: str = ALL_TYPES) -> Dict[str, List[str]]:
        """Return ``{arch_type: [selectable, ...]}`` of not-yet-downloaded models.

        Faithful port of ``download_list_fill``: filters each catalogue entry by
        whether the target file already exists on disk, and (for MDX23-C) fetches
        any missing config YAML so the model is usable once downloaded.
        """
        result: Dict[str, List[str]] = {}

        if model_type in (VR_ARCH_TYPE, ALL_TYPES):
            vr_list = [
                selectable
                for selectable, model in self.vr_download_list.items()
                if not os.path.isfile(os.path.join(paths.VR_MODELS_DIR, model))
            ]
            result[VR_ARCH_TYPE] = vr_list or [NO_NEW_MODELS]

        if model_type in (MDX_ARCH_TYPE, ALL_TYPES):
            mdx_list: List[str] = []
            for selectable, model in self.mdx_download_list.items():
                if isinstance(model, dict):
                    items_list = list(model.items())
                    model_name, config = items_list[0]
                    self._ensure_mdx_c_config(config)
                else:
                    model_name = str(model)
                if not os.path.isfile(os.path.join(paths.MDX_MODELS_DIR, model_name)):
                    mdx_list.append(selectable)
            result[MDX_ARCH_TYPE] = mdx_list or [NO_NEW_MODELS]

        if model_type in (DEMUCS_ARCH_TYPE, ALL_TYPES):
            demucs_list: List[str] = []
            for selectable, model in self.demucs_download_list.items():
                for file_name in model.keys():
                    if any(x in selectable for x in DEMUCS_NEWER_ARCH_TYPES):
                        target = os.path.join(paths.DEMUCS_NEWER_REPO_DIR, file_name)
                    else:
                        target = os.path.join(paths.DEMUCS_MODELS_DIR, file_name)
                    if not os.path.isfile(target):
                        demucs_list.append(selectable)
            # Preserve order while de-duplicating (matches dict.fromkeys in UVR).
            demucs_list = list(dict.fromkeys(demucs_list))
            result[DEMUCS_ARCH_TYPE] = demucs_list or [NO_NEW_MODELS]

        return result

    def _ensure_mdx_c_config(self, config: str) -> None:
        config_local = os.path.join(paths.MDX_C_CONFIG_PATH, config)
        if os.path.isfile(config_local):
            return
        try:
            os.makedirs(paths.MDX_C_CONFIG_PATH, exist_ok=True)
            with _urlopen(f"{MDX23_CONFIG_CHECKS}{config}") as response:
                with open(config_local, "wb") as out_file:
                    out_file.write(response.read())
        except Exception:
            pass

    # -- Resolve a selection to concrete download jobs --------------------------

    def resolve(self, selection: str, arch_type: str) -> List[Tuple[str, str]]:
        """Return ``[(url, save_path), ...]`` for ``selection``.

        Port of ``download_model_select`` + the per-arch branches of
        ``download_item``. VR/MDX yield a single job; Demucs v3/v4 ("newer") yield
        one job per checkpoint/yaml file.
        """
        if not selection or selection in (NO_MODEL, NO_NEW_MODELS):
            return []

        model_repo = self.decoded_vip_link if VIP_SELECTION in selection else NORMAL_REPO

        if arch_type == VR_ARCH_TYPE:
            model = self.vr_download_list.get(selection)
            if not model:
                return []
            return [(f"{model_repo}{model}", os.path.join(paths.VR_MODELS_DIR, model))]

        if arch_type == MDX_ARCH_TYPE:
            model = self.mdx_download_list.get(selection)
            if model is None:
                return []
            model_name = list(model.keys())[0] if isinstance(model, dict) else str(model)
            return [(f"{model_repo}{model_name}", os.path.join(paths.MDX_MODELS_DIR, model_name))]

        if arch_type == DEMUCS_ARCH_TYPE:
            model = self.demucs_download_list.get(selection)
            if not model:
                return []
            is_newer = any(x in selection for x in DEMUCS_NEWER_ARCH_TYPES)
            jobs: List[Tuple[str, str]] = []
            for file_name, url in model.items():
                directory = paths.DEMUCS_NEWER_REPO_DIR if is_newer else paths.DEMUCS_MODELS_DIR
                jobs.append((url, os.path.join(directory, file_name)))
            return jobs

        return []

    # -- Downloading ------------------------------------------------------------

    def download(
        self,
        jobs: List[Tuple[str, str]],
        on_progress: Optional[Callable[[float], None]] = None,
        on_info: Optional[Callable[[str], None]] = None,
        stop_event=None,
    ) -> str:
        """Download every ``(url, save_path)`` job sequentially.

        Reports overall progress in ``[0, 1]`` via ``on_progress`` and a short
        status string via ``on_info``. Honours a ``threading.Event``-style
        ``stop_event`` for cooperative cancellation (checked between chunks).
        Returns one of ``"complete"`` / ``"stopped"`` / ``"exists"``; raises on
        network/IO error so the caller can surface it through the error log.
        """
        from .debug_log import debug, debug_elapsed

        if not jobs:
            if on_info:
                on_info(NO_MODEL)
            return "exists"

        started = time.perf_counter()
        debug("download", f"download start jobs={len(jobs)}")
        total = len(jobs)
        any_downloaded = False
        for index, (url, save_path) in enumerate(jobs):
            if stop_event is not None and stop_event.is_set():
                return "stopped"
            if on_info:
                on_info(f"Downloading Item {index + 1}/{total}...")
            if os.path.isfile(save_path):
                continue
            any_downloaded = True
            self._download_file(url, save_path, index, total, on_progress, stop_event)
            if stop_event is not None and stop_event.is_set():
                # Remove the partial file so a retry restarts cleanly.
                if os.path.isfile(save_path):
                    try:
                        os.remove(save_path)
                    except OSError:
                        pass
                return "stopped"

        if on_progress:
            on_progress(1.0)
        result = "complete" if any_downloaded else "exists"
        debug_elapsed("download", f"download done status={result}", started)
        return result

    def _download_file(self, url, save_path, index, total, on_progress, stop_event) -> None:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        tmp_path = f"{save_path}.part"
        try:
            with _urlopen(url) as response:
                length_header = response.getheader("Content-Length")
                file_total = int(length_header) if length_header and length_header.isdigit() else 0
                downloaded = 0
                with open(tmp_path, "wb") as out_file:
                    while True:
                        if stop_event is not None and stop_event.is_set():
                            out_file.close()
                            if os.path.isfile(tmp_path):
                                try:
                                    os.remove(tmp_path)
                                except OSError:
                                    pass
                            return
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)
                        if on_progress and file_total:
                            file_fraction = downloaded / file_total
                            overall = (index + file_fraction) / total
                            on_progress(max(0.0, min(1.0, overall)))
            os.replace(tmp_path, save_path)
        except Exception:
            if os.path.isfile(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    # -- Model-data mapper refresh ----------------------------------------------

    def update_model_settings(self, repo=None) -> bool:
        """Download and persist the four model-data mapper JSON files.

        Port of ``download_model_settings``; on any failure existing local files
        are left untouched. Returns ``True`` on a successful refresh.

        When ``repo`` is supplied, its stem-check cache is invalidated after a
        successful refresh so model lists reflect the new mapper data.
        """
        try:
            fetched = []
            for url, _dest in _MODEL_DATA_URLS:
                with _urlopen(url) as response:
                    fetched.append(json.load(response))
        except Exception:
            return False

        for (url, dest), data in zip(_MODEL_DATA_URLS, fetched):
            try:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "w") as out_file:
                    out_file.write(json.dumps(data, indent=4))
            except OSError:
                continue
        if repo is not None:
            repo.invalidate_stem_check()
        return True

    # -- Update check -----------------------------------------------------------

    def update_status(self) -> Dict[str, object]:
        """Return the app version / update status (port of the update half of
        ``online_data_refresh``).

        Keys: ``current`` (running patch), ``version`` (UVR semantic version),
        ``latest`` (newest patch online or ``''``), ``is_current`` bool,
        ``is_online`` bool, ``update_link`` (download/instructions URL).
        """
        current = _current_patch()
        latest = self.latest_version
        is_current = bool(latest) and latest == current

        if OPERATING_SYSTEM == "Linux":
            update_link = UPDATE_LINUX_REPO
        elif OPERATING_SYSTEM == "Darwin":
            update_link = UPDATE_MAC_X86_64_REPO
        else:
            update_link = f"{UPDATE_REPO}{latest}.zip" if latest else UPDATE_REPO

        return {
            "current": current,
            "version": VERSION,
            "latest": latest,
            "is_current": is_current,
            "is_online": self.is_online,
            "update_link": update_link,
        }

    # -- Manual downloads -------------------------------------------------------

    def manual_download_data(self) -> Dict[str, dict]:
        """Return ``{vr, mdx, demucs}`` link catalogues for the manual flow.

        Prefers the live ``online_data`` (VIP-merged), falling back to the bundled
        ``model_manual_download.json`` cache - exactly the source priority
        ``menu_manual_downloads`` uses.
        """
        source = self.online_data if self.online_data else self._load_cache()

        vr = dict(source.get("vr_download_list", {}))
        mdx = dict(source.get("mdx_download_list", {}))
        mdx.update(source.get("mdx23c_download_list", {}))
        mdx.update(source.get("roformer_download_list", {}))
        demucs = dict(source.get("demucs_download_list", {}))

        if self.decoded_vip_link != NO_CODE:
            vr.update(source.get("vr_download_vip_list", {}))
            mdx.update(source.get("mdx_download_vip_list", {}))
            mdx.update(source.get("mdx23c_download_vip_list", {}))
            mdx.update(source.get("roformer_download_vip_list", {}))

        return {"vr": vr, "mdx": mdx, "demucs": demucs}

    @staticmethod
    def _load_cache() -> Dict:
        try:
            with open(DOWNLOAD_MODEL_CACHE, "r") as cache_file:
                return json.load(cache_file)
        except (OSError, ValueError):
            return {}

    @staticmethod
    def manual_links(arch_type: str, model) -> List[Tuple[str, str]]:
        """Return ``[(label, url), ...]`` direct links for a manual-download entry.

        VR/MDX models live in the public release repo (``NORMAL_REPO`` + file);
        MDX23-C and Demucs entries are dicts whose values are already full URLs.
        """
        links: List[Tuple[str, str]] = []
        if arch_type == VR_ARCH_TYPE:
            links.append(("Open Link to Model", f"{NORMAL_REPO}{model}"))
        elif arch_type == MDX_ARCH_TYPE:
            if isinstance(model, dict):
                model_name = list(model.keys())[0]
                links.append(("Open Link to Model", f"{NORMAL_REPO}{model_name}"))
            else:
                links.append(("Open Link to Model", f"{NORMAL_REPO}{model}"))
        elif arch_type == DEMUCS_ARCH_TYPE and isinstance(model, dict):
            multi = len(model) > 1
            for number, url in enumerate(model.values(), start=1):
                suffix = f" {number}" if multi else ""
                links.append((f"Open Link to Model{suffix}", url))
        return links

    @staticmethod
    def model_directory(arch_type: str, selection: str = "") -> str:
        """Return the on-disk directory a manually-downloaded model belongs in."""
        if arch_type == VR_ARCH_TYPE:
            return paths.VR_MODELS_DIR
        if arch_type == MDX_ARCH_TYPE:
            return paths.MDX_MODELS_DIR
        if arch_type == DEMUCS_ARCH_TYPE:
            if any(x in selection for x in DEMUCS_NEWER_ARCH_TYPES):
                return paths.DEMUCS_NEWER_REPO_DIR
            return paths.DEMUCS_MODELS_DIR
        return paths.MODELS_DIR
