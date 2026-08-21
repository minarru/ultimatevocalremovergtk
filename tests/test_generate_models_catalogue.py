import os
import sys
import unittest
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from core.catalogue_types import SourceId  # noqa: E402
import generate_models_catalogue as catalogue  # noqa: E402


class UiNoteTests(unittest.TestCase):
    def test_vocals_other_note_only_for_two_stem_models(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="Roformer",
            catalogue_label="MelBand Roformer Kim | Inst v1 by Unwa",
            weight_file="model.ckpt",
            instruments=["other", "vocals"],
            stem_count=2,
        )
        self.assertIn("Vocals / Instrumental", catalogue._ui_note(entry))

    def test_four_stem_vocals_other_uses_subset_row_note(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="SCNet",
            catalogue_label="4-stems SCNet Large",
            weight_file="model.ckpt",
            instruments=["Drums", "Bass", "Other", "Vocals"],
            stem_count=4,
            name_intent="multi_stem",
        )
        self.assertEqual(catalogue._ui_note(entry), "UI: per-stem subset or focus row")

    def test_special_fx_best_result_and_focus(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="VR Architecture",
            catalogue_label="UVR-DeNoise by FoxJoy",
            weight_file="UVR-DeNoise.pth",
            primary_stem="noise",
            name_intent="special_fx",
            metadata_source="community_models.txt",
        )
        catalogue._finalize_entry(entry)
        self.assertIn("Noise", entry.best_result)
        self.assertTrue(entry.backend_focus.startswith("special_fx_primary:"))
        self.assertIn("complement", entry.ui_export_note)

    def test_karaoke_2_gets_karaoke_backend_focus(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="MDX-Net ONNX",
            catalogue_label="MDX-Net Model: UVR-MDX-NET Karaoke 2",
            weight_file="UVR_MDXNET_KARA_2.onnx",
            primary_stem="Instrumental",
            name_intent="karaoke",
            metadata_source="community_models.txt",
        )
        catalogue._finalize_entry(entry)
        self.assertTrue(entry.is_karaoke)
        self.assertEqual(entry.backend_focus, "karaoke_instrumental_primary")

    def test_specialty_stem_flags_old_vocals_mismatch(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="Roformer",
            catalogue_label="BandSplit Roformer | Male-Female by aufr33",
            weight_file="model.ckpt",
            instruments=["male", "female"],
            primary_stem="male",
            name_intent="vocals",
            backend_focus="two_stem",
            metadata_source="remote_yaml:test.yaml",
        )
        flags = catalogue._flag_mismatches(entry)
        self.assertTrue(any("specialty 2-stem" in flag for flag in flags))


class SourceForTests(unittest.TestCase):
    def test_mdx23c_download_list_counts_as_trvlvr(self) -> None:
        trvlvr = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(catalogue._source_for("Some Model", None, trvlvr), "TRvlvr")

    def test_mdx23c_only_in_politrees_is_politrees(self) -> None:
        politrees = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(catalogue._source_for("Some Model", politrees, {}), "Politrees")

    def test_mdx23c_in_both_is_combined(self) -> None:
        politrees = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        trvlvr = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(
            catalogue._source_for("Some Model", politrees, trvlvr), "TRvlvr+Politrees"
        )

    def test_unattributed_label_is_unknown_not_trvlvr(self) -> None:
        """No membership anywhere is 'not proven', not positive provenance."""
        self.assertEqual(catalogue._source_for("Unknown Model", None, {}), "unknown")

    def test_failed_upstream_payload_does_not_attribute_everything_to_trvlvr(self) -> None:
        """A source that failed to load yields {}, which must not read as TRvlvr.

        _source_payload returns {} when a source has no content, so under a cold
        cache every label would otherwise be stamped with positive TRvlvr
        provenance on the strength of a failed membership check.
        """
        politrees = {"mdx23c_download_list": {"In Politrees": "a.ckpt"}}
        self.assertEqual(catalogue._source_for("In Politrees", politrees, {}), "Politrees")
        self.assertEqual(catalogue._source_for("In Nothing", politrees, {}), "unknown")

    def test_mdx23_download_list_only_in_politrees_is_politrees(self) -> None:
        politrees = {"mdx23_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(catalogue._source_for("Some Model", politrees, {}), "Politrees")

    def test_scnet_in_upstream_counts_as_trvlvr(self) -> None:
        trvlvr = {"scnet_download_list": {"SCnet: Huge": {"huge.ckpt": "https://u/huge.ckpt"}}}
        politrees = {"scnet_download_list": {"SCnet: Huge": {"huge.ckpt": "https://p/huge.ckpt"}}}
        self.assertEqual(
            catalogue._source_for("SCnet: Huge", politrees, trvlvr), "TRvlvr+Politrees"
        )

    def test_extras_only_is_extras(self) -> None:
        extras = {
            "roformer_download_list": {
                "Roformer Model: BandSplit Roformer | HyperACE": {
                    "bs_hyperace.ckpt": "https://u/bs_hyperace.ckpt"
                }
            }
        }
        self.assertEqual(
            catalogue._source_for("Roformer Model: BandSplit Roformer | HyperACE", extras=extras),
            "extras",
        )

    def test_apollo_in_extras_is_extras(self) -> None:
        extras = {
            "apollo_download_list": {
                "Apollo Model: EDM Restoration by essid": {
                    "apollo_edm_by_essid.ckpt": "https://u/apollo.ckpt"
                }
            }
        }
        self.assertEqual(
            catalogue._source_for("Apollo Model: EDM Restoration by essid", extras=extras),
            "extras",
        )

    def test_mvsepless_only_is_mvsepless(self) -> None:
        mvsepless = {
            "mdx_download_list": {
                "MelBand Roformer Karaoke": {"kara.ckpt": "https://u/kara.ckpt"}
            }
        }
        self.assertEqual(
            catalogue._source_for("MelBand Roformer Karaoke", mvsepless=mvsepless),
            "mvsepless",
        )

    def test_upstream_and_extras_combine_in_merge_order(self) -> None:
        trvlvr = {"mdx_download_list": {"Shared": "shared.onnx"}}
        extras = {"mdx_download_list": {"Shared": {"shared.onnx": "https://u/shared.onnx"}}}
        self.assertEqual(
            catalogue._source_for("Shared", None, trvlvr, extras=extras),
            "TRvlvr+extras",
        )


def _local(source_id: SourceId, payload: dict):
    from core.remote_catalog_cache import RemoteJsonSource

    return RemoteJsonSource(source_id=source_id, local_loader=lambda: payload)


def _disabled(source_id: SourceId):
    from core.remote_catalog_cache import RemoteJsonSource

    return RemoteJsonSource(source_id=source_id, enabled=lambda: False)


class CollectEntriesTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))

    def _coordinator(self):
        from core.catalogue_coordinator import CatalogueCoordinator
        from core.catalogue_types import SourceId

        extras = {
            "roformer_download_list": {
                "Roformer Model: BandSplit Roformer | HyperACE": {
                    "bs_hyperace.ckpt": "https://u/bs_hyperace.ckpt"
                }
            },
            "apollo_download_list": {
                "Apollo Model: EDM Restoration by essid": {
                    "apollo_edm_by_essid.ckpt": "https://u/apollo.ckpt"
                }
            },
        }
        mvsepless = {
            "mdx_download_list": {
                "MelBand Roformer Karaoke": {"kara.ckpt": "https://u/kara.ckpt"}
            }
        }
        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: _local(
                    SourceId.UPSTREAM,
                    {
                        "vr_download_list": {},
                        "mdx_download_list": {},
                        "demucs_download_list": {},
                    },
                ),
                SourceId.POLITREES: _disabled(SourceId.POLITREES),
                SourceId.EXTRAS: _local(SourceId.EXTRAS, extras),
                SourceId.MVSEPLESS: _local(SourceId.MVSEPLESS, mvsepless),
            }
        )
        self.addCleanup(coordinator.close)
        return coordinator

    def test_collect_entries_uses_coordinator_sources(self) -> None:
        ctx = catalogue.CatalogueContext()
        entries = catalogue._collect_entries(
            ctx, allow_network=False, coordinator=self._coordinator()
        )
        by_label = {entry.catalogue_label: entry for entry in entries}
        hyperace = by_label["Roformer Model: BandSplit Roformer | HyperACE"]
        self.assertEqual(hyperace.source, "extras")
        self.assertEqual(hyperace.family, "Roformer")
        apollo = by_label["Apollo Model: EDM Restoration by essid"]
        self.assertEqual(apollo.source, "extras")
        self.assertEqual(apollo.family, "Apollo")
        karaoke = by_label["MelBand Roformer Karaoke"]
        self.assertEqual(karaoke.source, "mvsepless")


class OfflinePolicyTests(unittest.TestCase):
    """--offline must be cache-only: no fetch, no writes into model config storage."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))
        self.tmp = tempfile.mkdtemp(prefix="uvr-offline-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.calls: list = []

    def _coordinator(self):
        from core.catalogue_coordinator import CatalogueCoordinator

        # An MDX-C entry with a remote yaml: the path that reaches _load_yaml_meta.
        upstream = {
            "vr_download_list": {},
            "mdx_download_list": {
                "MDX23C Model: Test": {
                    "model_test.ckpt": "https://example.invalid/model_test.ckpt",
                    "model_test.yaml": "https://example.invalid/model_test.yaml",
                }
            },
            "demucs_download_list": {},
        }
        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: _local(SourceId.UPSTREAM, upstream),
                SourceId.POLITREES: _disabled(SourceId.POLITREES),
                SourceId.EXTRAS: _disabled(SourceId.EXTRAS),
                SourceId.MVSEPLESS: _disabled(SourceId.MVSEPLESS),
            }
        )
        self.addCleanup(coordinator.close)
        return coordinator

    def _patches(self):
        """Record every network entry point instead of raising.

        _fetch_cached swallows URLError/OSError, so a raising stub could be
        silently absorbed and the test would pass while the socket was opened.
        """
        from unittest import mock

        def record_urlopen(request: Any, *args: Any, **kwargs: Any):
            import urllib.error

            url = getattr(request, "full_url", request)
            self.calls.append(f"_urlopen({url})")
            # A URLError is what a real offline machine raises, and _fetch_cached
            # handles it; the recorded call list is what the assertions read.
            raise urllib.error.URLError("blocked by test")

        def record_fetch_config(name: Any, url: Any, *args: Any, **kwargs: Any) -> bool:
            self.calls.append(f"fetch_mdx_config_url({name}, {url})")
            return False

        return [
            mock.patch("core.mdx_config_fetch._urlopen", record_urlopen),
            mock.patch("core.mdx_config_fetch.fetch_mdx_config_url", record_fetch_config),
            mock.patch.object(catalogue, "_scan_weight_hashes", lambda *a: {}),
            mock.patch.object(catalogue, "POLITREES_CACHE_DIR", os.path.join(self.tmp, "pt")),
            mock.patch.object(catalogue, "COMMUNITY_CACHE_DIR", os.path.join(self.tmp, "cm")),
            mock.patch.object(catalogue, "YAML_CACHE_DIR", os.path.join(self.tmp, "yaml")),
            mock.patch.object(catalogue, "REFERENCE_TSV_PATH", os.path.join(self.tmp, "ref.tsv")),
            mock.patch.object(catalogue, "OUTPUT_PATH", os.path.join(self.tmp, "out.md")),
        ]

    def test_build_catalogue_context_offline_makes_no_network_calls(self) -> None:
        import contextlib

        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            catalogue._build_catalogue_context(allow_network=False)
        self.assertEqual(self.calls, [])

    def test_offline_cache_miss_does_not_create_the_cache_dir(self) -> None:
        """Offline is read-only: a miss must not leave an empty cache dir behind."""
        cache_dir = os.path.join(self.tmp, "cold")
        path = catalogue._fetch_cached(
            "https://example.invalid/x.json", cache_dir, "x.json", allow_network=False
        )
        self.assertIsNone(path)
        self.assertFalse(os.path.exists(cache_dir), "offline miss created a cache dir")

    def test_load_yaml_meta_offline_does_not_fetch_or_write_config(self) -> None:
        import contextlib

        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            result = catalogue._load_yaml_meta(
                "model_test.yaml",
                "https://example.invalid/model_test.yaml",
                allow_network=False,
            )
        self.assertEqual(self.calls, [])
        # Falls back to the name heuristic rather than fetching.
        self.assertIsInstance(result, tuple)

    def test_main_offline_makes_no_network_calls(self) -> None:
        import contextlib
        from unittest import mock

        coordinator = self._coordinator()
        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            real = catalogue._snapshot_and_payloads
            seen = {}

            def spy(*, allow_network: bool, coordinator: Any = None):
                seen["allow_network"] = allow_network
                return real(allow_network=allow_network, coordinator=self._co)

            self._co = coordinator
            stack.enter_context(mock.patch.object(catalogue, "_snapshot_and_payloads", spy))
            rc = catalogue.main(["--offline"])

        self.assertEqual(rc, 0)
        self.assertIs(seen["allow_network"], False)
        self.assertEqual(self.calls, [])

    def test_online_still_fetches(self) -> None:
        """The offline guard must not disable networking for normal runs."""
        import contextlib

        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            catalogue._build_catalogue_context(allow_network=True)
        self.assertTrue(self.calls, "online mode should still attempt fetches")


class DemucsFinalizationTests(unittest.TestCase):
    """Demucs family facts must land before the single finalization pass.

    The overlay used to run *after* _finalize_entry, so ui_export_note and
    flags were derived from an entry with no instruments and no stem count.
    """

    class _Snapshot:
        def __init__(self, demucs: dict) -> None:
            self.vr: dict = {}
            self.mdx: dict = {}
            self.demucs = demucs
            self.apollo: dict = {}
            self.meta: dict = {}
            self.unsupported: dict = {}

    def _entry(self, label: str, weight: str):
        snapshot = self._Snapshot({label: weight})
        entries = catalogue._entries_from_snapshot(
            snapshot, ({}, {}, {}, {}), catalogue.CatalogueContext(),
            policy=catalogue.OFFLINE_FETCH_POLICY
        )
        self.assertEqual(len(entries), 1)
        return entries[0]

    def test_six_stem_demucs_gets_its_export_note(self) -> None:
        entry = self._entry("Demucs v4: htdemucs_6s", "htdemucs_6s.th")
        self.assertEqual(entry.stem_count, 6)
        self.assertEqual(entry.ui_export_note, "UI: per-stem subset or focus row")

    def test_four_stem_demucs_gets_its_export_note(self) -> None:
        entry = self._entry("Demucs v4: htdemucs", "htdemucs.th")
        self.assertEqual(entry.stem_count, 4)
        self.assertEqual(entry.ui_export_note, "UI: per-stem subset or focus row")

    def test_two_stem_uvr_demucs_is_not_labelled_multi_stem(self) -> None:
        """The UVR Demucs model emits vocals+instrumental, not a multi-stem set."""
        entry = self._entry("Demucs v3: UVR Model", "UVR_Demucs_Model_1.th")
        self.assertEqual(entry.stem_count, 2)
        self.assertEqual(entry.backend_focus, "two_stem")

    def test_family_specific_best_result_prose_is_preserved(self) -> None:
        self.assertEqual(self._entry("Demucs v4: htdemucs_6s", "a.th").best_result, "6-stem Demucs")
        self.assertEqual(self._entry("Demucs v4: htdemucs", "b.th").best_result, "4-stem Demucs")
        self.assertEqual(
            self._entry("Demucs v3: UVR Model", "c.th").best_result,
            "2-stem: instrumental + vocals (user picks focus)",
        )

    def test_metadata_source_records_the_heuristic(self) -> None:
        self.assertEqual(
            self._entry("Demucs v4: htdemucs", "b.th").metadata_source, "demucs_heuristic"
        )


class CacheIdentityTests(unittest.TestCase):
    """Ephemeral downloads: keyed by URL, TTL'd, and out of the docs tree."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="uvr-cache-id-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.fetched: list = []

    def _opener(self, body: bytes = b'{"ok": 1}'):
        from unittest import mock

        def record(request: Any, *args: Any, **kwargs: Any):
            url = getattr(request, "full_url", request)
            self.fetched.append(url)

            class _R:
                def read(self) -> bytes:
                    return body

                def __enter__(self) -> "_R":
                    return self

                def __exit__(self, *exc: Any) -> bool:
                    return False

            return _R()

        return mock.patch("core.mdx_config_fetch._urlopen", record)

    def test_caches_live_under_cache_dir_not_the_docs_tree(self) -> None:
        from core import paths

        for cache_dir in (
            catalogue.YAML_CACHE_DIR,
            catalogue.POLITREES_CACHE_DIR,
            catalogue.COMMUNITY_CACHE_DIR,
        ):
            self.assertTrue(
                cache_dir.startswith(paths.CACHE_DIR),
                f"{cache_dir} is not under CACHE_DIR",
            )
            self.assertNotIn("docs", os.path.relpath(cache_dir, paths.CACHE_DIR))

    def test_same_basename_from_different_urls_does_not_alias(self) -> None:
        """Two models can both ship a 'config.yaml'."""
        with self._opener(b"first"):
            a = catalogue._fetch_cached("https://a.invalid/x/config.yaml", self.tmp, "config.yaml")
        with self._opener(b"second"):
            b = catalogue._fetch_cached("https://b.invalid/y/config.yaml", self.tmp, "config.yaml")
        self.assertNotEqual(a, b)
        assert a is not None and b is not None
        self.assertEqual(open(a, "rb").read(), b"first")
        self.assertEqual(open(b, "rb").read(), b"second")

    def test_a_fresh_cache_entry_is_not_refetched(self) -> None:
        url = "https://a.invalid/data.json"
        with self._opener():
            catalogue._fetch_cached(url, self.tmp, "data.json")
            catalogue._fetch_cached(url, self.tmp, "data.json")
        self.assertEqual(len(self.fetched), 1)

    def test_a_stale_cache_entry_is_refetched(self) -> None:
        """A normal online run must not reuse an arbitrarily old supplement."""
        url = "https://a.invalid/data.json"
        with self._opener():
            path = catalogue._fetch_cached(url, self.tmp, "data.json")
            assert path
            os.utime(path, (0, 0))  # epoch: far older than any TTL
            catalogue._fetch_cached(url, self.tmp, "data.json")
        self.assertEqual(len(self.fetched), 2)

    def test_stale_entry_is_still_served_when_offline(self) -> None:
        url = "https://a.invalid/data.json"
        with self._opener():
            path = catalogue._fetch_cached(url, self.tmp, "data.json")
            assert path
            os.utime(path, (0, 0))
        with self._opener():
            served = catalogue._fetch_cached(url, self.tmp, "data.json", allow_network=False)
        self.assertEqual(served, path)
        self.assertEqual(len(self.fetched), 1)

    def test_refresh_refetches_even_a_fresh_entry(self) -> None:
        url = "https://a.invalid/data.json"
        with self._opener():
            catalogue._fetch_cached(url, self.tmp, "data.json")
            catalogue._fetch_cached(url, self.tmp, "data.json", refresh=True)
        self.assertEqual(len(self.fetched), 2)

    def test_refresh_flag_is_exposed_on_the_cli(self) -> None:
        self.assertTrue(catalogue._parse_args(["--refresh"]).refresh)
        self.assertFalse(catalogue._parse_args([]).refresh)


class PublicationGuardTests(unittest.TestCase):
    """A degraded snapshot must not replace a good catalogue document."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))
        self.tmp = tempfile.mkdtemp(prefix="uvr-guard-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "models-catalogue.md")

    def _report(self, *, usable: bool = True, failed: tuple = ()):
        from core.catalogue_types import RefreshMode, RefreshReport

        return RefreshReport(mode=RefreshMode.OFFLINE, usable=usable, failed=failed)

    def test_previous_entry_count_is_read_from_an_existing_document(self) -> None:
        with open(self.out, "w", encoding="utf-8") as handle:
            handle.write("## Summary\n\n- Total catalogue entries: **412**\n")
        self.assertEqual(catalogue._previous_entry_count(self.out), 412)

    def test_missing_document_has_no_previous_count(self) -> None:
        self.assertIsNone(catalogue._previous_entry_count(self.out))

    def test_unusable_snapshot_is_refused(self) -> None:
        verdict = catalogue._publication_verdict(
            entries=[], report=self._report(usable=False), previous_count=None
        )
        self.assertFalse(verdict.ok)
        self.assertIn("unusable", verdict.reason.lower())

    def test_a_large_drop_is_refused_even_when_no_source_reported_failure(self) -> None:
        """The real cold-cache case: offline sources are not refreshed, not failed.

        A run against an empty supplemental cache produced 88 entries where the
        published document had 474, with report.usable True and report.failed
        empty -- so failure state cannot be the trigger. The count is.
        """
        verdict = catalogue._publication_verdict(
            entries=[object()] * 88, report=self._report(), previous_count=474
        )
        self.assertFalse(verdict.ok)
        self.assertIn("474", verdict.reason)

    def test_a_small_drop_still_publishes(self) -> None:
        """Ordinary regeneration jitter must not need an override flag."""
        verdict = catalogue._publication_verdict(
            entries=[object()] * 398, report=self._report(), previous_count=400
        )
        self.assertTrue(verdict.ok, verdict.reason)

    def test_failed_sources_are_named_in_the_refusal(self) -> None:
        from core.catalogue_types import SourceId

        verdict = catalogue._publication_verdict(
            entries=[object()] * 10,
            report=self._report(failed=((SourceId.UPSTREAM, "boom"),)),
            previous_count=400,
        )
        self.assertFalse(verdict.ok)
        self.assertIn("upstream", verdict.reason)

    def test_a_healthy_snapshot_publishes(self) -> None:
        verdict = catalogue._publication_verdict(
            entries=[object()] * 400, report=self._report(), previous_count=400
        )
        self.assertTrue(verdict.ok, verdict.reason)

    def test_allow_degraded_overrides_a_refusal(self) -> None:
        verdict = catalogue._publication_verdict(
            entries=[], report=self._report(usable=False), previous_count=400,
            allow_degraded=True,
        )
        self.assertTrue(verdict.ok, verdict.reason)

    def test_allow_degraded_flag_is_exposed_on_the_cli(self) -> None:
        self.assertTrue(catalogue._parse_args(["--allow-degraded"]).allow_degraded)
        self.assertFalse(catalogue._parse_args([]).allow_degraded)


class EntryMetaOverlayTests(unittest.TestCase):
    def test_fills_blank_stems_target_and_unknown_intent(self) -> None:
        from core.catalog_sources import EntryMeta
        from core.model_stem_semantics import INTENT_KARAOKE

        entry = catalogue.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label="MelBand Roformer Karaoke",
            weight_file="kara.ckpt",
            name_intent="unknown",
        )
        meta = EntryMeta(
            label=entry.catalogue_label,
            display="MelBand Roformer — Karaoke",
            arch="MDX",
            stems=["vocals", "other"],
            target_instrument="vocals",
            intent=INTENT_KARAOKE,
        )
        catalogue._apply_entry_meta(entry, meta)
        self.assertEqual(entry.instruments, ["vocals", "other"])
        self.assertEqual(entry.target_instrument, "vocals")
        self.assertEqual(entry.primary_stem, "vocals")
        self.assertEqual(entry.name_intent, INTENT_KARAOKE)

    def test_does_not_overwrite_resolved_fields_or_unknown_intent(self) -> None:
        from core.catalog_sources import EntryMeta
        from core.model_stem_semantics import INTENT_UNKNOWN

        entry = catalogue.ModelEntry(
            source="extras",
            family="Roformer",
            catalogue_label="Named",
            weight_file="model.ckpt",
            instruments=["drums", "bass"],
            target_instrument="drums",
            primary_stem="drums",
            name_intent="instrumental",
        )
        meta = EntryMeta(
            label=entry.catalogue_label,
            display="Named",
            arch="MDX",
            stems=["vocals"],
            target_instrument="vocals",
            intent=INTENT_UNKNOWN,
        )
        catalogue._apply_entry_meta(entry, meta)
        self.assertEqual(entry.instruments, ["drums", "bass"])
        self.assertEqual(entry.target_instrument, "drums")
        self.assertEqual(entry.primary_stem, "drums")
        self.assertEqual(entry.name_intent, "instrumental")

        entry.name_intent = "unknown"
        catalogue._apply_entry_meta(entry, meta)
        self.assertEqual(entry.name_intent, "unknown")


class RenderDisplayTests(unittest.TestCase):
    def test_render_uses_canonical_display_name(self) -> None:
        from core.model_naming import canonical_display_name

        label = "Roformer Model: BandSplit Roformer | HyperACE by Unwa"
        entry = catalogue.ModelEntry(
            source="extras",
            family="Roformer",
            catalogue_label=label,
            weight_file="bs_hyperace.ckpt",
            name_intent="instrumental",
            best_result="Instrumental",
            backend_focus="instrumental_primary",
        )
        rendered = catalogue._render([entry])
        display = canonical_display_name(label)
        self.assertIn(display, rendered)
        self.assertNotIn("Roformer Model:", rendered)

    def test_render_header_lists_all_sources(self) -> None:
        rendered = catalogue._render([])
        self.assertIn("TRvlvr + Politrees + extras + mvsepless", rendered)
        self.assertIn(
            "catalogue helper summarizing primary/target",
            rendered,
        )
        self.assertNotIn("what `ModelConfig` uses as `primary_stem`", rendered)

    def test_parse_args_offline(self) -> None:
        args = catalogue._parse_args(["--offline"])
        self.assertTrue(args.offline)


class FetchHelperTests(unittest.TestCase):
    def test_fetch_cached_uses_core_urlopen(self) -> None:
        import tempfile
        from unittest.mock import patch

        class _Resp:
            def read(self) -> bytes:
                return b'{"ok": true}'

            def __enter__(self) -> "_Resp":
                return self

            def __exit__(self, *args: object) -> None:
                return None

        with tempfile.TemporaryDirectory() as tmp, patch(
            "core.mdx_config_fetch._urlopen", return_value=_Resp()
        ):
            path = catalogue._fetch_cached("https://example.invalid/x.json", tmp, "x.json")
            if path is None:
                self.fail("expected a cached file")
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), '{"ok": true}')

    def test_load_yaml_meta_prefers_core_config_fetch(self) -> None:
        import tempfile
        from unittest.mock import patch

        yaml_name = "zz_core_fetch_probe.yaml"
        body = "training:\n  instruments: [vocals, other]\n  target_instrument: vocals\n"

        def fake_fetch(name: str, url: str) -> bool:
            dest = os.path.join(catalogue.paths.MDX_C_CONFIG_PATH, name)
            os.makedirs(catalogue.paths.MDX_C_CONFIG_PATH, exist_ok=True)
            with open(dest, "w", encoding="utf-8") as handle:
                handle.write(body)
            return True

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            catalogue.paths, "MDX_C_CONFIG_PATH", tmp
        ), patch(
            "core.mdx_config_fetch.fetch_mdx_config_url", side_effect=fake_fetch
        ), patch.object(
            catalogue, "_fetch_yaml", side_effect=AssertionError("yaml cache fallback")
        ):
            instruments, target, _arch, source = catalogue._load_yaml_meta(
                yaml_name, "https://example.invalid/x.yaml"
            )
        self.assertEqual(instruments, ["vocals", "other"])
        self.assertEqual(target, "vocals")
        self.assertEqual(source, f"remote_yaml:{yaml_name}")


if __name__ == "__main__":
    unittest.main()
