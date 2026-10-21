"""Pixel identity, invalidation and overlay isolation of the display cache."""
import importlib.util
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from stereofine.preview import PreviewImageCache, draw_grid_overlay, draw_measure_cross_overlay


class PreviewDisplayCacheTests(unittest.TestCase):
    def setUp(self):
        self.source = Image.fromarray(np.random.default_rng(46).integers(
            0, 256, (400, 640, 3), dtype=np.uint8))
        self.cache = PreviewImageCache()

    def test_repeated_frames_resize_once_and_preserve_pixels(self):
        expected = self.source.resize((480, 300), Image.Resampling.LANCZOS)
        with patch.object(self.source, 'resize', wraps=self.source.resize) as resize:
            first = self.cache.scaled(self.source, (480, 300), Image.Resampling.LANCZOS)
            for _ in range(30):
                self.assertIs(self.cache.scaled(self.source, (480, 300), Image.Resampling.LANCZOS), first)
            self.assertEqual(resize.call_count, 1)
        self.assertEqual(first.tobytes(), expected.tobytes())

    def test_source_size_and_resampling_changes_never_reuse_stale_pixels(self):
        other = Image.new('RGB', self.source.size, (32, 64, 128))
        for source, size, sampling in [
            (self.source, (480, 300), Image.Resampling.BILINEAR),
            (self.source, (480, 300), Image.Resampling.LANCZOS),
            (self.source, (320, 200), Image.Resampling.LANCZOS),
            (other, (320, 200), Image.Resampling.LANCZOS),
            (self.source, self.source.size, Image.Resampling.LANCZOS),
        ]:
            expected = source.copy() if size == source.size else source.resize(size, sampling)
            actual = self.cache.scaled(source, size, sampling)
            self.assertEqual(actual.tobytes(), expected.tobytes())
            self.assertIsNot(actual, source)

    @unittest.skipUnless(importlib.util.find_spec('cv2'), 'OpenCV required for reticle drawing')
    def test_moving_cross_and_grid_do_not_accumulate_on_cached_background(self):
        size = (480, 300)
        background = self.cache.scaled(self.source, size, Image.Resampling.LANCZOS)
        original = background.tobytes()
        for x, y in [(240, 150), (1, 1), (479, 299), (120, 220)]:
            cached = draw_measure_cross_overlay(background, x, y)
            fresh = draw_measure_cross_overlay(self.source.resize(size, Image.Resampling.LANCZOS), x, y)
            self.assertEqual(cached.tobytes(), fresh.tobytes())
            self.assertEqual(background.tobytes(), original)
        draw_grid_overlay(background, '50 Promille', 'White')
        self.assertEqual(background.tobytes(), original)


if __name__ == '__main__':
    unittest.main()
