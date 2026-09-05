"""Preservation contracts across real planning phases with injected I/O."""

from __future__ import annotations

import copy
import dataclasses
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from core.export_naming import OutputNamingContext, build_output_naming_context
from core.job_acquisition import acquire_configurations
from core.job_diagnostics import stem_semantics_diagnostics
from core.job_materialization import collect_descriptor_evidence, describe_models
from core.job_plan import (
    JobResolver,
    JobSpec,
    ModelDescriptor,
    ValidationLevel,
    planned_output_routes,
)
from core.job_projection import project_descriptor, project_input, select_output_routes
from core.model_identity import MdxSpec, ModelArtifacts, ModelRecord
from core.model_stem_semantics import resolve_catalogue_stem_semantics
from core.settings import Settings
from core.types import ProcessMethod
from tests.planning_fixtures import (
    ConfigurationFiles,
    FileProbes,
    IdentityRecords,
    QueuedMaterializer,
)


def record(name: str = "primary", *, yaml: str = "") -> ModelRecord:
    return ModelRecord(
        f"mdx:{name}",
        "mdx",
        name,
        name.title(),
        name,
        ModelArtifacts(name + ".ckpt", (yaml,) if yaml else ()),
        installed=True,
        mdx=MdxSpec("mel_band_roformer") if yaml else None,
    )


def model(**values: Any) -> Any:
    fields = dict(
        model_status=True,
        model_path="",
        model_hash_dir="/local.json",
        primary_stem="Vocals",
        secondary_stem="Instrumental",
        compensate=1.125,
        mdx_model_stems=(),
        mdxnet_stems_selected=(),
        demucs_source_list=(),
        is_vocal_split_model_activated=False,
        vocal_split_model=None,
    )
    fields.update(values)
    return SimpleNamespace(**fields)


def spec(*, secondary: bool = False, ensemble: bool = False) -> JobSpec:
    settings = Settings.defaults()
    settings.process.method = ProcessMethod.ENSEMBLE if ensemble else ProcessMethod.MDX
    settings.process.export_path = "/settings-output"
    settings.mdx.model = "mdx:primary"
    settings.mdx.compensate = None
    settings.mdx.is_secondary_model_activate = secondary
    settings.mdx.voc_inst_secondary_model = "mdx:helper"
    if ensemble:
        settings.ensemble.selected_models = ["mdx:primary", "mdx:two"]
        settings.ensemble.main_stem = "mode.multi_stem"
    return JobSpec("ensemble" if ensemble else "separate", settings, ("/song.wav",), "/out")


class PlanningPhaseTests(unittest.TestCase):
    def test_clean_load_plan_checks_supplied_materialized_models(self) -> None:
        materializer = QueuedMaterializer([model()])
        probes = FileProbes()
        plan = JobResolver(
            None,
            identities=IdentityRecords([record()]),
            configs=ConfigurationFiles(),
            materializer=materializer,
            probes=probes,
        ).resolve(spec(), ValidationLevel.LOAD)
        self.assertEqual(plan.diagnostics, ())
        self.assertEqual(materializer.loads, 1)
        self.assertEqual(probes.calls[-2:], ["packages", "device"])

    def test_failed_final_status_retains_returned_model_projection(self) -> None:
        job = spec()
        runner = JobResolver(
            None,
            identities=IdentityRecords([record()]),
            configs=ConfigurationFiles(),
            materializer=QueuedMaterializer([model(model_status=False)]),
            probes=FileProbes(present=("/song.wav", "/local.json")),
        )
        plan = runner.resolve(job)
        self.assertEqual(
            [(d.code, d.severity) for d in plan.diagnostics], [("model.configuration", "error")]
        )
        self.assertEqual(plan.models[0].primary_stem, "Vocals")
        self.assertEqual(plan.settings.mdx.compensate, 1.125)
        self.assertEqual(plan.provenance, {"mdx.compensate": "model-local"})
        self.assertIsNone(job.settings.mdx.compensate)

    def test_failed_primary_status_does_not_publish_topology(self) -> None:
        identities = IdentityRecords([record(), record("helper")])
        materializer = QueuedMaterializer([model(model_status=False)])
        plan = JobResolver(
            None,
            identities=identities,
            configs=ConfigurationFiles(),
            materializer=materializer,
            probes=FileProbes(),
        ).resolve(spec(secondary=True), ValidationLevel.CONFIG)
        self.assertEqual([d.code for d in plan.diagnostics], ["model.configuration"])
        self.assertIsNone(plan.models[0].primary_stem)
        self.assertIsNone(plan.settings.mdx.compensate)
        self.assertEqual(identities.calls, ["mdx:primary"])
        self.assertEqual(len(materializer.calls), 1)

    def test_partial_final_list_is_used_instead_of_complete_topology(self) -> None:
        materializer = QueuedMaterializer([model(), model()], [model()])
        plan = JobResolver(
            None,
            identities=IdentityRecords([record(), record("two"), record("helper")]),
            configs=ConfigurationFiles(),
            materializer=materializer,
            probes=FileProbes(),
        ).resolve(spec(secondary=True, ensemble=True))
        self.assertEqual([d.code for d in plan.diagnostics], ["model.configuration"])
        self.assertEqual([d.id for d in plan.models], ["mdx:primary"])
        self.assertEqual(materializer.calls[0][1], {})
        self.assertEqual(
            tuple(materializer.calls[1][1]),
            (
                "ensemble.selected_models[0]",
                "ensemble.selected_models[1]",
                "mdx.voc_inst_secondary_model",
            ),
        )

    def test_failed_acquisition_keeps_original_mapping_after_partial_download(self) -> None:
        first, second = record(yaml="first.yaml"), record("two", yaml="second.yaml")
        dependencies = {"mdx.model": first, "mdx.voc_inst_secondary_model": second}
        identities = IdentityRecords([first, second])
        configs = ConfigurationFiles()

        def ensure(yaml_name: str, *, allow_network: bool) -> bool:
            configs.available.add(yaml_name)
            return yaml_name == "first.yaml"

        configs.ensure = ensure
        result = acquire_configurations(dependencies, identities, configs, allow_network=True)
        self.assertFalse(result.available)
        self.assertIs(result.dependencies, dependencies)
        self.assertEqual(identities.calls, [])
        self.assertEqual(
            result.diagnostics[0].message, "MDX configuration 'second.yaml' could not be downloaded"
        )
        self.assertIn("first.yaml", configs.available)

    def test_second_acquisition_failure_keeps_complete_dependency_map(self) -> None:
        primary, helper = record(), record("helper", yaml="helper.yaml")
        plan = JobResolver(
            None,
            identities=IdentityRecords([primary, helper]),
            configs=ConfigurationFiles(downloads=False),
            materializer=QueuedMaterializer([model()]),
            probes=FileProbes(),
        ).resolve(spec(secondary=True))
        self.assertEqual(
            tuple(plan.model_dependencies), ("mdx.model", "mdx.voc_inst_secondary_model")
        )
        self.assertIs(plan.model_dependencies["mdx.model"], primary)
        self.assertEqual([d.code for d in plan.diagnostics], ["model.configuration"])
        self.assertEqual(plan.models[0].primary_stem, "Vocals")
        self.assertIsNone(plan.settings.mdx.compensate)

    def test_second_karaoke_failure_keeps_first_records_and_refreshed_dependencies(self) -> None:
        old = record()
        new = dataclasses.replace(old, backend_name="refreshed")
        job = spec(secondary=True)
        job.settings.process.vocal_splitter_enabled = True
        job.settings.process.vocal_splitter = "mdx:splitter"
        identities = IdentityRecords(
            [old, record("helper"), record("splitter", yaml="split.yaml")], refreshed=[new]
        )
        plan = JobResolver(
            None,
            identities=identities,
            configs=ConfigurationFiles(),
            materializer=QueuedMaterializer([model()]),
            probes=FileProbes(),
        ).resolve(job)
        self.assertIs(plan.model_dependencies["mdx.model"], new)
        self.assertEqual(plan.models[0].backend_name, "primary")
        self.assertEqual(
            [(d.code, d.severity) for d in plan.diagnostics], [("model.identity", "error")]
        )
        self.assertEqual(identities.calls[-1], "karaoke")

    def test_config_topology_does_not_enrich_native_settings_or_hash(self) -> None:
        probes = FileProbes(present=("/song.wav", "/weight", "/local.json"))
        plan = JobResolver(
            None,
            identities=IdentityRecords([record(), record("helper")]),
            configs=ConfigurationFiles(),
            materializer=QueuedMaterializer([model(model_path="/weight")]),
            probes=probes,
        ).resolve(spec(secondary=True), ValidationLevel.CONFIG)
        self.assertEqual(plan.models[0].metadata_source, "model-local")
        self.assertEqual(plan.models[0].primary_stem, "Vocals")
        self.assertIsNone(plan.settings.mdx.compensate)
        self.assertEqual(plan.provenance, {})
        self.assertEqual(probes.calls, ["file:/song.wav", "file:/local.json"])

    def test_warning_only_focus_suppresses_load_and_missing_packages_skip_device(self) -> None:
        for missing in ((), ("kthread", "soundfile")):
            with self.subTest(missing=missing):
                job = spec()
                job.settings.process.stem_focus = "raw:unavailable"
                probes = FileProbes(missing=missing)
                materializer = QueuedMaterializer([model()])
                plan = JobResolver(
                    None,
                    identities=IdentityRecords([record()]),
                    configs=ConfigurationFiles(),
                    materializer=materializer,
                    probes=probes,
                ).resolve(job, ValidationLevel.LOAD)
                self.assertEqual(
                    (plan.diagnostics[0].code, plan.diagnostics[0].severity),
                    ("stems.focus_unmatched", "warning"),
                )
                self.assertEqual(materializer.loads, 0)
                self.assertEqual("device" in probes.calls, not bool(missing))
                if missing:
                    self.assertEqual(
                        plan.diagnostics[1].message, "Missing Python packages: kthread, soundfile"
                    )

    def test_adopt_keeps_settings_output_and_omits_resolve_only_diagnostics(self) -> None:
        job = dataclasses.replace(spec(), inputs=(), output="")
        probes = FileProbes(missing=("kthread",))
        resolver = JobResolver(
            None,
            identities=IdentityRecords([record()]),
            configs=ConfigurationFiles(),
            materializer=QueuedMaterializer(),
            probes=probes,
        )
        plan = resolver.adopt(job, [record()], [model()], level=ValidationLevel.LOAD)
        self.assertEqual(plan.output, "/settings-output")
        self.assertEqual(plan.diagnostics, ())
        self.assertEqual(plan.settings.mdx.compensate, 1.125)
        self.assertEqual(probes.calls, ["file:/local.json", "file:/local.json"])

    def test_invalid_native_value_stops_before_next_native_metadata_probe(self) -> None:
        probes = FileProbes()
        resolver = JobResolver(
            None,
            identities=IdentityRecords([record(), record("two")]),
            configs=ConfigurationFiles(),
            probes=probes,
        )
        with self.assertRaises(ValueError):
            resolver.adopt(
                spec(ensemble=True),
                [record(), record("two")],
                [model(compensate="invalid"), model(model_hash_dir="/second.json")],
            )
        self.assertEqual(
            probes.calls, ["file:/local.json", "file:/second.json", "file:/local.json"]
        )

    def test_input_diagnostics_do_not_block_acquisition_and_model_materialization(self) -> None:
        job = dataclasses.replace(spec(), inputs=("/missing-1", "/missing-2"), output="")
        configs = ConfigurationFiles()
        materializer = QueuedMaterializer([model()])
        plan = JobResolver(
            None,
            identities=IdentityRecords([record(yaml="active.yaml")]),
            configs=configs,
            materializer=materializer,
            probes=FileProbes(),
        ).resolve(job)
        self.assertEqual(
            [(d.code, d.path) for d in plan.diagnostics],
            [
                ("input.missing", "/missing-1"),
                ("input.missing", "/missing-2"),
                ("output.empty", None),
            ],
        )
        self.assertEqual(configs.calls, [("exists", "active.yaml"), ("ensure", "active.yaml")])
        self.assertEqual(plan.models[0].primary_stem, "Vocals")


class ProjectionBoundaryTests(unittest.TestCase):
    def test_semantic_events_precede_runtime_and_output_events(self) -> None:
        events: list[str] = []

        class Probes(FileProbes):
            def missing_runtime_packages(self) -> tuple[str, ...]:
                events.append("packages")
                return ()

            def device_diagnostics(self, settings: Any) -> tuple[Any, ...]:
                events.append("device")
                return ()

        semantics = resolve_catalogue_stem_semantics(
            "mdx:unreviewed", native_stems=("Vocals", "Instrumental")
        )
        materializer = QueuedMaterializer(
            [model(stem_semantics=semantics), model(stem_semantics=semantics)]
        )
        resolver = JobResolver(
            None,
            identities=IdentityRecords([record(), record("two")]),
            configs=ConfigurationFiles(),
            materializer=materializer,
            probes=Probes(),
        )

        def log(_category: str, name: str, **fields: Any) -> None:
            events.append(f"{name}:{fields.get('model_id', '')}")

        with patch("core.debug_log.log_event", side_effect=log):
            resolver.resolve(spec(ensemble=True), ValidationLevel.RUNTIME)
        self.assertEqual(
            events,
            [
                "stem_semantics_fallback:mdx:primary",
                "stem_semantics_fallback:mdx:two",
                "packages",
                "device",
                "planned_outputs:",
                "plan_resolved:",
            ],
        )

    def test_descriptor_observations_preserve_per_model_order_and_projection_is_pure(self) -> None:
        probes = FileProbes(present=("/one", "/two", "/local.json"))
        first, second = model(model_path="/one"), model(model_path="/two")

        def routes(value: Any):
            probes.calls.append(f"routes:{value.model_path}")
            value.stem_semantics_cache_key = "prepared"
            return ()

        def count(value: Any):
            probes.calls.append(f"count:{value.model_path}")
            return 2

        with (
            patch("core.job_materialization.model_stem_routes", side_effect=routes),
            patch("core.job_materialization.model_stem_count", side_effect=count),
        ):
            descriptors = describe_models(
                [record(), record("two")], [first, second], probes, verify=True
            )
        self.assertEqual(
            probes.calls,
            [
                "file:/one",
                "hash:/one",
                "routes:/one",
                "file:/local.json",
                "count:/one",
                "file:/two",
                "hash:/two",
                "routes:/two",
                "file:/local.json",
                "count:/two",
            ],
        )
        self.assertEqual([d.checkpoint_hash for d in descriptors], ["fixture-hash", "fixture-hash"])
        self.assertEqual(first.stem_semantics_cache_key, "prepared")
        evidence = collect_descriptor_evidence(first, probes, verify=False)
        before = copy.deepcopy(first.__dict__)
        with (
            patch("os.path.isfile", side_effect=AssertionError("pure projection probed a file")),
            patch(
                "core.job_materialization.model_stem_routes",
                side_effect=AssertionError("pure projection materialized routes"),
            ),
        ):
            projected = project_descriptor(record(), evidence)
        self.assertEqual(first.__dict__, before)
        self.assertEqual(projected.checkpoint, "/one")

    def test_semantic_event_is_emitted_before_later_descriptor_failure(self) -> None:
        good = ModelDescriptor(
            "mdx:bs_neo_inst_beta",
            "mdx",
            "m",
            "M",
            primary_stem="other",
            stem_semantics=resolve_catalogue_stem_semantics(
                "mdx:bs_neo_inst_beta", native_stems=("other",)
            ),
        )
        bad = dataclasses.replace(good, stem_semantics=SimpleNamespace())
        seen = []
        with patch(
            "core.debug_log.log_event", side_effect=lambda *args, **kwargs: seen.append(args)
        ):
            with self.assertRaises(AttributeError):
                stem_semantics_diagnostics((good, bad))
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], "model")

    def test_output_trace_failure_is_suppressed_but_semantic_failure_propagates(self) -> None:
        descriptor = ModelDescriptor(
            "mdx:x", "mdx", "x", "X", primary_stem="Vocals", secondary_stem="Instrumental"
        )
        with patch("core.debug_log.log_event", side_effect=RuntimeError("logging failed")):
            routes = planned_output_routes(spec().settings, (descriptor,), command="separate")
            self.assertEqual([route.label for route in routes], ["Vocals", "Instrumental"])
            semantic = dataclasses.replace(
                descriptor,
                stem_semantics=resolve_catalogue_stem_semantics(
                    "mdx:bs_neo_inst_beta", native_stems=("other",)
                ),
            )
            with self.assertRaisesRegex(RuntimeError, "logging failed"):
                stem_semantics_diagnostics((semantic,))

    def test_literal_input_projection_and_per_input_timestamp_names(self) -> None:
        settings = spec().settings
        descriptor = ModelDescriptor(
            "mdx:x", "mdx", "x", "X", primary_stem="Vocals", secondary_stem="Instrumental"
        )
        selected = select_output_routes(settings, (descriptor,), command="separate")
        naming = OutputNamingContext("/song.wav", "song", "song", "/out", "wav", 1, 1)
        planned = project_input("/song.wav", naming, selected.routes, command="separate")
        self.assertEqual(
            [output.path for output in planned.outputs],
            ["/out/song (Vocals).wav", "/out/song (Instrumental).wav"],
        )
        settings.process.testing_audio = True
        job = JobSpec("separate", settings, ("/a.wav", "/b.wav"), "/out")
        resolver = JobResolver(
            None,
            identities=IdentityRecords([record()]),
            configs=ConfigurationFiles(),
            probes=FileProbes(present=("/a.wav", "/b.wav")),
            naming=build_output_naming_context,
        )
        with patch("core.export_naming.time.time", side_effect=[100.0, 200.0]):
            plan = resolver.resolve(job, ValidationLevel.CONFIG)
        self.assertEqual([item.naming.timestamp for item in plan.inputs], ["100", "200"])
