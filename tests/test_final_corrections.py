"""Master-based colour toggles, interrupted previews and physical key releases."""
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import tifffile

from stereofine.color_profiles import transform_rgb
from stereofine.color_transfer import fit_symmetric_color_transfer, apply_symmetric_color_transfer
from stereofine.inputs import LoadedStereoPair, master_to_uint8
from stereofine.native_preview import native_key, native_geometry_key, prepare_native_preview, fit_display_pair
from stereofine.processing import ProcessingDefaults
from stereofine.render import render_final_pair
from stereofine.session import browse_source, save_browsed_state
from stereofine.settings import AppSettings, save_settings, load_settings
from stereofine.sources import source_from_pair
from stereofine.state import PairState
from stereofine.worker import CancellationToken, WorkerMessage, WorkerMessageKind
from tests import test_preview_stability, test_keyboard_filename
from tests.test_tiff_detail import linear_rgb_profile


def loaded_pair(dtype=np.uint8, identical=False, profile=None):
    y, x = np.indices((480, 720))
    left = np.stack([(x * 7) % 256, (y * 5) % 256, ((x + y) * 3) % 256], axis=2).astype(dtype)
    if dtype == np.uint16:
        left *= 257
    right = left.copy() if identical else np.clip(left.astype(np.int32) + 19 * (257 if dtype == np.uint16 else 1),
                                                 0, np.iinfo(dtype).max).astype(dtype)
    return LoadedStereoPair(left, right, Path('left'), Path('right'), 'pair', 720, 480, 720, 480, 720, 480,
                            icc_profile=profile)


class FinalCorrectionTests(unittest.TestCase):
    def test_clipped_endpoints_are_fixed_for_direct_and_lut_paths(self):
        for dtype in (np.uint8, np.uint16):
            peak = np.iinfo(dtype).max
            for value, other in ((0, 40), (255, 215)):
                left = np.full((8, 12, 3), value * (peak // 255), dtype)
                right = np.full_like(left, other * (peak // 255))
                transfer = fit_symmetric_color_transfer(left, right)
                for image in (left, np.tile(left, (100, 100, 1))):
                    result, _ = apply_symmetric_color_transfer(image, image, transfer)
                    self.assertTrue(np.all(result == value * (peak // 255)))

    def test_saved_curves_are_reused_without_replacing_adjustments(self):
        for dtype in (np.uint8, np.uint16):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                left = np.arange(256, dtype=dtype)[None, :, None].repeat(20, 0).repeat(3, 2)
                left *= np.iinfo(dtype).max // 255
                right = np.clip(left.astype(np.int32) + 40 * (np.iinfo(dtype).max // 255),
                                0, np.iinfo(dtype).max).astype(dtype)
                for name, eye in [('l', left), ('r', right)]:
                    tifffile.imwrite(root / f'{name}.tif', eye, photometric='rgb')
                source = source_from_pair(root / 'l.tif', root / 'r.tif', root)
                session = browse_source(source)
                session.state.manual.delta_x_px = 2
                session.state.floating_window.bottom_permille = 5
                render_final_pair(session.loaded_pair, session.state)
                parameters = deepcopy(session.state.color.parameters)
                save_browsed_state(session)
                reopened = browse_source(source)
                a, b, info = render_final_pair(reopened.loaded_pair, reopened.state)
                self.assertFalse(info.color_refit)
                self.assertEqual(reopened.state.color.parameters, parameters)
                self.assertEqual(reopened.state.manual.delta_x_px, 2)
                self.assertEqual(reopened.state.floating_window.bottom_permille, 5)
                reopened.state.color.valid = False
                fresh = render_final_pair(reopened.loaded_pair, reopened.state)
                np.testing.assert_array_equal(a, fresh[0])
                np.testing.assert_array_equal(b, fresh[1])

    def test_native_variants_match_full_depth_export_with_the_same_crop(self):
        profile = linear_rgb_profile()
        for dtype in (np.uint8, np.uint16):
            loaded = loaded_pair(dtype, profile=profile)
            for aspect in ('original', 'maximum', '1:1', '16:9'):
                state = PairState()
                state.framing.aspect = aspect
                state.framing.crop_zoom_index = 2
                state.framing.pan_x_permille = 210
                state.manual.delta_x_px = 3
                state.alignment.valid = True
                state.alignment.correction = {'rotation_deg': .6, 'scale': 1.002, 'vertical_shift_px': 2.4}
                session = SimpleNamespace(state=state)
                result = prepare_native_preview(loaded, deepcopy(state), native_key(session), (320, 230), CancellationToken())
                views = result[4]
                for enabled in (False, True):
                    reference = deepcopy(state)
                    reference.color.enabled = enabled
                    left, right, _ = render_final_pair(loaded, reference, apply_floating_window=False)
                    expected = fit_display_pair(*[master_to_uint8(transform_rgb(eye, profile)) for eye in (left, right)],
                                                (320, 230))
                    for actual, wanted in zip(views[2][enabled], expected):
                        np.testing.assert_array_equal(actual, wanted)
                self.assertEqual(views[2][False][0].shape, views[2][True][0].shape)

    def test_color_toggle_reuses_master_variants_and_preserves_geometry(self):
        app = test_preview_stability.PreviewStabilityTests().app()
        loaded = loaded_pair(identical=True)
        app.current.loaded_pair = loaded
        app._preview_bounds = lambda: (320, 230)
        app.current.state.framing.aspect = 'original'
        app.current.state.alignment.valid = True
        app.current.state.alignment.correction = {'rotation_deg': .6, 'scale': 1.002, 'vertical_shift_px': 2.4}
        state = deepcopy(app.current.state)
        result = prepare_native_preview(loaded, state, native_key(app.current), (320, 230), CancellationToken())
        app._native_cache = result[:3]
        app._native_views = result[4]
        app._build_preview_anaglyph = lambda: None
        app._request_native_preview = lambda **kwargs: None
        app._ensure_preview_base = lambda *args, **kwargs: self.fail('A colour toggle must reuse the master crop')
        previous = None
        for enabled in (False, True, False, True):
            app.current.state.color.enabled = enabled
            app._render_session_preview(app.current)
            np.testing.assert_array_equal(app._preview_left_current, result[4][2][enabled][0])
            if previous is not None:
                # Symmetric rotations sample each eye differently; the fitted
                # curves can change rounding by one level even for this pair.
                self.assertEqual(app._preview_left_current.shape, previous.shape)
                self.assertLessEqual(np.abs(app._preview_left_current.astype(int) - previous).max(), 1)
            previous = app._preview_left_current.copy()

    def test_completed_background_result_survives_busy_cancel_and_error(self):
        for kind in ('save', 'analysis'):
            for outcome in ('cancel', 'error'):
                app = test_preview_stability.PreviewStabilityTests().app()
                app._preview_bounds = lambda: (320, 230)
                loaded = loaded_pair()
                app.current.loaded_pair = loaded
                app.current.state.color.enabled = True
                result = prepare_native_preview(loaded, deepcopy(app.current.state), native_key(app.current),
                                                (320, 230), CancellationToken())
                app.busy_state = kind
                app.current_job_kind = kind
                app.current_job_id = 'main'
                app._native_job_id = 'native'
                app._native_worker.messages.put(WorkerMessage('native', WorkerMessageKind.RESULT, result))
                app._build_preview_anaglyph = lambda: None
                app._poll_native_preview()
                self.assertTrue(app._native_deferred)
                self.assertFalse(app.current.state.color.valid)
                app._refresh_control_states = lambda: None
                app._stop_activity = lambda: None
                app._render_status = lambda: None
                app._t = lambda key, **kwargs: key
                app.tr = SimpleNamespace(message=str)
                with patch('stereofine.gui.messagebox.showinfo'), patch('stereofine.gui.messagebox.showerror'):
                    if outcome == 'cancel':
                        app._finish_worker_cancelled()
                    else:
                        app._finish_worker_error(RuntimeError('cancelled operation'))
                self.assertEqual(app.busy_state, 'idle')
                self.assertFalse(app._native_deferred)
                self.assertTrue(app.current.state.color.valid)
                self.assertEqual(app._preview_left_current.shape, result[4][2][True][0].shape)
                self.assertIsNone(app._native_after_id)

    def test_outdated_background_result_cannot_replace_new_image_or_crop(self):
        for change in ('image', 'crop'):
            app = test_preview_stability.PreviewStabilityTests().app()
            loaded = loaded_pair()
            result = prepare_native_preview(loaded, deepcopy(app.current.state), native_key(app.current),
                                            (320, 230), CancellationToken())
            if change == 'image':
                app.current = SimpleNamespace(state=deepcopy(app.current.state))
            else:
                app.current.state.framing.aspect = '1:1'
            app.busy_state = 'save'
            app._native_job_id = 'old'
            app._native_worker.messages.put(WorkerMessage('old', WorkerMessageKind.RESULT, result))
            app._poll_native_preview()
            self.assertIsNone(app._native_cache)
            self.assertIsNone(app._native_views)
            self.assertFalse(app.current.state.color.valid)

    def test_window_enlargement_refits_native_pixels_and_refreshes_both_variants(self):
        app = test_preview_stability.PreviewStabilityTests().app()
        loaded = loaded_pair()
        app.current.loaded_pair = loaded
        app._detail_session_id = id(app.current)
        result = prepare_native_preview(loaded, deepcopy(app.current.state), native_key(app.current),
                                        (200, 140), CancellationToken())
        app._native_cache, app._native_views = result[:3], result[4]
        app._preview_bounds = lambda: (600, 450)
        app._build_preview_anaglyph = lambda: None
        app._render_session_preview(app.current)
        expected = fit_display_pair(result[1], result[2], (600, 450))
        np.testing.assert_array_equal(app._preview_left_current, expected[0])
        self.assertIsNotNone(app._native_after_id)
        self.assertTrue(app._native_views_need_resize())

    def test_color_toggle_during_a_busy_result_preserves_latest_choice(self):
        app = test_preview_stability.PreviewStabilityTests().app()
        app._preview_bounds = lambda: (320, 230)
        app._detail_session_id = id(app.current)
        loaded = loaded_pair()
        app.current.loaded_pair = loaded
        result = prepare_native_preview(loaded, deepcopy(app.current.state), native_key(app.current),
                                        (320, 230), CancellationToken())
        app.current.state.color.enabled = True
        app.busy_state = 'save'
        app._native_job_id = 'old-color'
        app._native_worker.messages.put(WorkerMessage('old-color', WorkerMessageKind.RESULT, result))
        app._poll_native_preview()
        app.busy_state = 'idle'
        app._build_preview_anaglyph = lambda: None
        app._refresh_preview()
        self.assertTrue(app.current.state.color.enabled)
        self.assertTrue(app.current.state.color.valid)
        np.testing.assert_array_equal(app._preview_left_current, result[4][2][True][0])
        self.assertIsNotNone(app._native_after_id)

    def test_new_defaults_preserve_existing_settings_and_sidecars(self):
        self.assertEqual(AppSettings().default_aspect, 'original')
        self.assertTrue(AppSettings().color_match_enabled)
        self.assertEqual(ProcessingDefaults().aspect, 'original')
        self.assertTrue(ProcessingDefaults().color_enabled)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            old = AppSettings(default_aspect='maximum', color_match_enabled=False)
            save_settings(old, path)
            restored = load_settings(path)
            self.assertEqual(restored.default_aspect, 'maximum')
            self.assertFalse(restored.color_match_enabled)
            from tests.test_restart_alignment import RestartAlignmentTests
            source = RestartAlignmentTests().source(Path(directory))
            session = browse_source(source, ProcessingDefaults(aspect='maximum', color_enabled=False))
            save_browsed_state(session)
            restored = browse_source(source)
            self.assertEqual(restored.state.framing.aspect, 'maximum')
            self.assertFalse(restored.state.color.enabled)

    def test_mode_release_blocks_held_arrows_until_physical_release(self):
        for mode in ('measure', 'left', 'right', 'top', 'bottom'):
            for direction in ('left', 'right', 'up', 'down'):
                fixture = test_keyboard_filename.KeyboardFocusTests()
                fixture.setUp()
                app = fixture.app
                app.float_lr_symmetric = SimpleNamespace(get=lambda: False)
                callbacks = {}
                def after(_delay, callback):
                    job = len(callbacks) + 1
                    callbacks[job] = callback
                    return job
                app.after = after
                app.after_idle = lambda callback: after(0, callback)
                app.after_cancel = lambda job: callbacks.pop(job, None)
                app._status_after_id = None
                if mode == 'measure':
                    app.measure_cross_active = True
                    app._move_measure_cross = lambda *args: None
                else:
                    app._set_floating_key(mode)
                app._on_arrow(direction)
                before = deepcopy(app.current.state)
                if mode == 'measure':
                    app._on_measure_release()
                else:
                    app._clear_floating_key(mode)
                job = app._mode_release_ids[mode]
                callbacks.pop(job)()
                for _ in range(5):
                    app._on_arrow(direction)
                self.assertEqual(app.current.state, before)
                app._on_arrow_release(SimpleNamespace(keysym=direction.title()))
                # X11's synthetic release/press pair must retain the guard.
                app._on_arrow(direction)
                self.assertEqual(app.current.state, before)
                app._on_arrow_release(SimpleNamespace(keysym=direction.title()))
                job = app._detail_arrow_releases[direction]
                callbacks.pop(job)()
                app._on_arrow(direction)
                self.assertNotEqual(app.current.state.manual, before.manual)
