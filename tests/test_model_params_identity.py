"""Change Model Defaults consumes canonical identity records directly."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from bundled.constants import MDX_ARCH_TYPE
from core.model_identity import ModelArtifacts, ModelRecord


class ChangeDefaultsIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.record = ModelRecord(
            id="mdx:checkpoint",
            family="mdx",
            basename="checkpoint",
            display="MDX-Net — Friendly checkpoint",
            backend_name="checkpoint.onnx",
            artifacts=ModelArtifacts("checkpoint.onnx"),
            installed=True,
        )
        self.settings = object()
        self.repo = object()

    def _resolve(self, *, hash_dir_only: bool) -> tuple[object, mock.Mock]:
        from ui.dialogs import model_params

        configured = object()
        constructor = mock.Mock(return_value=configured)
        with mock.patch.object(
            model_params.ModelIdentityService,
            "lookup",
            autospec=True,
            return_value=self.record,
        ), mock.patch.object(model_params, "ModelConfig", constructor):
            result = model_params._change_defaults_model_config(
                SimpleNamespace(settings=self.settings, repo=self.repo),
                self.record.id,
                is_get_hash_dir_only=hash_dir_only,
            )
        self.assertIs(result, configured)
        return result, constructor

    def test_normal_dry_inspection_passes_exact_record_identity(self) -> None:
        _result, constructor = self._resolve(hash_dir_only=False)

        constructor.assert_called_once_with(
            self.settings,
            self.repo,
            self.record.display,
            self.record.arch,
            is_dry_check=True,
            is_get_hash_dir_only=False,
            identity=self.record,
        )

    def test_hash_directory_inspection_preserves_exact_record_identity(self) -> None:
        _result, constructor = self._resolve(hash_dir_only=True)

        constructor.assert_called_once_with(
            self.settings,
            self.repo,
            self.record.display,
            MDX_ARCH_TYPE,
            is_dry_check=True,
            is_get_hash_dir_only=True,
            identity=self.record,
        )


if __name__ == "__main__":
    unittest.main()
