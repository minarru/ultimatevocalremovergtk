"""Scoring commands must operate on saved audio without model resolution."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from cli.main import main


class ScoreCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.x = np.tile([[0.25, -0.125], [-0.25, 0.125]], (4000, 1))
        for name, x in [('vocals', self.x), ('piano', self.x * 0.5), ('estimate', self.x * 0.5)]:
            sf.write(self.root / f'{name}.wav', x, 8000, subtype='FLOAT')

    def invoke(self, *args: Any):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main(['score', *map(str, args), '--report', 'json'])
        return code, json.loads(out.getvalue())

    def source_manifest(self):
        path = self.root / 'sources.json'
        path.write_text(
            json.dumps(
                {
                    'schema_version': 1,
                    'kind': 'uvr.score.sources',
                    'songs': [
                        {
                            'id': 'song1',
                            'title': 'Sparse',
                            'artist': 'Artist',
                            'split': 'core',
                            'sources': [
                                {'stem': 'vocals', 'path': 'vocals.wav'},
                                {'stem': 'piano', 'path': 'piano.wav'},
                            ],
                        }
                    ],
                }
            )
        )
        return path

    def test_files_prints_score_and_reports_missing_bss_group(self):
        code, result = self.invoke(
            'files',
            '--reference',
            f'vocals={self.root}/vocals.wav',
            '--estimate',
            f'vocals={self.root}/estimate.wav',
            '--metrics',
            'basic',
        )
        self.assertEqual(code, 0, result)
        self.assertAlmostEqual(
            result['rows'][0]['metrics']['waveform_sdr']['value'], 6.020599913, places=6
        )

    def test_prepare_retains_silence_and_reconstructs_both_groups(self):
        code, report = self.invoke(
            'prepare', '--sources', self.source_manifest(), '-o', self.root / 'prepared'
        )
        self.assertEqual(code, 0, report)
        dataset = json.loads(Path(report['dataset']).read_text())
        song = dataset['songs'][0]
        self.assertEqual(song['split'], 'core')
        self.assertTrue(song['groups']['four']['bass']['silent'])
        base = Path(report['dataset']).parent
        mixture, sr = sf.read(base / song['mixture']['path'])
        self.assertEqual(sr, 8000)
        for group in ('pair', 'four'):
            refs = [sf.read(base / r['path'])[0] for r in song['groups'][group].values()]
            np.testing.assert_allclose(sum(refs), mixture, atol=1e-7)
        code, _ = self.invoke(
            'prepare', '--sources', self.source_manifest(), '-o', self.root / 'prepared'
        )
        self.assertEqual(code, 2)

    def estimates(self, dataset_path: str | Path, *, broken: bool = False):
        d = json.loads(Path(dataset_path).read_text())
        base = Path(dataset_path).parent
        groups = d['songs'][0]['groups']
        estimates = {s: str(base / r['path']) for s, r in groups['pair'].items()}
        if broken:
            estimates['vocals'] = str(base / 'missing.wav')
        path = self.root / ('bad-estimates.json' if broken else 'estimates.json')
        path.write_text(
            json.dumps(
                {
                    'schema_version': 1,
                    'kind': 'uvr.score.estimates',
                    'candidates': [
                        {
                            'id': 'model-one',
                            'label': 'Model One',
                            'kind': 'model',
                            'estimates': [
                                {'song_id': 'song1', 'group': 'pair', 'stems': estimates}
                            ],
                        }
                    ],
                }
            )
        )
        return path

    def test_batch_reports_model_identity_and_compares_exact_pairs(self):
        _, prep = self.invoke(
            'prepare', '--sources', self.source_manifest(), '-o', self.root / 'prepared'
        )
        code, report = self.invoke(
            'run',
            '--dataset',
            prep['dataset'],
            '--estimates',
            self.estimates(prep['dataset']),
            '--metrics',
            'basic',
            '-o',
            self.root / 'scores',
        )
        self.assertEqual(code, 0, report)
        self.assertEqual(report['rows'][0]['candidate']['kind'], 'model')
        self.assertTrue((self.root / 'scores' / 'results.csv').exists())
        code, comparison = self.invoke(
            'compare', self.root / 'scores' / 'results.json', self.root / 'scores' / 'results.json'
        )
        self.assertEqual(code, 0, comparison)
        self.assertEqual(comparison['coverage']['matched'], 2)
        self.assertEqual(
            comparison['rows'][0]['metrics']['waveform_sdr']['status'], 'nonfinite_pair'
        )

    def test_invalid_estimate_has_runtime_failure_and_persistent_report(self):
        _, prep = self.invoke(
            'prepare', '--sources', self.source_manifest(), '-o', self.root / 'prepared'
        )
        code, report = self.invoke(
            'run',
            '--dataset',
            prep['dataset'],
            '--estimates',
            self.estimates(prep['dataset'], broken=True),
            '--metrics',
            'basic',
            '-o',
            self.root / 'scores',
        )
        self.assertEqual(code, 1, report)
        self.assertTrue((self.root / 'scores' / 'results.json').exists())
        self.assertEqual(len(report['errors']), 1)

    def test_human_and_jsonl_progress_are_readable_and_structured(self):
        args = [
            'score',
            'files',
            '--reference',
            f'vocals={self.root}/vocals.wav',
            '--estimate',
            f'vocals={self.root}/estimate.wav',
            '--metrics',
            'basic',
        ]
        for mode in ('human', 'jsonl'):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(main([*args, '--report', mode]), 0)
            if mode == 'human':
                self.assertIn('waveform_sdr=6.021', out.getvalue())
            else:
                events = [json.loads(line) for line in out.getvalue().splitlines()]
                self.assertEqual(events[-1]['event'], 'finished')
                self.assertTrue(any(e.get('metric_stage') == 'basic' for e in events))

    def test_compare_human_and_protocol_mismatch(self):
        _, report = self.invoke(
            'files',
            '--reference',
            f'vocals={self.root}/vocals.wav',
            '--estimate',
            f'vocals={self.root}/estimate.wav',
            '--metrics',
            'basic',
            '-o',
            self.root / 'score',
        )
        result = Path(report['results_path'])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['score', 'compare', str(result), str(result)]), 0)
        self.assertIn('median_delta', out.getvalue())
        document = json.loads(result.read_text())
        document['protocol']['version'] = 999
        other = self.root / 'other.json'
        other.write_text(json.dumps(document))
        code, _ = self.invoke('compare', result, other)
        self.assertEqual(code, 2)

    def test_interrupted_batch_preserves_completed_group_and_signal_handler(self):
        import signal
        from unittest.mock import patch

        from core.scoring.evaluate import score_group

        _, prep = self.invoke(
            'prepare', '--sources', self.source_manifest(), '-o', self.root / 'prepared'
        )
        estimates = self.estimates(prep['dataset'])
        data = json.loads(estimates.read_text())
        second = {**data['candidates'][0], 'id': 'ensemble-two', 'kind': 'ensemble'}
        data['candidates'].append(second)
        estimates.write_text(json.dumps(data))
        previous = signal.getsignal(signal.SIGTERM)
        calls = 0

        def interrupt(*args: Any, **kwargs: Any):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt
            return score_group(*args, **kwargs)

        with patch('core.scoring.evaluate.score_group', side_effect=interrupt):
            code, report = self.invoke(
                'run',
                '--dataset',
                prep['dataset'],
                '--estimates',
                estimates,
                '--metrics',
                'basic',
                '-o',
                self.root / 'scores',
            )
        self.assertEqual(code, 130)
        self.assertTrue(report['stopped'])
        saved = json.loads((self.root / 'scores/results.json').read_text())
        self.assertEqual(len(saved['rows']), 2)
        self.assertTrue(saved['stopped'])
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    def test_duplicate_and_malformed_manifests_are_usage_errors(self):
        source = self.source_manifest()
        data = json.loads(source.read_text())
        data['songs'][0]['sources'].append(data['songs'][0]['sources'][0])
        source.write_text(json.dumps(data))
        code, _ = self.invoke('prepare', '--sources', source, '-o', self.root / 'out')
        self.assertEqual(code, 2)
        bad = self.root / 'bad.json'
        bad.write_text(json.dumps({'schema_version': 1, 'kind': 'uvr.score.results'}))
        code, _ = self.invoke('compare', bad, bad)
        self.assertEqual(code, 2)

    def test_partial_failure_and_run_collision_keep_existing_report(self):
        _, prep = self.invoke(
            'prepare', '--sources', self.source_manifest(), '-o', self.root / 'prepared'
        )
        estimates = self.estimates(prep['dataset'])
        data = json.loads(estimates.read_text())
        import copy

        bad = copy.deepcopy(data['candidates'][0])
        bad.update(id='broken', kind='ensemble')
        bad['estimates'][0]['stems']['vocals'] = 'missing.wav'
        data['candidates'].append(bad)
        estimates.write_text(json.dumps(data))
        args = (
            'run',
            '--dataset',
            prep['dataset'],
            '--estimates',
            estimates,
            '--metrics',
            'basic',
            '-o',
            self.root / 'scores',
        )
        code, report = self.invoke(*args)
        self.assertEqual(code, 3, report)
        self.assertEqual(len(report['rows']), 2)
        saved = (self.root / 'scores/results.json').read_bytes()
        code, _ = self.invoke(*args)
        self.assertEqual(code, 2)
        self.assertEqual((self.root / 'scores/results.json').read_bytes(), saved)

    def test_batch_verifies_reference_hash_before_scoring(self):
        _, prep = self.invoke(
            'prepare', '--sources', self.source_manifest(), '-o', self.root / 'prepared'
        )
        estimates = self.estimates(prep['dataset'])
        data = json.loads(Path(prep['dataset']).read_text())
        path = Path(prep['dataset']).parent / data['songs'][0]['groups']['pair']['vocals']['path']
        sf.write(path, self.x * 0.9, 8000, subtype='FLOAT')
        code, report = self.invoke(
            'run',
            '--dataset',
            prep['dataset'],
            '--estimates',
            estimates,
            '--metrics',
            'basic',
            '-o',
            self.root / 'scores',
        )
        self.assertEqual(code, 1)
        self.assertIn('hash mismatch', report['errors'][0]['error'])

    def test_quiet_jsonl_has_only_final_result(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main(
                [
                    'score',
                    'files',
                    '--reference',
                    f'vocals={self.root}/vocals.wav',
                    '--estimate',
                    f'vocals={self.root}/estimate.wav',
                    '--metrics',
                    'basic',
                    '--quiet',
                    '--report',
                    'jsonl',
                ]
            )
        self.assertEqual(code, 0)
        events = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([e['event'] for e in events], ['finished'])
