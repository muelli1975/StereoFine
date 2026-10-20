from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from stereofine.alignment import _y_residual_field_from_payload, warp_pair_symmetric
from stereofine.alignment_refinement import corrected_point_residuals
from stereofine.lens_refinement import refine_residual_field
from stereofine.state import reproducible_alignment_correction


class LensRefinementTests(unittest.TestCase):
    def points(self):
        x, y = np.meshgrid(np.arange(20, 780, 10), np.arange(20, 580, 10))
        left = np.column_stack([x.ravel(), y.ravel()]).astype(float)
        right = left + [-20, 0]
        # Smooth asymmetric edge error that a quadratic cannot reproduce.
        xn = (left[:, 0] - 399.5) / 800
        yn = (left[:, 1] - 299.5) / 600
        right[:, 1] += 32 * xn * xn * yn + 8 * yn ** 3
        return left, right

    def baseline(self):
        return {"model": "Affine", "correction": {
            "scale": 1., "rotation_deg": 0., "vertical_shift_px": 0.,
        }}

    def run_refinement(self, left, right, baseline=None):
        gray = np.zeros((600, 800), np.uint8)
        baseline = baseline or self.baseline()
        # These tests isolate geometry and validation. Real patch agreement
        # itself is tested with shifted image data in test_alignment_refinement.
        with patch("stereofine.lens_refinement.patch_correlations", return_value=np.ones(len(left))):
            return refine_residual_field(baseline, left, right, gray, gray, 1.)

    def test_cubic_edge_error_reduced_and_held_out_blocks_do_not_train(self):
        left, right = self.points()
        from stereofine.lens_refinement import _weighted_lstsq
        matrices = []

        def capture(matrix, target, weights):
            matrices.append(matrix.copy())
            return _weighted_lstsq(matrix, target, weights)

        with patch("stereofine.lens_refinement._weighted_lstsq", side_effect=capture):
            result = self.run_refinement(left, right)
        self.assertTrue(result["correction"]["lens_refinement_validation"]["accepted"])
        blocks = np.floor(left / 32).astype(np.int64)
        holdout = (blocks[:, 0] * 73856093 + blocks[:, 1] * 19349663) % 5 == 0
        # The initial design's x column encodes the original average eye x.
        # Check exact training row count; per-x overlap across rows is normal.
        expected = (~holdout) & (np.abs(right[:, 1] - left[:, 1]) <= 3)
        self.assertEqual(len(matrices[0]), int(expected.sum()))
        np.testing.assert_allclose(matrices[0][:, 1],
                                   ((left[expected, 0] + right[expected, 0]) / 2 - 399.5) / 800)
        np.testing.assert_allclose(matrices[0][:, 2],
                                   ((left[expected, 1] + right[expected, 1]) / 2 - 299.5) / 600)
        residual = corrected_point_residuals(result["correction"], left, right, (600, 800), 1.)
        self.assertLess(np.percentile(np.abs(residual), 95), .01)
        self.assertEqual(result["model"], "Affine + yCubic")

    def test_perfect_pair_keeps_original_geometry(self):
        left, _ = self.points()
        baseline = self.baseline()
        result = self.run_refinement(left, left + [-20, 0], baseline)
        self.assertIs(result, baseline)
        self.assertNotIn("y_residual_apply", result["correction"])

    def test_large_disagreement_only_in_check_blocks_is_not_fitted_away(self):
        left, right = self.points()
        blocks = np.floor(left / 32).astype(np.int64)
        held = (blocks[:, 0] * 73856093 + blocks[:, 1] * 19349663) % 5 == 0
        # Training points have no distortion; check points disagree independently.
        right[~held, 1] = left[~held, 1]
        result = self.run_refinement(left, right)
        self.assertFalse(result["correction"]["lens_refinement_validation"]["accepted"])
        self.assertNotIn("y_residual_apply", result["correction"])

    def test_sparse_or_collinear_support_is_rejected(self):
        left, right = self.points()
        result = self.run_refinement(left[:80], right[:80])
        self.assertFalse(result["correction"]["lens_refinement_validation"]["accepted"])

    def test_unobserved_edge_extrapolation_beyond_limit_is_rejected(self):
        left, _ = self.points()
        right = left + [-20, 0]
        right[:, 1] += 125 * ((left[:, 0] - 399.5) / 800) ** 3
        result = self.run_refinement(left, right)
        audit = result["correction"]["lens_refinement_validation"]
        self.assertFalse(audit["accepted"])
        self.assertEqual(audit["reason"], "field_limit")

    def test_optional_fit_failure_keeps_working_previous_result(self):
        left, right = self.points()
        baseline = self.baseline()
        with patch("stereofine.lens_refinement._weighted_lstsq", side_effect=np.linalg.LinAlgError):
            result = self.run_refinement(left, right, baseline)
        self.assertIs(result, baseline)
        self.assertEqual(result["correction"]["lens_refinement_validation"]["reason"], "numerical_fit_failed")

    def test_cubic_payload_survives_cache_and_changes_actual_raster(self):
        rng = np.random.default_rng(33)
        image = rng.integers(0, 256, (80, 120, 3), dtype=np.uint8)
        correction = self.baseline()["correction"]
        correction["y_residual_apply"] = {
            "enabled": True, "model_name": "y_cubic", "terms": ["x2y"],
            "coefficients": [{"term": "x2y", "coefficient_fullres_px": 16.}],
            "normalization": {}, "max_abs_correction_px": 8.,
        }
        compact = reproducible_alignment_correction(correction)
        a, b = warp_pair_symmetric(image, image, correction)
        c, d = warp_pair_symmetric(image, image, compact)
        np.testing.assert_array_equal(a, c)
        np.testing.assert_array_equal(b, d)
        self.assertGreater(float(np.mean(np.abs(a.astype(float) - b.astype(float)))), 1.)
        field = _y_residual_field_from_payload(80, 120, compact["y_residual_apply"])
        # Independently calculate a known point from the cubic field equation.
        self.assertAlmostEqual(float(field[60, 100]), 16 * ((100-59.5)/120)**2 * ((60-39.5)/80), places=6)


if __name__ == "__main__":
    unittest.main()
