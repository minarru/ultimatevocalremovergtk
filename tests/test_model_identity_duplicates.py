"""One checkpoint must yield one record, and an exact id must resolve."""

import unittest

from core.model_identity import ModelRecord, resolve_model_record


def _rec(model_id: str, basename: str, *, installed: bool = True, display: str = "") -> ModelRecord:
    return ModelRecord(
        id=model_id, family=model_id.split(":", 1)[0], basename=basename,
        display=display or basename, installed=installed,
    )


class ExactIdPrecedenceTests(unittest.TestCase):
    """A fully-qualified id must win over a looser casefold sibling."""

    def _records(self):
        return (
            _rec("mdx:mdx23c_d1581", "mdx23c_d1581", installed=True),
            _rec("mdx:MDX23C_D1581", "MDX23C_D1581", installed=False),
        )

    def test_an_exact_id_resolves_despite_a_case_variant_sibling(self) -> None:
        record = resolve_model_record("mdx:mdx23c_d1581", self._records())
        self.assertEqual(record.id, "mdx:mdx23c_d1581")
        self.assertTrue(record.installed)

    def test_the_other_exact_id_also_resolves(self) -> None:
        record = resolve_model_record("mdx:MDX23C_D1581", self._records())
        self.assertEqual(record.id, "mdx:MDX23C_D1581")

    def test_an_unqualified_case_ambiguous_term_still_raises(self) -> None:
        """Without an exact id there is genuinely nothing to prefer."""
        with self.assertRaises(ValueError) as ctx:
            resolve_model_record("mdx23c_d1581", self._records())
        self.assertIn("ambiguous", str(ctx.exception))

    def test_a_single_casefold_match_still_resolves(self) -> None:
        records = (_rec("mdx:Some_Model", "Some_Model"),)
        self.assertEqual(
            resolve_model_record("mdx:some_model", records).id, "mdx:Some_Model"
        )

    def test_an_unknown_reference_still_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_model_record("mdx:nope", self._records())


class CatalogueDuplicateTests(unittest.TestCase):
    """A catalogue label differing only in case from an installed model
    must not become a second, uninstallable record."""

    class _Repo:
        def __init__(self, mdx_installed: list, mdx_catalogue: dict) -> None:
            self._mdx = mdx_installed
            self._cat = mdx_catalogue

        def list_vr_models(self) -> list:
            return []

        def list_mdx_models(self) -> list:
            return list(self._mdx)

        def list_demucs_models(self) -> list:
            return []

        def vr_catalogue_display_index(self, allow_network: bool = False) -> dict:
            return {}

        def mdx_catalogue_display_index(self, allow_network: bool = False) -> dict:
            return dict(self._cat)

        def demucs_catalogue_display_index(self, allow_network: bool = False) -> dict:
            return {}

    def _records(self, installed: list, catalogue: dict) -> list:
        from unittest.mock import patch

        from core.model_identity import ModelIdentityService

        svc = ModelIdentityService(self._Repo(installed, catalogue))
        with patch(
            "core.model_display.map_basenames_to_display",
            side_effect=lambda names, *a, **k: list(names),
        ), patch("core.apollo.list_apollo_models", return_value=[]):
            return [r for r in svc.records() if r.family == "mdx"]

    def test_a_case_variant_catalogue_label_is_dropped(self) -> None:
        records = self._records(["mdx23c_d1581"], {"MDX23C_D1581": "MDX23C D1581"})
        self.assertEqual([r.id for r in records], ["mdx:mdx23c_d1581"])

    def test_the_installed_record_is_the_one_kept(self) -> None:
        records = self._records(["mdx23c_d1581"], {"MDX23C_D1581": "MDX23C D1581"})
        self.assertTrue(records[0].installed)

    def test_a_genuinely_different_catalogue_model_is_kept(self) -> None:
        records = self._records(["mdx23c_d1581"], {"Some_Other": "Some Other"})
        self.assertEqual(
            sorted(r.id for r in records), ["mdx:Some_Other", "mdx:mdx23c_d1581"]
        )

    def test_an_exact_case_match_still_defers_to_installed(self) -> None:
        records = self._records(["mdx23c_d1581"], {"mdx23c_d1581": "Catalogue Name"})
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].installed)


if __name__ == "__main__":
    unittest.main()
