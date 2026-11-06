"""A file save must not replace the displayed view with a delayed render."""
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from stereofine.native_preview import native_key, prepare_native_preview
from stereofine.batch import BatchRunOptions, BatchRunResult, run_batch
from stereofine.geometry import apply_floating_window_masks
from stereofine.worker import CancellationToken, WorkerMessage, WorkerMessageKind
from tests import test_preview_stability
from tests.test_final_corrections import loaded_pair
from tests import test_restart_alignment
from stereofine.processing import ProcessingOptions, process_source
from stereofine.session import BrowsedSource, save_browsed_state
from stereofine.sidecar import load_sidecar
from stereofine.state import PairState


class SaveViewStabilityTests(unittest.TestCase):
    def test_geometry_identity_keeps_render_terms_and_ignores_analysis_diagnostics(self):
        state = PairState()
        state.alignment.valid = True
        state.alignment.correction = {
            'rotation_deg': .6, 'scale': 1.002, 'vertical_shift_px': 2.4,
            'vergence_ready': True, 'vergence_v_px': 1.2, 'vergence_h_px': .8,
            'trapez_apply': {'enabled': True,
                            'params': {'a_projective_x': .001, 'b_projective_y': .002}},
            'y_residual_apply': {'enabled': True, 'coefficients': [
                {'term': 'x2', 'coefficient_fullres_px': .25}]},
            'pipeline_basis': {'diagnostics': [1, 2, 3]},
        }
        session = SimpleNamespace(state=state)
        before = native_key(session)
        compact = PairState.from_sidecar(state.to_sidecar(source={}))
        session.state = compact
        self.assertEqual(native_key(session), before)
        edits = (
            lambda s: s.alignment.correction.__setitem__('rotation_deg', .7),
            lambda s: s.alignment.correction.__setitem__('scale', 1.003),
            lambda s: s.alignment.correction.__setitem__('vertical_shift_px', 2.5),
            lambda s: s.alignment.correction.__setitem__('vergence_v_px', 1.3),
            lambda s: s.alignment.correction.__setitem__('vergence_h_px', .9),
            lambda s: s.alignment.correction['trapez_apply']['params'].__setitem__('a_projective_x', .003),
            lambda s: s.alignment.correction['trapez_apply']['params'].__setitem__('b_projective_y', .003),
            lambda s: s.alignment.correction['y_residual_apply']['coefficients'][0].__setitem__(
                'coefficient_fullres_px', .3),
            lambda s: setattr(s.manual, 'delta_x_px', 1),
            lambda s: setattr(s.manual, 'delta_y_px', 1),
            lambda s: setattr(s.framing, 'pan_x_permille', 10),
            lambda s: setattr(s.framing, 'crop_zoom_index', 1),
            lambda s: setattr(s.input_transform, 'left_orientation', '90'),
        )
        for index, edit in enumerate(edits):
            with self.subTest(edit=index):
                session.state = deepcopy(compact)
                edit(session.state)
                self.assertNotEqual(native_key(session), before)

    def test_save_immediately_after_real_analysis_keeps_the_master_view(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = test_restart_alignment.RestartAlignmentTests().source(root)
            for path in (source.left_path, source.right_path):
                with Image.open(path) as image:
                    enlarged = image.resize((720, 480), Image.Resampling.BICUBIC)
                enlarged.save(path)
            processed = process_source(source, ProcessingOptions(keep_loaded_pair=True,
                                                                 restart_alignment=True))
            session = BrowsedSource(source, processed.loaded_pair, processed.source_stamp,
                                    processed.state, load_sidecar(source.sidecar_path))
            app = test_preview_stability.PreviewStabilityTests().app()
            app.current = session
            app._preview_bounds = lambda: (320, 230)
            app._preview_base = app._preview_base_session_id = None
            app._sync_vars_from_current = app._render_status = lambda: None
            requests, frames = [], []
            app._request_native_preview = lambda **kw: requests.append(True)
            def record():
                frames.append((app._preview_left_current.copy(), app._preview_right_current.copy()))
                app._preview_pil = Image.fromarray(app._preview_left_current)
            app._build_preview_anaglyph = record
            prepared = app._prepare_session_preview(session, (320, 230), CancellationToken())
            app._install_session_preview(prepared)
            app._render_session_preview(session)
            before_key = native_key(session)
            before = frames[-1]
            save_browsed_state(session)
            payload = run_batch([source], BatchRunOptions(output_folder=root/'output'))
            self.assertFalse(payload.failed)
            # This must really traverse the full fresh-analysis -> compact-sidecar
            # transition. A session loaded from .sfin alone cannot expose it.
            self.assertNotEqual(processed.state.alignment.correction,
                                payload.items[0].processed.state.alignment.correction)
            self.assertTrue(app._adopt_saved_result(payload))
            after_save = frames[-1]
            after_key = native_key(session)
            result = prepare_native_preview(session.loaded_pair, deepcopy(session.state),
                                            after_key, (320, 230), CancellationToken())
            # Holding the display must not conceal a real output/view mismatch.
            for actual, expected in zip(result[4][2][session.state.color.enabled], before):
                np.testing.assert_array_equal(actual, expected)
            app._native_cache, app._native_views = result[:3], result[4]
            app._apply_native_preview()
            for frame in (after_save, frames[-1]):
                for actual, expected in zip(frame, before):
                    np.testing.assert_array_equal(actual, expected)
            self.assertEqual(after_key, before_key)
            self.assertEqual(requests, [])

    def test_save_preserves_image_rectangle_when_native_result_arrives_during_export(self):
        app = test_preview_stability.PreviewStabilityTests().app()
        app.current.loaded_pair = loaded_pair()
        app.current.source = SimpleNamespace(sidecar_path='photo.sfin')
        app.current.state.color.enabled = False
        app.current.state.alignment.valid = True
        app.current.state.alignment.correction = {'rotation_deg': 2.4, 'scale': 1.002,
                                                 'vertical_shift_px': 2.4}
        app._detail_session_id = id(app.current)
        app._preview_base = app._preview_base_session_id = None
        app._request_native_preview = lambda **kw: None
        frames = []
        app._build_preview_anaglyph = lambda: frames.append(app._preview_left_current.copy())
        app._render_session_preview(app.current)
        before = frames[-1]
        app._preview_pil = Image.fromarray(before)
        result = prepare_native_preview(app.current.loaded_pair, deepcopy(app.current.state),
                                        native_key(app.current), app._preview_bounds(), CancellationToken())
        app._cancel_disparity_refresh = app._render_status = lambda: None
        app._stop_measure_repeat = lambda: None
        app._refresh_control_states = app._start_activity = lambda: None
        app.worker = SimpleNamespace(start=lambda *a, **kw: SimpleNamespace(job_id='save'))
        app._start_worker('save', '', lambda *args: None)
        app._native_job_id = 'pending'
        app._native_worker.messages.put(WorkerMessage('pending', WorkerMessageKind.RESULT, result))
        app._poll_native_preview()
        app.busy_state = 'idle'
        processed = SimpleNamespace(source=app.current.source, source_stamp=app.current.source_stamp,
                                    state=deepcopy(app.current.state))
        payload = SimpleNamespace(failed=[], items=[SimpleNamespace(processed=processed)])
        app._sync_vars_from_current = app._render_status = lambda: None
        with patch('stereofine.gui.load_sidecar', return_value=SimpleNamespace(status='valid')):
            self.assertTrue(app._adopt_saved_result(payload))
        for frame in frames:
            self.assertEqual(frame.shape, before.shape)
        np.testing.assert_array_equal(frames[-1], result[4][2][False][0])

    def test_an_explicit_window_edit_after_save_updates_the_view(self):
        app = test_preview_stability.PreviewStabilityTests().app()
        app.current.loaded_pair = loaded_pair()
        result = prepare_native_preview(app.current.loaded_pair, deepcopy(app.current.state),
            native_key(app.current), app._preview_bounds(), CancellationToken())
        app._native_cache, app._native_views = result[:3], result[4]
        app._build_preview_anaglyph = lambda: None
        app._apply_native_preview()
        app._preview_pil = Image.fromarray(app._preview_left_current)
        before = app._preview_left_current.copy()
        app.current.state.floating_window.bottom_permille = 5
        app._render_session_preview(app.current)
        expected = apply_floating_window_masks(*result[4][2][app.current.state.color.enabled], 0, 0, 0, 5)
        np.testing.assert_array_equal(app._preview_left_current, expected[0])
        self.assertFalse(np.array_equal(app._preview_left_current, before))

    def test_save_does_not_exit_native_inspection(self):
        app = test_preview_stability.PreviewStabilityTests().app()
        app._preview_pil = Image.new('RGB', (300, 200))
        app.detail_active = True
        app._detail_center = (517, 409)
        app._cancel_disparity_refresh = app._render_status = lambda: None
        app._refresh_control_states = app._start_activity = app._stop_measure_repeat = lambda: None
        app._end_detail_preview = lambda: self.fail('Saving must keep the current inspection view')
        app.worker = SimpleNamespace(start=lambda *a, **kw: SimpleNamespace(job_id='save'))
        app._start_worker('save', '', lambda *args: None)
        self.assertTrue(app.detail_active)
        self.assertEqual(app._detail_center, (517, 409))

    def test_failed_save_does_not_reload_the_current_image(self):
        app = test_preview_stability.PreviewStabilityTests().app()
        source = SimpleNamespace(display_name='photo')
        payload = BatchRunResult(failed=[(source, 'write error')])
        app._finish_busy_common = lambda: 'save'
        app._t = lambda key, **kw: key
        app.tr = SimpleNamespace(message=str)
        app.sources, app.source_index = [source], 0
        app._load_source_index = lambda *a, **kw: self.fail('A failed save must not reload the view')
        refreshes = []
        app._refresh_preview = lambda: refreshes.append(True)
        with patch('stereofine.gui.messagebox.showwarning'):
            app._finish_worker_success(payload)
        self.assertEqual(refreshes, [True])
