from __future__ import annotations

import unittest
from unittest.mock import patch
import cv2
import numpy as np

from stereofine.alignment_refinement import patch_correlations, corrected_point_residuals, refine_alignment


class RefinementTests(unittest.TestCase):
    def test_photometric_checks_keep_real_shift_and_reject_flat_patch(self):
        rng = np.random.default_rng(22)
        left = rng.integers(0, 256, (100, 180), dtype=np.uint8)
        right = cv2.warpAffine(left, np.float32([[1, 0, -12], [0, 1, 2]]), (180, 100))
        points = np.array([[50., 40.], [100., 70.]])
        scores = patch_correlations(left, right, points, points + [-12, 2])
        self.assertTrue(np.all(scores > .99))
        self.assertTrue(np.all(patch_correlations(left * 0, right * 0, points, points + [-12, 2]) < 0))

    def test_corrected_coordinates_follow_symmetric_vertical_translation(self):
        points = np.array([[50., 40.], [100., 70.]])
        correction = dict(scale=1., rotation_deg=0., vertical_shift_px=-2.)
        np.testing.assert_allclose(corrected_point_residuals(correction, points, points + [-12, 2], (100, 180), 1), 0)

    def exercise(self, candidate_error):
        x, y = np.meshgrid(np.arange(20, 600, 12), np.arange(20, 400, 12))
        points = np.column_stack([x.ravel(), y.ravel()]).astype(float)
        mask = np.arange(len(points)) % 2 == 0
        baseline = {"correction": {"y_residual_apply": {"enabled": True}}}
        candidate = {"correction": {"y_residual_apply": {"enabled": True}}}
        captured = {}

        def fitter(*args, **kwargs):
            captured["mask"] = kwargs["inlier_mask"]
            return candidate

        def residuals(correction, left, *args):
            return np.full(len(left), 2. if correction is baseline["correction"] else candidate_error)

        gray = np.zeros((420, 620), np.uint8)
        with patch("stereofine.alignment_refinement.patch_correlations", return_value=np.ones(len(points))), \
             patch("stereofine.alignment_refinement.corrected_point_residuals", side_effect=residuals), \
             patch("stereofine.alignment._analyze_matched_points", side_effect=fitter):
            result = refine_alignment(baseline, points, points, mask, gray, gray, 1, "AKAZE")
        blocks = np.floor(points / 32).astype(np.int64)
        holdout = (blocks[:, 0] * 73856093 + blocks[:, 1] * 19349663) % 5 == 0
        self.assertFalse(np.any(captured["mask"] & holdout))
        return result, baseline, candidate

    def test_check_blocks_never_train_and_useful_refit_is_selected(self):
        result, _, candidate = self.exercise(.4)
        self.assertIs(result, candidate)
        self.assertTrue(result["correction"]["refinement_validation"]["accepted"])

    def test_unhelpful_refit_preserves_original_result(self):
        result, baseline, _ = self.exercise(2.)
        self.assertIs(result, baseline)
        self.assertFalse(result["correction"]["refinement_validation"]["accepted"])


if __name__ == "__main__":
    unittest.main()
