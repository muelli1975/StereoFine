"""Lost key releases and opt-in deviation suffixes must preserve existing work."""
from __future__ import annotations

from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

from stereofine.batch import BatchRunOptions, run_batch
from stereofine.export import deviation_filename_suffix, save_pair_outputs
from stereofine.processing import ProcessingOptions
from stereofine.settings import AppSettings, load_settings, save_settings
from stereofine.state import PairState
from tests.test_foundation import _import_gui_without_customtkinter_runtime


class KeyboardFocusTests(unittest.TestCase):
    def setUp(self):
        gui = _import_gui_without_customtkinter_runtime()
        self.app = object.__new__(gui.StereoFineApp)
        self.app._init_native_preview()
        app = self.app
        app.current = types.SimpleNamespace(state=PairState())
        app.busy_state = 'idle'
        app._floating_key_edge = None
        app._g_key_down = False
        app._shortcut_keys_down = set()
        app._keyboard_focus_after_id = None
        app.measure_cross_active = False
        app._measure_repeat_job = None
        app._measure_repeat_direction = None
        app._measure_hold_started_at = None
        app._measure_last_tick_at = None
        self.cancelled = []
        app.after_cancel = self.cancelled.append
        app._update_preview_display = lambda: None
        app._refresh_preview = lambda: None
        app._render_session_preview = lambda session: None
        app._render_status = lambda: None
        app._schedule_state_save = lambda: None
        app._schedule_status_refresh = lambda: None
        app._schedule_disparity_refresh = lambda: None
        app.preview_mode = types.SimpleNamespace(get=lambda: 'Farbig')
        self.focus = None
        app.focus_get = lambda: self.focus

    def press_right(self, state=0):
        self.app._on_arrow('right', types.SimpleNamespace(state=state))

    def test_focus_loss_recovers_manual_nudges_after_lost_floating_key_release(self):
        app = self.app
        app._set_floating_key('top')
        app.current.state.manual.delta_x_px = 17
        app.current.state.floating_window.top_permille = 4
        self.press_right()
        self.assertEqual(app.current.state.manual.delta_x_px, 17)
        self.assertEqual(app.current.state.floating_window.top_permille, 5)
        app._reset_keyboard_if_unfocused()
        self.assertIsNone(app._floating_key_edge)
        self.assertEqual(app.current.state.floating_window.top_permille, 5)
        for modifier, step in [(0, 1), (1, 5), (4, 10)]:
            before = app.current.state.manual.delta_x_px
            self.press_right(modifier)
            self.assertEqual(app.current.state.manual.delta_x_px, before+step)

    def test_focus_loss_stops_cross_repeat_and_clears_only_transient_keys(self):
        app = self.app
        app.current.state.manual.delta_y_px = -7
        app._floating_key_edge = 'right'
        app._g_key_down = True
        app._shortcut_keys_down = {'f11', 's', 'ctrl-r'}
        app.measure_cross_active = True
        app._measure_repeat_job = 'repeat-job'
        app._measure_repeat_direction = 'left'
        app._reset_keyboard_if_unfocused()
        self.assertFalse(app.measure_cross_active)
        self.assertIsNone(app._measure_repeat_job)
        self.assertIsNone(app._measure_repeat_direction)
        self.assertEqual(self.cancelled, ['repeat-job'])
        self.assertFalse(app._g_key_down)
        self.assertEqual(app._shortcut_keys_down, set())
        self.assertEqual(app.current.state.manual.delta_y_px, -7)

    def test_internal_focus_change_preserves_held_keys(self):
        app = self.app
        app._floating_key_edge = 'left'
        app._shortcut_keys_down = {'f11'}
        self.focus = types.SimpleNamespace(winfo_toplevel=lambda: app)
        app._reset_keyboard_if_unfocused()
        self.assertEqual(app._floating_key_edge, 'left')
        self.assertEqual(app._shortcut_keys_down, {'f11'})
        self.focus = types.SimpleNamespace(winfo_toplevel=lambda: object())
        app._reset_keyboard_if_unfocused()
        self.assertIsNone(app._floating_key_edge)

    def test_focus_events_coalesce_and_only_root_unmap_resets(self):
        app = self.app
        pending = []
        app.after_idle = lambda callback: pending.append(callback) or 'focus-job'
        app._on_keyboard_focus_out()
        app._on_keyboard_focus_out()
        self.assertEqual(len(pending), 1)
        app._floating_key_edge = 'bottom'
        app._on_keyboard_unmap(types.SimpleNamespace(widget=object()))
        self.assertEqual(app._floating_key_edge, 'bottom')
        app._on_keyboard_unmap(types.SimpleNamespace(widget=app))
        self.assertIsNone(app._floating_key_edge)
        self.assertEqual(self.cancelled, ['focus-job'])
        self.assertIsNone(app._keyboard_focus_after_id)


class DeviationFilenameTests(unittest.TestCase):
    def test_suffix_rounding_and_unavailable_values(self):
        for value, expected in [(57, '_057'), (57.49, '_057'), (57.5, '_058'),
                                (0, '_000'), (999.5, '_1000'), (None, ''),
                                (float('nan'), ''), (float('inf'), ''), (-1, '')]:
            with self.subTest(value=value):
                self.assertEqual(deviation_filename_suffix(value), expected)

    def test_opt_in_changes_both_names_without_changing_jpeg_bytes(self):
        rng = np.random.default_rng(72)
        left = rng.integers(0, 256, (24, 36, 3), dtype=np.uint8)
        right = np.roll(left, -2, axis=1)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plain = save_pair_outputs(left, right, root, 'photo')
            named = save_pair_outputs(left, right, root, 'photo', filename_deviation_permille=57.1)
            self.assertEqual(plain.sbs_path.name, 'photo_sbs.jpg')
            self.assertEqual(plain.anaglyph_path.name, 'photo_anaglyph.jpg')
            self.assertEqual(named.sbs_path.name, 'photo_057_sbs.jpg')
            self.assertEqual(named.anaglyph_path.name, 'photo_057_anaglyph.jpg')
            self.assertEqual(plain.sbs_path.read_bytes(), named.sbs_path.read_bytes())
            self.assertEqual(plain.anaglyph_path.read_bytes(), named.anaglyph_path.read_bytes())

    def test_settings_migration_and_disk_roundtrip(self):
        self.assertFalse(AppSettings.from_dict({'language': 'en'}).append_deviation_to_filename)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'settings.json'
            settings = AppSettings(append_deviation_to_filename=True, language='en')
            save_settings(settings, path)
            restored = load_settings(path)
            self.assertTrue(restored.append_deviation_to_filename)
            self.assertEqual(restored.language, 'en')

    def test_batch_and_single_save_forward_only_current_valid_measurements(self):
        source = types.SimpleNamespace(base_name='photo', display_name='photo', metadata_source=None)
        image = np.zeros((8, 12, 3), np.uint8)
        with tempfile.TemporaryDirectory() as temporary:
            for enabled, valid, stale, uncertain, expected in [
                (False, True, False, False, None), (True, True, False, False, 57.),
                (True, True, False, True, 57.), (True, False, False, True, None),
                (True, True, True, True, None),
            ]:
                state = PairState()
                state.disparity.total_permille = 57.
                state.disparity.valid, state.disparity.stale = valid, stale
                state.disparity.uncertain = uncertain
                processed = types.SimpleNamespace(state=state, analysis_record=object(),
                                                  preview_pair=None, loaded_pair=types.SimpleNamespace(icc_profile=None))
                options = BatchRunOptions(processing=ProcessingOptions(save_sidecar=False),
                    output_folder=Path(temporary), append_deviation_to_filename=enabled)
                with patch('stereofine.batch.validate_source_names'), \
                     patch('stereofine.batch.process_source', return_value=processed), \
                     patch('stereofine.batch.render_final_pair', return_value=(image, image, None)), \
                     patch('stereofine.batch.save_pair_outputs', wraps=save_pair_outputs) as save:
                    result = run_batch([source], options)
                self.assertEqual(result.failed, [])
                self.assertEqual(save.call_args.kwargs['filename_deviation_permille'], expected)
                suffix = '' if expected is None else '_057'
                exported = result.items[0].export
                self.assertEqual(exported.sbs_path.name, 'photo'+suffix+'_sbs.jpg')
                self.assertEqual(exported.anaglyph_path.name, 'photo'+suffix+'_anaglyph.jpg')
                self.assertEqual(state.disparity.uncertain, uncertain)


if __name__ == '__main__':
    unittest.main()

