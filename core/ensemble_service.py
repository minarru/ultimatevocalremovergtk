"""Saved and curated ensemble resolution shared by GUI and CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ensemble_presets import curated_combo_label, curated_id_from_combo_label
from .model_data import ModelRepository
from .model_identity import ModelIdentityService
from .stems import EnsemblePair, coerce_ensemble_pair


@dataclass(frozen=True)
class ResolvedEnsemblePreset:
    id: str
    display: str
    kind: str
    main_stem: EnsemblePair
    algorithm: str
    members: tuple[str, ...]
    source_members: tuple[str, ...] = ()
    description: str = ""
    wav_ensemble: bool = False
    save_all_outputs: bool = True


class EnsembleService:
    def __init__(self, repo: Any | None = None):
        self.repo = repo or ModelRepository()
        self.identities = ModelIdentityService(self.repo)

    def resolve(self, name: str) -> ResolvedEnsemblePreset:
        from . import ensemble_presets, model_data

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
            data = model_data.load_ensemble(raw)
        if data is None:
            candidate = raw.replace(" ", "_")
            if candidate in ensemble_presets.list_curated_ensembles():
                data = ensemble_presets.load_curated_ensemble(candidate)
                if data is not None:
                    kind, preset_id, display = "curated", candidate, curated_combo_label(candidate)
        if data is None:
            known = [
                *(curated_combo_label(item) for item in ensemble_presets.list_curated_ensembles()[:6]),
                *model_data.list_saved_ensembles()[:6],
            ]
            raise ValueError(
                f"unknown ensemble {raw!r}; available: "
                + (", ".join(repr(item) for item in known) or "(none)")
            )
        source_members = list(data.get("selected_models") or [])
        if kind == "curated":
            source_members = ensemble_presets.resolve_member_tags(source_members, self.repo)
        members: list[str] = []
        unresolved: list[str] = []
        for reference in source_members:
            try:
                if str(reference).partition(":")[0].casefold() in {"vr", "mdx", "demucs"}:
                    members.append(self.identities.resolve(reference).id)
                else:
                    members.append(self.identities.canonical_id_from_member_tag(reference))
            except (AttributeError, TypeError, ValueError):
                unresolved.append(str(reference))
        # Preserve unresolved curated references for the GUI's missing-model
        # download offer; canonical migration handles user storage separately.
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
        from .model_data import load_ensemble, save_ensemble

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
        from .model_data import delete_ensemble

        return delete_ensemble(name)


def apply_ensemble_preset(settings: Any, name: str, *, repo: Any | None = None) -> ResolvedEnsemblePreset:
    return EnsembleService(repo).apply(settings, name)
