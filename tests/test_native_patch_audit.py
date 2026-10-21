import unittest

import cv2
import numpy as np

from stereofine.near_point_recovery import native_patch_checks


class NativePatchAuditTests(unittest.TestCase):
    def test_audit_does_not_change_confirmed_displacement(self):
        rng = np.random.default_rng(81)
        a = rng.integers(0, 256, (160, 480), dtype=np.uint8)
        b = cv2.warpAffine(a, np.float32([[1, 0, -24], [0, 1, 0]]), (480, 160))
        points = [dict(x=200, y=80, disparity_px=24.)]
        expected = native_patch_checks(a, b, a.shape, points)
        audit = []
        actual = native_patch_checks(a, b, a.shape, points, audit=audit)
        self.assertEqual(expected, actual)
        self.assertEqual(len(actual), 1)
        self.assertAlmostEqual(actual[0]['disparity_permille'], 50.)
        self.assertEqual(audit[0]['reason'], 'accepted')

    def test_diagnostics_distinguish_texture_and_border(self):
        a = np.full((160, 480), 120, dtype=np.uint8)
        points = [dict(x=200, y=80, disparity_px=0.), dict(x=5, y=80, disparity_px=0.)]
        audit = []
        self.assertEqual(native_patch_checks(a, a, a.shape, points, audit=audit), [])
        self.assertEqual({p['reason'] for p in audit}, {'source_border', 'source_texture'})

    def test_larger_patch_cannot_confirm_periodic_texture(self):
        a = np.tile(np.array([0, 80, 190, 255, 190, 80, 0, 20], np.uint8), (160, 60))
        audit = []
        self.assertEqual(native_patch_checks(a, a, a.shape,
            [dict(x=200, y=80, disparity_px=0.)], patch_radius=32, audit=audit), [])
        self.assertEqual(audit[0]['reason'], 'forward_uniqueness')


if __name__ == '__main__':
    unittest.main()
