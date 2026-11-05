"""A file save must not replace the displayed view with a delayed render."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from stereofine.native_preview import native_key, prepare_native_preview
from stereofine.batch import BatchRunResult
from stereofine.geometry import apply_floating_window_masks
from stereofine.worker import CancellationToken, WorkerMessage, WorkerMessageKind
from tests import test_preview_stability
from tests.test_final_corrections import loaded_pair


class SaveViewStabilityTests(unittest.TestCase):
    def test_save_keeps_the_visible_proxy_when_native_result_arrives_during_export(self):
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
            np.testing.assert_array_equal(frame, before)

    def test_an_explicit_window_edit_after_save_updates_the_held_view(self):
        app = test_preview_stability.PreviewStabilityTests().app()
        app.current.loaded_pair = loaded_pair()
        result = prepare_native_preview(app.current.loaded_pair, deepcopy(app.current.state),
            native_key(app.current), app._preview_bounds(), CancellationToken())
        app._native_cache, app._native_views = result[:3], result[4]
        app._build_preview_anaglyph = lambda: None
        app._apply_native_preview()
        app._preview_pil = Image.fromarray(app._preview_left_current)
        before = app._preview_left_current.copy()
        app._hold_current_preview()
        app.current.state.floating_window.bottom_permille = 5
        app._render_session_preview(app.current)
        self.assertFalse(app._preview_is_held())
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
        with patch('stereofine.gui.messagebox.showwarning'):
            app._finish_worker_success(payload)
