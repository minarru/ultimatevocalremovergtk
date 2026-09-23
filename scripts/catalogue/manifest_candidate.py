"""Manifest candidate for the one-snapshot catalogue publication pipeline."""

from __future__ import annotations

import copy
from typing import (
    TYPE_CHECKING,
    Any,
    Mapping,
    Sequence,
)

if TYPE_CHECKING:
    from core.model_manifest.schema import ModelManifestRegistry

from catalogue.audit_rules import _catalogue_model_id, _diagnostic_sort_key, _sorted_model_ids
from catalogue.audit_types import ManifestCandidateResult, StemAuditDiagnostic
from catalogue.types import ModelEntry


def _manifest_config_sources(entry: ModelEntry, existing: object) -> tuple[str, ...]:
    """Return exact sources for collected config bytes without inventing provenance."""
    if entry.config_url:
        return (entry.config_url,)
    if entry.metadata_source == f"bundled_yaml:{entry.config_yaml}":
        return ("models/MDX_Net_Models/model_data/mdx_c_configs/" + entry.config_yaml,)
    raw_sources = getattr(existing, "sources", ())
    return tuple(str(source) for source in raw_sources if str(source))


def _manifest_evidence_document(entry: ModelEntry) -> dict[str, str]:
    evidence = {
        "source": entry.source,
        "catalogue_label": entry.catalogue_label,
        "primary_artifact": entry.weight_file,
        "metadata_source": entry.metadata_source,
    }
    # Demucs bag YAML is an engine descriptor, not MDX training-config
    # evidence.  Publishing it in this field would make runtime consumers
    # request an MDX-style config proof for an exact non-config declaration.
    if entry.config_yaml and _catalogue_model_id(entry).startswith("mdx:"):
        evidence["config_yaml"] = entry.config_yaml
    return evidence


def build_manifest_candidate(
    entries: Sequence[ModelEntry],
    document: Mapping[str, object],
    *,
    registry: ModelManifestRegistry,
) -> ManifestCandidateResult:
    """Combine reviewed decisions with exact evidence from one collected snapshot.

    Lifecycle and semantic changes are findings, never automatic edits.  Only
    ``catalogue_evidence`` and the exact associated ``config_evidence`` row are
    refreshed; aliases, waivers, stem routes, roles, pairs, and runtime
    contracts remain byte-for-byte-equivalent Python values from ``document``.
    """
    from core.model_manifest import ModelManifestError, load_model_manifest_document

    candidate = copy.deepcopy(dict(document))
    raw_models = candidate.get("models")
    if not isinstance(raw_models, dict):
        raise ModelManifestError(("models",), "must be an object with string keys")

    entries_by_id: dict[str, ModelEntry] = {}
    duplicate_ids: set[str] = set()
    for entry in entries:
        model_id = _catalogue_model_id(entry)
        if model_id in entries_by_id:
            duplicate_ids.add(model_id)
        else:
            entries_by_id[model_id] = entry

    current_ids = {
        model_id for model_id, record in registry.models.items() if record.lifecycle == "current"
    }
    retired_ids = set(registry.models).difference(current_ids)
    collected_ids = set(entries_by_id)
    diagnostics: list[StemAuditDiagnostic] = []
    if duplicate_ids:
        diagnostics.append(
            StemAuditDiagnostic(
                code="catalogue-duplicate-id",
                model_ids=_sorted_model_ids(duplicate_ids),
                message="multiple collected entries project to the same canonical model ID",
            )
        )
    new_ids = collected_ids.difference(registry.models)
    if new_ids:
        diagnostics.append(
            StemAuditDiagnostic(
                code="manifest-new-current",
                model_ids=_sorted_model_ids(new_ids),
                message="catalogue IDs need an explicit reviewed manifest record",
            )
        )
    missing_ids = current_ids.difference(collected_ids)
    if missing_ids:
        diagnostics.append(
            StemAuditDiagnostic(
                code="manifest-missing-current",
                model_ids=_sorted_model_ids(missing_ids),
                message="current manifest IDs must be explicitly retired before disappearing",
            )
        )
    reappeared_ids = retired_ids.intersection(collected_ids)
    if reappeared_ids:
        diagnostics.append(
            StemAuditDiagnostic(
                code="manifest-retired-reappeared",
                model_ids=_sorted_model_ids(reappeared_ids),
                message="retired manifest IDs must be explicitly reviewed as current",
            )
        )

    evidence_states = {
        "ready": 0,
        "pending": 0,
        "unavailable": 0,
        "stale": 0,
        "not_applicable": 0,
    }
    reference_drift_ids: set[str] = set()
    for model_id in sorted(current_ids.intersection(collected_ids), key=str.casefold):
        entry = entries_by_id[model_id]
        raw_record = raw_models.get(model_id)
        if not isinstance(raw_record, dict):
            continue
        observed_catalogue = _manifest_evidence_document(entry)
        reviewed_catalogue = registry.models[model_id].catalogue_evidence
        if (
            observed_catalogue["source"] == reviewed_catalogue.source
            and observed_catalogue["catalogue_label"] == reviewed_catalogue.catalogue_label
            and observed_catalogue["primary_artifact"] == reviewed_catalogue.primary_artifact
            and observed_catalogue["metadata_source"]
            in reviewed_catalogue.metadata_source.split("+")
        ):
            # A collected source can expose only one layer of an already
            # exact, composite provenance chain.  Do not erase the other
            # reviewed exact layer when identity and artifact are unchanged.
            observed_catalogue["metadata_source"] = reviewed_catalogue.metadata_source
        required_catalogue_values = (
            entry.source,
            entry.catalogue_label,
            entry.weight_file,
            entry.metadata_source,
        )
        unavailable_catalogue = (
            any(not value for value in required_catalogue_values)
            or entry.source
            in {
                "unknown",
                "unavailable",
            }
            or entry.metadata_source == "unavailable"
        )
        if unavailable_catalogue:
            diagnostics.append(
                StemAuditDiagnostic(
                    code="catalogue-evidence-missing",
                    model_ids=(model_id,),
                    message="current catalogue record lacks required exact acquisition evidence",
                )
            )
            evidence_states["unavailable"] += 1
            continue

        reviewed_configs = registry.models[model_id].config_evidence
        reviewed_config = registry.models[model_id].catalogue_evidence.config_yaml
        if (
            model_id.startswith("mdx:")
            and reviewed_configs
            and reviewed_config
            and not entry.config_yaml
        ):
            diagnostics.append(
                StemAuditDiagnostic(
                    code="config-evidence-missing",
                    model_ids=(model_id,),
                    message="reviewed config association is absent from collected evidence",
                    expected=(reviewed_config,),
                    actual=(entry.config_yaml,),
                )
            )
            evidence_states["unavailable"] += 1
            # Do not delete exact reviewed evidence on an unavailable fetch.
            continue

        if raw_record.get("catalogue_evidence") != observed_catalogue:
            reference_drift_ids.add(model_id)
        raw_record["catalogue_evidence"] = observed_catalogue

        if model_id in registry.stems.waivers:
            evidence_states["not_applicable"] += 1
        else:
            evidence_states["ready"] += 1

        # A catalogue config name is acquisition evidence, not permission to
        # invent a new semantic authority.  Only refresh config evidence that
        # already exists in the reviewed manifest.
        if not reviewed_configs or not entry.config_yaml or not model_id.startswith("mdx:"):
            continue
        existing = reviewed_configs.get(entry.config_yaml)
        sources = _manifest_config_sources(entry, existing)
        if not entry.config_sha256 or not sources:
            diagnostics.append(
                StemAuditDiagnostic(
                    code="config-evidence-missing",
                    model_ids=(model_id,),
                    message="associated config lacks exact bytes, digest, or provenance",
                )
            )
            evidence_states["ready"] -= 1
            evidence_states["unavailable"] += 1
            continue

        observed_instruments = tuple(str(value) for value in entry.instruments)
        observed_target = entry.target_instrument or None
        if existing is not None and (
            observed_instruments != tuple(existing.training_instruments)
            or observed_target != existing.target_instrument
        ):
            diagnostics.append(
                StemAuditDiagnostic(
                    code="config-semantic-mismatch",
                    model_ids=(model_id,),
                    message="parsed config signature or target differs from reviewed evidence",
                    expected=(
                        "|".join(existing.training_instruments),
                        existing.target_instrument or "",
                    ),
                    actual=("|".join(observed_instruments), observed_target or ""),
                )
            )
            continue
        if existing is not None and entry.config_sha256 != existing.content_sha256:
            if model_id in registry.runtime.contracts:
                diagnostics.append(
                    StemAuditDiagnostic(
                        code="runtime-config-digest-mismatch",
                        model_ids=(model_id,),
                        message=(
                            "strict runtime contract requires the exact approved config digest"
                        ),
                        expected=(existing.content_sha256,),
                        actual=(entry.config_sha256,),
                    )
                )
                # Runtime contracts deliberately bind exact bytes. Keep the
                # approved record intact until a human reviews the contract.
                continue
            diagnostics.append(
                StemAuditDiagnostic(
                    code="config-digest-drift",
                    model_ids=(model_id,),
                    message="config bytes changed while parsed training semantics stayed the same",
                    expected=(existing.content_sha256,),
                    actual=(entry.config_sha256,),
                    structural=False,
                )
            )
        observed_config = {
            "training_instruments": list(observed_instruments),
            "target_instrument": observed_target,
            "content_sha256": entry.config_sha256,
            "sources": list(sources),
        }
        raw_configs = raw_record.setdefault("config_evidence", {})
        if not isinstance(raw_configs, dict):
            continue
        if raw_configs.get(entry.config_yaml) != observed_config:
            reference_drift_ids.add(model_id)
        raw_configs[entry.config_yaml] = observed_config

    diagnostics.sort(key=_diagnostic_sort_key)
    candidate_presentation: Mapping[str, Any] | None = None
    if not any(diagnostic.structural for diagnostic in diagnostics):
        # A candidate is publishable only when every domain and cross-reference
        # still passes the same strict loader used by runtime consumers.
        candidate_presentation = load_model_manifest_document(candidate).presentation
    return ManifestCandidateResult(
        document=candidate,
        diagnostics=tuple(diagnostics),
        current_model_ids=_sorted_model_ids(current_ids),
        retired_model_ids=_sorted_model_ids(retired_ids),
        evidence_states=evidence_states,
        reference_drift_model_ids=_sorted_model_ids(reference_drift_ids),
        presentation=candidate_presentation,
    )
