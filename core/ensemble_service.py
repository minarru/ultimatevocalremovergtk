"""Saved and curated ensemble resolution shared by GUI and CLI."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from typing import Any, List, Optional

from . import paths
from .ensemble_presets import curated_combo_label, curated_id_from_combo_label
from .model_identity import ModelIdentityService, parse_stored_model_id
from .stems import EnsemblePair, coerce_ensemble_pair

_ENSEMBLE_NAME_RE = re.compile(r"^[A-Za-z0-9 _-]{1,25}$")


def canonical_saved_ensemble_name(name: str) -> str:
    """Validate and canonicalize a user-supplied saved-ensemble name."""
    value = name.strip()
    if not value or not _ENSEMBLE_NAME_RE.fullmatch(value):
        raise ValueError(
            "Ensemble names may contain only letters, numbers, spaces, "
            "underscores, and hyphens (maximum 25 characters)."
        )
    if value.startswith("-") or value.endswith("-"):
        raise ValueError("Ensemble names cannot start or end with a hyphen.")
    return value.replace(" ", "_")


def _saved_ensemble_path(name: str) -> str:
    canonical = canonical_saved_ensemble_name(name)
    cache_dir = paths.ENSEMBLE_CACHE_DIR
    root = os.path.abspath(cache_dir)
    path = os.path.abspath(os.path.join(root, f"{canonical}.json"))
    if os.path.commonpath((root, path)) != root:
        raise ValueError("Ensemble path escapes the ensemble cache")
    return path


def list_saved_ensembles() -> List[str]:
    """Return the names of every saved ensemble (UVR's ``last_found_ensembles``)."""
    cache_dir = paths.ENSEMBLE_CACHE_DIR
    if not os.path.isdir(cache_dir):
        return []
    names = []
    for entry in os.listdir(cache_dir):
        if not entry.lower().endswith(".json"):
            continue
        stem = os.path.splitext(entry)[0]
        try:
            canonical = canonical_saved_ensemble_name(stem)
        except ValueError:
            continue
        if canonical == stem:
            names.append(canonical)
    return sorted(names)


def save_ensemble(
    name: str, ensemble_main_stem: Any, ensemble_type: str, selected_models: Any,
    *, wav_ensemble: bool = False, save_all_outputs: bool = True,
) -> str:
    """Persist an ensemble (``ensemble_main_stem`` is an :class:`~core.stems.EnsemblePair` id)."""
    pair = (
        ensemble_main_stem
        if isinstance(ensemble_main_stem, EnsemblePair)
        else coerce_ensemble_pair(ensemble_main_stem)
    )
    saved_data = {
        "ensemble_main_stem": pair.value,
        "ensemble_type": ensemble_type,
        "selected_models": list(selected_models),
        "is_wav_ensemble": bool(wav_ensemble),
        "save_all_outputs": bool(save_all_outputs),
    }
    path = _saved_ensemble_path(name)
    cache_dir = paths.ENSEMBLE_CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=cache_dir
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as outfile:
            json.dump(saved_data, outfile, indent=4)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return path


class EnsembleDocument(dict[str, Any]):
    """Saved ensemble payload with transient reader validation warnings."""

    def __init__(
        self, payload: dict[str, Any], validation_warnings: list[str]
    ) -> None:
        super().__init__(payload)
        self.validation_warnings = validation_warnings


def _ensemble_syntax_warnings(payload: dict[str, Any]) -> list[str]:
    from bundled.constants import CHOOSE_MODEL, NO_MODEL

    warnings: list[str] = []
    members = payload.get("selected_models")
    if not isinstance(members, list):
        return warnings
    for index, value in enumerate(members):
        if isinstance(value, str) and value in {"", CHOOSE_MODEL, NO_MODEL}:
            continue
        if isinstance(value, str):
            try:
                parse_stored_model_id(value)
            except ValueError:
                pass
            else:
                continue
        warnings.append(
            f"selected_models[{index}]: expected canonical model ID "
            f"family:basename or a permitted sentinel; preserved {value!r}"
        )
    return warnings


def load_ensemble(name: str) -> Optional[EnsembleDocument]:
    """Load a saved ensemble's data (``selection_action_chosen_ensemble_load_saved``)."""
    path = _saved_ensemble_path(name)
    if os.path.isfile(path):
        with open(path) as infile:
            payload = json.load(infile)
        if not isinstance(payload, dict):
            raise ValueError(f"saved ensemble {name!r} must contain a JSON object")
        return EnsembleDocument(payload, _ensemble_syntax_warnings(payload))
    return None


def delete_ensemble(name: str) -> bool:
    """Remove a saved ensemble file (UVR's ``deletion_entry``)."""
    path = _saved_ensemble_path(name)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


@dataclass(frozen=True)
class ResolvedEnsemblePreset:
    id: str
    display: str
    kind: str
    main_stem: EnsemblePair
    algorithm: str
    members: tuple[Any, ...]
    source_members: tuple[Any, ...] = ()
    description: str = ""
    wav_ensemble: bool = False
    save_all_outputs: bool = True
    validation_warnings: tuple[str, ...] = ()


class EnsembleService:
    def __init__(self, repo: Any | None = None):
        from .model_repository import ModelRepository

        self.repo = repo or ModelRepository()
        self.identities = ModelIdentityService(self.repo)

    def resolve(self, name: str) -> ResolvedEnsemblePreset:
        from . import ensemble_presets

        raw = str(name or "").strip()
        if not raw:
            raise ValueError("ensemble name is empty")
        data = None
        kind = "saved"
        display = raw
        preset_id = raw
        curated_id = curated_id_from_combo_label(raw)
        if curated_id is not None:
            data = ensemble_presets.load_curated_ensemble(curated_id)
            if data is not None:
                kind, preset_id, display = "curated", curated_id, curated_combo_label(curated_id)
        if data is None:
            data = load_ensemble(raw)
        if data is None:
            candidate = raw.replace(" ", "_")
            if candidate in ensemble_presets.list_curated_ensembles():
                data = ensemble_presets.load_curated_ensemble(candidate)
                if data is not None:
                    kind, preset_id, display = "curated", candidate, curated_combo_label(candidate)
        if data is None:
            known = [
                *(curated_combo_label(item) for item in ensemble_presets.list_curated_ensembles()[:6]),
                *list_saved_ensembles()[:6],
            ]
            raise ValueError(
                f"unknown ensemble {raw!r}; available: "
                + (", ".join(repr(item) for item in known) or "(none)")
            )
        source_members = list(data.get("selected_models") or [])
        validation_warnings: list[str] = list(
            getattr(data, "validation_warnings", ())
        )
        members: list[Any] = []
        unresolved: list[Any] = []
        for index, reference in enumerate(source_members):
            try:
                members.append(self.identities.resolve(reference).id)
            except (AttributeError, TypeError, ValueError) as exc:
                unresolved.append(reference)
                # Syntax/type failures are already retained by the document
                # reader. Exact canonical IDs that disappear from the current
                # index need their own stage-two, field-specific warning.
                try:
                    parse_stored_model_id(reference)
                except (TypeError, ValueError):
                    pass
                else:
                    validation_warnings.append(
                        f"selected_models[{index}]: {exc}; preserved {reference!r}"
                    )
        # Preserve unresolved references for the GUI's missing-model download
        # offer; persistence validation never rewrites stored text.
        members.extend(unresolved)
        return ResolvedEnsemblePreset(
            preset_id,
            display,
            kind,
            coerce_ensemble_pair(data.get("ensemble_main_stem")),
            str(data.get("ensemble_type") or ""),
            tuple(members),
            tuple(source_members),
            str(data.get("description") or "").strip(),
            bool(data.get("is_wav_ensemble", False)),
            bool(data.get("save_all_outputs", True)),
            tuple(validation_warnings),
        )

    def apply(self, settings: Any, name: str) -> ResolvedEnsemblePreset:
        preset = self.resolve(name)
        settings.ensemble.selected_models = list(preset.members)
        if preset.algorithm:
            settings.ensemble.type = preset.algorithm
        settings.ensemble.main_stem = preset.main_stem
        settings.ensemble.chosen_ensemble = preset.display
        settings.ensemble.wav_ensemble = preset.wav_ensemble
        settings.ensemble.save_all_outputs = preset.save_all_outputs
        return preset

    def create(
        self, name: str, *, members: list[str], main_stem: str,
        algorithm: str, wav_ensemble: bool = False,
        save_all_outputs: bool = True, replace: bool = False,
    ) -> ResolvedEnsemblePreset:
        if load_ensemble(name) is not None and not replace:
            raise ValueError(f"ensemble {name!r} already exists; pass --replace")
        records = [self.identities.resolve(member) for member in members]
        if any(record.family == "apollo" for record in records):
            raise ValueError("Apollo restoration models cannot be ensemble members")
        canonical = list(dict.fromkeys(record.id for record in records))
        if len(canonical) < 2:
            raise ValueError("an ensemble requires at least two distinct models")
        pair = coerce_ensemble_pair(main_stem)
        if pair is EnsemblePair.CHOOSE:
            raise ValueError("choose an ensemble stem pair")
        if not str(algorithm).strip():
            raise ValueError("choose an ensemble algorithm")
        save_ensemble(
            name, pair, algorithm, canonical,
            wav_ensemble=wav_ensemble, save_all_outputs=save_all_outputs,
        )
        return self.resolve(name)

    @staticmethod
    def delete(name: str) -> bool:
        return delete_ensemble(name)


def apply_ensemble_preset(settings: Any, name: str, *, repo: Any | None = None) -> ResolvedEnsemblePreset:
    return EnsembleService(repo).apply(settings, name)
