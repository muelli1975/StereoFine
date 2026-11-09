import unittest

import numpy as np
from PIL import Image

from stereofine.anaglyph import make_anaglyph
from stereofine.color_transfer import linear_to_srgb, srgb_to_linear
from stereofine.exposure import apply_exposure
from stereofine.folder_settings import FolderChoices, _patch_preferences
from stereofine.geometry import apply_floating_window_masks
from stereofine.sidecar import SidecarDocument
from stereofine.state import FloatingWindowState, PairState
from stereofine.viewport_render import render_viewport


class ExposureTests(unittest.TestCase):
    def test_exposure_bypasses_neutral_and_matches_linear_light_scaling(self):
        for dtype in (np.uint8, np.uint16):
            peak = np.iinfo(dtype).max
            ramp = np.arange(peak + 1, dtype=dtype)
            self.assertIs(apply_exposure(ramp, 0), ramp)
            for ev in (-2.0, -.3, .7, 2.0):
                with self.subTest(dtype=dtype, ev=ev):
                    linear = srgb_to_linear(ramp.astype(np.float32) / peak)
                    expected = np.rint(linear_to_srgb(linear * np.float32(2 ** ev)) * peak).astype(dtype)
                    actual = apply_exposure(ramp, ev)
                    self.assertEqual(actual.dtype, dtype)
                    np.testing.assert_array_equal(actual, expected)

    def test_exposure_is_the_only_saved_photo_value(self):
        raw = PairState(exposure=.7).to_sidecar(source={}).to_dict()
        self.assertEqual(raw['photo'], {'exposure': .7})
        raw['photo']['other'] = 30
        document = SidecarDocument.from_dict(raw)
        self.assertEqual(document.to_dict()['photo'], {'exposure': .7})
        self.assertEqual(PairState.from_sidecar(document).exposure, .7)
        self.assertEqual(PairState.from_sidecar(SidecarDocument()).exposure, 0)

    def test_folder_exposure_replaces_or_clears_the_value(self):
        raw = PairState(exposure=.7).to_sidecar(source={}).to_dict()
        raw['framing'] = {'aspect': '16:9'}
        result = _patch_preferences(raw, FolderChoices(exposure=.4))
        self.assertEqual(result['photo'], {'exposure': .4})
        self.assertEqual(result['framing'], raw['framing'])
        self.assertEqual(_patch_preferences(raw, FolderChoices(color_enabled=False))['photo'],
                         {'exposure': .7})
        self.assertEqual(FolderChoices(exposure=0).selected, {'exposure'})
        self.assertNotIn('photo', _patch_preferences(result, FolderChoices(exposure=0)))

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
