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

    def test_parameter_dialog_prefers_the_carried_identity_display(self) -> None:
        from ui.dialogs import model_params

        model_data = SimpleNamespace(
            process_method=MDX_ARCH_TYPE,
            model_path="checkpoint.onnx",
            model_name="raw-checkpoint",
            model_display_label=self.record.display,
            repo=self.repo,
        )
        dialog = model_params._ParamDialog.__new__(model_params._ParamDialog)
        dialog.model_data = model_data
        dialog.existing = {}
        groups: list[object] = []
        page = SimpleNamespace(add=groups.append)

        class Group:
            def __init__(self, **kwargs: object) -> None:
                self.title = kwargs.get("title")

        with mock.patch.object(
            model_params.Adw, "PreferencesGroup", Group
        ), mock.patch.object(
            model_params, "display_name_for_model", return_value="stale mapper label"
        ), mock.patch.object(dialog, "_build_mdx"):
            dialog._build(page)

        self.assertEqual(getattr(groups[0], "title", None), self.record.display)

    def test_parameter_dialog_keeps_the_carried_display_without_a_repository(
        self,
    ) -> None:
        from ui.dialogs import model_params

        model_data = SimpleNamespace(
            process_method=MDX_ARCH_TYPE,
            model_path="checkpoint.onnx",
            model_name="raw-checkpoint",
            model_display_label=self.record.display,
            repo=None,
        )
        dialog = model_params._ParamDialog.__new__(model_params._ParamDialog)
        dialog.model_data = model_data
        dialog.existing = {}
        groups: list[object] = []
        page = SimpleNamespace(add=groups.append)

        class Group:
            def __init__(self, **kwargs: object) -> None:
                self.title = kwargs.get("title")

        with mock.patch.object(
            model_params.Adw, "PreferencesGroup", Group
        ), mock.patch.object(dialog, "_build_mdx"):
            dialog._build(page)

        self.assertEqual(getattr(groups[0], "title", None), self.record.display)


if __name__ == "__main__":
    unittest.main()
