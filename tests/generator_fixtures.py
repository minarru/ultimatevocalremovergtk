"""Shared generator fixtures; no discovered test classes."""

import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import generate_models_catalogue as cli  # noqa: E402
from catalogue import audit_types as catalogue_audit_types  # noqa: E402
from catalogue import evidence as catalogue_evidence  # noqa: E402
from catalogue import manifest_candidate as catalogue_manifest_candidate  # noqa: E402
from catalogue import types as catalogue_types  # noqa: E402
from catalogue.audit_types import (  # noqa: E402
    CatalogueEvidenceCounts,
    StemAuditResult,
)

from core.catalogue_types import SourceId  # noqa: E402


def _clean_stem_audit(*_args: object, **_kwargs: object) -> StemAuditResult:
    """Keep publication fixtures focused on artifact behavior, not manifest coverage."""
    return StemAuditResult(
        catalogue_model_ids=(),
        reviewed_model_ids=(),
        waived_model_ids=(),
        raw_model_ids=(),
        evidence_counts=CatalogueEvidenceCounts(148, 123, 92, ()),
        diagnostics=(),
    )


@contextmanager
def _legacy_publication_manifest_fixture():
    """Keep pre-unification CLI fixtures focused on their original boundary."""
    import copy
    import tempfile

    source_document = json.loads(Path(cli.BUNDLED_MODEL_MANIFEST_PATH).read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="uvr-generator-manifest-fixture-") as directory:
        path = Path(directory) / "model_manifest.json"
        path.write_text(
            json.dumps(source_document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        def unchanged_candidate(
            entries: list[catalogue_types.ModelEntry],
            document: dict[str, object],
            **_kwargs: object,
        ) -> object:
            ids = tuple(
                sorted(
                    (catalogue_evidence.catalogue_projection(entry)[0] for entry in entries),
                    key=str.casefold,
                )
            )
            return catalogue_audit_types.ManifestCandidateResult(
                document=copy.deepcopy(document),
                diagnostics=(),
                current_model_ids=ids,
                retired_model_ids=(),
                evidence_states={
                    "ready": len(ids),
                    "pending": 0,
                    "unavailable": 0,
                    "stale": 0,
                    "not_applicable": 0,
                },
            )

        with (
            mock.patch.object(cli, "BUNDLED_MANIFEST_PATH", path),
            mock.patch.object(
                catalogue_manifest_candidate,
                "build_manifest_candidate",
                side_effect=unchanged_candidate,
            ),
        ):
            yield


def _local(source_id: SourceId, payload: dict):
    from core.remote_catalog_cache import RemoteJsonSource

    return RemoteJsonSource(source_id=source_id, local_loader=lambda: payload)


def _disabled(source_id: SourceId):
    from core.remote_catalog_cache import RemoteJsonSource

    return RemoteJsonSource(source_id=source_id, enabled=lambda: False)


def _generator_manifest_document(*, lifecycle: str = "current") -> dict[str, Any]:
    """Small valid unified manifest for generator candidate-contract tests."""
    return {
        "schema_version": 1,
        "author_aliases": {},
        "roles": {
            "vocal.vocals": {
                "display": "Vocals",
                "filename_tag": "Vocals",
                "family": "vocal",
            }
        },
        "pairs": {},
        "models": {
            "mdx:model": {
                "lifecycle": lifecycle,
                "display_alias": "Reviewed Fixture",
                "stem_semantics": {
                    "native_signature": ["Vocals"],
                    "intent": "vocals",
                    "contexts": {
                        "full_mix": {
                            "logical_primary": "vocal.vocals",
                            "outputs": [
                                {
                                    "native": "Vocals",
                                    "role": "vocal.vocals",
                                }
                            ],
                        }
                    },
                    "review_note": "Human-reviewed fixture semantics.",
                },
                "catalogue_evidence": {
                    "source": "old-source",
                    "catalogue_label": "Old label",
                    "primary_artifact": "model.ckpt",
                    "metadata_source": "old-metadata",
                    "config_yaml": "model.yaml",
                },
                "config_evidence": {
                    "model.yaml": {
                        "training_instruments": ["Vocals", "Other"],
                        "target_instrument": "Vocals",
                        "content_sha256": "a" * 64,
                        "sources": ["https://old.test/model.yaml"],
                    }
                },
            }
        },
    }


def _generator_manifest_entry(**changes: object) -> catalogue_types.ModelEntry:
    values: dict[str, object] = {
        "source": "fixture-source",
        "family": "MDX23C",
        "catalogue_label": "Fixture Model",
        "weight_file": "model.ckpt",
        "config_yaml": "model.yaml",
        "config_url": "https://new.test/model.yaml",
        "config_sha256": "a" * 64,
        "instruments": ["Vocals", "Other"],
        "target_instrument": "Vocals",
        "metadata_source": "remote_yaml:model.yaml",
    }
    values.update(changes)
    return catalogue_types.ModelEntry(**values)  # type: ignore[arg-type]


def _candidate_document(
    result: catalogue_audit_types.ManifestCandidateResult,
) -> dict[str, Any]:
    """Narrow a validated candidate to the JSON object shape used by fixtures."""
    return cast(dict[str, Any], result.document)
