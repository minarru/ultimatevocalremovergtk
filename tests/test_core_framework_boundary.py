"""Core imports and failure recording must work without a GUI installation."""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


class CoreFrameworkBoundaryTests(unittest.TestCase):
    def run_code(self, code: str) -> None:
        result = subprocess.run(
            [sys.executable, '-c', "import tests\n" + textwrap.dedent(code)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_domain_import_does_not_initialize_orchestration(self) -> None:
        self.run_code('''
            import sys
            import core.stem_roles
            forbidden = ('core.job_runner', 'core.audio_tools', 'core.job_plan', 'gi', 'torch', 'engines', 'cli')
            assert not [name for name in sys.modules if any(name == p or name.startswith(p + '.') for p in forbidden)]
        ''')

    def test_public_exports_keep_identity_and_submodule_imports(self) -> None:
        self.run_code('''
            import core
            from core import JobRunner, Settings, DATA_DIR, assemble_model, paths
            from core.job_runner import JobRunner as Runner
            from core.settings import Settings as SettingsClass
            from core.model_config import assemble_model as assemble
            assert JobRunner is Runner is core.JobRunner
            assert Settings is SettingsClass
            assert assemble_model is assemble
            assert DATA_DIR == paths.DATA_DIR
            assert len(core.__all__) == 54
            assert set(core.__all__) <= set(dir(core))
            namespace = {}
            exec('from core import *', namespace)
            assert all(namespace[name] is getattr(core, name) for name in core.__all__)
            try:
                core.not_a_public_name
            except AttributeError:
                pass
            else:
                raise AssertionError('unknown attribute accepted')
        ''')

    def test_core_has_no_ui_imports(self) -> None:
        violations = []
        for path in Path('core').rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or '']
                    if isinstance(node, ast.ImportFrom)
                    else []
                )
                if any(name == 'ui' or name.startswith('ui.') for name in names):
                    violations.append(f'{path}:{getattr(node, "lineno", 0)}')
        self.assertEqual(violations, [])

    def test_error_store_retains_record_without_gi(self) -> None:
        self.run_code('''
            import sys
            import tests  # arm the outbound network guard
            from importlib.abc import MetaPathFinder
            class NoGI(MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == 'gi' or fullname.startswith('gi.'):
                        raise ImportError('GI deliberately unavailable')
            sys.meta_path.insert(0, NoGI())
            from core.error_log import log_error, get_error_log
            assert 'gi' not in sys.modules
            formatted = log_error('download', RuntimeError('transfer failed'), context='test context')
            assert get_error_log() == formatted
            assert 'transfer failed' in formatted and 'test context' in formatted
        ''')

    def test_actual_download_and_sample_failures_record_without_gi(self) -> None:
        self.run_code('''
            import sys
            import tests
            from importlib.abc import MetaPathFinder
            from unittest.mock import Mock, patch
            class NoGI(MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == 'gi' or fullname.startswith('gi.'):
                        raise ImportError('no GI')
            sys.meta_path.insert(0, NoGI())
            from core.error_log import get_error_log, set_error_log
            from core.download_queue import DownloadQueue, DownloadQueueItem
            from core.job_runner import JobRunner
            from core.job_callbacks import JobCallbacks
            from core.settings import Settings
            manager = Mock()
            manager.download.side_effect = RuntimeError('transfer unavailable')
            queue = DownloadQueue(manager)
            item = DownloadQueueItem('test', 'chosen model', 'MDX-Net', 'test', [])
            assert not queue._process_item(item)
            assert item.status == 'failed'
            assert 'transfer unavailable' in get_error_log()
            set_error_log('')
            runner = JobRunner(Settings.defaults(), repo=Mock())
            def prepare(settings, paths, *, on_fallback):
                on_fallback(paths[0], RuntimeError('clip decode failed'))
                return paths
            with patch('core.job_runner.prepare_input_paths', side_effect=prepare):
                assert runner._prepare_paths_for_run(['song.wav'], JobCallbacks()) == ['song.wav']
            assert 'clip decode failed' in get_error_log()
            assert 'processing the full file' in get_error_log()
            assert not any(n == 'ui' or n.startswith('ui.') for n in sys.modules)
        ''')
