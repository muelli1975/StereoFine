"""Displayed measurements and batch status must belong to the finished image."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from stereofine.batch import BatchRunOptions, run_batch
from stereofine.inputs import master_to_uint8
from stereofine.processing import BatchProgress, ProcessingDefaults, ProcessingOptions, process_source
from stereofine.render import render_final_pair
from stereofine.session import browse_source
from stereofine.state import PairState
from stereofine.status import build_status_sections
from stereofine.worker import CancellationToken, JobCancelled
from tests.test_foundation import _import_gui_without_customtkinter_runtime
from tests import test_restart_alignment as fixtures


def measurement(low, high, *, uncertain=False):
    return dict(ready=True, low_edge_permille=low, high_edge_permille=high,
                deviation_permille=high-low, traffic='green',
                status='uncertain' if uncertain else 'ok',
                uncertain_reasons=['near_control_unconfirmed'] if uncertain else [])


class FinalCropStatusTests(unittest.TestCase):
    def test_initial_analysis_reports_only_final_crop_and_its_confidence(self):
        for aspect, uncertain in [('1:1', False), ('16:9', True)]:
            with self.subTest(aspect=aspect), tempfile.TemporaryDirectory() as td:
                source = fixtures.RestartAlignmentTests().source(Path(td))
                baseline = measurement(4., 24., uncertain=not uncertain)
                final = measurement(-35., -5., uncertain=uncertain)
                with patch('stereofine.processing.analyze_horizontal_disparity',
                           side_effect=[baseline, final]) as analyze:
                    item = process_source(source, ProcessingOptions(keep_loaded_pair=True,
                        defaults=ProcessingDefaults(aspect=aspect, color_enabled=False)))
                self.assertEqual(analyze.call_count, 2)
                left, right, _ = render_final_pair(item.loaded_pair, item.state,
                    apply_color=False, apply_floating_window=False)
                np.testing.assert_array_equal(analyze.call_args.args[0], master_to_uint8(left))
                np.testing.assert_array_equal(analyze.call_args.args[1], master_to_uint8(right))
                self.assertEqual(item.state.disparity.reference_width_px, left.shape[1])
                self.assertTrue(item.state.disparity.basis['rendered_pair'])
                self.assertEqual(item.state.disparity.total_permille, 30.)
                self.assertEqual(item.state.disparity.uncertain, uncertain)
                self.assertEqual(item.state.current_scene_positions_permille(), (-5., 35.))
                # Final confidence never feeds back into automatic placement.
                baseline_width = analyze.call_args_list[0].args[0].shape[1]
                expected_shift = int(np.ceil((24.+3.) * baseline_width / 1000.))
                self.assertEqual(item.state.auto_offset_x_px, expected_shift)
                with patch('stereofine.processing.analyze_horizontal_disparity',
                           side_effect=AssertionError('Unexpected repeated measurement')):
                    cached = process_source(source)
                self.assertTrue(cached.disparity_from_cache)

    def legacy_source(self, root):
        source = fixtures.RestartAlignmentTests().source(root)
        with patch('stereofine.processing.analyze_horizontal_disparity',
                   side_effect=[measurement(4., 24.), measurement(-24., -4.)]):
            process_source(source)
        payload = json.loads(source.sidecar_path.read_text())
        for key in ('rendered_pair', 'offset_x_px', 'offset_y_px'):
            payload['disparity']['basis'].pop(key, None)
        payload['disparity']['reference_width_px'] = None
        payload['manual'].update(delta_x_px=7, delta_y_px=-2)
        payload['framing'].update(aspect='1:1', crop_zoom_index=3,
                                  pan_x_permille=210, pan_y_permille=-130)
        payload['favorite'] = True
        payload['floating_window']['right_permille'] = 4
        source.sidecar_path.write_text(json.dumps(payload))
        return source

    def test_legacy_measurement_is_refreshed_without_reframing_or_losing_edits(self):
        with tempfile.TemporaryDirectory() as td:
            source = self.legacy_source(Path(td))
            before = browse_source(source)
            self.assertTrue(before.state.disparity.stale)
            self.assertFalse(before.state.disparity.valid)
            reset = deepcopy(before.state)
            reset.disparity.basis.update(aspect=reset.framing.aspect,
                crop_zoom_index=0, pan_x_permille=0, pan_y_permille=0)
            reset.reset_manual_to_auto()
            self.assertTrue(reset.disparity.stale)
            self.assertFalse(reset.disparity.valid)
            edits = (asdict(before.state.framing), asdict(before.state.manual),
                     asdict(before.state.floating_window), before.state.favorite)
            expected = render_final_pair(before.loaded_pair, deepcopy(before.state),
                apply_color=False, apply_floating_window=False)[:2]
            with patch('stereofine.processing.analyze_horizontal_disparity',
                       return_value=measurement(-30., -3.)) as analyze:
                item = process_source(source)
            self.assertTrue(item.alignment_from_cache)
            self.assertEqual(analyze.call_count, 1)
            for actual, pixels in zip(analyze.call_args.args[:2], expected):
                np.testing.assert_array_equal(actual, master_to_uint8(pixels))
            self.assertEqual(edits, (asdict(item.state.framing), asdict(item.state.manual),
                asdict(item.state.floating_window), item.state.favorite))
            reopened = browse_source(source)
            self.assertTrue(reopened.state.disparity.valid)
            self.assertFalse(reopened.state.disparity.stale)

    def test_cancel_during_final_measurement_keeps_saved_adjustments(self):
        with tempfile.TemporaryDirectory() as td:
            source = self.legacy_source(Path(td))
            before = source.sidecar_path.read_bytes()
            token = CancellationToken()
            calls = []
            def analyze(*args):
                calls.append(args)
                if len(calls) == 2:
                    token.cancel()
                return measurement(4., 24.)
            with patch('stereofine.processing.analyze_horizontal_disparity', side_effect=analyze):
                with self.assertRaises(JobCancelled):
                    process_source(source, ProcessingOptions(restart_alignment=True), cancellation=token)
            self.assertEqual(len(calls), 2)
            self.assertEqual(source.sidecar_path.read_bytes(), before)

    def test_batch_status_uses_progress_snapshot_and_clears_previous_warning(self):
        gui = _import_gui_without_customtkinter_runtime()
        app = object.__new__(gui.StereoFineApp)
        old, new = PairState(), PairState()
        old.disparity.valid = old.disparity.uncertain = True
        new.disparity.valid = True
        new.disparity.total_permille = 20.
        new.disparity.traffic = 'green'
        new.favorite = True
        app.current = SimpleNamespace(state=old)
        app.current_job_kind = 'batch'
        app._schedule_status_refresh = lambda *args: None
        app._handle_progress(BatchProgress(2, 7, 'B.jpg', 'analysis'))
        self.assertFalse(app._status_state().disparity.valid)
        self.assertFalse(app._status_state().disparity.uncertain)
        app._handle_progress(BatchProgress(2, 7, 'B.jpg', 'measured', state=new))
        self.assertIs(app._status_state(), new)
        rows = build_status_sections(app._status_state(), input_text='B.jpg')[2].rows
        self.assertFalse(any(row.role == 'warning' for row in rows))
        self.assertEqual(app._traffic_color(), gui.TRAFFIC_GREEN)
        self.assertIs(app.current.state, old)
        app._handle_progress(BatchProgress(3, 7, 'C.jpg', 'analysis'))
        self.assertFalse(app._status_state().disparity.valid)
        app.current_job_kind = None
        self.assertIs(app._status_state(), old)

    def test_batch_progress_snapshot_does_not_share_mutable_worker_state(self):
        with tempfile.TemporaryDirectory() as td:
            source = fixtures.RestartAlignmentTests().source(Path(td))
            progress = []
            result = run_batch([source], BatchRunOptions(analysis_only=True), progress=progress.append)
            self.assertFalse(result.failed)
            snapshots = [event.state for event in progress if event.state is not None]
            self.assertTrue(snapshots)
            original = deepcopy(snapshots[0])
            result.items[0].processed.state.disparity.uncertain_reasons.append('later')
            result.items[0].processed.state.framing.aspect = '16:9'
            self.assertEqual(snapshots[0], original)


if __name__ == '__main__':
    unittest.main()
