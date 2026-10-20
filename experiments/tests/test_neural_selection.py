"""Safety checks kept outside packaged product tests; no Torch/downloads."""
import unittest

import cv2
import numpy as np

from experiments.select_neural_candidate import (
    assess_measurements, control_points, partition_blocks, select_candidate,
)


class NeuralSelectionTests(unittest.TestCase):
    def setUp(self):
        x, y = np.meshgrid(np.arange(10, 1000, 16), np.arange(10, 700, 16))
        self.points = np.column_stack([x.ravel(), y.ravel()]).astype(float)
        self.before = np.ones(len(self.points))
        self.after = np.full(len(self.points), .2)
        self.split = partition_blocks(self.points)
        self.shape = (700, 1000)

    def select(self, before=None, after=None):
        return select_candidate(self.points, self.before if before is None else before,
            self.after if after is None else after, self.split, self.shape, 1.)

    def test_clear_distributed_gain_passes_both_groups(self):
        result = self.select()
        self.assertEqual(result['selected'], 'lightglue_aliked')
        self.assertTrue(result['selection']['accepted'])
        self.assertTrue(result['confirmation']['accepted'])

    def test_same_blocks_never_cross_the_two_groups(self):
        points = np.array([[65., 65.], [68., 70.], [110., 90.], [129., 65.]])
        folds = partition_blocks(points)
        np.testing.assert_array_equal(folds[:3], np.full(3, folds[0]))
        self.assertNotEqual(folds[0], folds[-1])

    def test_confirmation_can_veto_a_selection_gain(self):
        after = self.after.copy()
        after[self.split == 1] = 1.5
        result = self.select(after=after)
        self.assertTrue(result['selection']['accepted'])
        self.assertFalse(result['confirmation']['accepted'])
        self.assertEqual(result['selected'], 'baseline')

    def test_corner_loss_is_not_hidden_by_global_improvement(self):
        before, after = self.before.copy(), self.after.copy()
        corner = (self.points[:, 0] > 900) & (self.points[:, 1] > 630)
        before[corner], after[corner] = .1, .9
        result = self.select(before, after)
        self.assertEqual(result['selected'], 'baseline')
        self.assertTrue(any(c['passed'] is False for c in result['selection']['corners']))

    def test_nonfinite_candidate_cannot_drop_bad_measurements(self):
        for value in [float('nan'), float('inf')]:
            after = self.after.copy()
            after[0] = value
            self.assertEqual(self.select(after=after)['selected'], 'baseline')

    def test_existing_quality_ceilings_are_a_separate_explicit_policy(self):
        corner = (self.points[:, 0] > 900) & (self.points[:, 1] > 630)
        before, after = self.before.copy(), self.after.copy()
        before[corner], after[corner] = .1, .4
        self.assertEqual(self.select(before, after)['selected'], 'baseline')
        relaxed = select_candidate(self.points, before, after, self.split, self.shape, 1.,
                                   region_quality_floor_analysis=(.5, 1.5))
        self.assertEqual(relaxed['selected'], 'lightglue_aliked')

    def test_explicit_ceilings_still_reject_large_local_loss(self):
        corner = (self.points[:, 0] > 900) & (self.points[:, 1] > 630)
        before, after = self.before.copy(), self.after.copy()
        before[corner], after[corner] = .1, 2.
        relaxed = select_candidate(self.points, before, after, self.split, self.shape, 1.,
                                   region_quality_floor_analysis=(.5, 1.5))
        self.assertEqual(relaxed['selected'], 'baseline')

    def test_insufficient_evidence_retains_baseline(self):
        result = select_candidate(self.points[:10], self.before[:10], self.after[:10],
                                  self.split[:10], self.shape, 1.)
        self.assertEqual(result['selected'], 'baseline')
        self.assertTrue(result['selection']['unverified_corners'])

    def test_already_good_result_is_retained_for_subprecision_gain(self):
        self.assertEqual(self.select(self.after, self.after-.01)['selected'], 'baseline')

    def test_lk_measures_known_translation_and_flat_scene_abstains(self):
        rng = np.random.default_rng(722)
        a = rng.integers(0, 256, (360, 640), dtype=np.uint8)
        b = cv2.warpAffine(a, np.float32([[1, 0, -12], [0, 1, 3]]), (640, 360))
        p, q, folds = control_points(a, b)
        self.assertGreater(len(p), 100)
        np.testing.assert_allclose(np.median(q-p, axis=0), [-12, 3], atol=.05)
        self.assertEqual(len(folds), len(p))
        flat = np.full_like(a, 100)
        p, q, folds = control_points(flat, flat)
        self.assertEqual(len(p), 0)
        decision = assess_measurements(p, np.array([]), np.array([]), flat.shape, 1.)
        self.assertFalse(decision['accepted'])


if __name__ == '__main__':
    unittest.main()
