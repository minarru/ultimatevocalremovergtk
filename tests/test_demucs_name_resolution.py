"""Demucs must resolve names to files the way VR and MDX already do."""

import os
import unittest
from unittest.mock import patch

from core.model_config import ModelConfig
from core.model_display import resolve_demucs_model_basename, resolve_mapper_basename
from core.model_identity import DemucsSpec, ModelArtifacts, ModelRecord


def _config_with_record(
    *,
    id: str,
    display: str,
    demucs: DemucsSpec,
    primary: str,
) -> ModelConfig:
    record = ModelRecord(
        id=id,
        family="demucs",
        basename=id.partition(":")[2],
        display=display,
        backend_name=os.path.splitext(primary)[0],
        artifacts=ModelArtifacts(primary),
        installed=True,
        demucs=demucs,
    )
    cfg = ModelConfig.__new__(ModelConfig)
    cfg.canonical_id = record.id
    cfg.model_name = record.display
    cfg.demucs = record.demucs
    cfg.is_ensemble_mode = True
    return cfg


class MapperSeparatorToleranceTests(unittest.TestCase):
    """The Demucs mapper stores 'v4 | X'; every display is canonicalised to 'v4 — X'."""

    _MAPPER = {"hdemucs_mmi.yaml": "v4 | hdemucs_mmi", "tasnet.th": "v1 | Tasnet"}

    def test_an_em_dash_label_inverts_a_pipe_mapper_value(self) -> None:
        self.assertEqual(
            resolve_mapper_basename("v4 — hdemucs_mmi", self._MAPPER), "hdemucs_mmi"
        )

    def test_the_original_pipe_form_still_inverts(self) -> None:
        self.assertEqual(
            resolve_mapper_basename("v4 | hdemucs_mmi", self._MAPPER), "hdemucs_mmi"
        )

    def test_a_bare_basename_still_inverts(self) -> None:
        self.assertEqual(resolve_mapper_basename("tasnet", self._MAPPER), "tasnet")

    def test_case_differences_do_not_prevent_a_match(self) -> None:
        self.assertEqual(resolve_mapper_basename("v1 — tasnet", self._MAPPER), "tasnet")

    def test_an_unrelated_label_still_returns_none(self) -> None:
        self.assertIsNone(resolve_mapper_basename("v9 — nope", self._MAPPER))

    def test_normalising_the_real_mappers_creates_no_collisions(self) -> None:
        """MDX shares this helper; a mapper edit that would collide must fail here."""
        from core import ModelRepository
        from core.model_display import _normalize_mapper_label

        repo = ModelRepository()
        repo.reload_mappers()
        for name, mapper in (
            ("mdx", repo.mdx_name_select_MAPPER),
            ("demucs", repo.demucs_name_select_MAPPER),
        ):
            if not mapper:
                continue
            keys = [_normalize_mapper_label(v) for v in mapper.values()]
            self.assertEqual(
                len(set(keys)), len(keys), f"{name} mapper collides when normalised"
            )


class BagOwnerResolutionTests(unittest.TestCase):
    """Inverting the catalogue index yields a bag *member*, not the selectable bag."""

    #: Five member signatures share one display, as the real index does.
    _INDEX = {
        "f7e0c4bc-ba3fe64a": "v4 — htdemucs_ft",
        "d12395a8-e57c48e6": "v4 — htdemucs_ft",
        "htdemucs_ft": "v4 — htdemucs_ft",
    }

    def test_a_member_signature_resolves_to_its_owning_bag(self) -> None:
        with patch(
            "core.model_display.demucs_bag_owner_basename",
            side_effect=lambda stem, *a, **k: "htdemucs_ft" if "-" in stem else None,
        ):
            got = resolve_demucs_model_basename(
                "v4 — htdemucs_ft", None, catalogue_index=self._INDEX
            )
        self.assertEqual(got, "htdemucs_ft")

    def test_a_non_member_stem_is_returned_unchanged(self) -> None:
        with patch(
            "core.model_display.demucs_bag_owner_basename", return_value=None
        ):
            got = resolve_demucs_model_basename(
                "v3 — something", None, catalogue_index={"something": "v3 — something"}
            )
        self.assertEqual(got, "something")

    def test_an_unknown_label_is_returned_unchanged(self) -> None:
        self.assertEqual(
            resolve_demucs_model_basename("nope", None, catalogue_index={}), "nope"
        )


class DemucsSpecAssignmentTests(unittest.TestCase):
    def test_v1_display_does_not_select_version(self) -> None:
        cfg = _config_with_record(
            id="demucs:tasnet",
            display="v1 — Tasnet",
            demucs=DemucsSpec("v1", "4_stem"),
            primary="tasnet.th",
        )
        cfg.get_demucs_model_data()

        from bundled.constants import DEMUCS_V1

        self.assertEqual(cfg.demucs_version, DEMUCS_V1)

    def test_misleading_display_does_not_change_version(self) -> None:
        cfg = _config_with_record(
            id="demucs:tasnet",
            display="v1 — Tasnet",
            demucs=DemucsSpec("v1", "4_stem"),
            primary="tasnet.th",
        )
        cfg.model_name = "v4 | nope"
        cfg.get_demucs_model_data()

        from bundled.constants import DEMUCS_V1

        self.assertEqual(cfg.demucs_version, DEMUCS_V1)

    def test_htdemucs_6s_is_six_source_before_inference(self) -> None:
        cfg = _config_with_record(
            id="demucs:htdemucs_6s",
            display="v4 — htdemucs_6s",
            demucs=DemucsSpec("v4", "6_stem"),
            primary="htdemucs_6s.yaml",
        )
        cfg.get_demucs_model_data()

        self.assertEqual(cfg.demucs_stem_count, 6)
        self.assertEqual(
            cfg.demucs_source_list,
            ["drums", "bass", "other", "vocals", "guitar", "piano"],
        )


class DemucsPathResolutionTests(unittest.TestCase):
    """get_demucs_model_path must go through the canonicalizer, like VR and MDX."""

    def test_the_installed_model_resolves_to_a_file_that_exists(self) -> None:
        from bundled.constants import DEMUCS_ARCH_TYPE
        from core import ModelRepository
        from core.settings import Settings

        repo = ModelRepository()
        repo.reload_mappers()
        installed = list(repo.list_demucs_models())
        if not installed:
            self.skipTest("no Demucs model installed")

        from core.model_display import display_name_for_model

        settings = Settings.defaults()
        display = display_name_for_model(DEMUCS_ARCH_TYPE, installed[0], repo)
        model_id = f"demucs:{installed[0]}"
        settings.demucs.model = model_id
        model = repo.resolve_model_dry(settings, DEMUCS_ARCH_TYPE, model_id)
        path = str(getattr(model, "model_path", "") or "")
        self.assertTrue(
            path and os.path.isfile(path),
            f"display {display!r} resolved to a non-existent path {path!r}",
        )


if __name__ == "__main__":
    unittest.main()
