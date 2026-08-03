"""Pure-helper tests for the model probe. No network, no weights."""

import importlib.util
import json
import os
import struct
import sys
import unittest
from typing import Any

_SPEC = importlib.util.spec_from_file_location(
    "model_probe",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "model_probe.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
model_probe = importlib.util.module_from_spec(_SPEC)
sys.modules["model_probe"] = model_probe
_SPEC.loader.exec_module(model_probe)


def _safetensors_bytes(names: dict) -> bytes:
    """Build a minimal .safetensors prefix: u64 header length + JSON header."""
    header = json.dumps(names).encode("utf-8")
    return struct.pack("<Q", len(header)) + header


class SafetensorsHeaderTests(unittest.TestCase):
    def test_reports_the_byte_span_the_header_occupies(self) -> None:
        blob = _safetensors_bytes({"a.weight": {"shape": [2]}})
        span = model_probe.safetensors_header_span(blob[:8])
        self.assertEqual(span, (8, 8 + len(blob) - 8))

    def test_lists_tensor_names_from_the_header(self) -> None:
        blob = _safetensors_bytes({
            "enc.weight": {"dtype": "F32", "shape": [4, 4], "data_offsets": [0, 64]},
            "enc.bias": {"dtype": "F32", "shape": [4], "data_offsets": [64, 80]},
        })
        self.assertEqual(
            sorted(model_probe.parse_safetensors_header(blob)),
            ["enc.bias", "enc.weight"],
        )

    def test_ignores_the_metadata_pseudo_entry(self) -> None:
        blob = _safetensors_bytes({
            "__metadata__": {"format": "pt"},
            "w": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]},
        })
        self.assertEqual(model_probe.parse_safetensors_header(blob), ["w"])

    def test_rejects_a_header_that_is_not_json(self) -> None:
        blob = struct.pack("<Q", 4) + b"nope"
        with self.assertRaises(ValueError):
            model_probe.parse_safetensors_header(blob)


def _file_reader(path: str):
    """A RangeReader over a local file — what an HTTP range reader stands in for."""

    def read(start: int, end: int) -> bytes:
        with open(path, "rb") as handle:
            handle.seek(start)
            return handle.read(end - start)

    return read, os.path.getsize(path)


class TorchCheckpointKeyTests(unittest.TestCase):
    """Torch .ckpt is a zip; its keys live in data.pkl, not in the entry names."""

    def _save(self, obj: Any, name: str = "ckpt.pt") -> str:
        import torch

        path = os.path.join(self.tmp.name, name)
        torch.save(obj, path)
        return path

    def setUp(self) -> None:
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_reads_keys_of_a_plain_state_dict(self) -> None:
        import torch

        path = self._save({"enc.weight": torch.zeros(2, 2), "enc.bias": torch.zeros(2)})
        read, size = _file_reader(path)
        self.assertEqual(
            sorted(model_probe.torch_checkpoint_keys(read, size)),
            ["enc.bias", "enc.weight"],
        )

    def test_descends_into_a_lightning_style_wrapper(self) -> None:
        import torch

        path = self._save({
            "epoch": 3,
            "global_step": 120,
            "state_dict": {"net.0.weight": torch.zeros(1), "net.0.bias": torch.zeros(1)},
        })
        read, size = _file_reader(path)
        self.assertEqual(
            sorted(model_probe.torch_checkpoint_keys(read, size)),
            ["net.0.bias", "net.0.weight"],
        )

    def test_reads_far_less_than_the_whole_file(self) -> None:
        """The point of the exercise: header only, not the tensor payload."""
        import torch

        path = self._save({f"layer{i}.weight": torch.zeros(256, 256) for i in range(8)})
        read, size = _file_reader(path)
        billed = []

        def counting_read(start: int, end: int) -> bytes:
            billed.append(end - start)
            return read(start, end)

        keys = model_probe.torch_checkpoint_keys(counting_read, size)
        self.assertEqual(len(keys), 8)
        self.assertLess(sum(billed), size // 4, f"read {sum(billed)} of {size} bytes")

    def test_reads_an_ordereddict_carrying_torch_s_metadata_attribute(self) -> None:
        """``Module.state_dict()`` sets ``_metadata`` on the dict instance, which
        pickles as a BUILD opcode — plain ``dict`` cannot accept that."""
        import collections

        import torch

        state = collections.OrderedDict(
            [("conv.weight", torch.zeros(2)), ("conv.bias", torch.zeros(2))]
        )
        state._metadata = collections.OrderedDict([("", {"version": 1})])  # type: ignore[attr-defined]
        path = self._save(state, "with_metadata.pt")
        read, size = _file_reader(path)
        self.assertEqual(
            sorted(model_probe.torch_checkpoint_keys(read, size)),
            ["conv.bias", "conv.weight"],
        )

    def test_rejects_a_file_that_is_not_a_zip(self) -> None:
        path = os.path.join(self.tmp.name, "legacy.pth")
        with open(path, "wb") as handle:
            handle.write(b"\x80\x02}q\x00.")  # a bare pickle, pre-zip torch format
        read, size = _file_reader(path)
        with self.assertRaises(ValueError):
            model_probe.torch_checkpoint_keys(read, size)


class KeyDiffTests(unittest.TestCase):
    def test_reports_a_clean_match(self) -> None:
        diff = model_probe.diff_state_dict_keys(["a", "b"], ["b", "a"])
        self.assertTrue(diff.matches)
        self.assertEqual(diff.missing, [])
        self.assertEqual(diff.unexpected, [])

    def test_missing_are_keys_the_checkpoint_has_and_the_module_lacks(self) -> None:
        diff = model_probe.diff_state_dict_keys(
            module_keys=["a"], checkpoint_keys=["a", "skip.weight"]
        )
        self.assertFalse(diff.matches)
        self.assertEqual(diff.missing, ["skip.weight"])
        self.assertEqual(diff.unexpected, [])

    def test_unexpected_are_keys_the_module_has_and_the_checkpoint_lacks(self) -> None:
        diff = model_probe.diff_state_dict_keys(
            module_keys=["a", "extra.bias"], checkpoint_keys=["a"]
        )
        self.assertEqual(diff.unexpected, ["extra.bias"])
        self.assertEqual(diff.missing, [])


_REPO = os.path.dirname(os.path.dirname(__file__))
#: A small committed SCNet config — no weights involved, builds in ~1s.
_SCNET_CONFIG = os.path.join(
    _REPO, "models", "MDX_Net_Models", "model_data", "mdx_c_configs",
    "config_musdb18_scnet.yaml",
)
#: A committed MDX23C config, which takes the TFC_TDF_net path instead.
_MDX23C_CONFIG = os.path.join(
    _REPO, "models", "MDX_Net_Models", "model_data", "mdx_c_configs",
    "model_2_stem_full_band.yaml",
)


class BuildFromConfigTests(unittest.TestCase):
    """The whole point: architecture comes from the yaml, never the weights."""

    @unittest.skipUnless(os.path.isfile(_SCNET_CONFIG), "config not present")
    def test_builds_a_roformer_family_model_with_no_checkpoint(self) -> None:
        built = model_probe.build_from_config(_SCNET_CONFIG)
        self.assertEqual(built.architecture, "SCNet")
        self.assertGreater(built.parameters, 1_000_000)
        self.assertEqual(built.stems, ["Drums", "Bass", "Other", "Vocals"])

    @unittest.skipUnless(os.path.isfile(_MDX23C_CONFIG), "config not present")
    def test_falls_back_to_the_mdx23c_builder(self) -> None:
        built = model_probe.build_from_config(_MDX23C_CONFIG)
        self.assertEqual(built.architecture, "TFC_TDF_net")

    @unittest.skipUnless(os.path.isfile(_MDX23C_CONFIG), "config not present")
    def test_mdx23c_reports_no_dropped_keys(self) -> None:
        """TFC_TDF_net consumes the whole config, so no kwarg filtering happens —
        reporting its model section as dropped would be a false alarm."""
        built = model_probe.build_from_config(_MDX23C_CONFIG)
        self.assertEqual(built.dropped, [])

    @unittest.skipUnless(os.path.isfile(_SCNET_CONFIG), "config not present")
    def test_a_fully_supported_filtered_config_drops_nothing(self) -> None:
        built = model_probe.build_from_config(_SCNET_CONFIG)
        self.assertEqual(built.dropped, [])

    def test_reports_an_unbuildable_config_instead_of_raising(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bogus.yaml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("audio:\n  sample_rate: 44100\n")
            built = model_probe.build_from_config(path)
            self.assertIsNone(built.module)
            self.assertIn("architecture", built.error.lower())


class DroppedConfigKeyTests(unittest.TestCase):
    """``_filter_init_kwargs`` silently drops yaml keys a class does not accept,
    so a model can build while missing the very feature that made it unsupported."""

    class _Net:
        def __init__(self, dim: int, depth: int = 2) -> None:
            pass

    class _NetWithKwargs:
        def __init__(self, dim: int, **kwargs: Any) -> None:
            pass

    def test_reports_keys_the_constructor_will_not_accept(self) -> None:
        dropped = model_probe.dropped_config_keys(
            self._Net, {"dim": 4, "depth": 2, "skip_connection": True}
        )
        self.assertEqual(dropped, ["skip_connection"])

    def test_nothing_is_dropped_when_the_class_takes_kwargs(self) -> None:
        dropped = model_probe.dropped_config_keys(
            self._NetWithKwargs, {"dim": 4, "skip_connection": True}
        )
        self.assertEqual(dropped, [])

    def test_a_fully_understood_config_drops_nothing(self) -> None:
        self.assertEqual(
            model_probe.dropped_config_keys(self._Net, {"dim": 4, "depth": 1}), []
        )


class ForwardProbeTests(unittest.TestCase):
    @unittest.skipUnless(os.path.isfile(_SCNET_CONFIG), "config not present")
    def test_runs_real_audio_shaped_noise_through_the_module(self) -> None:
        built = model_probe.build_from_config(_SCNET_CONFIG)
        result = model_probe.forward_probe(built, seconds=1.0)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.input_shape[:2], (1, 2))
        self.assertTrue(result.finite)

    @unittest.skipUnless(os.path.isfile(_MDX23C_CONFIG), "config not present")
    def test_uses_the_config_chunk_size_so_stft_framing_lines_up(self) -> None:
        """MDX23C rejects an arbitrary length; the config states its chunk size."""
        built = model_probe.build_from_config(_MDX23C_CONFIG)
        result = model_probe.forward_probe(built)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.input_shape, (1, 2, 260096))

    @unittest.skipUnless(os.path.isfile(_SCNET_CONFIG), "config not present")
    def test_an_explicit_duration_overrides_the_config_chunk_size(self) -> None:
        built = model_probe.build_from_config(_SCNET_CONFIG)
        result = model_probe.forward_probe(built, seconds=1.0)
        self.assertEqual(result.input_shape, (1, 2, built.sample_rate))

    def test_reports_the_failure_when_the_module_never_built(self) -> None:
        built = model_probe.BuiltModel(
            config_path="x.yaml", architecture="", module=None, error="boom"
        )
        result = model_probe.forward_probe(built, seconds=0.1)
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "boom")


_CATALOGUE = {
    "mbr_syhft_4stem": {
        "full_name": "MelBand Roformer 4stem SYHFT",
        "model_type": "mel_band_roformer",
        "checkpoint_url": "https://example.invalid/w.ckpt",
        "config_url": "https://example.invalid/c.yaml",
    },
    "medley_thing": {
        "full_name": "Medley Vox Thing",
        "model_type": "medley_vox",
        "checkpoint_url": "https://example.invalid/m.ckpt",
        "config_url": "https://example.invalid/m.yaml",
    },
}


class ResolveTargetTests(unittest.TestCase):
    def test_resolves_an_entry_to_its_config_and_checkpoint_urls(self) -> None:
        target = model_probe.resolve_target("mbr_syhft_4stem", catalogue=_CATALOGUE)
        self.assertEqual(target.config_url, "https://example.invalid/c.yaml")
        self.assertEqual(target.checkpoint_url, "https://example.invalid/w.ckpt")
        self.assertEqual(target.label, "MelBand Roformer 4stem SYHFT")

    def test_carries_the_catalogue_unsupported_reason(self) -> None:
        """Why the entry is listed unsupported is the context for the verdict."""
        target = model_probe.resolve_target("mbr_syhft_4stem", catalogue=_CATALOGUE)
        self.assertEqual(target.reason, "Mel-Band skip_connection not ported")
        other = model_probe.resolve_target("medley_thing", catalogue=_CATALOGUE)
        self.assertEqual(other.reason, "Medley-Vox engine not ported")

    def test_unknown_entry_id_is_an_error(self) -> None:
        with self.assertRaises(KeyError):
            model_probe.resolve_target("nope", catalogue=_CATALOGUE)

    def test_config_filename_comes_from_the_url(self) -> None:
        target = model_probe.resolve_target("mbr_syhft_4stem", catalogue=_CATALOGUE)
        self.assertEqual(target.config_name, "c.yaml")


class ReportTests(unittest.TestCase):
    def _result(self, **kw: Any) -> Any:
        base = dict(
            entry_id="x",
            label="X",
            reason="not ported",
            build=model_probe.BuiltModel("c.yaml", "MelBandRoformer", module=object(),
                                         parameters=1_000_000, stems=["Vocals"]),
            forward=model_probe.ForwardResult(ok=True, output_shape=(1, 1, 2, 4),
                                              finite=True),
        )
        base.update(kw)
        return model_probe.ProbeResult(**base)

    def test_verdict_is_buildable_when_build_and_forward_succeed(self) -> None:
        self.assertEqual(self._result().verdict, "buildable")

    def test_verdict_is_build_failed_when_the_architecture_is_unported(self) -> None:
        result = self._result(
            build=model_probe.BuiltModel("c.yaml", "", error="TypeError: skip_connection"),
            forward=model_probe.ForwardResult(ok=False, error="model not built"),
        )
        self.assertEqual(result.verdict, "build-failed")

    def test_verdict_is_forward_failed_when_it_builds_but_cannot_run(self) -> None:
        result = self._result(
            forward=model_probe.ForwardResult(ok=False, error="RuntimeError: shape")
        )
        self.assertEqual(result.verdict, "forward-failed")

    def test_dropped_config_keys_mean_the_build_is_not_really_the_model(self) -> None:
        result = self._result(
            build=model_probe.BuiltModel(
                "c.yaml", "MelBandRoformer", module=object(),
                dropped=["skip_connection"],
            )
        )
        self.assertEqual(result.verdict, "config-ignored")

    def test_report_names_the_silently_dropped_keys(self) -> None:
        text = model_probe.render_report(
            self._result(
                build=model_probe.BuiltModel(
                    "c.yaml", "MelBandRoformer", module=object(),
                    dropped=["skip_connection"],
                )
            )
        )
        self.assertIn("skip_connection", text)

    def test_key_mismatch_downgrades_a_buildable_verdict(self) -> None:
        result = self._result(
            keys=model_probe.KeyDiff(missing=["skip.weight"], unexpected=[], matched=9)
        )
        self.assertEqual(result.verdict, "key-mismatch")

    def test_report_names_the_entry_and_the_verdict(self) -> None:
        text = model_probe.render_report(self._result())
        self.assertIn("X", text)
        self.assertIn("buildable", text)

    def test_result_round_trips_through_json(self) -> None:
        payload = json.loads(json.dumps(self._result().to_json()))
        self.assertEqual(payload["verdict"], "buildable")
        self.assertEqual(payload["architecture"], "MelBandRoformer")


class HttpRangeReaderTests(unittest.TestCase):
    """The range request is the whole trick — assert the header, not the network."""

    class _FakeResponse:
        def __init__(self, payload: bytes, headers: dict) -> None:
            self._payload = payload
            self.headers = headers

        def read(self) -> bytes:
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *exc: Any) -> bool:
            return False

    def test_requests_exactly_the_half_open_span_as_an_inclusive_range(self) -> None:
        seen = []

        def opener(request: Any) -> Any:
            seen.append(request.get_header("Range"))
            return self._FakeResponse(b"abcd", {})

        read = model_probe.http_range_reader("https://example.invalid/f", opener=opener)
        self.assertEqual(read(100, 140), b"abcd")
        self.assertEqual(seen, ["bytes=100-139"])

    def test_reads_the_length_from_a_content_range_header(self) -> None:
        def opener(request: Any) -> Any:
            return self._FakeResponse(b"x", {"Content-Range": "bytes 0-0/123456"})

        size = model_probe.remote_size("https://example.invalid/f", opener=opener)
        self.assertEqual(size, 123456)


class CliTests(unittest.TestCase):
    """``--config`` is the fully offline path: no catalogue, no checkpoint."""

    @unittest.skipUnless(os.path.isfile(_SCNET_CONFIG), "config not present")
    def test_probing_a_local_config_succeeds(self) -> None:
        import io as _io
        import contextlib

        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = model_probe.main(["--config", _SCNET_CONFIG])
        self.assertEqual(code, 0)
        self.assertIn("buildable", buf.getvalue())

    def test_unbuildable_config_exits_nonzero(self) -> None:
        import io as _io
        import contextlib
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bogus.yaml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("audio:\n  sample_rate: 44100\n")
            buf = _io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = model_probe.main(["--config", path])
        self.assertNotEqual(code, 0)
        self.assertIn("build-failed", buf.getvalue())

    @unittest.skipUnless(os.path.isfile(_SCNET_CONFIG), "config not present")
    def test_local_checkpoint_keys_are_diffed_against_the_built_module(self) -> None:
        """A checkpoint whose names disagree is the failure mode this exists for."""
        import io as _io
        import contextlib
        import tempfile

        import torch

        with tempfile.TemporaryDirectory() as tmp:
            ckpt = os.path.join(tmp, "wrong_names.ckpt")
            torch.save({"state_dict": {"not.a.real.key": torch.zeros(1)}}, ckpt)
            buf = _io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = model_probe.main(
                    ["--config", _SCNET_CONFIG, "--checkpoint", ckpt]
                )
        self.assertNotEqual(code, 0)
        output = buf.getvalue()
        self.assertIn("key-mismatch", output)
        self.assertIn("not.a.real.key", output)

    @unittest.skipUnless(os.path.isfile(_SCNET_CONFIG), "config not present")
    def test_json_output_is_written_to_the_given_path(self) -> None:
        import io as _io
        import contextlib
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "probe.json")
            with contextlib.redirect_stdout(_io.StringIO()):
                model_probe.main(["--config", _SCNET_CONFIG, "--json", out])
            with open(out, encoding="utf-8") as handle:
                payload = json.load(handle)
        self.assertEqual(payload["verdict"], "buildable")
        self.assertEqual(payload["architecture"], "SCNet")


if __name__ == "__main__":
    unittest.main()
