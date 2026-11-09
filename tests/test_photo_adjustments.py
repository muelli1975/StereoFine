from dataclasses import replace
import unittest

import numpy as np
from PIL import Image

from stereofine.anaglyph import make_anaglyph
from stereofine.folder_settings import FolderChoices, _patch_preferences
from stereofine.geometry import apply_floating_window_masks
from stereofine.photo import NEUTRAL_PHOTO, PhotoAdjustments, apply_photo
from stereofine.sidecar import SidecarDocument
from stereofine.state import FloatingWindowState, PairState
from stereofine.viewport_render import render_viewport


class PhotoAdjustmentTests(unittest.TestCase):
    def test_neutral_bypasses_and_exposure_preserves_depth(self):
        pixel = np.full((1, 1, 3), 16000, dtype=np.uint16)
        self.assertIs(apply_photo(pixel, NEUTRAL_PHOTO), pixel)
        brighter = apply_photo(pixel, PhotoAdjustments(exposure=1))
        self.assertEqual(brighter.dtype, np.uint16)
        self.assertTrue(np.all(brighter > pixel))
        self.assertTrue(np.all(brighter == brighter[0, 0, 0]))

    def test_tone_directions_and_white_balance(self):
        image = np.repeat(np.array([[[48], [128], [225]]], dtype=np.uint8), 3, axis=2)
        raised = apply_photo(image, PhotoAdjustments(shadows=50, highlights=-50))
        self.assertGreater(raised[0, 0, 0], image[0, 0, 0])
        self.assertLess(raised[0, 2, 0], image[0, 2, 0])
        warm = apply_photo(image, PhotoAdjustments(temperature=50))
        self.assertGreater(warm[0, 1, 0], warm[0, 1, 2])
        magenta = apply_photo(image, PhotoAdjustments(tint=50))
        self.assertLess(magenta[0, 1, 1], magenta[0, 1, 0])

    def test_white_balance_folder_overwrite_preserves_tone_edits(self):
        state = PairState(photo=PhotoAdjustments(exposure=.7, shadows=20, tint=13))
        raw = state.to_sidecar(source={}).to_dict()
        result = _patch_preferences(raw, FolderChoices(white_balance=(12, 0)))
        restored = PairState.from_sidecar(SidecarDocument.from_dict(result))
        self.assertEqual(restored.photo, replace(state.photo, temperature=12, tint=0))
        self.assertEqual(PairState.from_sidecar(SidecarDocument()).photo, NEUTRAL_PHOTO)

    def test_viewport_matches_full_render_with_tilted_masks(self):
        rng = np.random.default_rng(45)
        shape = 563, 811, 3
        left, right = (rng.integers(0, 256, shape, dtype=np.uint8) for _ in range(2))
        viewport = (0., 13.7, 443.5, 463.75), (287, 291)
        for field in ('top_permille', 'bottom_permille'):
            window = FloatingWindowState(**{field: 25})
            masked = apply_floating_window_masks(left, right, **{field: 25})
            for mode in ('Farbig', 'Graustufen'):
                with self.subTest(field=field, mode=mode):
                    expected = Image.fromarray(make_anaglyph(*masked, gray=mode == 'Graustufen')).resize(
                        viewport[1], Image.Resampling.LANCZOS, box=viewport[0])
                    actual = render_viewport(left, right, window, mode, viewport, lambda a, b: (a, b))
                    np.testing.assert_array_equal(actual, expected)
