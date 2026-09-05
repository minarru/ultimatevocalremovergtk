"""Import ordering and facade compatibility during lint cleanup."""

import importlib
import subprocess
import sys
import unittest


class InitializationTests(unittest.TestCase):
    def test_gui_normalizes_logging_before_loading_application(self) -> None:
        script = '''
import builtins
import sys
from types import ModuleType
from unittest.mock import patch

import ui.__main__ as entry
assert "ui.application" not in sys.modules
normalized = False

def normalize():
    global normalized
    normalized = True

original_import = builtins.__import__
application = ModuleType("ui.application")
application.main = lambda: 17

def guarded_import(name, *args, **kwargs):
    if name == "application":
        assert normalized, "application imported before logging normalization"
        return application
    return original_import(name, *args, **kwargs)

with patch.object(entry, "normalize_g_messages_debug_env", normalize):
    with patch("builtins.__import__", guarded_import):
        assert entry.main() == 17
'''
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_constants_facade_preserves_legacy_exports(self) -> None:
        from bundled import constants

        expected = {}
        for name in ("platform_info", "urls", "formats", "stems", "process", "messages", "defaults"):
            module = importlib.import_module(f"bundled.constants.{name}")
            expected.update({key: value for key, value in vars(module).items() if not key.startswith("_")})
        for name, value in expected.items():
            with self.subTest(name=name):
                self.assertIs(getattr(constants, name), value)

    def test_method_views_preserve_registration_order(self) -> None:
        script = "from ui.views import METHOD_VIEWS; assert [view.__module__ for view in METHOD_VIEWS[:3]] == ['ui.views.vr', 'ui.views.mdx', 'ui.views.demucs']"
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
