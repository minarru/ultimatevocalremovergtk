import unittest

from ui.run_progress import RunProgressPresenter


class ProgressPresentationTests(unittest.TestCase):
    def test_suspension_throttle_and_terminal(self):
        presenter = RunProgressPresenter()
        presenter.reset(10.0)
        self.assertIsNone(presenter.update(0.4, 10.1, suspended=True))
        first = presenter.update(0.4, 10.1)
        assert first is not None
        self.assertEqual(first.fraction, 0.4)
        self.assertIsNone(presenter.update(0.5, 10.11))
        last = presenter.update(0.999, 10.12)
        assert last is not None
        self.assertEqual(last.fraction, 1.0)
        self.assertEqual(last.pulse, 'stop')

    def test_loading_pulses_and_phase_change_forces_paint(self):
        presenter = RunProgressPresenter()
        presenter.reset(0)
        initial = presenter.update(0, 1, local_step=0)
        assert initial is not None
        self.assertEqual(initial.pulse, 'start')
        self.assertIsNotNone(
            presenter.update(0.2, 1.01, local_step=0.2, pass_index=1, pass_total=2)
        )

    def test_throttled_samples_still_update_eta_and_pass_change_forces_paint(self):
        from unittest.mock import patch

        presenter = RunProgressPresenter()
        presenter.reset(1)
        with patch.object(presenter.tracker, 'update', wraps=presenter.tracker.update) as update:
            presenter.update(0.2, 1.1, local_step=0.2, pass_index=1, pass_total=2)
            self.assertIsNone(
                presenter.update(0.21, 1.11, local_step=0.21, pass_index=1, pass_total=2)
            )
            self.assertEqual(update.call_count, 2)
            self.assertIsNotNone(
                presenter.update(0.3, 1.12, local_step=0.1, pass_index=2, pass_total=2)
            )
