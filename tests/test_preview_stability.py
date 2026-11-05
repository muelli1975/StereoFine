"""View stability, exact native window crops and held-key behaviour."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from stereofine.geometry import apply_floating_window_masks
from stereofine.native_preview import NativePreviewMixin, native_key, pan_speed
from stereofine.state import PairState
from stereofine.worker import WorkerMessage, WorkerMessageKind
from tests.test_foundation import _import_gui_without_customtkinter_runtime


class PreviewStabilityTests(unittest.TestCase):
    def app(self):
        gui = _import_gui_without_customtkinter_runtime()
        app = object.__new__(gui.StereoFineApp)
        app._init_native_preview()
        app.current = SimpleNamespace(state=PairState(), source='source', source_stamp='stamp')
        app.busy_state = 'idle'
        app.after = lambda *args: 1
        app.after_cancel = lambda *args: None
        app._preview_bounds = lambda: (300, 200)
        return app

    def test_failed_detail_render_retries_only_after_a_fresh_z_press(self):
        app = self.app()
        app.current.loaded_pair = SimpleNamespace(icc_profile=None)
        app._detail_session_id = id(app.current)
        app.detail_active = True
        key = native_key(app.current)
        app._native_job_id = 'failed'
        app._native_running_key = key
        app._native_worker.messages.put(WorkerMessage('failed', WorkerMessageKind.ERROR,
                                        {'exception': RuntimeError('transient render error')}))
        app.preview_label = SimpleNamespace(configure=lambda **kwargs: None,
                                _label=SimpleNamespace(configure=lambda **kwargs: None))
        app._t = lambda key, **kwargs: key
        app._stop_measure_repeat = lambda: None
        app._apply_native_preview = lambda: True
        with patch.object(app._native_worker, 'start', return_value=SimpleNamespace(job_id='retry')) as start:
            app._poll_native_preview()
            self.assertEqual(app._native_failed_key, key)
            for _ in range(5):
                app._on_detail_press()
                app._start_native_preview()
            start.assert_not_called()
            app._end_detail_preview()
            app._on_detail_press()
            app._start_native_preview()
            start.assert_called_once()
            a = np.zeros((10, 10, 3), np.uint8)
            app._native_worker.messages.put(WorkerMessage('retry', WorkerMessageKind.RESULT,
                                            (key, a, a, app.current.state.color, None)))
            app._poll_native_preview()
        self.assertIsNone(app._native_failed_key)
        self.assertEqual(app._native_cache[0], key)

    def test_detail_edge_skips_redraw_but_moving_back_and_explicit_refresh_work(self):
        app = self.app()
        app.detail_active = True
        a = np.zeros((400, 600, 3), np.uint8)
        app._native_cache = (native_key(app.current), a, a)
        app._preview_bounds = lambda: (200, 100)
        app._effective_preview_mode = lambda: 'Farbig'
        app.grid_mode = SimpleNamespace(get=lambda: 'Aus')
        app.measure_cross_active = False
        app.preview_label = SimpleNamespace(_get_widget_scaling=lambda: 1, configure=lambda **kwargs: None)
        with patch('stereofine.native_preview.ctk.CTkImage', create=True) as images:
            for direction, center in [('right', (500, 200)), ('left', (100, 200)),
                                      ('up', (300, 50)), ('down', (300, 350))]:
                app._detail_center = center
                previous_count = images.call_count
                for _ in range(10):
                    app._move_detail(direction, 20.)
                self.assertEqual(images.call_count, previous_count)
                self.assertEqual(app._detail_center, center)
                app._show_detail_preview()
                self.assertEqual(images.call_count, previous_count + 1)
                opposite = {'right': 'left', 'left': 'right', 'up': 'down', 'down': 'up'}[direction]
                app._move_detail(opposite, 1.)
                self.assertEqual(images.call_count, previous_count + 2)

    def test_native_window_crop_matches_full_export_mask(self):
        a = np.full((227, 401, 3), 233, np.uint8)
        for values in [(0, 0, 0, 5), (0, 0, 5, 0), (7, 9, 0, 0)]:
            full = apply_floating_window_masks(a, a, *values)
            for x, y, w, h in [(0, 0, 40, 30), (0, 170, 45, 57), (370, 160, 31, 67), (100, 60, 73, 41)]:
                part = a[y:y+h, x:x+w]
                cropped = apply_floating_window_masks(part, part, *values,
                            reference_size=(401, 227), origin=(x, y))
                for actual, expected in zip(cropped, full):
                    np.testing.assert_array_equal(actual, expected[y:y+h, x:x+w])

    def test_window_edit_uses_cached_pixels_and_has_no_delayed_replacement(self):
        app = self.app()
        a = np.full((400, 600, 3), 200, np.uint8)
        key = native_key(app.current)
        app._native_cache = (key, a, a.copy())
        app._preview_bounds = lambda: (300, 200)
        app._build_preview_anaglyph = lambda: None
        app.current.state.floating_window.bottom_permille = 5
        self.assertEqual(native_key(app.current), key)
        self.assertTrue(app._apply_native_preview())
        before = app._preview_left_current.copy()
        fit_cache = app._native_fit_cache
        app._render_session_preview(app.current)
        np.testing.assert_array_equal(app._preview_left_current, before)
        self.assertIs(app._native_fit_cache, fit_cache)
        self.assertIsNone(app._native_after_id)

    def test_save_adopts_persisted_state_without_reloading_pixels_or_view(self):
        app = self.app()
        app.current.source = SimpleNamespace(sidecar_path=Path('photo.sfin'))
        app.current.state.color.enabled = True
        app.current.state.floating_window.bottom_permille = 5
        app._native_cache = (native_key(app.current), object(), object())
        app._detail_center = (517, 409)
        app._sync_vars_from_current = lambda: None
        app._render_status = lambda: None
        app._refresh_preview = lambda: self.fail('An unchanged export must not rebuild the view')
        previous = app.current
        cached = app._native_cache
        processed = SimpleNamespace(source=app.current.source, source_stamp='stamp', state=deepcopy(app.current.state))
        processed.state.color.valid = True
        payload = SimpleNamespace(failed=[], items=[SimpleNamespace(processed=processed)])
        with patch('stereofine.gui.load_sidecar', return_value=SimpleNamespace(status='valid')):
            self.assertTrue(app._adopt_saved_result(payload))
        self.assertIs(app.current, previous)
        self.assertIs(app._native_cache, cached)
        self.assertEqual(app._detail_center, (517, 409))
        self.assertTrue(app.current.state.color.valid)

    def test_acceleration_is_time_based_and_stops_on_exit(self):
        app = self.app()
        app.detail_active = True
        app._detail_center = (1000., 800.)
        app._native_cache = (native_key(app.current), object(), object())
        app._show_detail_preview = lambda **kwargs: None
        before = deepcopy(app.current.state)
        with patch('stereofine.native_preview.time.perf_counter', return_value=10.):
            for _ in range(12):
                app._handle_detail_arrow('right')
        self.assertEqual(app._detail_center, (1001., 800.))
        with patch('stereofine.native_preview.time.perf_counter', return_value=10.1):
            app._detail_repeat_tick()
        self.assertEqual(app._detail_center[0], 1001.)
        app._detail_last_tick_at = 10.2
        with patch('stereofine.native_preview.time.perf_counter', return_value=10.216):
            app._detail_repeat_tick()
        first_move = app._detail_center[0] - 1001.
        app._detail_last_tick_at = 10.984
        previous_x = app._detail_center[0]
        with patch('stereofine.native_preview.time.perf_counter', return_value=11.):
            app._detail_repeat_tick()
        self.assertGreater(app._detail_center[0] - previous_x, first_move)
        self.assertEqual(app._measure_speed(.3), pan_speed(.3))
        app._apply_native_preview = lambda: True
        app._end_detail_preview()
        self.assertIsNone(app._detail_repeat_job)
        stopped = app._detail_center
        app._detail_repeat_tick()
        self.assertEqual(app._detail_center, stopped)
        self.assertTrue(app._handle_detail_arrow('right'))
        self.assertEqual(app.current.state, before)
