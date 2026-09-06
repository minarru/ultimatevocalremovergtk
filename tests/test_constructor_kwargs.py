"""Constructor analysis is import-light and never changes compatibility policy."""

import unittest
from typing import Any
from unittest import mock

from core.constructor_kwargs import analyze_constructor_kwargs


class ConstructorKwargsTests(unittest.TestCase):
    class Strict:
        def __init__(self, first: Any = None, second: Any = None) -> None:
            raise AssertionError("analysis must not construct")

    def test_retains_order_values_and_raw_dropped_facts(self) -> None:
        value: list[int] = []
        result = analyze_constructor_kwargs(
            self.Strict, {"z": 7, "second": value, "a": 8, "first": 2}
        )
        self.assertEqual(list(result.accepted), ["second", "first"])
        self.assertIs(result.accepted["second"], value)
        self.assertEqual(result.dropped, ("z", "a"))

    def test_empty_config_preserves_constructor_defaults(self) -> None:
        self.assertEqual(analyze_constructor_kwargs(self.Strict, {}).accepted, {})

    def test_kwargs_includes_self_and_keeps_value_identity(self) -> None:
        class Flexible:
            def __init__(self, **kwargs: Any) -> None:
                raise AssertionError("analysis must not construct")

        value: list[int] = []
        cfg = {"self": value, "unknown": 2}
        result = analyze_constructor_kwargs(Flexible, cfg)
        self.assertEqual(result.accepted, cfg)
        self.assertIsNot(result.accepted, cfg)
        self.assertIs(result.accepted["self"], value)
        self.assertEqual(result.dropped, ())

    def test_inherited_constructor_is_analyzed(self) -> None:
        class Child(self.Strict):
            pass

        self.assertEqual(analyze_constructor_kwargs(Child, {"first": 3}).accepted, {"first": 3})

    def test_positional_only_names_are_still_retained(self) -> None:
        class Positional:
            def __init__(self, first: int, /) -> None:
                pass

        self.assertEqual(
            analyze_constructor_kwargs(Positional, {"first": 3}).accepted, {"first": 3}
        )

    def test_signature_failure_propagates(self) -> None:
        with mock.patch(
            "core.constructor_kwargs.inspect.signature", side_effect=ValueError("bad signature")
        ):
            with self.assertRaisesRegex(ValueError, "bad signature"):
                analyze_constructor_kwargs(self.Strict, {})

    def test_strict_mapping_iterates_once_and_does_not_read_dropped_values(self) -> None:
        class Config:
            def __init__(self) -> None:
                self.iterations = 0

            def __iter__(self):
                self.iterations += 1
                return iter(("first", 1, "unsupported"))

            def __getitem__(self, key: str) -> object:
                if key != "first":
                    raise AssertionError("dropped value was read")
                return 3

        cfg = Config()
        result = analyze_constructor_kwargs(self.Strict, cfg)
        self.assertEqual(result.accepted, {"first": 3})
        self.assertEqual(result.dropped, (1, "unsupported"))
        self.assertEqual(cfg.iterations, 1)
