#!/usr/bin/env python3
"""Probe a model's portability without downloading its weights.

Answers "can this build run this model?" from the yaml config alone:

1. Build the architecture from the config (random init, no checkpoint).
2. Run a real forward pass on noise and report the output shape.
3. Optionally range-fetch only the checkpoint's *header* (a few tens of KB of
   a multi-hundred-MB file) and diff its ``state_dict`` keys against the
   built module's, which is what catches a port whose submodules are named
   differently from the weights.

See docs/models.md for the unsupported-model classes this exists to triage.
"""

from __future__ import annotations

import gc
import io
import json
import os
import pickle
import struct
import sys
import zipfile
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

#: ``read(start, end) -> bytes`` over a local file or an HTTP range request.
RangeReader = Callable[[int, int], bytes]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _add_repo_to_path() -> None:
    """Make ``core`` / ``engines`` / ``ml`` importable when run as a script."""
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)

_SAFETENSORS_LEN_BYTES = 8

#: Enough to cover a zip end-of-central-directory record plus the directory of
#: a checkpoint with a few thousand tensors.
_ZIP_TAIL_BYTES = 256 * 1024

#: Keys a training checkpoint wraps its weights in.
_STATE_DICT_WRAPPERS = ("state_dict", "model_state_dict", "model", "weights")


def safetensors_header_span(head: bytes) -> Tuple[int, int]:
    """Return ``(start, end)`` byte offsets of a ``.safetensors`` JSON header.

    The first 8 bytes are a little-endian u64 header length, so this needs only
    that prefix to say which range to fetch next.
    """
    if len(head) < _SAFETENSORS_LEN_BYTES:
        raise ValueError("need at least 8 bytes to read a safetensors header length")
    (length,) = struct.unpack("<Q", head[:_SAFETENSORS_LEN_BYTES])
    return _SAFETENSORS_LEN_BYTES, _SAFETENSORS_LEN_BYTES + int(length)


def parse_safetensors_header(blob: bytes) -> List[str]:
    """Return the tensor names declared in a ``.safetensors`` header."""
    start, end = safetensors_header_span(blob)
    raw = blob[start:end]
    if len(raw) < end - start:
        raise ValueError("safetensors header truncated")
    try:
        header = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"safetensors header is not JSON: {exc}") from exc
    if not isinstance(header, dict):
        raise ValueError("safetensors header is not a JSON object")
    return [key for key in header if key != "__metadata__"]


class _AttrDict(dict):
    """A dict that tolerates attribute assignment.

    ``Module.state_dict()`` hangs ``_metadata`` off the OrderedDict instance, so
    the pickle carries a BUILD opcode that sets ``__dict__`` — which a plain
    ``dict`` rejects. Every real checkpoint hits this.
    """


class _StubUnpickler(pickle.Unpickler):
    """Rebuild a checkpoint's key structure without importing or executing anything.

    ``find_class`` never resolves a real symbol and ``persistent_load`` never
    touches storage, so the pickle's dict keys survive while every value
    collapses to an inert placeholder. That is all a key diff needs.
    """

    def find_class(self, module: str, name: str) -> Any:  # noqa: D102
        if (module, name) == ("collections", "OrderedDict"):
            return _AttrDict
        return lambda *args, **kwargs: None

    def persistent_load(self, pid: Any) -> Any:  # noqa: D102
        return None


def parse_torch_pickle_keys(data: bytes) -> List[str]:
    """Return the ``state_dict`` keys held in a torch ``data.pkl`` payload."""
    try:
        obj = _StubUnpickler(io.BytesIO(data)).load()
    except Exception as exc:  # noqa: BLE001 - any malformed pickle is a probe failure
        raise ValueError(f"could not read checkpoint pickle: {exc}") from exc
    return _keys_of_state_dict(obj)


def _keys_of_state_dict(obj: Any) -> List[str]:
    """Pull the weight keys out of a checkpoint object, unwrapping if needed."""
    if not isinstance(obj, dict):
        raise ValueError(f"checkpoint root is {type(obj).__name__}, not a dict")
    for wrapper in _STATE_DICT_WRAPPERS:
        inner = obj.get(wrapper)
        if isinstance(inner, dict) and inner:
            return [str(key) for key in inner]
    return [str(key) for key in obj]


def _data_pkl_name(archive: zipfile.ZipFile) -> str:
    """Name of the ``data.pkl`` member holding the checkpoint's key structure."""
    names = [name for name in archive.namelist() if name.endswith("data.pkl")]
    if not names:
        raise ValueError("zip has no data.pkl entry")
    return names[0]


class _TailFile(io.RawIOBase):
    """Seekable file-like view that pulls byte ranges on demand."""

    def __init__(self, read: RangeReader, size: int) -> None:
        self._read = read
        self._size = size
        self._pos = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self._pos = offset
        elif whence == io.SEEK_CUR:
            self._pos += offset
        else:
            self._pos = self._size + offset
        return self._pos

    def tell(self) -> int:
        return self._pos

    def read(self, n: Optional[int] = -1) -> bytes:
        # ``None`` and a negative size both mean "to EOF" per RawIOBase.
        end = self._size if n is None or n < 0 else min(self._size, self._pos + n)
        if end <= self._pos:
            return b""
        chunk = self._read(self._pos, end)
        self._pos += len(chunk)
        return chunk


def torch_checkpoint_keys(read: RangeReader, size: int) -> List[str]:
    """Return a torch checkpoint's ``state_dict`` keys, reading only its header.

    ``read`` is a range reader over the checkpoint; zipfile seeks to the central
    directory and the ``data.pkl`` entry, so the tensor payload is never fetched.
    """
    try:
        with zipfile.ZipFile(_TailFile(read, size)) as archive:
            return parse_torch_pickle_keys(archive.read(_data_pkl_name(archive)))
    except zipfile.BadZipFile as exc:
        raise ValueError(
            f"not a zip archive (legacy torch pickle format?): {exc}"
        ) from exc


@dataclass(frozen=True)
class KeyDiff:
    """How a built module's parameter names line up with a checkpoint's."""

    missing: List[str] = field(default_factory=list)
    unexpected: List[str] = field(default_factory=list)
    matched: int = 0

    @property
    def matches(self) -> bool:
        return not self.missing and not self.unexpected


def diff_state_dict_keys(
    module_keys: List[str], checkpoint_keys: List[str]
) -> KeyDiff:
    """Compare a module's parameter names against a checkpoint's.

    Uses ``load_state_dict``'s own wording so probe output can be read straight
    against a torch error: ``unexpected`` are keys the checkpoint carries that
    the module has no home for — the signature of an unported submodule —
    and ``missing`` are keys the module needs that the checkpoint lacks.
    """
    mod = set(module_keys)
    ckpt = set(checkpoint_keys)
    return KeyDiff(
        missing=sorted(mod - ckpt),
        unexpected=sorted(ckpt - mod),
        matched=len(mod & ckpt),
    )


@dataclass
class BuiltModel:
    """A network instantiated from a config, with random weights."""

    config_path: str
    architecture: str
    module: Any = None
    error: str = ""
    parameters: int = 0
    stems: List[str] = field(default_factory=list)
    sample_rate: int = 44100
    config: Any = None
    #: Config keys the chosen class silently ignores.
    dropped: List[str] = field(default_factory=list)
    #: Set by release_module() so ``ok`` survives the module being freed.
    _ok_override: Optional[bool] = None

    @property
    def ok(self) -> bool:
        if self._ok_override is not None:
            return self._ok_override
        return self.module is not None

    def release_module(self) -> None:
        """Drop the live module to reclaim its weights' memory.

        A batch sweep (``sweep_catalogue``) builds hundreds of real models
        back to back; nothing after the forward/key-diff pass for one entry
        ever needs its module again, but ``results`` keeps every
        ``ProbeResult`` (and thus every ``BuiltModel``) around until the whole
        sweep finishes printing/serializing. Holding hundreds of models' worth
        of parameters resident at once is what runs a machine out of RAM.
        """
        self._ok_override = self.ok
        self.module = None


def dropped_config_keys(model_cls: Any, model_cfg: Any) -> List[str]:
    """Config keys ``model_cls.__init__`` will not accept.

    Mirrors ``engines.mdx_c._filter_init_kwargs``, which drops unknown keys so a
    model still builds. That silence is the trap: a checkpoint trained *with*
    a feature loads into a network built *without* it.
    """
    import inspect

    params = inspect.signature(model_cls.__init__).parameters
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return []
    allowed = {name for name in params if name != "self"}
    return sorted(key for key in model_cfg if key not in allowed)


def _load_config(config_path: str) -> Any:
    """Parse a yaml config into the ``ConfigDict`` the engines expect."""
    _add_repo_to_path()
    from ml_collections import ConfigDict

    from core.model_data import load_mdx_c_config

    return ConfigDict(load_mdx_c_config(config_path))


#: Checkpoint-byte-size buckets ``SeperateVR.seperate`` picks a VR architecture
#: variant from — see engines/vr.py:64-69. The yaml never declares this; it is
#: purely a property of the checkpoint file this probe deliberately never
#: downloads, so building a VR model requires a checkpoint size from elsewhere
#: (``--checkpoint`` or ``--check-keys``'s remote HEAD-ish range request).
_VR_NN_ARCH_SIZES = [31191, 33966, 56817, 123821, 123812, 129605, 218409, 537238, 537227]
#: The subset of the above that route to the "5.1" CascadedNet rather than the
#: classic CascadedASPPNet (engines/vr.py:67,89-96).
_VR_5_1_ARCH_SIZES = {56817, 218409}

_VR_MODULE_CLASS_NAMES = {"CascadedNet", "CascadedASPPNet"}


def _vr_nn_arch_size_from_checkpoint_size(size_bytes: int) -> int:
    """Mirror ``engines/vr.py``'s own heuristic exactly, from a byte count."""
    import math

    model_size_kb = math.ceil(size_bytes / 1024)
    return min(_VR_NN_ARCH_SIZES, key=lambda x: abs(x - model_size_kb))


def _build_vr_model(model_section: Any, *, checkpoint_size_bytes: Optional[int]) -> Any:
    """Build a VR network straight from a mvsepless VR yaml's ``model`` section.

    mvsepless VR yamls set ``is_vr6`` for the "v6 beta3" family, which has no
    matching network class anywhere in this port (``ml/vr_network/`` only ever
    implements the VR5/"5.1" ``CascadedASPPNet``/``CascadedNet`` pair) — report
    that honestly rather than building the wrong architecture.
    """
    if model_section.get("is_vr6"):
        raise ValueError("VR6 architecture has no ported network class in this build")
    if checkpoint_size_bytes is None:
        raise ValueError(
            "VR architecture selection needs a checkpoint size (nn_arch_size is "
            "derived from the checkpoint's byte size, not declared in the yaml) "
            "-- pass --checkpoint or --check-keys"
        )
    params = getattr(model_section, "model_params", None)
    if params is None or "bins" not in params:
        raise ValueError("VR config has no model.model_params.bins band spec")
    n_fft_bins = int(params["bins"]) * 2
    nn_arch_size = _vr_nn_arch_size_from_checkpoint_size(checkpoint_size_bytes)
    if nn_arch_size in _VR_5_1_ARCH_SIZES:
        from ml.vr_network.nets_new import CascadedNet

        nout = model_section.get("nout") or 32
        nout_lstm = model_section.get("nout_lstm") or 128
        return CascadedNet(n_fft_bins, nn_arch_size, nout=nout, nout_lstm=nout_lstm)
    from ml.vr_network.nets import determine_model_capacity

    return determine_model_capacity(n_fft_bins, nn_arch_size)


def _build_htdemucs_model(config: Any, htdemucs_section: Any) -> Tuple[Any, List[str]]:
    """Build the vendored (but never-wired-up) ``HTDemucs`` from its yaml.

    Returns ``(module, dropped_keys)`` — the yaml's ``htdemucs:`` section is
    filtered against ``HTDemucs.__init__`` the same way MDX-C variants are
    filtered against theirs, so a feature the yaml asks for that this vendored
    copy doesn't implement (e.g. ``num_subbands``) shows up as a dropped key
    rather than silently vanishing.
    """
    from engines.mdx_c import _filter_init_kwargs
    from vendor.demucs.htdemucs import HTDemucs

    kwargs = _filter_init_kwargs(HTDemucs, htdemucs_section)
    training = getattr(config, "training", None)
    sources = list(getattr(training, "instruments", []) or []) if training else []
    if not sources:
        raise ValueError("htdemucs config has no training.instruments to use as sources")
    kwargs["sources"] = sources
    # MSST/mvsepless yamls declare segment (seconds) under training:, not
    # htdemucs: -- HTDemucs.forward's fixed-length padding uses it (default 10
    # otherwise), and it must agree with the config's own audio.chunk_size.
    segment = getattr(training, "segment", None) if training is not None else None
    if segment:
        kwargs["segment"] = segment
    module = HTDemucs(**kwargs)
    return module, dropped_config_keys(HTDemucs, htdemucs_section)


def _instantiate(
    config: Any,
    state_dict_keys: Optional[List[str]] = None,
    model_type_hint: Optional[str] = None,
    checkpoint_size_bytes: Optional[int] = None,
) -> Tuple[Any, str, bool, Optional[List[str]]]:
    """Build a module via the same two paths ``SeperateMDXC`` uses, plus VR and
    HTDemucs paths this probe builds standalone (see module docstring).

    The third element says whether the class received *filtered* kwargs — only
    then can a config key have been silently discarded. The fourth overrides
    ``build_from_config``'s generic dropped-key derivation for a builder (VR,
    HTDemucs) whose real kwargs section isn't ``config.model``.
    """
    import torch

    from engines.mdx_c import UnknownMDXCArchitecture, _build_mdx_c_model
    from ml.tfc_tdf_v3 import TFC_TDF_net

    model_section = getattr(config, "model", None)

    if model_type_hint == "htdemucs" or model_section == "htdemucs":
        htdemucs_section = getattr(config, "htdemucs", None)
        if htdemucs_section is None:
            raise ValueError("htdemucs config has no 'htdemucs' kwargs section")
        module, dropped = _build_htdemucs_model(config, htdemucs_section)
        return module, type(module).__name__, False, dropped

    if model_type_hint == "vr" or (
        model_section is not None
        and not isinstance(model_section, str)
        and "is_vr5" in model_section
    ):
        module = _build_vr_model(model_section, checkpoint_size_bytes=checkpoint_size_bytes)
        return module, type(module).__name__, False, None

    try:
        module = _build_mdx_c_model(
            config, state_dict_keys=state_dict_keys, model_type_hint=model_type_hint
        )
        return module, type(module).__name__, True, None
    except UnknownMDXCArchitecture:
        # Not a Roformer/SCNet/Bandit config. SeperateMDXC routes MDX23C to
        # TFC_TDF_net, but only try that when there is a model section to read —
        # otherwise the original "unknown architecture" is the honest answer.
        if getattr(config, "model", None) is None:
            raise
    # TFC_TDF_net consumes the whole config object, so nothing is filtered out.
    module = TFC_TDF_net(config, device=torch.device("cpu"))
    return module, type(module).__name__, False, None


def build_from_config(
    config_path: str,
    state_dict_keys: Optional[List[str]] = None,
    model_type_hint: Optional[str] = None,
    checkpoint_size_bytes: Optional[int] = None,
) -> BuiltModel:
    """Instantiate a model from its yaml. Never raises; reports instead.

    ``state_dict_keys`` lets a checkpoint steer variants a config does not
    declare — HyperACE BS-Roformer being the case in point. ``model_type_hint``
    does the same from the catalogue entry, for variants (SCNet Masked) that a
    ``--check-keys``-free build never gets ``state_dict_keys`` for.
    ``checkpoint_size_bytes`` is VR-specific: its architecture variant is a
    checkpoint-byte-size heuristic the yaml never declares.
    """
    try:
        config = _load_config(config_path)
    except Exception as exc:  # noqa: BLE001 - a bad config is a probe result
        return BuiltModel(config_path, "", error=f"config unreadable: {exc}")

    training = getattr(config, "training", None)
    stems = list(getattr(training, "instruments", []) or []) if training else []
    audio = getattr(config, "audio", None)
    sample_rate = int(getattr(audio, "sample_rate", 44100) or 44100) if audio else 44100

    try:
        module, arch, filtered, dropped_override = _instantiate(
            config, state_dict_keys, model_type_hint, checkpoint_size_bytes
        )
    except Exception as exc:  # noqa: BLE001 - unported architecture is the answer
        return BuiltModel(
            config_path,
            "",
            error=f"{type(exc).__name__}: {exc}",
            stems=stems,
            sample_rate=sample_rate,
            config=config,
        )

    module.eval()
    if dropped_override is not None:
        dropped = dropped_override
    else:
        section = getattr(config, "model", None)
        if section is None:
            section = getattr(config, "kwargs", None)  # Bandit configs
        dropped = (
            dropped_config_keys(type(module), section)
            if filtered and section is not None
            else []
        )
    return BuiltModel(
        config_path,
        arch,
        module=module,
        parameters=sum(p.numel() for p in module.parameters()),
        stems=stems,
        sample_rate=sample_rate,
        config=config,
        dropped=dropped,
    )


@dataclass
class ForwardResult:
    """Outcome of pushing noise through a randomly-initialised module."""

    ok: bool = False
    error: str = ""
    input_shape: Tuple[int, ...] = ()
    output_shape: Tuple[int, ...] = ()
    finite: bool = False


def natural_chunk_samples(built: BuiltModel) -> Optional[int]:
    """The input length a config declares, if any.

    STFT-framed architectures (MDX23C) reject anything else, so an arbitrary
    duration would report a forward failure that says nothing about the port.
    """
    audio = getattr(built.config, "audio", None)
    chunk = getattr(audio, "chunk_size", None) if audio is not None else None
    if chunk:
        return int(chunk)
    inference = getattr(built.config, "inference", None)
    hop = getattr(audio, "hop_length", None) if audio is not None else None
    dim_t = getattr(inference, "dim_t", None) if inference is not None else None
    if hop and dim_t:
        return int(hop) * (int(dim_t) - 1)
    return None


def _vr_probe_input(built: BuiltModel) -> Any:
    """Spectrogram-shaped noise for a VR module — unlike every other
    architecture this probe builds, VR's forward pass takes ``(B, 2, bins, T)``
    already-STFT'd magnitude, not a raw waveform."""
    import torch

    model_section = getattr(built.config, "model", None)
    params = getattr(model_section, "model_params", None) if model_section is not None else None
    bins = int(params["bins"]) if params is not None and "bins" in params else 256
    return torch.randn(1, 2, bins, 64)


def forward_probe(
    built: BuiltModel, *, seconds: Optional[float] = None
) -> ForwardResult:
    """Run audio-shaped noise through ``built``. Proves the graph is wired up.

    Defaults to the config's own chunk size; ``seconds`` overrides it.
    """
    if built.module is None:
        return ForwardResult(ok=False, error=built.error or "model not built")

    import torch

    # BSRoformer/MelBandRoformer fix their expected channel count from the
    # config's own ``stereo`` flag and assert on it in forward() -- a mono
    # config (``stereo: false``) rejects the 2-channel noise every other
    # architecture here is happy with.
    channels = 2 if getattr(built.module, "stereo", True) else 1

    if type(built.module).__name__ in _VR_MODULE_CLASS_NAMES:
        noise = _vr_probe_input(built)
    elif seconds is not None:
        samples = max(1, int(built.sample_rate * seconds))
        noise = torch.randn(1, channels, samples)
    else:
        samples = natural_chunk_samples(built) or int(built.sample_rate * 2)
        noise = torch.randn(1, channels, samples)
    try:
        with torch.no_grad():
            out = built.module(noise)
    except Exception as exc:  # noqa: BLE001 - a broken forward is a probe result
        return ForwardResult(
            ok=False, error=f"{type(exc).__name__}: {exc}", input_shape=tuple(noise.shape)
        )
    tensor = out[0] if isinstance(out, (tuple, list)) else out
    return ForwardResult(
        ok=True,
        input_shape=tuple(noise.shape),
        output_shape=tuple(tensor.shape),
        finite=bool(torch.isfinite(tensor).all()),
    )


@dataclass
class ProbeTarget:
    """A catalogue entry resolved to the URLs and metadata the probe needs."""

    entry_id: str
    label: str
    model_type: str = ""
    config_url: str = ""
    checkpoint_url: str = ""
    reason: str = ""
    is_bv_model: bool = False

    @property
    def config_name(self) -> str:
        from urllib.parse import unquote, urlparse

        return os.path.basename(unquote(urlparse(self.config_url).path))


def _default_mvsepless_catalogue(*, allow_network: bool = True) -> Dict[str, Any]:
    """Raw mvsepless ``models.json`` via the same coordinator Download Center uses."""
    _add_repo_to_path()
    from core.catalogue_coordinator import CatalogueCoordinator
    from core.catalogue_types import SourceId

    coordinator = CatalogueCoordinator()
    try:
        coordinator.ensure(vip=False, allow_network=allow_network)
        content = coordinator.source(SourceId.MVSEPLESS).state.content
        if content is None:
            return {}
        return dict(content.payload)
    finally:
        coordinator.close()


def resolve_target(entry_id: str, catalogue: Optional[Dict[str, Any]] = None) -> ProbeTarget:
    """Look up ``entry_id`` in the mvsepless catalogue.

    ``catalogue`` is injectable so callers (and tests) can work offline.
    """
    _add_repo_to_path()

    if catalogue is None:
        catalogue = _default_mvsepless_catalogue()

    entry = catalogue.get(entry_id)
    if not isinstance(entry, dict):
        raise KeyError(f"no catalogue entry {entry_id!r}")

    return _target_from_entry(entry_id, entry)


def _target_from_entry(entry_id: str, entry: Dict[str, Any]) -> ProbeTarget:
    from core.mvsepless_catalog import classify_entry, entry_label

    _supported, reason = classify_entry(entry_id, entry)
    return ProbeTarget(
        entry_id=entry_id,
        label=entry_label(entry_id, entry),
        model_type=str(entry.get("model_type") or ""),
        config_url=str(entry.get("config_url") or ""),
        checkpoint_url=str(entry.get("checkpoint_url") or ""),
        reason=reason,
        is_bv_model=bool(entry.get("is_bv_model")),
    )


def iter_catalogue_targets(
    catalogue: Optional[Dict[str, Any]] = None, *, unsupported_only: bool = True
) -> Iterator[ProbeTarget]:
    """Yield a :class:`ProbeTarget` per mvsepless catalogue entry.

    Defaults to the entries ``classify_entry`` marks unsupported — the actual
    triage workload this script exists for. ``catalogue`` is injectable so
    callers (and tests) can work offline, same as :func:`resolve_target`.
    """
    _add_repo_to_path()
    from core.mvsepless_catalog import classify_entry

    if catalogue is None:
        catalogue = _default_mvsepless_catalogue()

    for entry_id, entry in catalogue.items():
        if not isinstance(entry, dict):
            continue
        if unsupported_only:
            supported, _reason = classify_entry(entry_id, entry)
            if supported:
                continue
        yield _target_from_entry(entry_id, entry)


VERDICT_BUILDABLE = "buildable"
VERDICT_BUILD_FAILED = "build-failed"
VERDICT_FORWARD_FAILED = "forward-failed"
VERDICT_KEY_MISMATCH = "key-mismatch"
VERDICT_CONFIG_IGNORED = "config-ignored"
#: Infrastructure failure (network, bad yaml) rather than a legitimate
#: build/forward outcome — only set by :func:`sweep_catalogue`.
VERDICT_PROBE_ERROR = "probe-error"


@dataclass
class ProbeResult:
    """Everything the probe learned about one model."""

    entry_id: str
    label: str
    build: BuiltModel
    forward: ForwardResult
    reason: str = ""
    keys: Optional[KeyDiff] = None
    #: Overrides the computed verdict — set only for a :data:`VERDICT_PROBE_ERROR`
    #: result, where there is no real build/forward outcome to derive one from.
    error_verdict: str = ""

    @property
    def verdict(self) -> str:
        """One word for "how far does this get without weights?"."""
        if self.error_verdict:
            return self.error_verdict
        if not self.build.ok:
            return VERDICT_BUILD_FAILED
        if not self.forward.ok:
            return VERDICT_FORWARD_FAILED
        if self.build.dropped:
            # Root cause: it built only because unknown keys were discarded.
            return VERDICT_CONFIG_IGNORED
        if self.keys is not None and not self.keys.matches:
            return VERDICT_KEY_MISMATCH
        return VERDICT_BUILDABLE

    def to_json(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "entry_id": self.entry_id,
            "label": self.label,
            "catalogue_reason": self.reason,
            "verdict": self.verdict,
            "architecture": self.build.architecture,
            "parameters": self.build.parameters,
            "stems": list(self.build.stems),
            "build_error": self.build.error,
            "dropped_config_keys": list(self.build.dropped),
            "forward": {
                "ok": self.forward.ok,
                "error": self.forward.error,
                "input_shape": list(self.forward.input_shape),
                "output_shape": list(self.forward.output_shape),
                "finite": self.forward.finite,
            },
        }
        if self.keys is not None:
            payload["state_dict"] = {
                "matches": self.keys.matches,
                "matched": self.keys.matched,
                "missing": list(self.keys.missing),
                "unexpected": list(self.keys.unexpected),
            }
        return payload


_VERDICT_BLURB = {
    VERDICT_BUILDABLE: "architecture builds and runs — port looks viable",
    VERDICT_BUILD_FAILED: "architecture does not instantiate — unported feature",
    VERDICT_FORWARD_FAILED: "instantiates but the forward pass breaks",
    VERDICT_KEY_MISMATCH: "runs, but parameter names disagree with the checkpoint",
    VERDICT_CONFIG_IGNORED: "builds only because config keys were silently dropped",
    VERDICT_PROBE_ERROR: "could not be probed at all (network or bad yaml)",
}

_KEYS_SHOWN = 12


def render_report(result: ProbeResult) -> str:
    """Human-readable probe report."""
    build, forward = result.build, result.forward
    lines = [
        f"{result.label}  [{result.entry_id}]",
        f"  verdict      {result.verdict} — {_VERDICT_BLURB[result.verdict]}",
    ]
    if result.reason:
        lines.append(f"  catalogue    listed unsupported: {result.reason}")
    if build.ok:
        lines.append(
            f"  architecture {build.architecture}  "
            f"{build.parameters / 1e6:.1f}M params"
        )
        if build.stems:
            lines.append(f"  stems        {', '.join(build.stems)}")
        if build.dropped:
            lines.append(f"  dropped      {', '.join(build.dropped)}  (config asks for these; the class ignores them)")
    else:
        lines.append(f"  build error  {build.error}")
    if forward.ok:
        lines.append(
            f"  forward      {tuple(forward.input_shape)} -> "
            f"{tuple(forward.output_shape)}  finite={forward.finite}"
        )
    elif build.ok:
        lines.append(f"  forward err  {forward.error}")

    if result.keys is not None:
        diff = result.keys
        lines.append(
            f"  state_dict   {diff.matched} matched, "
            f"{len(diff.missing)} missing, {len(diff.unexpected)} unexpected"
        )
        for label, names in (("missing", diff.missing), ("unexpected", diff.unexpected)):
            for name in names[:_KEYS_SHOWN]:
                lines.append(f"    {label:10s} {name}")
            if len(names) > _KEYS_SHOWN:
                lines.append(f"    {'':10s} ... and {len(names) - _KEYS_SHOWN} more")
    return "\n".join(lines)


def _default_opener(request: Any) -> Any:
    from core.mdx_config_fetch import _urlopen

    return _urlopen(request)


def _request(url: str, headers: Dict[str, str]) -> Any:
    import urllib.request

    return urllib.request.Request(url, headers=headers)


class RangeError(RuntimeError):
    """A range request returned something other than the bytes that were asked for.

    Worth its own type because the failure is silent otherwise: a server that
    ignores ``Range`` streams the entire checkpoint, and a short or misaligned
    body gets hashed as though it were the requested span.
    """


def _parse_content_range(value: str) -> Tuple[int, int, Optional[int]]:
    """``bytes 100-139/1000`` -> ``(100, 139, 1000)``. ``*`` total becomes None."""
    unit, _, spec = value.strip().partition(" ")
    if unit.lower() != "bytes":
        raise RangeError(f"unsupported Content-Range unit: {value!r}")
    span, _, total_text = spec.partition("/")
    first, _, last = span.partition("-")
    try:
        start, end = int(first), int(last)
    except ValueError:
        raise RangeError(f"unparsable Content-Range: {value!r}") from None
    total = int(total_text) if total_text.strip().isdigit() else None
    return start, end, total


def _response_status(response: Any) -> Optional[int]:
    status: Any = getattr(response, "status", None)
    if status is None:
        getcode = getattr(response, "getcode", None)
        status = getcode() if callable(getcode) else None
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def http_range_reader(url: str, *, opener: Optional[Callable[[Any], Any]] = None) -> RangeReader:
    """A :data:`RangeReader` backed by validated HTTP range requests.

    ``start``/``end`` are half-open like every other reader here; HTTP ranges
    are inclusive, hence the ``end - 1``.

    The response is checked rather than trusted: it must be a 206 whose
    ``Content-Range`` matches the span requested, carrying exactly that many
    bytes. Anything else raises :class:`RangeError` instead of being returned
    as though it were the requested bytes. A server may legitimately clamp the
    final range to the last byte of the file, which is accepted.
    """
    fetch = opener or _default_opener

    def read(start: int, end: int) -> bytes:
        request = _request(url, {"Range": f"bytes={start}-{end - 1}"})
        with fetch(request) as response:
            status = _response_status(response)
            if status != 206:
                raise RangeError(
                    f"{url}: expected 206 Partial Content, got {status} "
                    f"(the server may be ignoring Range)"
                )
            header = (response.headers or {}).get("Content-Range") or ""
            if not header:
                raise RangeError(f"{url}: 206 response carried no Content-Range")
            data = response.read()

        got_start, got_end, total = _parse_content_range(header)
        if got_start != start:
            raise RangeError(
                f"{url}: asked for bytes {start}-{end - 1}, server sent {got_start}-{got_end}"
            )
        at_eof = total is not None and got_end == total - 1
        if got_end != end - 1 and not at_eof:
            raise RangeError(
                f"{url}: asked for bytes {start}-{end - 1}, server sent {got_start}-{got_end}"
            )
        expected = got_end - got_start + 1
        if len(data) != expected:
            raise RangeError(
                f"{url}: Content-Range promised {expected} bytes, body carried {len(data)}"
            )
        return data

    return read


def remote_size(url: str, *, opener: Optional[Callable[[Any], Any]] = None) -> int:
    """Total size of a remote file, learned from a one-byte range request.

    A range request rather than HEAD: redirect-heavy hosts answer it more
    reliably, and ``Content-Range`` carries the total either way.
    """
    fetch = opener or _default_opener
    request = _request(url, {"Range": "bytes=0-0"})
    with fetch(request) as response:
        content_range = response.headers.get("Content-Range") or ""
    total = content_range.rpartition("/")[2].strip()
    if not total.isdigit():
        raise ValueError(f"server did not report a size for {url}")
    return int(total)


def remote_checkpoint_keys(url: str) -> List[str]:
    """Fetch only a remote checkpoint's header and return its ``state_dict`` keys."""
    read = http_range_reader(url)
    if url.endswith(".safetensors"):
        span = safetensors_header_span(read(0, _SAFETENSORS_LEN_BYTES))
        return parse_safetensors_header(read(0, span[1]))
    return torch_checkpoint_keys(read, remote_size(url))


def _checkpoint_keys_cache_path(dest_dir: str) -> str:
    return os.path.join(dest_dir, "checkpoint_keys.json")


def _read_checkpoint_keys_cache(dest_dir: str) -> Dict[str, List[str]]:
    try:
        with open(_checkpoint_keys_cache_path(dest_dir), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return payload
    except (OSError, ValueError, TypeError):
        pass
    return {}


def _write_checkpoint_keys_cache(dest_dir: str, payload: Dict[str, List[str]]) -> None:
    try:
        os.makedirs(dest_dir, exist_ok=True)
        with open(_checkpoint_keys_cache_path(dest_dir), "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    except OSError:
        pass


def cached_remote_checkpoint_keys(url: str, dest_dir: str) -> List[str]:
    """``remote_checkpoint_keys``, skipping the range-fetch on a repeat URL.

    Checkpoint headers are presumed immutable once fetched — same assumption
    ``_fetch_config`` makes for config yamls — so this caches with no TTL,
    keyed by URL, in one JSON file under ``dest_dir``.
    """
    cache = _read_checkpoint_keys_cache(dest_dir)
    cached = cache.get(url)
    if cached is not None:
        return cached
    keys = remote_checkpoint_keys(url)
    cache[url] = keys
    _write_checkpoint_keys_cache(dest_dir, cache)
    return keys


def local_checkpoint_keys(path: str) -> List[str]:
    """``state_dict`` keys of a checkpoint on disk, reading only its header."""

    def read(start: int, end: int) -> bytes:
        with open(path, "rb") as handle:
            handle.seek(start)
            return handle.read(end - start)

    if path.endswith(".safetensors"):
        span = safetensors_header_span(read(0, _SAFETENSORS_LEN_BYTES))
        return parse_safetensors_header(read(0, span[1]))
    return torch_checkpoint_keys(read, os.path.getsize(path))


def _fetch_config(url: str, dest_dir: str) -> str:
    """Download a yaml config (a few KB) into ``dest_dir`` and return the path."""
    from urllib.parse import unquote, urlparse

    from core.mdx_config_fetch import _urlopen

    name = os.path.basename(unquote(urlparse(url).path)) or "config.yaml"
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, name)
    if os.path.isfile(dest):
        return dest
    tmp_dest = f"{dest}.part"
    try:
        with _urlopen(url) as response:
            data = response.read()
        with open(tmp_dest, "wb") as handle:
            handle.write(data)
        os.replace(tmp_dest, dest)
    finally:
        try:
            os.unlink(tmp_dest)
        except FileNotFoundError:
            pass
    return dest


def _cache_dir() -> str:
    _add_repo_to_path()
    from core import paths

    return os.path.join(paths.CACHE_DIR, "model_probe")


def probe(
    config_path: str,
    *,
    entry_id: str = "",
    label: str = "",
    reason: str = "",
    checkpoint_url: str = "",
    checkpoint_path: str = "",
    seconds: Optional[float] = None,
    model_type_hint: Optional[str] = None,
    checkpoint_keys_cache_dir: Optional[str] = None,
) -> ProbeResult:
    """Build, forward-probe and (optionally) key-diff one model.

    ``checkpoint_keys_cache_dir``, when given, caches a remote checkpoint's
    header keys by URL so repeated ``--check-keys`` runs against the same
    checkpoint skip the range-fetch. Unused for a local ``checkpoint_path``.
    """
    # Read the checkpoint's keys first: they decide variants the config does
    # not declare, so the build itself depends on them.
    checkpoint_keys: Optional[List[str]] = None
    # VR's architecture variant is a checkpoint-byte-size heuristic (see
    # _build_vr_model) — best-effort, independent of the keys fetch above.
    checkpoint_size_bytes: Optional[int] = None
    if checkpoint_path:
        try:
            checkpoint_keys = local_checkpoint_keys(checkpoint_path)
            checkpoint_size_bytes = os.path.getsize(checkpoint_path)
        except Exception as exc:  # noqa: BLE001 - header probe is best-effort
            print(f"  (state_dict probe unavailable: {exc})")
    elif checkpoint_url:
        try:
            checkpoint_keys = (
                cached_remote_checkpoint_keys(checkpoint_url, checkpoint_keys_cache_dir)
                if checkpoint_keys_cache_dir is not None
                else remote_checkpoint_keys(checkpoint_url)
            )
        except Exception as exc:  # noqa: BLE001 - header probe is best-effort
            print(f"  (state_dict probe unavailable: {exc})")
        try:
            checkpoint_size_bytes = remote_size(checkpoint_url)
        except Exception as exc:  # noqa: BLE001 - size probe is best-effort
            print(f"  (checkpoint size unavailable: {exc})")

    build = build_from_config(
        config_path,
        state_dict_keys=checkpoint_keys,
        model_type_hint=model_type_hint,
        checkpoint_size_bytes=checkpoint_size_bytes,
    )
    forward = forward_probe(build, seconds=seconds)
    keys: Optional[KeyDiff] = None
    if checkpoint_keys is not None and build.ok:
        keys = diff_state_dict_keys(
            list(build.module.state_dict().keys()), checkpoint_keys
        )
    return ProbeResult(
        entry_id=entry_id or os.path.basename(config_path),
        label=label or os.path.basename(config_path),
        reason=reason,
        build=build,
        forward=forward,
        keys=keys,
    )


def sweep_catalogue(
    targets: List[ProbeTarget],
    *,
    check_keys: bool = False,
    seconds: Optional[float] = None,
    config_cache_dir: Optional[str] = None,
    checkpoint_keys_cache_dir: Optional[str] = None,
) -> List[ProbeResult]:
    """Probe every target in turn, printing progress as it goes.

    A per-entry failure (network error, unreadable yaml) becomes a
    :data:`VERDICT_PROBE_ERROR` result rather than aborting the whole sweep —
    the point of a sweep is a full verdict tally, not fail-fast.
    """
    config_cache_dir = config_cache_dir or _cache_dir()
    results: List[ProbeResult] = []
    total = len(targets)
    for index, target in enumerate(targets, 1):
        print(f"[{index}/{total}] {target.label}")
        try:
            if not target.config_url:
                raise ValueError("catalogue entry has no config_url")
            config_path = _fetch_config(target.config_url, config_cache_dir)
            result = probe(
                config_path,
                entry_id=target.entry_id,
                label=target.label,
                reason=target.reason,
                checkpoint_url=target.checkpoint_url if check_keys else "",
                seconds=seconds,
                model_type_hint=target.model_type,
                checkpoint_keys_cache_dir=checkpoint_keys_cache_dir,
            )
        except Exception as exc:  # noqa: BLE001 - one bad entry must not abort the sweep
            result = ProbeResult(
                entry_id=target.entry_id,
                label=target.label,
                reason=target.reason,
                build=BuiltModel(config_path="", architecture="", error=str(exc)),
                forward=ForwardResult(ok=False, error=""),
                error_verdict=VERDICT_PROBE_ERROR,
            )
        print(f"  {result.verdict}")
        results.append(result)
        # Free this entry's weights before building the next one -- see
        # release_module()'s docstring for why this can't wait until the loop
        # (or the whole sweep) finishes.
        result.build.release_module()
        gc.collect()
    return results


_SUMMARY_VERDICT_ORDER = [
    VERDICT_BUILDABLE,
    VERDICT_CONFIG_IGNORED,
    VERDICT_KEY_MISMATCH,
    VERDICT_FORWARD_FAILED,
    VERDICT_BUILD_FAILED,
    VERDICT_PROBE_ERROR,
]


def render_summary(results: List[ProbeResult]) -> str:
    """One-line verdict tally, mirroring ``model_sweep.py``'s summary line."""
    counts: Dict[str, int] = {}
    for result in results:
        counts[result.verdict] = counts.get(result.verdict, 0) + 1
    parts = [f"{counts[v]} {v}" for v in _SUMMARY_VERDICT_ORDER if v in counts]
    return "  ".join(parts)


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Probe whether this build can run a model, without its weights.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", help="Path to a local yaml config")
    source.add_argument("--entry", help="mvsepless catalogue entry id (fetches the yaml)")
    source.add_argument(
        "--sweep",
        action="store_true",
        help="Probe every unsupported mvsepless catalogue entry and print a verdict tally",
    )
    parser.add_argument(
        "--check-keys",
        action="store_true",
        help="With --entry/--sweep: range-fetch checkpoint header(s) and diff state_dict keys",
    )
    parser.add_argument(
        "--checkpoint",
        default="",
        help="With --config/--entry: diff state_dict keys against a checkpoint already on disk",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="Forward-pass noise length; defaults to the config's own chunk size",
    )
    parser.add_argument(
        "--only",
        default="",
        help="With --sweep: only probe entries whose id or label contains this substring",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="With --sweep: probe at most this many entries",
    )
    parser.add_argument(
        "--include-supported",
        action="store_true",
        help="With --sweep: also probe catalogue entries already marked supported",
    )
    parser.add_argument("--json", dest="json_path", default=None)
    args = parser.parse_args(argv)

    if args.sweep:
        targets = list(
            iter_catalogue_targets(unsupported_only=not args.include_supported)
        )
        if args.only:
            needle = args.only.lower()
            targets = [
                t for t in targets
                if needle in t.entry_id.lower() or needle in t.label.lower()
            ]
        if args.limit is not None:
            targets = targets[: args.limit]
        results = sweep_catalogue(
            targets,
            check_keys=args.check_keys,
            seconds=args.seconds,
            checkpoint_keys_cache_dir=_cache_dir(),
        )
        print(render_summary(results))
        if args.json_path:
            with open(args.json_path, "w", encoding="utf-8") as handle:
                json.dump({"results": [r.to_json() for r in results]}, handle, indent=2)
                handle.write("\n")
        return 0 if all(r.verdict == VERDICT_BUILDABLE for r in results) else 1

    if args.config:
        result = probe(
            args.config, checkpoint_path=args.checkpoint, seconds=args.seconds
        )
    else:
        target = resolve_target(args.entry)
        if not target.config_url:
            print(f"{target.label}: catalogue entry has no config_url")
            return 2
        config_path = _fetch_config(target.config_url, _cache_dir())
        result = probe(
            config_path,
            entry_id=target.entry_id,
            label=target.label,
            reason=target.reason,
            checkpoint_url=target.checkpoint_url if args.check_keys else "",
            checkpoint_path=args.checkpoint,
            seconds=args.seconds,
            model_type_hint=target.model_type,
            checkpoint_keys_cache_dir=_cache_dir(),
        )

    print(render_report(result))
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(result.to_json(), handle, indent=2)
            handle.write("\n")
    return 0 if result.verdict == VERDICT_BUILDABLE else 1


if __name__ == "__main__":
    raise SystemExit(main())
