"""Exclusive stem-only flags are gone from ModelConfig, StemRouting, and engines."""

from __future__ import annotations

import inspect
import unittest
from dataclasses import fields
from pathlib import Path
from typing import cast

from core.model_config import ModelConfig, StemRouting, process_determine_secondary_model
from core.stem_roles import ModelStemSemantics

_REPO = Path(__file__).resolve().parents[1]
_EXCLUSIVE_ATTRS = (
    "is_primary_stem_only",
    "is_secondary_stem_only",
    "is_primary_model_primary_stem_only",
    "is_primary_model_secondary_stem_only",
)


class ExclusiveAttrDeletionTests(unittest.TestCase):
    def test_stem_routing_provenance_defaults_to_unfiltered(self) -> None:
        self.assertIs(StemRouting().selected_routes_explicit, False)
        self.assertIs(StemRouting(selected_routes_explicit=True).selected_routes_explicit, True)

    def test_stem_routing_preserves_existing_positional_semantics_argument(self) -> None:
        semantics = cast(ModelStemSemantics, object())
        routing = StemRouting("primary", "secondary", "native", "model", (), (), (), (), semantics)

        self.assertIs(routing.semantics, semantics)
        self.assertIs(routing.selected_routes_explicit, False)

    def test_stem_routing_has_no_exclusive_flag_fields(self) -> None:
        names = {item.name for item in fields(StemRouting)}
        for attr in ("is_primary_stem_only", "is_secondary_stem_only"):
            with self.subTest(attr=attr):
                self.assertNotIn(attr, names)

    def test_model_config_init_has_no_primary_model_exclusive_kwargs(self) -> None:
        params = inspect.signature(ModelConfig.__init__).parameters
        self.assertNotIn("is_primary_model_primary_stem_only", params)
        self.assertNotIn("is_primary_model_secondary_stem_only", params)

    def test_secondary_model_lookup_has_no_exclusive_parameters(self) -> None:
        params = inspect.signature(process_determine_secondary_model).parameters
        self.assertNotIn("is_primary_stem_only", params)
        self.assertNotIn("is_secondary_stem_only", params)

    def test_engine_sources_do_not_assign_exclusive_stem_only_attrs(self) -> None:
        for relative in ("engines/base.py", "engines/mdx_c.py", "core/model_config/config.py"):
            source = (_REPO / relative).read_text(encoding="utf-8")
            for attr in _EXCLUSIVE_ATTRS:
                with self.subTest(path=relative, attr=attr):
                    self.assertFalse(
                        attr in source,
                        f"{attr} still appears in {relative}",
                    )
