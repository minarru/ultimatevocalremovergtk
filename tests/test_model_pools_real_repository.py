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

import argparse
import hashlib
import json
import os
import tempfile
import typing
import unittest
from unittest import mock

from core import paths
from core.model_repository import ModelRepository
from core.settings import Settings

_VR_KARAOKE = "5_HP-Karaoke-UVR"
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
            "LEGACY_REGISTERED_MODEL_INDEX": os.path.join(
                self.root, "legacy-registered_models.json"
            ),
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

    def _install_configured_mdx_c(
        self, name: str, *, write_config: bool = True
    ) -> tuple[str, dict[str, object]]:
        from core.model_hash_cache import remember

        checkpoint_path = os.path.join(paths.MDX_MODELS_DIR, f"{name}.ckpt")
        checkpoint_hash = _write_checkpoint(checkpoint_path, f"{name}-weights".encode())
        config_name = f"{name}.yaml"
        if write_config:
            config_path = os.path.join(paths.MDX_C_CONFIG_PATH, config_name)
            os.makedirs(paths.MDX_C_CONFIG_PATH, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write("model:\n  freqs_per_bands: !!python/tuple\n  - 2\n  - 2\n")
        _write_json(
            os.path.join(paths.MDX_HASH_DIR, f"{checkpoint_hash}.json"),
            {"config_yaml": config_name},
        )
        persisted_hashes: dict[str, object] = {}
        remember(persisted_hashes, checkpoint_path, checkpoint_hash)
        return config_name, persisted_hashes

    def test_installed_tags_are_canonical(self) -> None:
        self.assertEqual(
            sorted(self.repo.all_model_tags()),
            [f"mdx:{_MDX_VOCAL}", f"vr:{_VR_KARAOKE}", f"vr:{_VR_VOCAL}"],
        )

    def test_trusted_hash_associates_installed_mdx_c_yaml_offline(self) -> None:
        from core.model_identity import ModelIdentityService

        config_name, persisted_hashes = self._install_configured_mdx_c("configured")
        self.repo.bind_model_hash_table(lambda: persisted_hashes)

        with mock.patch(
            "core.mdx_c_registry.compute_checkpoint_hash",
            side_effect=AssertionError("inventory hashed checkpoint"),
        ):
            record = ModelIdentityService(self.repo).index.lookup("mdx:configured")

        self.assertTrue(record.identity_complete)
        self.assertEqual(record.artifacts.supporting_filenames, (config_name,))
        assert record.mdx is not None
        self.assertEqual(record.mdx.kind, "bs_roformer")

    def test_bound_hash_table_rehydrates_after_model_invalidation(self) -> None:
        from core.model_identity import ModelIdentityService

        _config_name, persisted_hashes = self._install_configured_mdx_c("invalidated-configured")
        self.repo.bind_model_hash_table(lambda: persisted_hashes)
        first = ModelIdentityService(self.repo).index.lookup("mdx:invalidated-configured")

        self.repo.invalidate_models()
        second = ModelIdentityService(self.repo).index.lookup("mdx:invalidated-configured")

        self.assertTrue(first.identity_complete)
        self.assertTrue(second.identity_complete)

    def test_cli_separate_binds_persisted_hashes_before_identity_lookup(self) -> None:
        import dataclasses

        from cli.execution import run_batch
        from cli.job import resolve_separate_job
        from cli.main import build_parser
        from cli.profiles import LoadedProfile
        from core.job_plan import ValidationLevel
        from core.job_runner import JobRunner

        _config_name, persisted_hashes = self._install_configured_mdx_c("cli-configured")
        base_settings = Settings.defaults()
        persisted_settings = Settings.defaults()
        persisted_settings.process.model_hash_table = persisted_hashes
        profile = LoadedProfile("defaults", "built-in")
        input_path = os.path.join(self.root, "input.wav")
        with open(input_path, "wb") as handle:
            handle.write(b"RIFF")
        args = build_parser().parse_args(
            [
                "separate",
                input_path,
                "-o",
                self.root,
                "--model",
                "mdx:cli-configured",
                "--offline",
                "--dry-run",
            ]
        )

        with (
            mock.patch(
                "cli.job._base_resolve",
                return_value=(base_settings, profile, [input_path], self.root),
            ),
            mock.patch("cli.job.Settings.load", return_value=persisted_settings),
        ):
            job = resolve_separate_job(args, validation_level=ValidationLevel.MODEL)

        assert job.model is not None
        self.assertEqual(job.model.id, "mdx:cli-configured")
        self.assertTrue(job.model.identity_complete)
        self.assertEqual(job.settings.process.model_hash_table, {})
        self.assertIsNotNone(getattr(job, "repo", None))
        assert job.resolved is not None
        job.inputs = []
        job.resolved = dataclasses.replace(job.resolved, inputs=())
        resolve_models = JobRunner.resolve_models

        def resolve_with_complete_identity(
            runner: JobRunner,
            model_dependencies: typing.Mapping[str, typing.Any] | None = None,
        ) -> object:
            from core.model_identity import ModelIdentityService

            record = ModelIdentityService(runner.repo).index.lookup("mdx:cli-configured")
            self.assertTrue(record.identity_complete, record.identity_error)
            return resolve_models(runner, model_dependencies)

        with mock.patch.object(JobRunner, "resolve_models", resolve_with_complete_identity):
            outcome = run_batch(args, job)

        self.assertEqual(outcome.status, "success")

    def test_job_runner_owned_repository_binds_persisted_hashes(self) -> None:
        from core.job_runner import JobRunner
        from core.model_identity import ModelIdentityService
        from core.types import ProcessMethod

        _config_name, persisted_hashes = self._install_configured_mdx_c("runner-configured")
        settings = Settings.defaults()
        settings.process.model_hash_table = persisted_hashes
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:runner-configured"

        runner = JobRunner(settings)
        record = ModelIdentityService(runner.repo).index.lookup("mdx:runner-configured")

        self.assertTrue(record.identity_complete, record.identity_error)
        models = runner.resolve_models()
        self.assertEqual(len(models), 1)
        self.assertTrue(models[0].model_status)
        self.assertTrue(models[0].is_mdx_c)

    def test_job_runner_does_not_rebind_explicit_repository(self) -> None:
        from core.job_runner import JobRunner
        from core.types import ProcessMethod

        _config_name, persisted_hashes = self._install_configured_mdx_c(
            "injected-runner-configured"
        )
        self.repo.bind_model_hash_table(lambda: persisted_hashes)
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:injected-runner-configured"

        runner = JobRunner(settings, self.repo)
        models = runner.resolve_models()

        self.assertIs(runner.repo, self.repo)
        self.assertEqual(len(models), 1)
        self.assertTrue(models[0].model_status)
        self.assertTrue(models[0].is_mdx_c)

    def test_models_list_inspection_forbids_yaml_fetch_and_metadata_writes(self) -> None:
        import io
        from contextlib import redirect_stdout

        from cli.discovery import _model_info, cmd_models_list
        from core.access_policy import current_access_policy

        _config_name, persisted_hashes = self._install_configured_mdx_c(
            "missing-yaml", write_config=False
        )
        settings = Settings.defaults()
        settings.process.model_hash_table = persisted_hashes
        args = argparse.Namespace(
            family="mdx",
            all_known=False,
            report="json",
            quiet=True,
            verbose=False,
            job_id="offline-list",
        )
        real_model_info = _model_info

        def inspect_under_policy(record: object, repo: object) -> dict[str, object]:
            policy = current_access_policy()
            self.assertFalse(policy.allow_network)
            self.assertFalse(policy.allow_metadata_writes)
            return real_model_info(record, repo)

        with (
            mock.patch("cli.discovery.Settings.load", return_value=settings),
            mock.patch("cli.discovery._model_info", side_effect=inspect_under_policy),
            mock.patch(
                "core.mdx_config_fetch._fetch_url_to_file",
                side_effect=AssertionError("models list fetched YAML"),
            ) as fetch,
            redirect_stdout(io.StringIO()),
        ):
            code = cmd_models_list(args)

        self.assertEqual(code, 0)
        fetch.assert_not_called()

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

    def test_pair_pools_require_exact_reviewed_model_semantics(self) -> None:
        members = self.repo.ensemble_model_list(self.settings, "pair.vocals_instrumental")
        # These fixture-only custom IDs have metadata but no exact manifest
        # declarations, so semantic pair membership must fail closed.
        self.assertEqual(members, [])
        self.assertEqual(
            self.repo.ensemble_model_list(self.settings, "pair.karaoke"),
            [f"vr:{_VR_KARAOKE}"],
        )
        self.assertEqual(
            sorted(self.repo.ensemble_model_list(self.settings, "mode.multi_stem")),
            [f"mdx:{_MDX_VOCAL}", f"vr:{_VR_KARAOKE}", f"vr:{_VR_VOCAL}"],
        )

    def test_karaoke_model_list_is_populated(self) -> None:
        self.assertEqual(self.repo.karaoke_model_list(self.settings), [f"vr:{_VR_KARAOKE}"])

    def test_karaoke_pool_rejects_only_models_without_exact_reviewed_split_context(self) -> None:
        rejected_vr = (
            "Metadata-Only-Karaoke",
            "4_HP-Vocal-UVR",
            "UVR-DeNoise",
        )
        for name in rejected_vr:
            checkpoint_hash = _write_checkpoint(
                os.path.join(paths.VR_MODELS_DIR, f"{name}.pth"),
                f"{name}-weights".encode(),
            )
            _write_json(
                os.path.join(paths.VR_HASH_DIR, f"{checkpoint_hash}.json"),
                {
                    "vr_model_param": "4band_v2",
                    "primary_stem": "Vocals",
                    "is_karaokee": True,
                },
            )

        reviewed = "UVR_MDXNET_KARA"
        reviewed_hash = _write_checkpoint(
            os.path.join(paths.MDX_MODELS_DIR, f"{reviewed}.onnx"),
            b"reviewed-karaoke-weights",
        )
        _write_json(
            os.path.join(paths.MDX_HASH_DIR, f"{reviewed_hash}.json"),
            {
                "compensate": 1.035,
                "mdx_dim_f_set": 2048,
                "mdx_dim_t_set": 8,
                "mdx_n_fft_scale_set": 6144,
                "primary_stem": "Vocals",
                "is_karaokee": True,
            },
        )
        self.repo.invalidate_models()

        self.assertEqual(
            self.repo.karaoke_model_list(self.settings),
            [f"vr:{_VR_KARAOKE}", f"mdx:{reviewed}"],
        )

    def test_real_planner_accepts_only_exact_karaoke_splitter_ids(self) -> None:
        from core.job_plan import JobResolver, JobSpec, ValidationLevel
        from core.types import ProcessMethod

        source = os.path.join(self.root, "karaoke-plan.wav")
        with open(source, "wb") as handle:
            handle.write(b"RIFF")

        def plan(splitter: str):
            settings = Settings.defaults()
            settings.process.method = ProcessMethod.MDX
            settings.mdx.model = f"mdx:{_MDX_VOCAL}"
            settings.process.vocal_splitter_enabled = True
            settings.process.vocal_splitter = splitter
            return JobResolver(self.repo).resolve(
                JobSpec("separate", settings, (source,), self.root),
                ValidationLevel.CONFIG,
                allow_network=False,
            )

        rejected = plan(f"vr:{_VR_VOCAL}")
        accepted = plan(f"vr:{_VR_KARAOKE}")

        self.assertIn("model.identity", [item.code for item in rejected.diagnostics])
        self.assertNotIn("model.identity", [item.code for item in accepted.diagnostics])
        self.assertEqual(
            accepted.model_dependencies["process.vocal_splitter"].id,
            f"vr:{_VR_KARAOKE}",
        )

    def test_real_planner_recovers_missing_trusted_mdx_yaml_online(self) -> None:
        from core.job_plan import JobResolver, JobSpec, ValidationLevel
        from core.types import ProcessMethod

        config_name, persisted_hashes = self._install_configured_mdx_c(
            "online-recovery", write_config=False
        )
        self.repo.bind_model_hash_table(lambda: persisted_hashes)
        source = os.path.join(self.root, "online-recovery.wav")
        with open(source, "wb") as handle:
            handle.write(b"RIFF")
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:online-recovery"

        def fetch(name: str, **_kwargs: object) -> bool:
            self.assertEqual(name, config_name)
            os.makedirs(paths.MDX_C_CONFIG_PATH, exist_ok=True)
            with open(
                os.path.join(paths.MDX_C_CONFIG_PATH, name),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("model_type: mdx23c\n")
            return True

        with mock.patch("core.mdx_config_fetch.ensure_mdx_c_config", side_effect=fetch) as ensure:
            plan = JobResolver(self.repo).resolve(
                JobSpec("separate", settings, (source,), self.root),
                ValidationLevel.CONFIG,
                allow_network=True,
            )

        ensure.assert_called_once()
        self.assertNotIn("model.identity", [item.code for item in plan.diagnostics])
        self.assertNotIn("model.configuration", [item.code for item in plan.diagnostics])
        dependency = plan.model_dependencies["mdx.model"]
        self.assertTrue(dependency.identity_complete)
        self.assertEqual(dependency.artifacts.supporting_filenames, (config_name,))

    def test_real_planner_missing_trusted_mdx_yaml_offline_is_read_only(self) -> None:
        from core.job_plan import JobResolver, JobSpec, ValidationLevel
        from core.types import ProcessMethod

        config_name, persisted_hashes = self._install_configured_mdx_c(
            "offline-recovery", write_config=False
        )
        self.repo.bind_model_hash_table(lambda: persisted_hashes)
        source = os.path.join(self.root, "offline-recovery.wav")
        with open(source, "wb") as handle:
            handle.write(b"RIFF")
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:offline-recovery"

        with mock.patch(
            "core.mdx_config_fetch.ensure_mdx_c_config",
            side_effect=AssertionError("offline planning fetched"),
        ) as ensure:
            plan = JobResolver(self.repo).resolve(
                JobSpec("separate", settings, (source,), self.root),
                ValidationLevel.CONFIG,
                allow_network=False,
            )

        ensure.assert_not_called()
        self.assertFalse(os.path.exists(os.path.join(paths.MDX_C_CONFIG_PATH, config_name)))
        self.assertIn("model.configuration", [item.code for item in plan.diagnostics])

    def test_model_list_returns_canonical_ids(self) -> None:
        """The secondary-model pickers read this pool."""
        pool = self.repo.model_list(self.settings, "Vocals", "Instrumental")
        self.assertTrue(pool)
        for entry in pool:
            family, separator, basename = entry.partition(":")
            self.assertTrue(separator, entry)
            self.assertIn(family, {"vr", "mdx", "demucs"})
            self.assertTrue(basename)

    def test_pool_ids_are_all_resolvable_records(self) -> None:
        """Every ID a pool emits must look up in the identity index.

        A dotted basename such as ``..._sdr_10.1956`` used to lose its ``.1956``
        to a second ``os.path.splitext`` in the row-key helper, so the ensemble
        page offered a member -- and ``--vocal-split`` a splitter -- that no
        record answered to.
        """
        from core.model_identity import ModelIdentityService

        dotted = "Test-Dotted-Model.1956"
        dotted_hash = _write_checkpoint(
            os.path.join(paths.VR_MODELS_DIR, f"{dotted}.pth"), b"vr-dotted-weights"
        )
        _write_json(
            os.path.join(paths.VR_HASH_DIR, f"{dotted_hash}.json"),
            {
                "vr_model_param": "4band_v2",
                "primary_stem": "Vocals",
                "is_karaokee": True,
            },
        )
        self.repo.invalidate_models()
        index = ModelIdentityService(self.repo).index

        pools = {
            "multi": self.repo.ensemble_model_list(self.settings, "mode.multi_stem"),
            "voc_inst": self.repo.ensemble_model_list(self.settings, "pair.vocals_instrumental"),
            "karaoke_pair": self.repo.ensemble_model_list(self.settings, "pair.karaoke"),
            "splitter": self.repo.karaoke_model_list(self.settings),
        }
        self.assertIn(f"vr:{dotted}", pools["multi"])
        # Exact identity resolution is not sufficient for Vocal Splitter:
        # this metadata-only custom model has no reviewed vocal_split context.
        self.assertNotIn(f"vr:{dotted}", pools["splitter"])
        for name, pool in pools.items():
            for tag in pool:
                with self.subTest(pool=name, tag=tag):
                    index.lookup(tag)

    def test_unrecognized_demucs_row_does_not_empty_valid_pools(self) -> None:
        """One unbuildable installed row must not discard valid siblings."""
        bad = "Test-Unrecognized-Demucs"
        _write_json(
            os.path.join(paths.DEMUCS_NEWER_REPO_DIR, f"{bad}.yaml"),
            {"models": []},
        )
        self.repo.invalidate_models()

        configs = self.repo.stem_check(self.settings)
        self.assertEqual(
            sorted(config.canonical_id for config in configs),
            [f"mdx:{_MDX_VOCAL}", f"vr:{_VR_KARAOKE}", f"vr:{_VR_VOCAL}"],
        )
        self.assertEqual(
            self.repo.ensemble_model_list(self.settings, "pair.vocals_instrumental"),
            [],
        )
        self.assertEqual(
            sorted(self.repo.ensemble_model_list(self.settings, "mode.multi_stem")),
            [f"mdx:{_MDX_VOCAL}", f"vr:{_VR_KARAOKE}", f"vr:{_VR_VOCAL}"],
        )
        self.assertEqual(self.repo.karaoke_model_list(self.settings), [f"vr:{_VR_KARAOKE}"])

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
