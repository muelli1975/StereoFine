"""Subpixel correspondence tests without free image correction."""
import unittest
import cv2
import numpy as np
from experiments.compare_rectification import training_mask
from experiments.compare_subpixel import refine_measurements


class SubpixelTests(unittest.TestCase):
    def scene(self, shift):
        rng = np.random.default_rng(33)
        image = rng.integers(0, 256, (320, 480), dtype=np.uint8)
        image = cv2.GaussianBlur(image, (7, 7), 1.3)
        right = cv2.warpAffine(image, np.array([[1., 0, shift[0]], [0, 1., shift[1]]]), (480, 320))
        x, y = np.meshgrid(np.arange(32, 440, 16), np.arange(32, 280, 16))
        p = np.column_stack([x.ravel(), y.ravel()]).astype(float)
        truth = p+shift
        q = truth+[.30, -.25]
        keep = training_mask(p, q)
        return image, right, p[keep], q[keep], truth[keep]

    def test_known_translation_measurements_become_more_precise(self):
        a, b, p, q, truth = self.scene([2.35, .65])
        result, changed = refine_measurements(a, b, p, q)
        self.assertGreater(changed.sum(), 20)
        before = np.linalg.norm(q[changed]-truth[changed], axis=1).mean()
        after = np.linalg.norm(result[changed]-truth[changed], axis=1).mean()
        self.assertLess(after, .1)
        self.assertLess(after, before/3)
        np.testing.assert_array_equal(result[~changed], q[~changed])

    def test_horizontal_scene_disparity_remains_measured(self):
        a, b, p, q, truth = self.scene([15.35, .65])
        result, changed = refine_measurements(a, b, p, q)
        self.assertGreater(changed.sum(), 20)
        self.assertGreater(np.median(result[changed, 0]-p[changed, 0]), 15.)
        self.assertLess(np.abs(result[changed, 0]-truth[changed, 0]).mean(), .1)

    def test_textureless_measurements_remain_unchanged(self):
        image = np.full((200, 300), 127, dtype=np.uint8)
        p = np.array([[90., 50.], [100., 70.]])
        q = p+[8., .5]
        result, changed = refine_measurements(image, image, p, q)
        self.assertFalse(changed.any())
        np.testing.assert_array_equal(result, q)


if __name__ == '__main__':
    unittest.main()
