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
_SKIP_PREFIXES = (
    Path("core/model_display.py"),
    Path("tests"),
    Path("scripts"),
)


class NoRuntimeDisplayInversionTests(unittest.TestCase):
    def test_runtime_modules_do_not_import_display_to_basename_helpers(self) -> None:
        violations: list[str] = []
        for folder in _SCAN_DIRS:
            for path in sorted((_ROOT / folder).rglob("*.py")):
                relative = path.relative_to(_ROOT)
                if relative in _ALLOWLIST or relative.parts[0] in {"tests", "scripts"}:
                    continue
                if relative.as_posix().startswith("core/model_display"):
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        for alias in node.names:
                            if alias.name in _FORBIDDEN:
                                violations.append(f"{relative}:{node.lineno}:{alias.name}")
        self.assertEqual(violations, [], "\n".join(violations))
