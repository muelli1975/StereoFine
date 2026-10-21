import unittest

import cv2
import numpy as np

from experiments.range_evidence import measure_range_evidence
from stereofine.disparity import analyze_horizontal_disparity


def scene(seed=23, sky=False, small=False, exposure=False, occlusion=False):
    rng = np.random.default_rng(seed)
    h, w = 960, 1440
    left = cv2.GaussianBlur(rng.integers(0, 256, (h, w), dtype=np.uint8), (3, 3), 0)
    right = cv2.warpAffine(left, np.float32([[1, 0, -8], [0, 1, 0]]), (w, h))
    if sky:
        left[:h//2] = 145
        right[:h//2] = 145
    for x, y, d, size in [(300, 650, -24, 100), (1180, 810, 48, 64 if small else 140)]:
        patch = cv2.GaussianBlur(rng.integers(0, 256, (size, size), dtype=np.uint8), (3, 3), 0)
        left[y:y+size, x:x+size] = patch
        right[y:y+size, x-d:x-d+size] = patch
    if occlusion:
        right[510:610, 600:700] = rng.integers(0, 256, (100, 100), dtype=np.uint8)
    if exposure:
        right = np.clip(right.astype(float)*.8+15, 0, 255).astype(np.uint8)
    return [np.repeat(a[..., None], 3, axis=2) for a in [left, right]]


class RangeEvidenceTests(unittest.TestCase):
    def test_additional_fixed_random_scenes_and_swapped_eyes(self):
        # These seeds are distinct from the development fixture. Both disparity
        # signs and different appearance/visibility changes use the same gates.
        for seed, options in [(41, dict(sky=True)), (67, dict(small=True)),
                              (113, dict(exposure=True)), (211, dict(occlusion=True))]:
            left, right = scene(seed, **options)
            for swap in [False, True]:
                a, b = (right, left) if swap else (left, right)
                with self.subTest(seed=seed, swap=swap):
                    dense = analyze_horizontal_disparity(a, b, 1000)
                    result = measure_range_evidence(a, b, 1000, dense)
                    self.assertTrue(result['endpoints_confirmed'])
                    self.assertAlmostEqual(result['observed_span_permille'], 50., delta=1.5)

    def test_single_plane_remains_zero_range(self):
        rng = np.random.default_rng(907)
        image = cv2.GaussianBlur(rng.integers(0, 256, (480, 720), dtype=np.uint8), (3, 3), 0)
        left = np.repeat(image[..., None], 3, axis=2)
        right = cv2.warpAffine(left, np.float32([[1, 0, -12], [0, 1, 0]]), (720, 480))
        dense = analyze_horizontal_disparity(left, right, 720)
        result = measure_range_evidence(left, right, 720, dense)
        self.assertTrue(result['endpoints_confirmed'])
        self.assertAlmostEqual(result['observed_span_permille'], 0., delta=.5)

    def test_known_signed_endpoints_at_two_analysis_scales(self):
        for options in [dict(), dict(sky=True), dict(small=True), dict(exposure=True), dict(occlusion=True)]:
            left, right = scene(**options)
            for width in [720, 1000]:
                with self.subTest(options=options, width=width):
                    dense = analyze_horizontal_disparity(left, right, width)
                    result = measure_range_evidence(left, right, width, dense)
                    self.assertTrue(result['endpoints_confirmed'], result['endpoints'])
                    self.assertAlmostEqual(result['endpoints']['far']['edge_permille'], -24/1.44, delta=1.)
                    self.assertAlmostEqual(result['endpoints']['near']['edge_permille'], 48/1.44, delta=1.)
                    self.assertAlmostEqual(result['observed_span_permille'], 50., delta=1.5)
                    self.assertEqual(result['completeness'], 'not_established')

    def test_textureless_and_repeated_images_do_not_produce_confirmed_span(self):
        for image in [np.full((240, 720), 145, np.uint8),
                      np.tile(np.array([0, 80, 190, 255, 190, 80, 0, 20], np.uint8), (240, 90))]:
            rgb = np.repeat(image[..., None], 3, axis=2)
            result = measure_range_evidence(rgb, rgb, 720)
            self.assertFalse(result['endpoints_confirmed'])
            self.assertIsNone(result['observed_span_permille'])


if __name__ == '__main__':
    unittest.main()
