"""Injected I/O fixtures for exercising real planning phases."""

from __future__ import annotations

from typing import Any

from core.job_acquisition import DefaultMdxConfigurationFiles
from core.job_dependencies import RepositoryPlanningIdentities
from core.job_materialization import DefaultPlanningMaterializer
from core.job_plan import JobResolver


def resolver_with_ports(repo: Any) -> JobResolver:
    """Allow fixtures to replace individual I/O methods without patching phases."""
    return JobResolver(
        repo,
        identities=RepositoryPlanningIdentities(repo),
        configs=DefaultMdxConfigurationFiles(),
        materializer=DefaultPlanningMaterializer(repo),
    )


class ConfigurationFiles:
    def __init__(self, *, available: tuple[str, ...] = (), downloads: bool = True):
        self.available = set(available)
        self.downloads = downloads
        self.calls: list[tuple[str, str]] = []

    def fallback_yaml(self, backend_name: str) -> str | None:
        return None

    def exists(self, yaml_name: str) -> bool:
        self.calls.append(("exists", yaml_name))
        return yaml_name in self.available

    def ensure(self, yaml_name: str, *, allow_network: bool) -> bool:
        if not allow_network:
            raise AssertionError("offline acquisition reached ensure")
        self.calls.append(("ensure", yaml_name))
        if self.downloads:
            self.available.add(yaml_name)
        return self.downloads


class IdentityRecords:
    def __init__(
        self,
        records: list[Any],
        *,
        refreshed: list[Any] | None = None,
        karaoke: tuple[str, ...] = (),
    ):
        self.records = {record.id: record for record in records}
        self.refreshed = refreshed
        self.eligible = karaoke
        self.inventory_generation = 7
        self.calls: list[str] = []

    def lookup(self, canonical_id: str):
        self.calls.append(canonical_id)
        try:
            return self.records[canonical_id]
        except KeyError:
            raise ValueError(f"unknown model {canonical_id!r}") from None

    def invalidate(self) -> None:
        self.calls.append("invalidate")
        if self.refreshed is not None:
            self.records.update({record.id: record for record in self.refreshed})

    def karaoke_ids(self, settings: Any) -> tuple[str, ...]:
        self.calls.append("karaoke")
        return self.eligible


class QueuedMaterializer:
    def __init__(self, *batches: list[Any]):
        self.batches = list(batches)
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any], bool]] = []
        self.loads = 0

    def assemble(
        self,
        settings: Any,
        command: str,
        records: Any,
        *,
        allow_network: bool,
        model_dependencies: Any,
    ) -> list[Any]:
        self.calls.append((tuple(records), dict(model_dependencies), allow_network))
        if not self.batches:
            raise AssertionError("unexpected assembly")
        return self.batches.pop(0)

    def load_checkpoints(self, models: Any) -> None:
        self.loads += 1


class FileProbes:
    def __init__(self, *, present: tuple[str, ...] = ("/song.wav",), missing: tuple[str, ...] = ()):
        self.present = set(present)
        self.missing = missing
        self.calls: list[str] = []

    def is_file(self, path: str) -> bool:
        self.calls.append(f"file:{path}")
        return path in self.present

    def checkpoint_hash(self, path: str) -> str:
        self.calls.append(f"hash:{path}")
        return "fixture-hash"

    def missing_runtime_packages(self) -> tuple[str, ...]:
        self.calls.append("packages")
        return self.missing

    def device_diagnostics(self, settings: Any) -> tuple[Any, ...]:
        self.calls.append("device")
        return ()
