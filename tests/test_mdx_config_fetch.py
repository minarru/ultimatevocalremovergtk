"""Tests for MDX-C config fetch (TRvlvr + Politrees fallback)."""

import builtins
import os
import tempfile
import unittest
from contextlib import contextmanager
from typing import Any, cast
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from core import paths
from core.mdx_config_fetch import (
    _safe_config_name,
    config_source_urls,
    ensure_mdx_c_config,
)


class SafeConfigNameTests(unittest.TestCase):
    def test_accepts_yaml_basename(self) -> None:
        self.assertEqual(_safe_config_name("config_melband_roformer_inst.yaml"), "config_melband_roformer_inst.yaml")

    def test_rejects_path_traversal(self) -> None:
        self.assertIsNone(_safe_config_name("../secret.yaml"))
        self.assertIsNone(_safe_config_name("sub/config.yaml"))

    def test_rejects_non_yaml(self) -> None:
        self.assertIsNone(_safe_config_name("model.pth"))


class ConfigSourceUrlsTests(unittest.TestCase):
    def test_order_trvlvr_then_politrees(self) -> None:
        urls = config_source_urls("model_bs_roformer_ep_317_sdr_12.9755.yaml")
        self.assertGreaterEqual(len(urls), 2)
        self.assertIn("TRvlvr/application_data", urls[0])
        self.assertIn("Politrees/UVR_resources", urls[1])


class EnsureMdxCConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._config_dir = os.path.join(self._tmpdir.name, "mdx_c_configs")
        os.makedirs(self._config_dir, exist_ok=True)
        self._path_patch = patch.object(paths, "MDX_C_CONFIG_PATH", self._config_dir)
        self._path_patch.start()

    def tearDown(self) -> None:
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_failed_write_leaves_no_config_and_retry_fetches_again(self) -> None:
        name = "retry.yaml"
        dest = os.path.join(self._config_dir, name)
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"model:\n  dim: 256\n"
        real_open, real_fdopen = builtins.open, os.fdopen

        @contextmanager
        def failing_writer(*args: Any, **kwargs: Any):
            opener = real_fdopen if isinstance(args[0], int) else real_open
            with opener(*args, **kwargs) as handle:
                writer = MagicMock(wraps=handle)

                def partial_write(data: bytes) -> None:
                    handle.write(data[:4])
                    handle.flush()
                    raise OSError(28, "No space left on device")

                writer.write.side_effect = partial_write
                yield writer

        with patch("core.mdx_config_fetch._urlopen", return_value=response) as network:
            with (
                patch("core.mdx_config_fetch.open", failing_writer, create=True),
                patch("core.mdx_config_fetch.os.fdopen", failing_writer),
                self.assertRaises(OSError),
            ):
                ensure_mdx_c_config(name)
            self.assertFalse(os.path.exists(dest))
            self.assertEqual(os.listdir(self._config_dir), [])
            self.assertTrue(ensure_mdx_c_config(name))
            self.assertEqual(network.call_count, 2)
        with open(dest, "rb") as handle:
            self.assertEqual(handle.read(), response.read.return_value)

    def test_existing_file_skips_network(self) -> None:
        name = "local_only.yaml"
        dest = os.path.join(self._config_dir, name)
        with open(dest, "wb") as fh:
            fh.write(b"training: {}\n")

        with patch("core.mdx_config_fetch._urlopen") as mock_open:
            self.assertTrue(ensure_mdx_c_config(name))
            mock_open.assert_not_called()

    def test_trvlvr_success(self) -> None:
        name = "from_trvlvr.yaml"
        body = b"audio:\n  hop_length: 1024\n"

        def fake_urlopen(url: str):
            if "TRvlvr/application_data" in url:
                resp = MagicMock()
                resp.read.return_value = body
                resp.__enter__ = MagicMock(return_value=resp)
                resp.__exit__ = MagicMock(return_value=False)
                return resp
            raise HTTPError(url, 404, "not found", cast(Any, None), None)

        with patch("core.mdx_config_fetch._urlopen", side_effect=fake_urlopen):
            self.assertTrue(ensure_mdx_c_config(name))

        with open(os.path.join(self._config_dir, name), "rb") as fh:
            self.assertEqual(fh.read(), body)

    def test_politrees_fallback_when_trvlvr_missing(self) -> None:
        name = "politrees_only.yaml"
        body = b"model:\n  dim: 256\n"

        def fake_urlopen(url: str):
            if "TRvlvr/application_data" in url:
                raise HTTPError(url, 404, "not found", cast(Any, None), None)
            if "Politrees/UVR_resources" in url and url.endswith(name):
                resp = MagicMock()
                resp.read.return_value = body
                resp.__enter__ = MagicMock(return_value=resp)
                resp.__exit__ = MagicMock(return_value=False)
                return resp
            raise HTTPError(url, 404, "not found", cast(Any, None), None)

        with patch("core.mdx_config_fetch._urlopen", side_effect=fake_urlopen):
            self.assertTrue(ensure_mdx_c_config(name))

        with open(os.path.join(self._config_dir, name), "rb") as fh:
            self.assertEqual(fh.read(), body)

    def test_all_sources_fail(self) -> None:
        errors: list[HTTPError] = []

        def fake_urlopen(url: str):
            error = HTTPError(url, 404, "not found", cast(Any, None), None)
            errors.append(error)
            raise error

        with patch("core.mdx_config_fetch._urlopen", side_effect=fake_urlopen):
            self.assertFalse(ensure_mdx_c_config("missing_everywhere.yaml"))

        self.assertTrue(errors)
        self.assertTrue(all(error.closed for error in errors))
        self.assertFalse(os.path.isfile(os.path.join(self._config_dir, "missing_everywhere.yaml")))


if __name__ == "__main__":
    unittest.main()
