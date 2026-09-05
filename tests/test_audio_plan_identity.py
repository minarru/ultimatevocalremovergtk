"""Semantic identity contract for resolved Audio Tools plans."""

from __future__ import annotations

import dataclasses
import tempfile
import unittest
from types import MappingProxyType, SimpleNamespace
from typing import Any
from unittest import mock

from bundled.constants import APOLLO_RESTORE, CHANGE_PITCH
from core.audio_plan import AudioJobResolver, AudioJobSpec, ResolvedAudioJob
from core.job_plan import (
    EMPTY_MODEL_IDENTITY_DIGEST,
    ModelDescriptor,
    ValidationLevel,
    compute_model_identity_digest,
)
from core.model_identity import ModelArtifacts, ModelRecord
from core.settings import Settings

_APOLLO_PATH = "audio_tools.apollo_model"


def _apollo_record(
    *,
    backend_name: str = "restorer.ckpt",
    artifacts: ModelArtifacts | None = None,
    installed: bool = True,
    identity_complete: bool = True,
) -> ModelRecord:
    return ModelRecord(
        id="apollo:restorer",
        family="apollo",
        basename="restorer",
        display="Apollo Restorer",
        backend_name=backend_name,
        artifacts=artifacts or ModelArtifacts("restorer.ckpt"),
        installed=installed,
        identity_complete=identity_complete,
        identity_error=None if identity_complete else "missing Apollo metadata",
    )


def _resolved_stub(record: ModelRecord, checkpoint: str) -> ResolvedAudioJob:
    dependencies = MappingProxyType({_APOLLO_PATH: record})
    return ResolvedAudioJob(
        tool=APOLLO_RESTORE,
        settings=Settings.defaults(),
        output="/tmp/out",
        units=(),
        provenance=MappingProxyType({}),
        diagnostics=(),
        validation_level=ValidationLevel.CONFIG,
        inventory_generation=7,
        settings_fingerprint="fingerprint",
        device="cpu",
        model=ModelDescriptor(
            id=record.id,
            family=record.family,
            basename=record.basename,
            display=record.display,
            backend_name=record.backend_name,
            artifacts=record.artifacts,
            checkpoint=checkpoint,
            checkpoint_hash="stable-checkpoint-md5",
        ),
        model_dependencies=dependencies,
        model_identity_digest=compute_model_identity_digest(dependencies),
    )


class AudioPlanIdentityTests(unittest.TestCase):
    def test_constructor_snapshots_and_freezes_dependency_mapping(self) -> None:
        record = _apollo_record()
        supplied = {_APOLLO_PATH: record}
        plan = dataclasses.replace(
            _resolved_stub(record, "/tmp/restorer.ckpt"),
            model_dependencies=supplied,
        )

        supplied.clear()
        self.assertEqual(dict(plan.model_dependencies), {_APOLLO_PATH: record})
        mutable_view: Any = plan.model_dependencies
        with self.assertRaises(TypeError):
            mutable_view[_APOLLO_PATH] = record

    def test_apollo_resolve_carries_exact_immutable_dependency_and_digest(self) -> None:
        record = _apollo_record(
            artifacts=ModelArtifacts("restorer.ckpt", ("restorer.yaml",))
        )
        settings = Settings.defaults()
        settings.audio_tools.apollo_model = record.id
        resolver = AudioJobResolver(mock.Mock(inventory_generation=7))
        resolver.identities = mock.Mock()
        resolver.identities.lookup.return_value = record
        resolver.identities.resolve.return_value = record

        with tempfile.NamedTemporaryFile(suffix=".wav") as source:
            plan = resolver.resolve(
                AudioJobSpec(
                    APOLLO_RESTORE,
                    settings,
                    "/tmp/out",
                    (source.name,),
                ),
                ValidationLevel.CONFIG,
            )

        dependencies = getattr(plan, "model_dependencies", {})
        self.assertEqual(dict(dependencies), {_APOLLO_PATH: record})
        self.assertEqual(
            getattr(plan, "model_identity_digest", None),
            compute_model_identity_digest({_APOLLO_PATH: record}),
        )
        mutable_view: Any = dependencies
        with self.assertRaises(TypeError):
            mutable_view[_APOLLO_PATH] = _apollo_record(backend_name="other.ckpt")
        resolver.identities.lookup.assert_called_once_with(record.id)
        resolver.identities.resolve.assert_not_called()

        carried_digest = "sha256:" + "f" * 64
        carried = dataclasses.replace(plan, model_identity_digest=carried_digest)
        payload = carried.to_dict()
        self.assertEqual(payload["model_dependencies"], {_APOLLO_PATH: record.id})
        self.assertEqual(payload["model_identity_digest"], carried_digest)

    def test_non_model_audio_plan_carries_empty_identity_contract(self) -> None:
        settings = Settings.defaults()
        with tempfile.NamedTemporaryFile(suffix=".wav") as source:
            plan = AudioJobResolver(mock.Mock(inventory_generation=7)).resolve(
                AudioJobSpec(
                    CHANGE_PITCH,
                    settings,
                    "/tmp/out",
                    (source.name,),
                ),
                ValidationLevel.CONFIG,
            )

        self.assertEqual(dict(getattr(plan, "model_dependencies", {})), {})
        self.assertEqual(
            getattr(plan, "model_identity_digest", None),
            EMPTY_MODEL_IDENTITY_DIGEST,
        )
        self.assertEqual(plan.to_dict().get("model_dependencies"), {})
        self.assertEqual(
            plan.to_dict().get("model_identity_digest"),
            EMPTY_MODEL_IDENTITY_DIGEST,
        )

    def test_apollo_semantic_change_is_stale_with_same_generation_and_md5(self) -> None:
        original = _apollo_record()
        changed_records = (
            dataclasses.replace(original, backend_name="renamed.ckpt"),
            dataclasses.replace(
                original,
                artifacts=ModelArtifacts("restorer.ckpt", ("new-config.yaml",)),
            ),
        )

        with tempfile.NamedTemporaryFile(suffix=".ckpt") as checkpoint:
            for changed in changed_records:
                with self.subTest(changed=changed):
                    resolver = AudioJobResolver(mock.Mock(inventory_generation=7))
                    resolver.identities = mock.Mock()
                    resolver.identities.lookup.return_value = changed
                    plan = _resolved_stub(original, checkpoint.name)

                    with mock.patch(
                        "core.apollo.checkpoint_md5",
                        return_value="stable-checkpoint-md5",
                    ):
                        self.assertFalse(resolver.is_current(plan))

                    resolver.identities.lookup.assert_called_once_with(original.id)

    def test_exact_unchanged_apollo_dependency_remains_current(self) -> None:
        record = _apollo_record()
        resolver = AudioJobResolver(mock.Mock(inventory_generation=7))
        resolver.identities = mock.Mock()
        resolver.identities.lookup.return_value = record

        with tempfile.NamedTemporaryFile(suffix=".ckpt") as checkpoint, mock.patch(
            "core.apollo.checkpoint_md5",
            return_value="stable-checkpoint-md5",
        ):
            self.assertTrue(resolver.is_current(_resolved_stub(record, checkpoint.name)))

        resolver.identities.lookup.assert_called_once_with(record.id)

    def test_apollo_dependency_lookup_or_validity_failure_is_stale(self) -> None:
        original = _apollo_record()
        current_values: tuple[ModelRecord | Exception, ...] = (
            ValueError("missing exact identity"),
            dataclasses.replace(original, installed=False),
            dataclasses.replace(
                original,
                identity_complete=False,
                identity_error="missing Apollo metadata",
            ),
        )

        with tempfile.NamedTemporaryFile(suffix=".ckpt") as checkpoint:
            plan = _resolved_stub(original, checkpoint.name)
            with mock.patch(
                "core.apollo.checkpoint_md5",
                return_value="stable-checkpoint-md5",
            ):
                for current in current_values:
                    with self.subTest(current=current):
                        resolver = AudioJobResolver(
                            mock.Mock(inventory_generation=7)
                        )
                        resolver.identities = mock.Mock()
                        if isinstance(current, Exception):
                            resolver.identities.lookup.side_effect = current
                        else:
                            resolver.identities.lookup.return_value = current
                        self.assertFalse(resolver.is_current(plan))


class AudioPlanSerializationTests(unittest.TestCase):
    def test_cli_payload_uses_plan_carried_identity_contract(self) -> None:
        from cli.audio import _audio_plan_payload

        carried_digest = "sha256:" + "a" * 64
        payload = _audio_plan_payload(
            SimpleNamespace(
                model=ModelDescriptor(
                    id="apollo:restorer",
                    family="apollo",
                    basename="restorer",
                    display="Apollo Restorer",
                    backend_name="descriptor-would-recompute.ckpt",
                    artifacts=ModelArtifacts("descriptor-would-recompute.ckpt"),
                ),
                to_dict=lambda: {
                    "command": "audio",
                    "model_dependencies": {_APOLLO_PATH: "apollo:carried"},
                    "model_identity_digest": carried_digest,
                },
            )
        )

        self.assertEqual(
            payload["model_dependencies"],
            {_APOLLO_PATH: "apollo:carried"},
        )
        self.assertEqual(payload["model_identity_digest"], carried_digest)


if __name__ == "__main__":
    unittest.main()
