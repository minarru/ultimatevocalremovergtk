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

import errno
import json
import os
import ssl
import threading
import time
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

from bundled.constants import (
    ALL_TYPES,
    APOLLO_ARCH_TYPE,
    BULLETIN_CHECK,
    DEMUCS_ARCH_TYPE,
    DEMUCS_MODEL_NAME_DATA_LINK,
    DEMUCS_NEWER_ARCH_TYPES,
    DOWNLOAD_CHECKS,
    INFO_UNAVAILABLE_TEXT,
    MDX_ARCH_TYPE,
    MDX_MODEL_DATA_LINK,
    MDX_MODEL_NAME_DATA_LINK,
    NO_CODE,
    NO_MODEL,
    NO_NEW_MODELS,
    NORMAL_REPO,
    OPERATING_SYSTEM,
    VIP_REPO,
    VIP_SELECTION,
    VR_ARCH_TYPE,
    VR_MODEL_DATA_LINK,
)

from . import paths
from .debug_log import debug
from .download_sizes import (
    describe_download_size,
    estimate_jobs_size,
    format_download_size,
    prefetch_remote_sizes,
)
from .extra_catalog import apollo_download_list, merge_extra_catalogues
from .mdx_config_fetch import ensure_mdx_c_config
from .politrees_catalog import (
    apollo_checkpoint_filename,
    hf_fallback_url,
    load_politrees_links,
    manual_links_for_model,
    mdx_checkpoint_filename,
    merge_politrees_catalogues,
    resolve_apollo_jobs,
    resolve_demucs_jobs,
    resolve_mdx_jobs,
    resolve_vr_jobs,
)
from .version_info import release_update_status

DOWNLOAD_MODEL_CACHE = paths.DOWNLOAD_MODEL_CACHE_PATH
# Minimum interval between byte-count status strings shown in the queue UI.
_INFO_UPDATE_INTERVAL_S = 0.25

# Mapper JSON download links paired with their on-disk destinations (the exact
# four files ``download_model_settings`` refreshes).
_MODEL_DATA_URLS = [
    (VR_MODEL_DATA_LINK, paths.VR_HASH_JSON),
    (MDX_MODEL_DATA_LINK, paths.MDX_HASH_JSON),
    (MDX_MODEL_NAME_DATA_LINK, paths.MDX_MODEL_NAME_SELECT),
    (DEMUCS_MODEL_NAME_DATA_LINK, paths.DEMUCS_MODEL_NAME_SELECT),
]


def _latest_version_key() -> str:
    if OPERATING_SYSTEM == "Darwin":
        return "current_version_mac"
    if OPERATING_SYSTEM == "Linux":
        return "current_version_linux"
    return "current_version"


_DOWNLOAD_TIMEOUT_SECONDS = 30


def _ssl_context() -> ssl.SSLContext:
    """Return a TLS context; set ``UVR_INSECURE_DOWNLOADS=1`` to disable verification."""
    if os.environ.get("UVR_INSECURE_DOWNLOADS") == "1":
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def _urlopen(url: str):
    return urllib.request.urlopen(url, context=_ssl_context(), timeout=_DOWNLOAD_TIMEOUT_SECONDS)


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
        # Apollo restoration models are fork-curated only (no upstream list).
        self.apollo_download_list: Dict[str, dict] = {}
        self._size_warmup_lock = threading.Lock()

    # -- Catalogue + size cache -------------------------------------------------

    def _has_any_catalogue(self) -> bool:
        return bool(
            self.vr_download_list
            or self.mdx_download_list
            or self.demucs_download_list
            or self.apollo_download_list
        )

    def ensure_catalogues(self) -> bool:
        """Populate download catalogues from in-memory, bundled, or Politrees data."""
        if self._has_any_catalogue():
            return True
        if self.online_data:
            self._rebuild_catalogues()
            self._merge_politrees_supplement()
            if self._has_any_catalogue():
                return True
        self.online_data = self._load_cache()
        if not self.online_data:
            debug("download", "ensure_catalogues no bundled cache")
            # Apollo (and any other fork-curated list) is bundled locally, so it
            # is still available with no upstream cache at all.
            self._merge_politrees_supplement()
            return self._has_any_catalogue()
        self._rebuild_catalogues()
        self._merge_politrees_supplement()
        debug(
            "download",
            "ensure_catalogues bundled fallback "
            f"vr={len(self.vr_download_list)} "
            f"mdx={len(self.mdx_download_list)} "
            f"demucs={len(self.demucs_download_list)} "
            f"apollo={len(self.apollo_download_list)}",
        )
        return self._has_any_catalogue()

    def catalogue_urls(self) -> List[str]:
        """Unique remote URLs for every catalogue entry."""
        urls: set[str] = set()
        for arch_type, catalogue in (
            (VR_ARCH_TYPE, self.vr_download_list),
            (MDX_ARCH_TYPE, self.mdx_download_list),
            (DEMUCS_ARCH_TYPE, self.demucs_download_list),
            (APOLLO_ARCH_TYPE, self.apollo_download_list),
        ):
            for name in catalogue:
                for url, _path in self.resolve(name, arch_type):
                    urls.add(url)
        return sorted(urls)

    def warm_size_cache(self) -> Dict[str, int]:
        """Prefetch remote sizes for catalogue URLs (7-day TTL)."""
        if not self.ensure_catalogues():
            debug("download", "size_cache_warmup skip no catalogues")
            return {"total": 0, "fresh": 0, "fetched": 0, "failed": 0}

        if not self._size_warmup_lock.acquire(blocking=False):
            debug("download", "size_cache_warmup skip already running")
            return {"total": 0, "fresh": 0, "fetched": 0, "failed": 0}

        from .debug_log import debug_elapsed

        try:
            urls = self.catalogue_urls()
            debug("download", f"size_cache_warmup start urls={len(urls)}")
            started = time.perf_counter()
            stats = prefetch_remote_sizes(urls)
            debug_elapsed(
                "download",
                "size_cache_warmup done "
                f"total={stats['total']} fresh={stats['fresh']} "
                f"fetched={stats['fetched']} failed={stats['failed']}",
                started,
            )
            return stats
        finally:
            self._size_warmup_lock.release()

    def schedule_size_cache_warmup(self) -> None:
        """Kick off a background size-cache refresh (idempotent per process)."""
        threading.Thread(target=self.warm_size_cache, daemon=True).start()

    # -- Online refresh ---------------------------------------------------------

    def refresh(self) -> bool:
        """Fetch the catalogue + bulletin. Returns ``True`` when online.

        Mirrors the network half of ``online_data_refresh``: on success the
        download lists and the latest-version string are populated; on any
        failure the manager flips to the offline state.
        """
        debug("download", "refresh start")
        try:
            with _urlopen(DOWNLOAD_CHECKS) as response:
                self.online_data = json.load(response)
            self.is_online = True
        except Exception as exc:
            self.is_online = False
            debug("download", f"refresh offline error={type(exc).__name__}: {exc}")
            return False

        try:
            with _urlopen(BULLETIN_CHECK) as response:
                bulletin = response.read().decode("utf-8")
            self.bulletin_data = bulletin.replace("~", "\u2022")
        except Exception:
            self.bulletin_data = INFO_UNAVAILABLE_TEXT

        self.latest_version = self.online_data.get(_latest_version_key(), "")
        self._rebuild_catalogues()
        self._merge_politrees_supplement()
        debug(
            "download",
            "refresh online "
            f"vr={len(self.vr_download_list)} "
            f"mdx={len(self.mdx_download_list)} "
            f"demucs={len(self.demucs_download_list)} "
            f"latest={self.latest_version!r}",
        )
        self.schedule_size_cache_warmup()
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
            self._merge_politrees_supplement()
        debug("download", f"vip_validate unlocked={unlocked}")
        return unlocked

    def _merge_politrees_supplement(self) -> None:
        politrees = load_politrees_links()
        if politrees:
            self.vr_download_list, self.mdx_download_list, self.demucs_download_list = (
                merge_politrees_catalogues(
                    self.vr_download_list,
                    self.mdx_download_list,
                    self.demucs_download_list,
                    politrees,
                )
            )
        # Fork-curated entries merge last so they fill gaps without ever
        # shadowing an upstream label, and survive ``refresh`` replacing
        # ``online_data`` wholesale.
        self.vr_download_list, self.mdx_download_list, self.demucs_download_list = (
            merge_extra_catalogues(
                self.vr_download_list,
                self.mdx_download_list,
                self.demucs_download_list,
            )
        )
        self.apollo_download_list = apollo_download_list()

    # -- Download lists ---------------------------------------------------------

    def available_downloads(self, model_type: str = ALL_TYPES) -> Dict[str, List[str]]:
        """Return ``{arch_type: [selectable, ...]}`` of not-yet-downloaded models.

        Faithful port of ``download_list_fill``: filters each catalogue entry by
        whether the target file already exists on disk. Config YAMLs are fetched
        when a model is resolved for download, not while building this list.
        """
        result: Dict[str, List[str]] = {}

        if model_type in (VR_ARCH_TYPE, ALL_TYPES):
            vr_list = [
                selectable
                for selectable, model in self.vr_download_list.items()
                if not os.path.isfile(
                    os.path.join(
                        paths.VR_MODELS_DIR,
                        mdx_checkpoint_filename(model) if isinstance(model, dict) else model,
                    )
                )
            ]
            result[VR_ARCH_TYPE] = vr_list or [NO_NEW_MODELS]

        if model_type in (MDX_ARCH_TYPE, ALL_TYPES):
            mdx_list: List[str] = []
            for selectable, model in self.mdx_download_list.items():
                if isinstance(model, dict):
                    model_name = mdx_checkpoint_filename(model)
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

        if model_type in (APOLLO_ARCH_TYPE, ALL_TYPES):
            apollo_list = [
                selectable
                for selectable, model in self.apollo_download_list.items()
                if not os.path.isfile(
                    os.path.join(paths.APOLLO_MODELS_DIR, apollo_checkpoint_filename(model))
                )
            ]
            result[APOLLO_ARCH_TYPE] = apollo_list or [NO_NEW_MODELS]

        return result

    def _ensure_mdx_c_config(self, config: str) -> None:
        ensure_mdx_c_config(config)

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
            return resolve_vr_jobs(model, model_repo)

        if arch_type == MDX_ARCH_TYPE:
            model = self.mdx_download_list.get(selection)
            if model is None:
                return []
            return resolve_mdx_jobs(model, model_repo)

        if arch_type == DEMUCS_ARCH_TYPE:
            model = self.demucs_download_list.get(selection)
            if not model:
                return []
            return resolve_demucs_jobs(model, selection)

        if arch_type == APOLLO_ARCH_TYPE:
            model = self.apollo_download_list.get(selection)
            if not model:
                return []
            return resolve_apollo_jobs(model)

        return []

    def describe_selection_download_size(self, selection: str, arch_type: str) -> str:
        """Human-readable size estimate for a catalogue selection."""
        jobs = self.resolve(selection, arch_type)
        if not jobs:
            return "—"
        return describe_download_size(jobs)

    # -- Downloading ------------------------------------------------------------

    def download(
        self,
        jobs: List[Tuple[str, str]],
        on_progress: Optional[Callable[[float], None]] = None,
        on_info: Optional[Callable[[str], None]] = None,
        stop_event=None,
        repo=None,
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
        pending_jobs = [(url, path) for url, path in jobs if not os.path.isfile(path)]
        total_bytes, _file_count, _known = estimate_jobs_size(pending_jobs)
        total = len(jobs)
        any_downloaded = False
        for index, (url, save_path) in enumerate(jobs):
            if stop_event is not None and stop_event.is_set():
                debug("download", "download stopped by user")
                return "stopped"
            if os.path.isfile(save_path):
                continue
            any_downloaded = True
            if on_info:
                if total_bytes is not None:
                    on_info(f"Downloading ({format_download_size(total_bytes)})")
                else:
                    on_info("Downloading…")
            self._download_file(url, save_path, index, total, on_progress, stop_event, on_info)
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
        if result in ("complete", "exists"):
            from .apollo_registry import register_apollo_from_download_jobs
            from .mdx_c_registry import register_mdx_c_from_download_jobs

            if register_mdx_c_from_download_jobs(jobs) and repo is not None:
                repo.invalidate_stem_check()
                repo.reload_mappers()
            # Apollo models are recognised by an md5 -> config_yaml mapping;
            # write it now so the Audio Tools picker does not prompt for a
            # config the catalogue already specified.
            register_apollo_from_download_jobs(jobs)
        debug_elapsed("download", f"download done status={result}", started)
        return result

    @staticmethod
    def _download_stopped(stop_event) -> bool:
        return stop_event is not None and stop_event.is_set()

    def _finalize_part_file(self, tmp_path: str, save_path: str, stop_event) -> None:
        """Rename a completed ``.part`` file unless the download was cancelled."""
        if self._download_stopped(stop_event):
            return
        if not os.path.isfile(tmp_path):
            raise FileNotFoundError(
                errno.ENOENT,
                os.strerror(errno.ENOENT),
                tmp_path,
            )
        os.replace(tmp_path, save_path)

    def _download_file(self, url, save_path, index, total, on_progress, stop_event, on_info=None) -> None:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        tmp_path = f"{save_path}.part"
        try:
            self._download_file_url(url, tmp_path, index, total, on_progress, stop_event, on_info)
            if self._download_stopped(stop_event):
                return
            self._finalize_part_file(tmp_path, save_path, stop_event)
        except Exception:
            if self._download_stopped(stop_event):
                return
            fallback = hf_fallback_url(url)
            if fallback and fallback != url:
                debug("download", f"hf fallback {os.path.basename(save_path)}")
                try:
                    if os.path.isfile(tmp_path):
                        os.remove(tmp_path)
                except OSError:
                    pass
                self._download_file_url(
                    fallback, tmp_path, index, total, on_progress, stop_event, on_info
                )
                if self._download_stopped(stop_event):
                    return
                self._finalize_part_file(tmp_path, save_path, stop_event)
                return
            if os.path.isfile(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    def _download_file_url(self, url, tmp_path, index, total, on_progress, stop_event, on_info=None) -> None:
        try:
            with _urlopen(url) as response:
                length_header = response.getheader("Content-Length")
                file_total = int(length_header) if length_header and length_header.isdigit() else 0
                downloaded = 0
                last_info_at = 0.0
                last_info_text = ""
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
                        if on_info and file_total:
                            info_text = (
                                f"{format_download_size(downloaded)} / "
                                f"{format_download_size(file_total)}"
                            )
                            now = time.monotonic()
                            if info_text != last_info_text and (
                                now - last_info_at >= _INFO_UPDATE_INTERVAL_S
                                or downloaded >= file_total
                            ):
                                last_info_at = now
                                last_info_text = info_text
                                on_info(info_text)
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
        debug("download", "update_model_settings start")
        try:
            fetched = []
            for url, _dest in _MODEL_DATA_URLS:
                with _urlopen(url) as response:
                    fetched.append(json.load(response))
        except Exception as exc:
            debug(
                "download",
                f"update_model_settings fetch failed error={type(exc).__name__}: {exc}",
            )
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
        debug(
            "download",
            f"update_model_settings ok invalidate_stem={repo is not None}",
        )
        return True

    # -- Update check -----------------------------------------------------------

    def check_release(self) -> Dict[str, object]:
        """Fetch fork release metadata and return GTK version/update status."""
        return release_update_status(force_refresh=True)

    def update_status(self) -> Dict[str, object]:
        """Return GTK fork version / update status for the Updates UI."""
        return release_update_status()

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

        politrees = load_politrees_links()
        vr, mdx, demucs = merge_politrees_catalogues(vr, mdx, demucs, politrees)

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
        """Return ``[(label, url), ...]`` direct links for a manual-download entry."""
        return manual_links_for_model(arch_type, model, NORMAL_REPO)

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
        if arch_type == APOLLO_ARCH_TYPE:
            return paths.APOLLO_MODELS_DIR
        return paths.MODELS_DIR
