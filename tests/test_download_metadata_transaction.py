import io
import json
import os
import tempfile
import unittest
from unittest import mock

from core import downloads as downloads_mod


class _JsonResponse:
    def __init__(self, payload: object) -> None:
        self.buffer = io.StringIO(json.dumps(payload))

    def __enter__(self) -> io.StringIO:
        return self.buffer

    def __exit__(self, *_args: object) -> None:
        return None


class MetadataRefreshTransactionTests(unittest.TestCase):
    def _setup(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        destinations = [os.path.join(tmp.name, f"mapper-{index}.json") for index in range(4)]
        originals = [{"old": index} for index in range(4)]
        for path, payload in zip(destinations, originals):
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
        return destinations, originals

    def test_invalid_payload_leaves_all_files_untouched(self) -> None:
        destinations, originals = self._setup()
        responses = [_JsonResponse({"new": index}) for index in range(3)]
        responses.append(_JsonResponse(["not", "an", "object"]))
        urls = [(f"https://example.test/{index}", path) for index, path in enumerate(destinations)]
        with mock.patch.object(downloads_mod, "_MODEL_DATA_URLS", urls), mock.patch.object(
            downloads_mod, "_NAME_MAPPER_DESTS", frozenset()
        ), mock.patch.object(downloads_mod, "_urlopen", side_effect=responses):
            self.assertFalse(downloads_mod.DownloadManager().update_model_settings())
        for path, expected in zip(destinations, originals):
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), expected)

    def test_commit_failure_rolls_back_every_destination(self) -> None:
        destinations, originals = self._setup()
        payloads = [{"new": index} for index in range(4)]
        urls = [(f"https://example.test/{index}", path) for index, path in enumerate(destinations)]
        real_replace = os.replace
        calls = 0

        def replace_once_then_fail(source: str, destination: str) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated commit failure")
            real_replace(source, destination)

        with mock.patch.object(downloads_mod, "_MODEL_DATA_URLS", urls), mock.patch.object(
            downloads_mod, "_NAME_MAPPER_DESTS", frozenset()
        ), mock.patch.object(
            downloads_mod, "_urlopen", side_effect=[_JsonResponse(payload) for payload in payloads]
        ), mock.patch.object(downloads_mod.os, "replace", side_effect=replace_once_then_fail):
            repo = mock.Mock()
            self.assertFalse(downloads_mod.DownloadManager().update_model_settings(repo))
            repo.invalidate_models.assert_not_called()
        for path, expected in zip(destinations, originals):
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), expected)


if __name__ == "__main__":
    unittest.main()
