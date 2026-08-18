"""Repository-aware migration of persisted model references to canonical IDs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from bundled.constants import (
    CHOOSE_ENSEMBLE_OPTION,
    CHOOSE_MODEL,
    NO_MODEL,
)

from . import paths
from .json_store import (
    content_digest,
    locked_json_path,
    read_json_object,
    write_json_if_unchanged,
)
from .model_identity import (
    ModelIdentityService,
    ModelRecord,
    ModelId,
    _qualified_family,
    resolve_model_record,
)
from .settings import Settings

IDENTITY_SCHEMA_VERSION = 2


class IdentityConflict(ValueError):
    """Raised when a stored reference matches more than one model or the wrong family."""


@dataclass(frozen=True)
class IdentityMigrationResult:
    converted: int = 0
    cleared: int = 0
    files_changed: int = 0
    failures: tuple[str, ...] = ()
    backups: tuple[str, ...] = ()
    settings_changes: tuple["IdentitySettingChange", ...] = ()
    conflicts: tuple[str, ...] = ()


@dataclass(frozen=True)
class IdentitySettingChange:
    path: str
    old: Any
    new: Any


def _settings_identity_values(settings: Settings) -> dict[str, Any]:
    values: dict[str, Any] = {
        "vr.model": settings.vr.model,
        "mdx.model": settings.mdx.model,
        "demucs.model": settings.demucs.model,
        "audio_tools.apollo_model": settings.audio_tools.apollo_model,
        "process.vocal_splitter": settings.process.vocal_splitter,
        "demucs.pre_proc_model": settings.demucs.pre_proc_model,
        "ensemble.selected_models": list(settings.ensemble.selected_models),
        "ensemble.chosen_ensemble": settings.ensemble.chosen_ensemble,
        "identity_schema_version": settings.identity_schema_version,
    }
    for section_name in ("vr", "mdx", "demucs"):
        section = getattr(settings, section_name)
        for name in (
            "voc_inst_secondary_model", "other_secondary_model",
            "bass_secondary_model", "drums_secondary_model",
        ):
            values[f"{section_name}.{name}"] = getattr(section, name)
    return values


class IdentityMigrator:
    def __init__(self, repo: Any):
        self.repo = repo
        self.identities = ModelIdentityService(repo)
        self.records = self._known_records()
        self.conflicts: tuple[str, ...] = ()

    def _known_records(self) -> tuple[ModelRecord, ...]:
        records = {record.id: record for record in self.identities.records()}
        try:
            from .downloads import DownloadManager

            manager = DownloadManager()
            manager.ensure_catalogues(allow_network=False)
            for display, payload in manager.apollo_download_list.items():
                filenames = list(payload) if isinstance(payload, dict) else [payload]
                checkpoint = next(
                    (
                        value for value in filenames
                        if str(value).casefold().endswith((".ckpt", ".bin", ".pth", ".pt"))
                    ),
                    filenames[0] if filenames else display,
                )
                filename = os.path.basename(str(checkpoint))
                basename = os.path.splitext(filename or str(display))[0]
                model_id = str(ModelId("apollo", basename))
                records.setdefault(
                    model_id,
                    ModelRecord(
                        model_id, "apollo", basename, str(display), False,
                        filename or None,
                    ),
                )
        except (OSError, TypeError, ValueError):
            pass
        return tuple(records.values())

    def canonical(
        self,
        value: Any,
        *,
        family: str | None = None,
        allowed_families: tuple[str, ...] | None = None,
    ) -> str | None:
        raw = str(value or "").strip()
        if not raw or raw in {CHOOSE_MODEL, NO_MODEL, CHOOSE_ENSEMBLE_OPTION}:
            return None
        query = raw
        records = self.records
        token_family = _qualified_family(raw)
        if family:
            family = family.casefold()
            if token_family is not None:
                if token_family != family:
                    raise IdentityConflict(
                        f"model {raw!r} does not belong to required family {family}"
                    )
            elif raw:
                query = f"{family}:{raw}"
            records = tuple(record for record in records if record.family == family)
        elif allowed_families is not None:
            allowed = frozenset(str(item).casefold() for item in allowed_families)
            if token_family is not None and token_family not in allowed:
                raise IdentityConflict(
                    f"model {raw!r} is not eligible for this setting"
                )
            records = tuple(record for record in records if record.family in allowed)
        try:
            return resolve_model_record(query, records).id
        except ValueError as exc:
            message = str(exc)
            if (
                "ambiguous" in message
                or "does not belong" in message
                or "not eligible" in message
            ):
                raise IdentityConflict(message) from exc
            return None

    def migrate_settings(self, settings: Settings) -> tuple[int, int]:
        converted = cleared = 0
        conflicts: list[str] = []

        def replace(
            owner: Any,
            name: str,
            *,
            family: str | None,
            empty: str,
            allowed_families: tuple[str, ...] | None = None,
            path: str | None = None,
        ) -> None:
            nonlocal converted, cleared
            old = getattr(owner, name)
            if old in {None, "", CHOOSE_MODEL, NO_MODEL}:
                return
            setting_path = path or name
            try:
                canonical = self.canonical(
                    old, family=family, allowed_families=allowed_families
                )
            except IdentityConflict as exc:
                conflicts.append(f"{setting_path}: {exc}")
                return
            if canonical:
                if canonical != old:
                    setattr(owner, name, canonical)
                    converted += 1
            else:
                setattr(owner, name, empty)
                cleared += 1

        replace(settings.vr, "model", family="vr", empty=CHOOSE_MODEL, path="vr.model")
        replace(settings.mdx, "model", family="mdx", empty=CHOOSE_MODEL, path="mdx.model")
        replace(
            settings.demucs, "model", family="demucs", empty=CHOOSE_MODEL,
            path="demucs.model",
        )
        replace(
            settings.audio_tools, "apollo_model", family="apollo", empty=CHOOSE_MODEL,
            path="audio_tools.apollo_model",
        )
        replace(
            settings.process, "vocal_splitter", family=None, empty=NO_MODEL,
            allowed_families=("vr", "mdx"), path="process.vocal_splitter",
        )
        for section_name in ("vr", "mdx", "demucs"):
            section = getattr(settings, section_name)
            for name in (
                "voc_inst_secondary_model", "other_secondary_model",
                "bass_secondary_model", "drums_secondary_model",
            ):
                replace(
                    section, name, family=None, empty=NO_MODEL,
                    allowed_families=("vr", "mdx", "demucs"),
                    path=f"{section_name}.{name}",
                )
        replace(
            settings.demucs, "pre_proc_model", family=None, empty=NO_MODEL,
            allowed_families=("vr", "mdx"), path="demucs.pre_proc_model",
        )
        members: list[str] = []
        for value in settings.ensemble.selected_models:
            try:
                canonical = self.canonical(value)
            except IdentityConflict as exc:
                conflicts.append(f"ensemble.selected_models: {exc}")
                members.append(str(value))
                continue
            if canonical:
                members.append(canonical)
                converted += int(canonical != value)
            else:
                cleared += 1
        settings.ensemble.selected_models = list(dict.fromkeys(members))
        if len(settings.ensemble.selected_models) < 2:
            settings.ensemble.chosen_ensemble = CHOOSE_ENSEMBLE_OPTION
        settings.identity_schema_version = IDENTITY_SCHEMA_VERSION
        self.conflicts = tuple(conflicts)
        return converted, cleared


def migrate_identity_storage(
    settings: Settings, repo: Any,
    *, profile_directory: str = paths.SETTINGS_CACHE_DIR,
    ensemble_directory: str = paths.ENSEMBLE_CACHE_DIR,
) -> IdentityMigrationResult:
    migrator = IdentityMigrator(repo)
    converted = cleared = changed = 0
    failures: list[str] = []
    conflicts: list[str] = []
    backups: list[str] = []
    original_settings = _settings_identity_values(settings)

    if settings.identity_schema_version < IDENTITY_SCHEMA_VERSION:
        # Development builds briefly treated Apollo as MDX and could clear a
        # valid filename. Recover it from the permanent pre-canonical backup
        # before applying the corrected Apollo identity migration.
        if (
            settings.identity_schema_version == 1
            and settings.audio_tools.apollo_model == CHOOSE_MODEL
            and settings.path
        ):
            backup_path = settings.path + ".pre-canonical-id.bak"
            if os.path.isfile(backup_path):
                try:
                    backup = Settings.from_json_dict(read_json_object(backup_path))
                    legacy_apollo = backup.audio_tools.apollo_model
                    if legacy_apollo and legacy_apollo != CHOOSE_MODEL:
                        settings.audio_tools.apollo_model = legacy_apollo
                except (OSError, TypeError, ValueError):
                    pass
        added, removed = migrator.migrate_settings(settings)
        converted += added
        cleared += removed
        conflicts.extend(migrator.conflicts)

    for directory, kind in ((ensemble_directory, "ensemble"), (profile_directory, "profile")):
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            if not name.endswith(".json") or not os.path.isfile(path):
                continue
            try:
                with locked_json_path(path):
                    digest = content_digest(path)
                    payload = read_json_object(path)
                    if int(payload.get("identity_schema_version") or 0) >= IDENTITY_SCHEMA_VERSION:
                        continue
                    if kind == "ensemble":
                        members = payload.get("selected_models") or []
                        canonical_members = []
                        for value in members:
                            try:
                                canonical = migrator.canonical(value)
                            except IdentityConflict as exc:
                                conflicts.append(f"{path}: {exc}")
                                canonical_members.append(str(value))
                                continue
                            if canonical:
                                canonical_members.append(canonical)
                                converted += int(canonical != value)
                            else:
                                cleared += 1
                        payload["selected_models"] = list(dict.fromkeys(canonical_members))
                        payload.setdefault("schema_version", 1)
                        payload["identity_schema_version"] = IDENTITY_SCHEMA_VERSION
                    else:
                        profile = (
                            Settings.from_json_dict(payload)
                            if "process" in payload or "schema_version" in payload
                            else Settings.from_flat(payload)
                        )
                        add, remove = migrator.migrate_settings(profile)
                        converted += add
                        cleared += remove
                        conflicts.extend(
                            f"{path}: {item}" for item in migrator.conflicts
                        )
                        payload = profile.to_json_dict()
                    backup_suffix = ".pre-canonical-id.bak"
                    if write_json_if_unchanged(
                        path, payload, digest, backup_suffix=backup_suffix,
                    ):
                        backups.append(f"{path}{backup_suffix}")
                        changed += 1
                    else:
                        conflicts.append(
                            f"{path}: skipped because the on-disk file changed "
                            "during migration"
                        )
            except (OSError, ValueError, TypeError) as exc:
                failures.append(f"{path}: {exc}")
    final_settings = _settings_identity_values(settings)
    settings_changes = tuple(
        IdentitySettingChange(path, old, final_settings[path])
        for path, old in original_settings.items()
        if old != final_settings[path]
    )
    return IdentityMigrationResult(
        converted, cleared, changed,
        tuple(failures) + tuple(conflicts),
        tuple(backups),
        settings_changes, tuple(conflicts),
    )


__all__ = [
    "IDENTITY_SCHEMA_VERSION", "IdentityConflict", "IdentityMigrationResult",
    "IdentityMigrator", "IdentitySettingChange",
    "migrate_identity_storage",
]
