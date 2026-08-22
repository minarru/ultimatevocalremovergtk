"""The dry-check model pools, exercised against a real ``ModelRepository``.

Every other test around these pools patches ``stem_check`` or ``ModelConfig``
out and feeds stubs speaking the legacy ``"Arch: Display"`` tag dialect, so a
canonical-ID regression in the real code path was invisible: ``stem_check``
returned a config per installed model with ``model_status=False`` for all of
them, emptying the ensemble member lists, ``--vocal-split`` and every secondary
picker. These tests build genuine checkpoints on disk and assert the pools come
back populated.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock

from core import paths
from core.model_repository import ModelRepository
from core.settings import Settings
from core.stems import EnsemblePair

_VR_KARAOKE = "Test-Karaoke-Model"
_VR_VOCAL = "Test-Vocal-Model"
_MDX_VOCAL = "Test-MDX-Model"


def _write_checkpoint(path: str, payload: bytes) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(payload)
    return hashlib.md5(payload).hexdigest()


def _write_json(path: str, payload: dict[str, object]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


class RealModelPoolTests(unittest.TestCase):
    """Fixture checkpoints under a temporary model root."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name

        models = os.path.join(self.root, "models")
        vr_dir = os.path.join(models, "VR_Models")
        mdx_dir = os.path.join(models, "MDX_Net_Models")
        demucs_dir = os.path.join(models, "Demucs_Models")
        apollo_dir = os.path.join(models, "Apollo_Models")
        vr_hash_dir = os.path.join(vr_dir, "model_data")
        mdx_hash_dir = os.path.join(mdx_dir, "model_data")
        for directory in (vr_dir, mdx_dir, demucs_dir, apollo_dir, vr_hash_dir, mdx_hash_dir):
            os.makedirs(directory, exist_ok=True)

        patches = {
            "MODELS_DIR": models,
            "VR_MODELS_DIR": vr_dir,
            "MDX_MODELS_DIR": mdx_dir,
            "DEMUCS_MODELS_DIR": demucs_dir,
            "DEMUCS_NEWER_REPO_DIR": os.path.join(demucs_dir, "v3_v4_repo"),
            "APOLLO_MODELS_DIR": apollo_dir,
            "APOLLO_HASH_DIR": os.path.join(apollo_dir, "model_data"),
            "VR_HASH_DIR": vr_hash_dir,
            "VR_HASH_JSON": os.path.join(vr_hash_dir, "model_data.json"),
            "MDX_HASH_DIR": mdx_hash_dir,
            "MDX_HASH_JSON": os.path.join(mdx_hash_dir, "model_data.json"),
            "MDX_C_CONFIG_PATH": os.path.join(mdx_hash_dir, "mdx_c_configs"),
            "MDX_MODEL_NAME_SELECT": os.path.join(mdx_hash_dir, "model_name_mapper.json"),
            "DEMUCS_MODEL_NAME_SELECT": os.path.join(
                demucs_dir, "model_data", "model_name_mapper.json"
            ),
            "DEMUCS_MODEL_SPECS": os.path.join(demucs_dir, "model_data", "model_specs.json"),
            "REGISTERED_MODEL_INDEX": os.path.join(self.root, "registered_models.json"),
            "DENOISER_MODEL_PATH": os.path.join(vr_dir, "UVR-DeNoise-Lite.pth"),
            "DEVERBER_MODEL_PATH": os.path.join(vr_dir, "UVR-DeEcho-DeReverb.pth"),
        }
        for name, value in patches.items():
            patcher = mock.patch.object(paths, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        # Both network catalogue sources must be off: either one leaks a
        # background refresh thread into later test modules.
        env = mock.patch.dict(
            os.environ,
            {"UVR_DISABLE_POLITREES": "1", "UVR_DISABLE_MVSEPLESS": "1"},
            clear=False,
        )
        env.start()
        self.addCleanup(env.stop)

        karaoke_hash = _write_checkpoint(
            os.path.join(vr_dir, f"{_VR_KARAOKE}.pth"), b"vr-karaoke-weights"
        )
        _write_json(
            os.path.join(vr_hash_dir, f"{karaoke_hash}.json"),
            {
                "vr_model_param": "4band_v2",
                "primary_stem": "Vocals",
                "is_karaokee": True,
            },
        )
        vocal_hash = _write_checkpoint(
            os.path.join(vr_dir, f"{_VR_VOCAL}.pth"), b"vr-vocal-weights"
        )
        _write_json(
            os.path.join(vr_hash_dir, f"{vocal_hash}.json"),
            {"vr_model_param": "4band_v2", "primary_stem": "Vocals"},
        )
        mdx_hash = _write_checkpoint(
            os.path.join(mdx_dir, f"{_MDX_VOCAL}.onnx"), b"mdx-onnx-weights"
        )
        _write_json(
            os.path.join(mdx_hash_dir, f"{mdx_hash}.json"),
            {
                "compensate": 1.035,
                "mdx_dim_f_set": 2048,
                "mdx_dim_t_set": 8,
                "mdx_n_fft_scale_set": 6144,
                "primary_stem": "Vocals",
            },
        )

        self.settings = Settings()
        self.repo = ModelRepository()

    def test_installed_tags_are_canonical(self) -> None:
        self.assertEqual(
            sorted(self.repo.all_model_tags()),
            [f"mdx:{_MDX_VOCAL}", f"vr:{_VR_KARAOKE}", f"vr:{_VR_VOCAL}"],
        )

    def test_stem_check_resolves_every_installed_model(self) -> None:
        """The regression: canonical tags left every config unavailable.

        ``ModelConfig``'s legacy ensemble-tag parser splits on ``': '``, which a
        ``family:basename`` ID never contains, so ``model_status`` was forced
        ``False`` for all of them.
        """
        configs = self.repo.stem_check(self.settings)

        self.assertEqual(len(configs), 3)
        self.assertTrue(
            all(config.model_status for config in configs),
            [(c.model_and_process_tag, c.model_status) for c in configs],
        )
        self.assertEqual(
            sorted(config.model_and_process_tag for config in configs),
            [f"mdx:{_MDX_VOCAL}", f"vr:{_VR_KARAOKE}", f"vr:{_VR_VOCAL}"],
        )
        for config in configs:
            self.assertNotEqual(config.model_name, "")
            self.assertIn(config.process_method, {"VR Arc", "MDX-Net"})
            self.assertEqual(config.primary_stem, "Vocals")

    def test_ensemble_model_list_is_populated(self) -> None:
        members = self.repo.ensemble_model_list(
            self.settings, EnsemblePair.VOCALS_INSTRUMENTAL
        )
        # The karaoke model buckets to the karaoke pair, not vocals/instrumental.
        self.assertEqual(
            sorted(members), [f"mdx:{_MDX_VOCAL}", f"vr:{_VR_VOCAL}"]
        )
        self.assertEqual(
            self.repo.ensemble_model_list(self.settings, EnsemblePair.KARAOKE),
            [f"vr:{_VR_KARAOKE}"],
        )
        self.assertEqual(
            sorted(self.repo.ensemble_model_list(self.settings, EnsemblePair.MULTI_STEM)),
            [f"mdx:{_MDX_VOCAL}", f"vr:{_VR_KARAOKE}", f"vr:{_VR_VOCAL}"],
        )

    def test_karaoke_model_list_is_populated(self) -> None:
        self.assertEqual(
            self.repo.karaoke_model_list(self.settings), [f"vr:{_VR_KARAOKE}"]
        )

    def test_model_list_returns_canonical_ids(self) -> None:
        """The secondary-model pickers read this pool."""
        pool = self.repo.model_list(self.settings, "Vocals", "Instrumental")
        self.assertTrue(pool)
        for entry in pool:
            family, separator, basename = entry.partition(":")
            self.assertTrue(separator, entry)
            self.assertIn(family, {"vr", "mdx", "demucs"})
            self.assertTrue(basename)

    def test_unresolvable_tag_degrades_to_unavailable(self) -> None:
        """A tag with no identity record must not raise, only be unavailable."""
        with mock.patch.object(
            ModelRepository,
            "all_model_tags",
            lambda _self: ["vr:Not-Installed-At-All"],
        ):
            self.repo.invalidate_stem_check()
            configs = self.repo.stem_check(self.settings)
        self.assertEqual(len(configs), 1)
        self.assertFalse(configs[0].model_status)


if __name__ == "__main__":  # pragma: no cover - manual runs
    unittest.main()
