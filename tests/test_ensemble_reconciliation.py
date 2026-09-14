"""Ensemble membership follows the same runtime roles as separation."""

import json
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from core.model_data import load_mdx_c_config_data
from core.model_manifest import ModelManifestError, load_model_manifest_document
from core.model_repository import ModelRepository
from core.settings import Settings
from core.stems import model_stem_routes
from tests.test_stem_runtime_reconciliation import KIM, runtime_model


class EnsembleReconciliationTests(unittest.TestCase):
    def test_alias_evidence_rejects_unreviewed_targets_or_missing_checkpoint(self):
        for field, value in (("target_aliases", ["Vocals"]), ("artifact_evidence", [])):
            with self.subTest(field=field):
                document = json.loads(Path("bundled/model_manifest.json").read_text())
                document["models"]["mdx:mbr_inst2_unwa"]["runtime_contract"][field] = value
                with self.assertRaises(ModelManifestError):
                    load_model_manifest_document(document)

    def test_alias_still_rejects_wrong_checkpoint(self):
        model = runtime_model(
            "mdx:mbr_inst2_unwa", ("Instrumental",), "Instrumental", digest="0" * 32
        )
        self.assertEqual(self.eligible(model), [])

    def test_inst_v2_identities_accept_both_reviewed_configs(self):
        config_dir = Path("models/MDX_Net_Models/model_data/mdx_c_configs")
        for model_id in (KIM, "mdx:mbr_inst2_unwa"):
            for filename in ("config_melbandroformer_inst_v2.yaml", "mbr_inst2_unwa_config.yaml"):
                with self.subTest(model_id=model_id, config=filename):
                    config = load_mdx_c_config_data((config_dir / filename).read_bytes())
                    target = config["training"]["target_instrument"]
                    model = runtime_model(
                        model_id, (target,), target, digest="951f8ef420a941a395a9919f5d55cce9"
                    )
                    model.mdx_c_configs = config
                    routes = model_stem_routes(model)
                    self.assertEqual([r.label for r in routes], ["Instrumental", "Vocals"])
                    self.assertFalse(model.stem_semantics.runtime_error)
                    self.assertEqual(self.eligible(model), [model_id])

    def eligible(self, model: Any) -> list[str]:
        repo = object.__new__(ModelRepository)
        with patch.object(repo, "stem_check", return_value=[model]):
            return repo.ensemble_model_list(Settings.defaults(), "pair.vocals_instrumental")

    def test_verified_target_rename_is_eligible(self):
        self.assertEqual(self.eligible(runtime_model()), [KIM])

    def test_matching_names_with_wrong_checkpoint_are_ineligible(self):
        model = runtime_model(natives=("Instrumental",), target="Instrumental", digest="0" * 32)
        self.assertEqual(self.eligible(model), [])

    def test_incompatible_layout_is_ineligible(self):
        model = runtime_model(natives=("Instrumental",), target="")
        self.assertEqual(self.eligible(model), [])

    def test_unknown_model_is_ineligible(self):
        self.assertEqual(self.eligible(runtime_model("mdx:unknown")), [])

    def test_vocal_split_context_is_ineligible_for_full_mix(self):
        model = runtime_model("mdx:bs_pope_karaoke2_lambda", ("lead",), "lead")
        model.is_vocal_split_model = True
        self.assertEqual(self.eligible(model), [])
