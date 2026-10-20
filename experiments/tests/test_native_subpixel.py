"""Native measurement invariants with known synthetic correspondences."""
import unittest
from unittest.mock import patch
import cv2
import numpy as np
from experiments.native_subpixel import map_pixel_centers, refine_native_correspondences


class NativeSubpixelTests(unittest.TestCase):
    def scene(self):
        rng = np.random.default_rng(142)
        a = cv2.GaussianBlur(rng.integers(0, 256, (320, 480), dtype=np.uint8), (7, 7), 1.3)
        displacement = np.array([18.35, .65])
        b = cv2.warpAffine(a, np.array([[1., 0, displacement[0]], [0, 1., displacement[1]]]), (480, 320))
        x, y = np.meshgrid(np.arange(40, 420, 16), np.arange(40, 280, 16))
        p = np.column_stack([x.ravel(), y.ravel()]).astype(float)
        truth = p+displacement
        return a, b, p, truth

    def test_native_measurement_improves_precision_and_keeps_depth_disparity(self):
        a, b, p, truth = self.scene()
        q = truth+[.3, -.25]
        before = q.copy()
        result, good, audit = refine_native_correspondences(a, b, p, q)
        self.assertGreater(good.sum(), 50)
        self.assertLess(np.linalg.norm(result[good]-truth[good], axis=1).mean(), .1)
        self.assertGreater(np.median(result[good, 0]-p[good, 0]), 18.)
        np.testing.assert_array_equal(q, before)
        np.testing.assert_array_equal(result[~good], q[~good])
        self.assertEqual(audit['accepted'], good.sum())

    def test_pixel_center_roundtrip_uses_actual_rounded_height(self):
        p = np.array([[0., 0.], [5267., 3499.], [123.45, 678.90]])
        source, target = (3500, 5268), (1993, 3000)
        mapped = map_pixel_centers(p, source, target)
        expected_y = (p[:, 1]+.5)*1993/3500-.5
        np.testing.assert_allclose(mapped[:, 1], expected_y)
        np.testing.assert_allclose(map_pixel_centers(mapped, target, source), p, atol=1e-10)

    def test_flat_image_retains_every_original_seed(self):
        a = np.full((100, 200), 127, dtype=np.uint8)
        p = np.array([[40., 40.], [80., 60.]])
        q = p+[10., .5]
        result, good, _ = refine_native_correspondences(a, a, p, q)
        self.assertFalse(good.any())
        np.testing.assert_array_equal(result, q)

    def test_invalid_coordinates_are_never_sent_to_tracker(self):
        a = np.full((100, 200), 127, dtype=np.uint8)
        p = np.array([[np.nan, 20.], [np.inf, 20.], [-4., 50.], [1., 1.]])
        q = p.copy()
        with patch('cv2.calcOpticalFlowPyrLK', side_effect=AssertionError('tracker called')):
            result, good, _ = refine_native_correspondences(a, a, p, q)
        self.assertFalse(good.any())
        np.testing.assert_array_equal(result, q)

    def test_wrong_image_type_and_coordinate_shape_are_rejected(self):
        a = np.zeros((80, 120), dtype=np.uint8)
        for b, p, q in [(a.astype(np.uint16), np.zeros((1, 2)), np.zeros((1, 2))),
                        (a, np.zeros((1, 2)), np.zeros((2, 2)))]:
            with self.assertRaises(ValueError):
                refine_native_correspondences(a, b, p, q)

    def test_tracker_failure_returns_original_measurements(self):
        a, b, p, truth = self.scene()
        with patch('cv2.calcOpticalFlowPyrLK', return_value=(None, None, None)):
            result, good, audit = refine_native_correspondences(a, b, p, truth)
        self.assertFalse(good.any())
        np.testing.assert_array_equal(result, truth)
        self.assertEqual(audit['reason'], 'forward_measurement_failed')

    def test_empty_measurements_are_valid_and_unchanged(self):
        a = np.zeros((80, 120), dtype=np.uint8)
        result, good, _ = refine_native_correspondences(a, a, np.empty((0, 2)), np.empty((0, 2)))
        self.assertEqual(result.shape, (0, 2))
        self.assertEqual(len(good), 0)


if __name__ == '__main__':
    unittest.main()
