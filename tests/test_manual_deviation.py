"""Manual nudges retain the measured range; actual crop changes still refresh it."""
from copy import deepcopy
from pathlib import Path
import json
import queue
import tempfile
import types
import unittest
from unittest.mock import patch

from stereofine.processing import (current_disparity_basis, disparity_basis_matches,
                                  process_source, refresh_current_disparity)
from stereofine.session import browse_source, save_browsed_state
from stereofine.state import PairState
from stereofine.worker import WorkerMessageKind
from tests.test_foundation import _import_gui_without_customtkinter_runtime
from tests import test_restart_alignment


def measured_state():
    state = PairState()
    state.alignment.valid = True
    state.framing.auto_near_offset_x_px = 30
    state.framing.auto_near_base_width_px = 1000
    d = state.disparity
    d.valid, d.stale, d.status = True, False, 'ok'
    d.low_edge_permille, d.high_edge_permille, d.total_permille = -23., -3., 20.
    d.basis = current_disparity_basis(state)
    d.reference_width_px = 1000
    d.diagnostics = dict(analysis_width=1000, scale=1.)
    return state


class ManualDeviationTests(unittest.TestCase):
    def app(self, state):
        gui = _import_gui_without_customtkinter_runtime()
        app = object.__new__(gui.StereoFineApp)
        app.current = types.SimpleNamespace(state=state)
        app.busy_state = 'idle'
        self.scheduled = []
        app._schedule_disparity_refresh = lambda: self.scheduled.append('measurement')
        app._schedule_state_save = lambda **kw: None
        app._refresh_preview = lambda: None
        app._schedule_status_refresh = lambda: None
        app._render_status = lambda: None
        return app

    def test_horizontal_and_vertical_nudges_retain_measurement_and_warning(self):
        state = measured_state()
        state.disparity.uncertain = True
        state.disparity.uncertain_reasons = ['near_control_unconfirmed']
        before = deepcopy(state.disparity)
        app = self.app(state)
        for dx, dy in [(1, 0), (10, 0), (-5, 0), (0, 1), (0, -10)]:
            app._adjust_manual_offset(dx, dy)
        self.assertEqual((state.manual.delta_x_px, state.manual.delta_y_px), (6, -9))
        self.assertEqual(state.disparity, before)
        self.assertEqual(self.scheduled, [])
        self.assertEqual(state.current_scene_positions_permille(), (-9., 29.))

    def test_legacy_rendered_measurement_uses_its_recorded_scale(self):
        state = measured_state()
        state.disparity.reference_width_px = None
        state.disparity.diagnostics = dict(analysis_width=1500, scale=.25)
        state.manual.delta_x_px = 12
        self.assertEqual(state.current_disparity_edges_permille(), (-25., -5.))
        state.manual.delta_x_px = -12
        self.assertEqual(state.current_disparity_edges_permille(), (-21., -1.))
        self.assertEqual(state.disparity.total_permille, 20.)

    def test_crop_zoom_and_pan_still_schedule_a_measurement(self):
        for action in ('zoom', 'pan'):
            with self.subTest(action=action):
                state = measured_state()
                app = self.app(state)
                if action == 'zoom':
                    app._adjust_crop_zoom(1)
                else:
                    app._adjust_framing_pan(20, -30)
                self.assertTrue(state.disparity.stale)
                self.assertEqual(self.scheduled, ['measurement'])

    def test_basis_ignores_only_manual_offsets(self):
        state = measured_state()
        original = current_disparity_basis(state)
        state.manual.delta_x_px, state.manual.delta_y_px = 10, -5
        self.assertTrue(disparity_basis_matches(original, current_disparity_basis(state)))
        for section, key, value in [('framing', 'aspect', '4:3'),
                                    ('framing', 'crop_zoom_index', 1),
                                    ('framing', 'pan_x_permille', 100),
                                    ('framing', 'pan_y_permille', -100),
                                    ('input_transform', 'swap_eyes', True)]:
            changed = deepcopy(state)
            setattr(getattr(changed, section), key, value)
            self.assertFalse(disparity_basis_matches(original, current_disparity_basis(changed)))
        changed = deepcopy(state)
        changed.alignment.correction = dict(vertical_shift_px=1.)
        self.assertFalse(disparity_basis_matches(original, current_disparity_basis(changed)))

    def test_in_flight_crop_result_is_accepted_after_manual_nudge(self):
        state = measured_state()
        app = self.app(state)
        app._measurement_basis = current_disparity_basis(state)
        app._measurement_job_id = 7
        app._measurement_session = app.current
        result = deepcopy(state.disparity)
        state.disparity.invalidate()
        app._adjust_manual_offset(10, 0)
        app.measurement_worker = types.SimpleNamespace(messages=queue.Queue())
        app.measurement_worker.messages.put(types.SimpleNamespace(
            job_id=7, kind=WorkerMessageKind.RESULT, payload=result))
        app._poll_disparity_refresh()
        self.assertTrue(state.disparity.valid)
        self.assertFalse(state.disparity.stale)
        self.assertIsNone(app._measurement_job_id)
        self.assertEqual(state.current_scene_positions_permille(), (-13., 33.))

    def test_ctrl_r_retains_measurement_unless_it_changes_the_measured_crop(self):
        state = measured_state()
        state.manual.delta_x_px, state.manual.delta_y_px = 10, 5
        state.reset_manual_to_auto()
        self.assertFalse(state.disparity.stale)
        self.assertEqual(state.current_scene_positions_permille(), (-3., 23.))
        state.framing.crop_zoom_index = 2
        state.disparity.basis = current_disparity_basis(state)
        state.reset_manual_to_auto()
        self.assertTrue(state.disparity.stale)

    def test_saved_manual_nudges_reuse_the_measured_crop_on_reopen_and_processing(self):
        with tempfile.TemporaryDirectory() as td:
            source = test_restart_alignment.RestartAlignmentTests().source(Path(td))
            process_source(source)
            session = browse_source(source)
            session.state.framing.crop_zoom_index = 1
            refresh_current_disparity(session.loaded_pair, session.state)
            before = deepcopy(session.state.disparity)
            # Large transient diagnostics are intentionally not written to sidecars.
            before.diagnostics = {}
            app = self.app(session.state)
            app._adjust_manual_offset(10, -2)
            save_browsed_state(session)
            reopened = browse_source(source)
            self.assertEqual(reopened.state.disparity, before)
            self.assertEqual(reopened.state.current_scene_positions_permille(),
                             session.state.current_scene_positions_permille())
            legacy = json.loads(source.sidecar_path.read_text(encoding='utf-8'))
            legacy['disparity'].pop('reference_width_px')
            source.sidecar_path.write_text(json.dumps(legacy), encoding='utf-8')
            with patch('stereofine.processing.analyze_horizontal_disparity',
                       side_effect=AssertionError('Legacy width recovery started a measurement')):
                migrated = browse_source(source)
            self.assertEqual(migrated.state.disparity.reference_width_px, before.reference_width_px)
            self.assertEqual(migrated.state.current_scene_positions_permille(),
                             session.state.current_scene_positions_permille())
            save_browsed_state(migrated)
            with patch('stereofine.processing.analyze_horizontal_disparity',
                       side_effect=AssertionError('Manual nudge started a new measurement')):
                saved = process_source(source)
            self.assertTrue(saved.disparity_from_cache)
            self.assertEqual(saved.state.disparity, before)
            # A real crop change still runs the analysis, using the same source.
            reopened.state.framing.crop_zoom_index = 2
            reopened.state.invalidate_disparity_for_framing()
            save_browsed_state(reopened)
            with patch('stereofine.processing.analyze_horizontal_disparity',
                       side_effect=RuntimeError('Expected crop measurement')) as analyze:
                with self.assertRaisesRegex(RuntimeError, 'Expected crop measurement'):
                    process_source(source)
            self.assertEqual(analyze.call_count, 1)


if __name__ == '__main__':
    unittest.main()
