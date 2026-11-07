"""Cross-view exports and crop measurements must preserve the reviewed image."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from stereofine.batch import BatchRunOptions, run_batch
from stereofine.export import save_pair_outputs
from stereofine.processing import ProcessingOptions, process_source, refresh_current_disparity
from stereofine.render import render_final_pair
from stereofine.session import browse_source, save_browsed_state
from stereofine.settings import AppSettings
from tests import test_restart_alignment as fixtures


class CrossMeasurementTests(unittest.TestCase):
    def test_cross_has_reversed_full_color_eyes_and_shared_deviation_suffix(self):
        left = np.full((32, 48, 3), [220, 30, 20], dtype=np.uint8)
        right = np.full_like(left, [20, 70, 210])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plain = save_pair_outputs(left, right, root/'plain', 'scene')
            cross = save_pair_outputs(left, right, root/'cross', 'scene', gray_anaglyph=True,
                                      save_cross=True, filename_deviation_permille=20)
            self.assertIsNone(plain.cross_path)
            self.assertEqual(cross.cross_path.name, 'scene_020_cross.jpg')
            self.assertEqual(plain.sbs_path.read_bytes(), cross.sbs_path.read_bytes())
            with Image.open(cross.cross_path) as image:
                self.assertEqual(image.size, (96, 32))
                np.testing.assert_allclose(np.asarray(image)[16, 24], right[16,24], atol=3)
                np.testing.assert_allclose(np.asarray(image)[16, 72], left[16,24], atol=3)

    def test_preview_mode_does_not_set_anaglyph_export(self):
        self.assertFalse(AppSettings.from_dict({'preview_mode': 'Graustufen'}).gray_anaglyph)
        settings = AppSettings.from_dict({'gray_anaglyph': True})
        settings.save_cross = True
        restored = AppSettings.from_dict(settings.to_dict())
        self.assertTrue(restored.gray_anaglyph and restored.save_cross)
        self.assertFalse(hasattr(restored, 'preview_mode'))
        self.assertNotIn('preview_mode', restored.to_dict())
        self.assertFalse(AppSettings.from_dict({'preview_mode': 'Graustufen', 'gray_anaglyph': False}).gray_anaglyph)

    def test_crop_measurement_keeps_geometry_and_save_reuses_exact_value(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = fixtures.RestartAlignmentTests().source(root)
            process_source(source)
            session = browse_source(source)
            state = session.state
            state.manual.delta_x_px = 8
            state.manual.delta_y_px = 2
            state.framing.aspect = '4:3'
            state.framing.crop_zoom_index = 4
            state.framing.pan_x_permille = 180
            state.floating_window.left_permille = 9
            state.invalidate_disparity_for_framing()
            geometry = asdict(state.framing), asdict(state.manual), asdict(state.alignment)
            expected_left, expected_right, _ = render_final_pair(session.loaded_pair, deepcopy(state),
                                                apply_color=False, apply_floating_window=False)
            before = render_final_pair(session.loaded_pair, deepcopy(state))[:2]
            measured = {'ready':True, 'low_edge_permille':-24., 'high_edge_permille':-4.,
                        'deviation_permille':20., 'traffic':'green', 'status':'ok'}
            with patch('stereofine.processing.analyze_horizontal_disparity', return_value=measured) as analyze:
                refresh_current_disparity(session.loaded_pair, state)
            np.testing.assert_array_equal(analyze.call_args.args[0], expected_left)
            np.testing.assert_array_equal(analyze.call_args.args[1], expected_right)
            self.assertEqual(geometry, (asdict(state.framing), asdict(state.manual), asdict(state.alignment)))
            self.assertEqual(state.current_scene_positions_permille(), (-4., 24.))
            for a,b in zip(before, render_final_pair(session.loaded_pair, state)[:2]):
                np.testing.assert_array_equal(a,b)
            save_browsed_state(session)
            with patch('stereofine.processing.analyze_horizontal_disparity', side_effect=AssertionError('Unexpected remeasurement')):
                saved = run_batch([source], BatchRunOptions(processing=ProcessingOptions(),
                    output_folder=root/'output', append_deviation_to_filename=True, save_cross=True))
            self.assertFalse(saved.failed)
            self.assertEqual(saved.items[0].export.cross_path.name, 'scene_020_cross.jpg')
            self.assertEqual(saved.items[0].processed.state.framing, state.framing)

    def test_save_before_debounce_measures_crop_without_reframing(self):
        with tempfile.TemporaryDirectory() as td:
            source = fixtures.RestartAlignmentTests().source(Path(td))
            process_source(source)
            session = browse_source(source)
            session.state.framing.crop_zoom_index = 3
            session.state.manual.delta_x_px = 11
            session.state.invalidate_disparity_for_framing()
            save_browsed_state(session)
            before = deepcopy(session.state.framing)
            result = process_source(source)
            self.assertEqual(before, result.state.framing)
            self.assertTrue(result.state.disparity.basis['rendered_pair'])


if __name__ == '__main__':
    unittest.main()
