"""The first completed analysis view must already be the final master view."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from stereofine.native_preview import native_key, prepare_native_preview
from stereofine.processing import ProcessedSource, ProcessingOptions
from stereofine.sidecar import SidecarStatus
from stereofine.worker import CancellationToken, JobCancelled, WorkerMessage, WorkerMessageKind
from tests.test_final_corrections import loaded_pair
from tests import test_preview_stability


class AnalysisPreviewHandoffTests(unittest.TestCase):
    def test_first_completed_analysis_frame_matches_settled_native_frame(self):
        for aspect in ('original', 'maximum', '1:1', '16:9'):
            for color in (False, True):
                with self.subTest(aspect=aspect, color=color):
                    app = test_preview_stability.PreviewStabilityTests().app()
                    app.current.loaded_pair = loaded_pair()
                    app.current.source = SimpleNamespace(sidecar_path='unused.sfin')
                    state = deepcopy(app.current.state)
                    state.framing.aspect = aspect
                    state.framing.crop_zoom_index = 1
                    state.color.enabled = color
                    state.alignment.valid = True
                    state.alignment.correction = {'rotation_deg': 2.4, 'scale': 1.002,
                                                  'vertical_shift_px': 2.4}
                    state.manual.delta_x_px = 3
                    processed = ProcessedSource(app.current.source, app.current.source_stamp,
                        state, SidecarStatus.VALID, False, False, loaded_pair=app.current.loaded_pair)
                    jobs, frames = [], []
                    app.batch_mode = False
                    app._flush_state_save = lambda **kw: True
                    app._processing_options = lambda **kw: ProcessingOptions(keep_loaded_pair=True)
                    app._start_worker = lambda kind, text, job: jobs.append(job)
                    app._t = lambda key, **kw: key
                    app._preview_bounds = lambda: (320, 230)
                    app._preview_base = app._preview_base_session_id = None
                    app._build_preview_anaglyph = lambda: frames.append(
                        (app._preview_left_current.copy(), app._preview_right_current.copy()))
                    app._request_native_preview = lambda **kw: None
                    app._finish_busy_common = lambda: 'analysis'
                    app._sync_vars_from_current = app._render_status = lambda: None
                    app._refresh_control_states = app._schedule_disparity_refresh = lambda: None
                    app.start_processing()
                    gui_module = app.start_processing.__globals__['__name__']
                    with patch(gui_module+'.process_source', return_value=processed), \
                            patch(gui_module+'.load_sidecar', return_value=SimpleNamespace(status=SidecarStatus.VALID)), \
                            patch(gui_module+'.play_ready_sound'):
                        payload = jobs[0](CancellationToken(), lambda event: None)
                        app._finish_worker_success(payload)
                    first = frames[-1]
                    reference = prepare_native_preview(app.current.loaded_pair,
                        deepcopy(app.current.state), native_key(app.current), (320, 230), CancellationToken())
                    app._native_cache, app._native_views = reference[:3], reference[4]
                    app._apply_native_preview()
                    for initial, settled in zip(first, frames[-1]):
                        np.testing.assert_array_equal(initial, settled)
                    self.assertEqual(app.current.state.alignment, state.alignment)
                    self.assertEqual(app.current.state.disparity, state.disparity)

    def test_cancelled_preparation_keeps_the_visible_session(self):
        app = test_preview_stability.PreviewStabilityTests().app()
        current = app.current
        token = CancellationToken()
        token.cancel()
        with self.assertRaises(JobCancelled):
            app._prepare_session_preview(current, (320, 230), token)
        self.assertIs(app.current, current)
        self.assertIsNone(app._native_cache)

    def test_late_result_from_previous_session_cannot_replace_prepared_view(self):
        app = test_preview_stability.PreviewStabilityTests().app()
        previous = app.current
        previous.loaded_pair = loaded_pair()
        old_key = native_key(previous)
        new = SimpleNamespace(state=deepcopy(previous.state), loaded_pair=previous.loaded_pair)
        prepared = app._prepare_session_preview(new, (300, 200), CancellationToken())
        app._install_session_preview(prepared)
        app.current = new
        cache, views = app._native_cache, app._native_views
        app._native_job_id = 'old-render'
        app._native_running_key = old_key
        eye = np.zeros((12, 18, 3), np.uint8)
        app._native_worker.messages.put(WorkerMessage('old-render', WorkerMessageKind.RESULT,
            (old_key, eye, eye, previous.state.color, None)))
        app._poll_native_preview()
        self.assertIs(app._native_cache, cache)
        self.assertIs(app._native_views, views)
        self.assertIsNone(app._native_job_id)
