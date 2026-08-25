"""Behavioral coverage for the generator's optional remote confidence audit."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from catalogue import collect, stem_audit


def _entry(entry_id: str, *, curated: bool = False) -> stem_audit.StemConfidenceEntry:
    return stem_audit.StemConfidenceEntry(
        entry_id=entry_id,
        label=entry_id,
        stems=["vocals", "other"],
        is_karaoke=True,
        is_karaoke_curated=curated,
        buckets=["Vocals", "Instrumental"],
        hash_status="matched" if curated else "unmatched",
    )


class ConfidenceAuditRenderingTests(unittest.TestCase):
    def test_table_and_summary_keep_confidence_and_evidence_visible(self) -> None:
        rendered = stem_audit.render_stem_confidence_table([_entry("model", curated=True)])
        self.assertIn("curated", rendered)
        self.assertIn("matched", rendered)
        self.assertIn("Vocals", rendered)
        self.assertIn(
            "1 curated", stem_audit.render_stem_confidence_summary([_entry("model", curated=True)])
        )

    def test_json_replacement_is_atomic_and_sorts_guesses_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "confidence.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("old")
            with patch.object(
                stem_audit,
                "iter_stem_confidence_entries",
                return_value=iter([_entry("curated", curated=True), _entry("guessed")]),
            ):
                self.assertEqual(
                    stem_audit.run_stem_confidence_audit(
                        policy=collect.FetchPolicy(), json_path=path, quiet=True
                    ),
                    0,
                )
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)[0]["entry_id"], "guessed")
            self.assertFalse(os.path.exists(f"{path}.part"))

    def test_interrupt_preserves_the_requested_json_and_returns_130(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "confidence.json")
            with (
                patch.object(
                    stem_audit, "iter_stem_confidence_entries", side_effect=KeyboardInterrupt
                ),
                redirect_stderr(io.StringIO()) as stderr,
            ):
                code = stem_audit.run_stem_confidence_audit(
                    policy=collect.FetchPolicy(), json_path=path, quiet=True
                )
            self.assertEqual(code, 130)
            self.assertFalse(os.path.exists(path))
            self.assertIn("interrupted", stderr.getvalue().lower())


class ConfidenceAuditCacheTests(unittest.TestCase):
    def test_successes_are_warm_cached_but_failures_are_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "hashes.json")
            cache = stem_audit.HashCache(path)
            cache.put("https://example.test/ok", stem_audit.HashLookup(digest="abc", status="ok"))
            cache.put("https://example.test/bad", stem_audit.HashLookup(status="fetch_failed"))
            cache.save()
            reloaded = stem_audit.HashCache(path)
            self.assertEqual(reloaded.get("https://example.test/ok").digest, "abc")  # type: ignore[union-attr]
            self.assertIsNone(reloaded.get("https://example.test/bad"))

    def test_refresh_bypasses_a_warm_hash_and_replaces_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = stem_audit.HashCache(os.path.join(tmp, "hashes.json"))
            cache.put(
                "https://example.test/model", stem_audit.HashLookup(digest="old", status="ok")
            )
            with patch(
                "scripts.model_tool_support.checkpoint_tail_hash", return_value="fresh"
            ) as fetched:
                result = stem_audit._remote_checkpoint_hash(
                    "https://example.test/model", cache=cache, refresh=True
                )
            self.assertEqual(result.digest, "fresh")
            fetched.assert_called_once()
            self.assertEqual(cache.get("https://example.test/model").digest, "fresh")  # type: ignore[union-attr]

    def test_offline_never_range_fetches_a_checkpoint(self) -> None:
        with patch(
            "scripts.model_tool_support.checkpoint_tail_hash",
            side_effect=AssertionError("offline range fetch"),
        ):
            result = stem_audit._remote_checkpoint_hash(
                "https://example.test/model", allow_network=False
            )
        self.assertEqual(result.status, "offline")


class ConfidenceAuditSelectionAndPolicyTests(unittest.TestCase):
    def _target(self, entry_id: str, label: str) -> SimpleNamespace:
        return SimpleNamespace(entry_id=entry_id, label=label)

    def test_only_and_limit_filter_before_the_remote_work(self) -> None:
        targets = [
            self._target("karaoke", "Karaoke model"),
            self._target("other", "Other model"),
        ]
        picked = stem_audit.select_confidence_targets(targets, only="KARA", limit=1)
        self.assertEqual([target.entry_id for target in picked], ["karaoke"])

    def test_offline_config_lookup_passes_the_shared_policy_to_the_cache_reader(self) -> None:
        target = SimpleNamespace(
            config_url="https://example.test/model.yaml", config_name="model.yaml"
        )
        policy = collect.FetchPolicy(allow_network=False, allow_cache_writes=False)
        with patch("catalogue.collect._fetch_yaml_bytes", return_value=(None, None)) as fetched:
            with self.assertRaisesRegex(OSError, "offline"):
                stem_audit._confidence_config(target, policy)
        self.assertIs(fetched.call_args.kwargs["policy"], policy)

    def test_warm_legacy_config_cache_is_reused_until_refresh(self) -> None:
        target = SimpleNamespace(
            config_url="https://example.test/model.yaml", config_name="model.yaml"
        )
        with (
            patch("catalogue.stem_audit.os.path.isfile", return_value=True),
            patch("core.model_data.load_mdx_c_config", return_value={"training": {}}) as loaded,
            patch("catalogue.collect._fetch_yaml_bytes", side_effect=AssertionError("cache miss")),
        ):
            self.assertEqual(
                stem_audit._confidence_config(target, collect.FetchPolicy()), {"training": {}}
            )
        loaded.assert_called_once()

    def test_checkpoint_hash_metadata_controls_curated_confidence(self) -> None:
        target = SimpleNamespace(
            entry_id="model",
            label="Some model",
            config_url="https://example.test/model.yaml",
            checkpoint_url="https://example.test/model.ckpt",
            is_bv_model=False,
        )
        with (
            patch.object(
                stem_audit,
                "_confidence_config",
                return_value={"training": {"instruments": ["vocals", "other"]}},
            ),
            patch.object(
                stem_audit,
                "_remote_checkpoint_hash",
                return_value=stem_audit.HashLookup(digest="known", status="ok"),
            ),
        ):
            entry = stem_audit._confidence_entry_for_target(
                target,
                {"known": {"is_karaoke": True}},
                policy=collect.FetchPolicy(),
                cache=None,
            )
        self.assertTrue(entry.is_karaoke)
        self.assertTrue(entry.is_karaoke_curated)
        self.assertEqual(entry.hash_status, "matched")

    def test_catalogue_target_load_uses_offline_policy_without_a_network_mode(self) -> None:
        source = SimpleNamespace(
            state=SimpleNamespace(content=SimpleNamespace(payload={})),
            load=lambda **kwargs: calls.append(kwargs),
        )
        coordinator = SimpleNamespace(source=lambda _source_id: source, close=lambda: None)
        calls: list[dict[str, Any]] = []
        with (
            patch("core.catalogue_coordinator.CatalogueCoordinator", return_value=coordinator),
            patch("scripts.model_tool_support.iter_catalogue_targets", return_value=iter(())),
        ):
            self.assertEqual(
                stem_audit._confidence_targets(collect.FetchPolicy(allow_network=False)), []
            )
        self.assertEqual(calls[0]["mode"].value, "offline")
        self.assertFalse(calls[0]["policy"].allow_network)

    def test_refresh_forces_the_catalogue_target_load(self) -> None:
        source = SimpleNamespace(
            state=SimpleNamespace(content=SimpleNamespace(payload={})),
            load=lambda **kwargs: calls.append(kwargs),
        )
        coordinator = SimpleNamespace(source=lambda _source_id: source, close=lambda: None)
        calls: list[dict[str, Any]] = []
        with (
            patch("core.catalogue_coordinator.CatalogueCoordinator", return_value=coordinator),
            patch("scripts.model_tool_support.iter_catalogue_targets", return_value=iter(())),
        ):
            self.assertEqual(stem_audit._confidence_targets(collect.FetchPolicy(refresh=True)), [])
        self.assertEqual([call["mode"].value for call in calls], ["offline", "force"])

    def test_cold_online_catalogue_load_blocks_until_one_target_is_available(self) -> None:
        target = self._target("fetched", "Fetched model")
        source = SimpleNamespace(state=SimpleNamespace(content=None))
        calls: list[dict[str, Any]] = []

        def load(**kwargs: Any) -> None:
            calls.append(kwargs)
            if kwargs["mode"].value == "force":
                source.state.content = SimpleNamespace(payload={"fetched": {}})

        source.load = load
        coordinator = SimpleNamespace(source=lambda _source_id: source, close=lambda: None)
        with (
            patch("core.catalogue_coordinator.CatalogueCoordinator", return_value=coordinator),
            patch(
                "scripts.model_tool_support.iter_catalogue_targets",
                side_effect=lambda payload, **_kwargs: iter([target] if payload else []),
            ),
            patch.object(stem_audit, "_curated_hash_table", return_value={}),
            patch.object(
                stem_audit, "_confidence_entry_for_target", return_value=_entry("fetched")
            ),
        ):
            entries = list(
                stem_audit.iter_stem_confidence_entries(
                    policy=collect.FetchPolicy(), show_progress=False
                )
            )

        self.assertEqual([entry.entry_id for entry in entries], ["fetched"])
        self.assertEqual([call["mode"].value for call in calls], ["offline", "force"])

    def test_progress_and_guessed_only_apply_to_the_real_entry_iterator(self) -> None:
        targets = [self._target("one", "One"), self._target("two", "Two")]
        with (
            patch.object(stem_audit, "_confidence_targets", return_value=targets),
            patch.object(stem_audit, "_curated_hash_table", return_value={}),
            patch.object(
                stem_audit,
                "_confidence_entry_for_target",
                side_effect=[_entry("one"), _entry("two", curated=True)],
            ),
            redirect_stderr(io.StringIO()) as stderr,
        ):
            entries = list(
                stem_audit.iter_stem_confidence_entries(
                    policy=collect.FetchPolicy(), guessed_only=True, show_progress=True
                )
            )
        self.assertEqual([entry.entry_id for entry in entries], ["one"])
        self.assertIn("[1/2] one: One", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
