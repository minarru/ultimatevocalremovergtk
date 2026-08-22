"""Runtime code must never turn display text back into an identity.

Two guards, both AST-based:

* runtime modules do not reach the ``display -> basename`` resolvers, by import
  *or* by attribute access on the module;
* the identity layer does not compare a ``ModelRecord``'s presentation fields
  against a query. That comparison is the half of the inversion that survived
  the substring matcher's removal, and it is what lets a catalogue rename move
  an existing model selection.
"""

import ast
from pathlib import Path
import unittest

_ROOT = Path(__file__).resolve().parents[1]
_FORBIDDEN = {
    "resolve_mdx_model_basename",
    "resolve_vr_model_basename",
    "resolve_demucs_model_basename",
    "resolve_model_basename",
    "resolve_mapper_basename",
}
_ALLOWLIST = {
    Path("core/model_display.py"),
}
_SCAN_DIRS = ("engines", "core", "cli")
#: Presentation fields that must not appear on either side of a comparison.
#: ``backend_name`` is checked only inside the identity modules -- elsewhere the
#: name belongs to the GPU backend record, which is unrelated.
_DISPLAY_FIELDS: tuple[str, ...] = ("display",)
_IDENTITY_ONLY_FIELDS: tuple[str, ...] = ("backend_name",)
_IDENTITY_MODULES = {
    Path("core/model_identity.py"),
    Path("core/model_inventory.py"),
}


def _runtime_modules() -> list[tuple[Path, ast.Module]]:
    modules: list[tuple[Path, ast.Module]] = []
    for folder in _SCAN_DIRS:
        for path in sorted((_ROOT / folder).rglob("*.py")):
            relative = path.relative_to(_ROOT)
            if relative in _ALLOWLIST or relative.parts[0] in {"tests", "scripts"}:
                continue
            if relative.as_posix().startswith("core/model_display"):
                continue
            modules.append(
                (relative, ast.parse(path.read_text(encoding="utf-8"), filename=str(relative)))
            )
    return modules


def _compared_attribute_names(node: ast.Compare) -> set[str]:
    """Attribute names appearing as operands, seeing through ``.casefold()``."""
    names: set[str] = set()
    for operand in (node.left, *node.comparators):
        expression: ast.expr = operand
        # ``record.display.casefold()`` and ``str(record.display).casefold()``
        # are the same inversion as a bare ``record.display``.
        while isinstance(expression, ast.Call):
            if isinstance(expression.func, ast.Attribute):
                expression = expression.func.value
            elif expression.args:
                expression = expression.args[0]
            else:
                break
        if isinstance(expression, ast.Attribute):
            names.add(expression.attr)
    return names


class NoRuntimeDisplayInversionTests(unittest.TestCase):
    def test_runtime_modules_do_not_import_display_to_basename_helpers(self) -> None:
        violations: list[str] = []
        for relative, tree in _runtime_modules():
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name in _FORBIDDEN:
                            violations.append(f"{relative}:{node.lineno}:{alias.name}")
        self.assertEqual(violations, [], "\n".join(violations))

    def test_runtime_modules_do_not_call_display_to_basename_helpers(self) -> None:
        """``model_display.resolve_vr_model_basename(...)`` dodges the import guard."""
        violations: list[str] = []
        for relative, tree in _runtime_modules():
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN:
                    violations.append(f"{relative}:{node.lineno}:{node.attr}")
        self.assertEqual(violations, [], "\n".join(violations))

    def test_identity_resolution_does_not_compare_presentation_fields(self) -> None:
        violations: list[str] = []
        for relative, tree in _runtime_modules():
            forbidden = set(_DISPLAY_FIELDS)
            if relative in _IDENTITY_MODULES:
                forbidden.update(_IDENTITY_ONLY_FIELDS)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                for name in sorted(_compared_attribute_names(node) & forbidden):
                    violations.append(f"{relative}:{node.lineno}:{name}")
        self.assertEqual(violations, [], "\n".join(violations))


if __name__ == "__main__":  # pragma: no cover - manual runs
    unittest.main()
