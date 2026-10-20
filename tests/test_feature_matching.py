from __future__ import annotations

import unittest
import cv2
import numpy as np

from stereofine.feature_matching import sift_ratio_matches


class ExactMatchingTests(unittest.TestCase):
    def assert_original_matches(self, query, train):
        original = cv2.BFMatcher(cv2.NORM_L2).knnMatch(query, train, k=2)
        expected = [(m.queryIdx, m.trainIdx, m.distance) for pair in original if len(pair) == 2
                    for m, n in [pair] if m.distance < .75 * n.distance]
        actual = [(m.queryIdx, m.trainIdx, m.distance) for m in sift_ratio_matches(query, train)]
        self.assertEqual(expected, actual)

    def test_quantized_vectors_match_original_indices_distances_and_ratio(self):
        rng = np.random.default_rng(2104)
        train = rng.integers(0, 256, (700, 128)).astype(np.float32)
        query = train[rng.integers(0, len(train), 650)].copy()
        query += rng.integers(-2, 3, query.shape)
        np.clip(query, 0, 255, out=query)
        self.assert_original_matches(query, train)

    def test_extreme_values_duplicate_vectors_and_ratio_boundary(self):
        train = np.zeros((8, 128), np.float32)
        train[1] = 255
        train[2, :64] = 255
        train[3] = train[2]
        train[4, 0], train[5, 0] = 3, 4
        train[6], train[7] = 100, 101
        self.assert_original_matches(np.vstack([train, np.ones((1, 128), np.float32)]), train)

    def test_nonquantized_vectors_use_unchanged_fallback(self):
        rng = np.random.default_rng(222)
        train = rng.random((100, 128), dtype=np.float32)
        self.assert_original_matches(train[:20].copy(), train)

    def test_noncontiguous_vectors_and_short_training_set(self):
        rng = np.random.default_rng(225)
        train = rng.integers(0, 256, (200, 256)).astype(np.float32)[:, ::2]
        self.assert_original_matches(train[::3], train)
        self.assertEqual(sift_ratio_matches(train[:2], train[:1]), [])


if __name__ == "__main__":
    unittest.main()
