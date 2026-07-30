import ast
from pathlib import Path
import unittest


_ROOT = Path(__file__).resolve().parents[1]
_ALLOWLIST = {
    Path("core/settings/coerce.py"),
    Path("core/settings/flat_map.py"),
    Path("core/settings/io.py"),
    Path("core/settings/model.py"),
}


def _is_settings_receiver(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "settings"
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "settings"
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


class NoCoreFlatSettingsTests(unittest.TestCase):
    def test_production_core_does_not_call_flat_string_settings_accessors(self):
        violations: list[str] = []
        for path in sorted((_ROOT / "core").rglob("*.py")):
            relative = path.relative_to(_ROOT)
            if relative in _ALLOWLIST:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr in {"get", "set"}
                    and _is_settings_receiver(func.value)
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    violations.append(
                        f"{relative}:{node.lineno}: settings.{func.attr}"
                    )
        self.assertEqual(violations, [], "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
