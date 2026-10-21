import unittest

import cv2
import numpy as np

from experiments.native_footprint import check_native_footprint


class NativeFootprintTests(unittest.TestCase):
    def test_context_disambiguates_locally_identical_patches(self):
        rng = np.random.default_rng(117)
        a = rng.integers(0, 256, (400, 1440), dtype=np.uint8)
        a[180:221, 780:821] = a[180:221, 380:421]
        b = cv2.warpAffine(a, np.float32([[1, 0, -24], [0, 1, 0]]), (1440, 400))
        # Pixel-centre map gives the known native point (400, 200).
        points = [dict(x=(400.5)/4-.5, y=(200.5)/4-.5, disparity_px=6.)]
        before, _ = check_native_footprint(a, b, (100, 360), points)
        after, audit = check_native_footprint(a, b, (100, 360), points, enabled=True)
        self.assertEqual(before, [])
        self.assertEqual(len(after), 1)
        self.assertAlmostEqual(after[0]['disparity_permille'], 24/1.44)
        self.assertEqual([p['reason'] for p in audit], ['forward_uniqueness', 'accepted'])

    def test_missing_local_texture_is_not_rescued_by_surroundings(self):
        rng = np.random.default_rng(195)
        a = rng.integers(0, 256, (400, 1440), dtype=np.uint8)
        a[180:221, 380:421] = 120
        b = a.copy()
        points = [dict(x=(400.5)/4-.5, y=(200.5)/4-.5, disparity_px=0.)]
        after, audit = check_native_footprint(a, b, (100, 360), points, enabled=True)
        self.assertEqual(after, [])
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]['reason'], 'source_texture')


if __name__ == '__main__':
    unittest.main()
