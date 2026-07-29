"""Phase 1 stubs — full hierarchy in follow-up."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ModelIdentity:
    pass


@dataclass
class ExportOptions:
    pass


@dataclass
class DeviceOptions:
    use_gpu: bool = False


@dataclass
class EnsembleMemberFlags:
    pass
