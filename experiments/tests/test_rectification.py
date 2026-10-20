"""Geometric invariants for the isolated OpenCV comparison, no image downloads."""
import unittest

import cv2
import numpy as np

from experiments.render_rectification import native_matrix, render_homographies

from experiments.compare_rectification import (
    fit_rectification, jacobian, normalize_gauge, training_mask, transform,
    warp_diagnostics, withheld,
)


class RectificationTests(unittest.TestCase):
    def test_projected_3d_scene_rectifies_external_points(self):
        rng = np.random.default_rng(321)
        xyz = rng.uniform([-2., -1.4, 4.], [2., 1.4, 12.], size=(800, 3))
        k = np.array([[700., 0, 400], [0, 700., 300], [0, 0, 1.]])
        rotation = cv2.Rodrigues(np.array([.02, -.04, .015]))[0]
        left = xyz @ k.T
        right = (xyz @ rotation.T + [-.18, .03, 0]) @ k.T
        p, q = left[:, :2]/left[:, 2:], right[:, :2]/right[:, 2:]
        train = training_mask(p, q)
        h1, h2, details = fit_rectification(p[train], q[train], (600, 800))
        dy = transform(h2, q[~train])[:, 1]-transform(h1, p[~train])[:, 1]
        self.assertGreater(len(dy), 50)
        # Robust F estimation uses a one-pixel inlier threshold; test a
        # subpixel external result rather than exact algebraic recovery.
        self.assertLess(np.max(np.abs(dy)), .1)
        self.assertGreater(details['inliers'], 100)
        # Horizontal disparity from varying depth must survive rectification.
        dx = transform(h2, q[~train])[:, 0]-transform(h1, p[~train])[:, 0]
        self.assertGreater(np.ptp(dx), 10.)

    def test_gauge_removes_arbitrary_common_image_shrink(self):
        h1 = np.array([[.01, .0001, 3], [0, .01, 5], [0, 0, 1.]])
        h2 = np.array([[.012, 0, 5], [0, .01, 5], [0, 0, 1.]])
        a, b, scale = normalize_gauge(h1, h2, (600, 800))
        center = [399.5, 299.5]
        area = np.sqrt(abs(np.linalg.det(jacobian(a, center))*np.linalg.det(jacobian(b, center))))
        self.assertAlmostEqual(area, 1., places=10)
        self.assertGreater(scale, 90.)

    def test_training_excludes_withheld_blocks_in_both_eyes(self):
        rng = np.random.default_rng(42)
        p, q = rng.uniform(0, 2000, (2, 3000, 2))
        good = training_mask(p, q)
        self.assertGreater(good.sum(), 100)
        for points in (p[good], q[good]):
            self.assertFalse(withheld(points).any())
            for dx in (-16, 0, 16):
                for dy in (-16, 0, 16):
                    self.assertFalse(withheld(points+[dx, dy]).any())

    def test_nearby_points_of_reserved_block_never_train(self):
        p = np.array([[5., 5.], [127., 5.], [129., 5.], [145., 5.]])
        self.assertTrue(withheld(p[:2]).all())
        self.assertFalse(training_mask(p, p)[:3].any())

    def test_horizon_is_detected_across_image(self):
        h = np.array([[1., 0, 0], [0, 1, 0], [.003, 0, -1.]])
        self.assertTrue(warp_diagnostics(h, np.eye(3), (600, 800))[0]['horizon'])

    def test_undefined_projection_rejected(self):
        h = np.array([[1., 0, 0], [0, 1, 0], [0, 0, 0.]])
        with self.assertRaises(ValueError):
            transform(h, np.array([[1., 2.]]))

    def test_native_coordinate_basis_preserves_pixel_centers(self):
        h = np.array([[1.01, .002, 4.], [.003, .99, 7.], [.00001, -.00002, 1.]])
        scale = .4
        points = np.array([[100., 300.], [2700., 1800.]])
        analysis = (points+.5)*scale-.5
        expected = (transform(h, analysis)+.5)/scale-.5
        np.testing.assert_allclose(transform(native_matrix(h, scale), points), expected, atol=1e-10)

    def test_identity_raster_keeps_exact_source_inside_valid_crop(self):
        rng = np.random.default_rng(44)
        image = rng.integers(0, 256, (70, 100, 3), dtype=np.uint8)
        a, b, crop = render_homographies(image, image, np.eye(3), np.eye(3))
        self.assertEqual(crop, [6, 6, 94, 64])  # existing rectangle helper adds 2px guard
        np.testing.assert_array_equal(a, image[6:64, 6:94])
        np.testing.assert_array_equal(b, a)

    def test_insufficient_training_rejected(self):
        with self.assertRaisesRegex(ValueError, '16'):
            fit_rectification(np.zeros((8, 2)), np.zeros((8, 2)), (600, 800))


if __name__ == '__main__':
    unittest.main()
