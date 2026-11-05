"""Native panning reuses exact pixels instead of mixing each frame again."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from stereofine.anaglyph import make_anaglyph
from stereofine.geometry import apply_floating_window_masks
from stereofine.native_preview import detail_box, native_key, prepare_native_preview
from stereofine.worker import CancellationToken
from tests import test_preview_stability
from tests.test_final_corrections import loaded_pair


class DetailTextureTests(unittest.TestCase):
    def test_cached_native_windows_equal_direct_mixing_in_all_modes(self):
        for mode in ('Farbig', 'Graustufen', 'Kreuzblick'):
            for masks in ((0, 0, 0, 0), (7, 9, 0, 0), (0, 0, 5, 0), (0, 0, 0, 5)):
                app = test_preview_stability.PreviewStabilityTests().app()
                app.current.loaded_pair = loaded_pair()
                fw = app.current.state.floating_window
                fw.left_permille, fw.right_permille, fw.top_permille, fw.bottom_permille = masks
                result = prepare_native_preview(app.current.loaded_pair, deepcopy(app.current.state),
                    native_key(app.current), (320, 230), CancellationToken(), mode)
                _, left, right, _, views = result
                texture = views[5][1]
                for x, y in ((0, 0), (500, 350), (200, 100)):
                    w, h = 100, 80
                    a, b = apply_floating_window_masks(left[y:y+h, x:x+w], right[y:y+h, x:x+w],
                        *masks, reference_size=(left.shape[1], left.shape[0]), origin=(x, y))
                    if mode == 'Kreuzblick':
                        actual = np.concatenate([np.asarray(texture.crop((x, y, x+w, y+h))),
                            np.asarray(texture.crop((x+left.shape[1], y, x+w+left.shape[1], y+h)))], axis=1)
                        expected = np.concatenate([b, a], axis=1)
                    else:
                        actual = np.asarray(texture.crop((x, y, x+w, y+h)))
                        expected = make_anaglyph(a, b, gray=mode == 'Graustufen')
                    np.testing.assert_array_equal(actual, expected)

    def test_warmed_panning_never_runs_anaglyph_mixing_again(self):
        app = test_preview_stability.PreviewStabilityTests().app()
        app.current.loaded_pair = loaded_pair()
        result = prepare_native_preview(app.current.loaded_pair, deepcopy(app.current.state),
            native_key(app.current), (320, 230), CancellationToken())
        app._native_cache, app._detail_texture_cache = result[:3], result[4][5]
        app.detail_active = True
        app._detail_center = (300, 220)
        app._preview_bounds = lambda: (320, 230)
        app.grid_mode = SimpleNamespace(get=lambda: 'Aus')
        app.preview_label = SimpleNamespace(_get_widget_scaling=lambda: 1, configure=lambda **kw: None)
        with patch('stereofine.native_preview.ctk.CTkImage', create=True) as images, \
                patch('stereofine.native_preview.make_anaglyph', side_effect=AssertionError('mixing during pan')):
            for _ in range(25):
                app._move_detail('right', 1)
            self.assertEqual(images.call_count, 25)
            actual = np.asarray(images.call_args.kwargs['light_image'])
        _, left, right = app._native_cache
        box, _ = detail_box(left.shape, (320, 230), app._detail_center)
        x, y, x1, y1 = box
        expected = make_anaglyph(left[y:y1, x:x1], right[y:y1, x:x1])
        np.testing.assert_array_equal(actual, expected)

    def test_optional_texture_allocation_failure_keeps_the_native_pair(self):
        app = test_preview_stability.PreviewStabilityTests().app()
        loaded = loaded_pair()
        with patch('stereofine.native_preview.prepare_detail_texture', side_effect=MemoryError):
            result = prepare_native_preview(loaded, deepcopy(app.current.state), native_key(app.current),
                                            (320, 230), CancellationToken())
        self.assertEqual(result[1].shape, loaded.left.shape)
        self.assertIsNone(result[4][5])
