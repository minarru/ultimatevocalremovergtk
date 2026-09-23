"""Numerical contracts for reference scoring; fixtures have known error energy."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf


class ScoringMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audio = np.tile(np.array([[0.25, 0.5], [-0.25, -0.5]]), (4000, 1))

    def write(self, name: str, audio: Any, rate: int = 8000):
        path = self.root / name
        sf.write(path, audio, rate, subtype='FLOAT')
        return path

    def score(self, estimate: Any):
        from core.scoring.metrics import score_pair

        return score_pair(self.write('ref.wav', self.audio), self.write('est.wav', estimate))

    def test_identity_and_gain_have_distinct_metrics(self):
        identity = self.score(self.audio)
        self.assertEqual(identity['waveform_sdr']['status'], 'positive_infinity')
        gain = self.score(self.audio * 0.5)
        self.assertAlmostEqual(gain['waveform_sdr']['value'], 6.020599913, places=6)
        self.assertEqual(gain['si_sdr']['status'], 'positive_infinity')

    def test_stereo_projection_is_shared_and_channels_are_not_swapped(self):
        scaled = self.audio.copy()
        scaled[:, 0] *= 0.5
        result = self.score(scaled)
        self.assertEqual(result['si_sdr']['status'], 'finite')
        self.assertLess(result['si_sdr']['value'], 20)
        self.assertLess(self.score(self.audio[:, ::-1])['waveform_sdr']['value'], 10)

    def test_interference_noise_and_delay_worsen_reconstruction(self):
        rng = np.random.default_rng(27)
        x = rng.normal(0, 0.1, (16000, 2))
        self.audio = x
        low = self.score(x + rng.normal(0, 0.001, x.shape))
        high = self.score(x + rng.normal(0, 0.03, x.shape))
        self.assertGreater(low['waveform_sdr']['value'], high['waveform_sdr']['value'] + 20)
        self.assertLess(self.score(np.roll(x, 1, axis=0))['waveform_sdr']['value'], 0)

    def test_silent_reference_reports_residual_not_success(self):
        self.audio = np.zeros((8000, 2))
        result = self.score(np.full((8000, 2), 0.01))
        self.assertEqual(result['waveform_sdr']['status'], 'silent_reference')
        self.assertIsNone(result['waveform_sdr']['value'])
        self.assertAlmostEqual(result['silent_target']['output_rms_dbfs']['value'], -40, places=5)
        self.assertEqual(result['silent_target']['windows'], 1)

    def test_strict_audio_validation(self):
        from core.scoring.metrics import score_pair

        ref = self.write('ref.wav', self.audio)
        for name, audio, rate in (
            ('rate.wav', self.audio, 16000),
            ('length.wav', self.audio[:-1], 8000),
            ('mono.wav', self.audio[:, 0], 8000),
            ('empty.wav', self.audio[:0], 8000),
            ('nan.wav', self.audio * np.nan, 8000),
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                score_pair(ref, self.write(name, audio, rate))
        bad = self.root / 'invalid.wav'
        bad.write_text('invalid')
        with self.assertRaises(ValueError):
            score_pair(ref, bad)


class BssScoringTests(unittest.TestCase):
    def test_missing_or_silent_sources_are_explicitly_unavailable(self):
        from core.scoring.bss import score_bss

        self.assertEqual(score_bss({}, {}, 'pair')['status'], 'incomplete_group')

    def test_adapter_matches_museval_on_stereo_noise_and_interference(self):
        import importlib.util

        if importlib.util.find_spec('museval') is None:
            self.skipTest('optional museval not installed')
        bss_eval = importlib.import_module('museval.metrics').bss_eval
        from threadpoolctl import threadpool_limits

        from core.scoring.bss import score_bss

        rng = np.random.default_rng(41)
        ref = rng.normal(0, 0.1, (2, 2048, 2))
        est = ref + ref[::-1] * 0.1 + rng.normal(0, 0.002, ref.shape)
        with tempfile.TemporaryDirectory() as td, threadpool_limits(limits=1):
            root = Path(td)
            references, estimates = {}, {}
            for i, stem in enumerate(('vocals', 'instrumental')):
                references[stem], estimates[stem] = root / f'r{i}.wav', root / f'e{i}.wav'
                sf.write(references[stem], ref[i], 1024, subtype='DOUBLE')
                sf.write(estimates[stem], est[i], 1024, subtype='DOUBLE')
            actual = score_bss(references, estimates, 'pair')
            direct = bss_eval(
                ref,
                est,
                window=1024,
                hop=1024,
                filters_len=512,
                compute_permutation=False,
                framewise_filters=False,
                bsseval_sources_version=False,
            )
            self.assertEqual(actual['status'], 'success')
            for i, stem in enumerate(('vocals', 'instrumental')):
                for j, name in enumerate(('bss_sdr', 'bss_isr', 'bss_sir', 'bss_sar')):
                    np.testing.assert_allclose(
                        [x['value'] for x in actual['stems'][stem][name]['windows']], direct[j][i]
                    )
            sf.write(estimates['vocals'], np.zeros((2048, 2)), 1024, subtype='FLOAT')
            self.assertEqual(score_bss(references, estimates, 'pair')['status'], 'silent_estimate')


class ScoringPreparationTests(unittest.TestCase):
    def test_shared_gain_mapping_backing_vocals_and_source_assignment(self):
        import json

        from core.scoring.prepare import prepare_dataset

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            categories = ['vocals', 'vocals', 'bass', 'drums', 'percussion', 'piano', 'guitar']
            sources = []
            for i, stem in enumerate(categories):
                sf.write(root / f'{i}.wav', np.full((80, 2), (i + 1) / 10), 8000, subtype='FLOAT')
                sources.append({'stem': stem, 'path': f'{i}.wav'})
            source = root / 'source.json'
            source.write_text(
                json.dumps(
                    {
                        'kind': 'uvr.score.sources',
                        'schema_version': 1,
                        'songs': [{'id': 'layered', 'split': 'holdout', 'sources': sources}],
                    }
                )
            )
            report = prepare_dataset(source, root / 'out')
            self.assertTrue(report['ok'], report)
            dataset = json.loads((root / 'out/dataset.json').read_text())
            song = dataset['songs'][0]
            self.assertEqual(song['split'], 'holdout')
            self.assertLess(song['gain'], 1)
            self.assertEqual(len(song['sources']), len(categories))
            for stem, expected in {'vocals': 0.3, 'bass': 0.3, 'drums': 0.9, 'other': 1.3}.items():
                audio, _ = sf.read(root / 'out' / song['groups']['four'][stem]['path'])
                np.testing.assert_allclose(audio, expected * song['gain'], atol=1e-7)
                self.assertLessEqual(np.max(np.abs(audio)), 0.99)
            mixture, _ = sf.read(root / 'out' / song['mixture']['path'])
            self.assertLessEqual(np.max(np.abs(mixture)), 0.99)

    def test_unequal_source_lengths_fail_without_partial_song(self):
        import json

        from core.scoring.prepare import prepare_dataset

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for i in range(2):
                sf.write(root / f'{i}.wav', np.ones((80 + i, 2)) * 0.1, 8000, subtype='FLOAT')
            source = root / 'source.json'
            source.write_text(
                json.dumps(
                    {
                        'kind': 'uvr.score.sources',
                        'schema_version': 1,
                        'songs': [
                            {
                                'id': 'bad',
                                'sources': [
                                    {'stem': 'vocals', 'path': '0.wav'},
                                    {'stem': 'piano', 'path': '1.wav'},
                                ],
                            }
                        ],
                    }
                )
            )
            report = prepare_dataset(source, root / 'out')
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['songs'], 0)
            self.assertIn('frames mismatch', report['errors'][0]['error'])
            self.assertEqual([p.name for p in (root / 'out').iterdir()], ['dataset.json'])

    def test_converted_moises_import_preserves_splits_and_track_identity(self):
        import json

        from core.scoring.prepare import load_sources

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'manifest.json'
            document = {
                'verified_tracks': 16,
                'archive_sha256': 'archive',
                'songs': [],
                'tracks': [],
            }
            for i in range(16):
                split = 'core' if i < 12 else 'holdout'
                document['songs'].append({'id': str(i), 'group': split, 'song': f'Song {i}'})
                document['tracks'].append(
                    {
                        'song_id': str(i),
                        'stem': 'vocals',
                        'track_id': f'track-{i}',
                        'path': f'{i}.flac',
                    }
                )
            path.write_text(json.dumps(document))
            songs = load_sources(path)
            self.assertEqual(sum(s['split'] == 'core' for s in songs), 12)
            self.assertEqual(sum(s['split'] == 'holdout' for s in songs), 4)
            self.assertEqual(songs[-1]['sources'][0]['track_id'], 'track-15')


class ScoreComparisonTests(unittest.TestCase):
    def test_paired_changes_coverage_splits_and_reference_guard(self):
        import copy

        from core.scoring.common import metric, write_json
        from core.scoring.evaluate import new_report, scoring_protocol
        from core.scoring.reports import compare_reports

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = {'id': 'm', 'label': 'Model', 'kind': 'model'}
            left = new_report(scoring_protocol('basic'), [candidate])
            for i, split in enumerate(('core', 'core', 'core', 'holdout')):
                left['rows'].append(
                    {
                        'candidate': candidate,
                        'song_id': str(i),
                        'split': split,
                        'group': 'pair',
                        'stem': 'vocals',
                        'reference_identity': str(i),
                        'audio': {'frames': 10, 'channels': 2, 'sample_rate': 8000},
                        'metrics': {'waveform_sdr': metric(10.0)},
                    }
                )
            right = copy.deepcopy(left)
            for i, delta in enumerate((1, -2, 0, 10)):
                right['rows'][i]['metrics']['waveform_sdr'] = metric(10 + delta)
            write_json(root / 'a.json', left)
            write_json(root / 'b.json', right)
            result = compare_reports(root / 'a.json', root / 'b.json')
            core, holdout = result['summary']
            self.assertEqual(
                (core['wins'], core['losses'], core['ties'], core['median_delta']), (1, 1, 1, 0)
            )
            self.assertEqual(holdout['median_delta'], 10)
            right['rows'].pop()
            write_json(root / 'b.json', right)
            self.assertEqual(
                len(compare_reports(root / 'a.json', root / 'b.json')['coverage']['only_a']), 1
            )
            right['rows'][0]['reference_identity'] = 'different'
            write_json(root / 'b.json', right)
            with self.assertRaisesRegex(ValueError, 'References'):
                compare_reports(root / 'a.json', root / 'b.json')


class ScoringEdgeTests(unittest.TestCase):
    def test_orthogonal_interference_and_dc_offset_have_expected_ratios(self):
        from core.scoring.metrics import score_pair

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            x = np.tile([[0.125, 0.25], [0.125, 0.25], [-0.125, -0.25], [-0.125, -0.25]], (2000, 1))
            z = np.tile([[0.125, 0.25], [-0.125, -0.25], [0.125, 0.25], [-0.125, -0.25]], (2000, 1))
            sf.write(root / 'r.wav', x, 8000, subtype='DOUBLE')
            sf.write(root / 'e.wav', x + 0.1 * z, 8000, subtype='DOUBLE')
            result = score_pair(root / 'r.wav', root / 'e.wav')
            self.assertAlmostEqual(result['waveform_sdr']['value'], 20, places=10)
            self.assertAlmostEqual(result['si_sdr']['value'], 20, places=10)
            sf.write(root / 'e.wav', x + 0.125, 8000, subtype='DOUBLE')
            result = score_pair(root / 'r.wav', root / 'e.wav')
            self.assertEqual(result['si_sdr']['status'], 'positive_infinity')
            self.assertEqual(result['waveform_sdr']['status'], 'finite')
            sf.write(root / 'e.wav', z, 8000, subtype='DOUBLE')
            self.assertEqual(
                score_pair(root / 'r.wav', root / 'e.wav')['si_sdr']['status'], 'negative_infinity'
            )

    def test_silence_window_locations_and_partial_tail(self):
        from core.scoring.metrics import score_pair

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            x = np.concatenate([np.zeros((8000, 2)), np.ones((8000, 2)) * 0.1, np.zeros((4000, 2))])
            sf.write(root / 'r.wav', x, 8000, subtype='FLOAT')
            sf.write(root / 'e.wav', x + 0.001, 8000, subtype='FLOAT')
            result = score_pair(root / 'r.wav', root / 'e.wav')['silent_target']
            self.assertEqual(result['windows'], 2)
            self.assertEqual([r['start_seconds'] for r in result['window_results']], [0, 2])
            self.assertEqual(result['window_results'][-1]['duration_seconds'], 0.5)
            self.assertAlmostEqual(result['output_rms_dbfs']['value'], -60, places=5)

    def test_optional_dependency_error_is_actionable(self):
        from unittest.mock import patch

        from core.scoring.bss import require_backend

        with patch('core.scoring.bss.importlib.import_module', side_effect=ImportError):
            with self.assertRaisesRegex(ValueError, 'requirements-score.txt'):
                require_backend()

    def test_incomplete_bss_still_scores_available_audio_and_rejects_invalid_reference(self):
        import importlib.util

        from core.scoring.evaluate import score_files

        if importlib.util.find_spec('museval') is None:
            self.skipTest('optional museval not installed')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            x = np.tile([[0.125, 0.25], [-0.125, -0.25]], (4000, 1))
            sf.write(root / 'r.wav', x, 8000, subtype='FLOAT')
            result = score_files({'vocals': root / 'r.wav'}, {'vocals': root / 'r.wav'})
            self.assertTrue(result['ok'])
            self.assertEqual(result['rows'][0]['metrics']['bss_sdr']['status'], 'incomplete_group')
            sf.write(root / 'bad.wav', x * np.nan, 8000, subtype='FLOAT')
            result = score_files(
                {'vocals': root / 'r.wav', 'instrumental': root / 'bad.wav'},
                {'vocals': root / 'r.wav'},
                metrics='basic',
            )
            self.assertEqual(result['status'], 'failed')

    def test_preparation_interruption_keeps_first_song(self):
        import json

        from core.scoring.prepare import prepare_dataset

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sf.write(root / 'r.wav', np.ones((80, 2)) * 0.1, 8000, subtype='FLOAT')
            source = root / 'source.json'
            source.write_text(
                json.dumps(
                    {
                        'kind': 'uvr.score.sources',
                        'schema_version': 1,
                        'songs': [
                            {'id': str(i), 'sources': [{'stem': 'vocals', 'path': 'r.wav'}]}
                            for i in range(2)
                        ],
                    }
                )
            )

            def stop(phase: str, values: dict[str, Any]):
                if phase == 'reading_audio' and values['song_id'] == '1':
                    raise KeyboardInterrupt

            result = prepare_dataset(source, root / 'out', callback=stop)
            self.assertEqual(result['status'], 'stopped')
            saved = json.loads((root / 'out/dataset.json').read_text())
            self.assertEqual(len(saved['songs']), 1)
            self.assertTrue(saved['stopped'])
            self.assertEqual(len(list((root / 'out').glob('song-*'))), 1)

    def test_file_change_during_multipass_scoring_is_rejected(self):
        from unittest.mock import patch

        from core.scoring.metrics import paired_blocks, score_pair

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            x = np.tile([[0.125, 0.25], [-0.125, -0.25]], (4000, 1))
            for name in ('r.wav', 'e.wav'):
                sf.write(root / name, x, 8000, subtype='FLOAT')
            changed = False

            def blocks(reference: Path, estimate: Path, frames: int):
                nonlocal changed
                yield from paired_blocks(reference, estimate, frames)
                if not changed:
                    changed = True
                    sf.write(estimate, x * 0.5, 8000, subtype='FLOAT')

            with patch('core.scoring.metrics.paired_blocks', side_effect=blocks):
                with self.assertRaisesRegex(ValueError, 'changed during scoring'):
                    score_pair(root / 'r.wav', root / 'e.wav')

    def test_duplicate_json_keys_are_rejected(self):
        from core.scoring.common import read_json

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'duplicate.json'
            path.write_text('{"stems": {"vocals": "one.wav", "vocals": "two.wav"}}')
            with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
                read_json(path)
            path.write_text('{"value": 1e309}')
            with self.assertRaisesRegex(ValueError, 'Non-finite JSON number'):
                read_json(path)
