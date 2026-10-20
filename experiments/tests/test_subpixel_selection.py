"""Independent confirmation and pooled regional veto safety checks."""
import unittest
import numpy as np
from experiments.compare_rectification import withheld
from experiments.select_subpixel_candidate import confirmation_split, select, apply_reference_veto


class SubpixelSelectionTests(unittest.TestCase):
    def setUp(self):
        x, y = np.meshgrid(np.arange(12, 5990, 32), np.arange(12, 3990, 32))
        points = np.column_stack([x.ravel(), y.ravel()]).astype(float)
        self.points = points[withheld(points)]
        self.split = confirmation_split(self.points)
        self.before = np.ones(len(self.points))
        self.after = np.full(len(self.points), .2)
        self.shape = (4000, 6000)

    def choose(self, before=None, after=None):
        return select(self.points, self.before if before is None else before,
            self.after if after is None else after, self.split, self.shape, 1.)

    def test_clear_gain_must_pass_both_stages_and_pool(self):
        row = self.choose()
        self.assertEqual(row['selected'], 'subpixel')
        self.assertTrue(all(row[k]['accepted'] for k in ('selection', 'confirmation', 'pooled')))

    def test_confirmation_rejects_a_selection_only_gain(self):
        after = self.after.copy()
        after[self.split == 1] = 1.2
        row = self.choose(after=after)
        self.assertTrue(row['selection']['accepted'])
        self.assertFalse(row['confirmation']['accepted'])
        self.assertEqual(row['selected'], 'baseline')

    def test_reserved_blocks_do_not_split_between_stages(self):
        block = np.floor(self.points/128).astype(int)
        for label in np.unique(block, axis=0):
            inside = np.all(block == label, axis=1)
            self.assertEqual(len(np.unique(self.split[inside])), 1)

    def test_non_reserved_controls_are_rejected(self):
        with self.assertRaises(ValueError):
            confirmation_split(np.array([[140., 10.]]))

    def test_regional_loss_cannot_hide_in_global_gain(self):
        corner = (self.points[:, 0] > .9*self.shape[1]) & (self.points[:, 1] > .9*self.shape[0])
        before, after = self.before.copy(), self.after.copy()
        before[corner], after[corner] = .1, .5
        self.assertEqual(self.choose(before, after)['selected'], 'baseline')

    def test_pool_detects_region_too_sparse_in_each_stage(self):
        corner = (self.points[:, 0] > .9*self.shape[1]) & (self.points[:, 1] > .9*self.shape[0])
        keep = ~corner
        for fold in (0, 1):
            keep[np.flatnonzero(corner & (self.split == fold))[:4]] = True
        p, split = self.points[keep], self.split[keep]
        before, after = self.before[keep].copy(), self.after[keep].copy()
        thin = corner[keep]
        before[thin], after[thin] = .1, .5
        row = select(p, before, after, split, self.shape, 1.)
        self.assertTrue(row['selection']['accepted'])
        self.assertTrue(row['confirmation']['accepted'])
        self.assertFalse(row['pooled']['accepted'])
        self.assertEqual(row['selected'], 'baseline')

    def test_nonfinite_values_cannot_disappear_from_validation(self):
        after = self.after.copy()
        after[0] = np.nan
        self.assertEqual(self.choose(after=after)['selected'], 'baseline')

    def test_gain_over_withheld_fit_cannot_replace_better_actual_rc3(self):
        decision = self.choose()
        self.assertEqual(decision['selected'], 'subpixel')
        stronger_reference = np.full(len(self.points), .1)
        row = apply_reference_veto(decision, self.points, stronger_reference, self.after,
                                  self.split, self.shape, 1.)
        self.assertEqual(row['experimental_selected'], 'subpixel')
        self.assertEqual(row['selected'], 'baseline')
        self.assertEqual(row['reason'], 'actual_rc3_reference_not_improved')

    def test_small_or_empty_evidence_retains_baseline(self):
        for n in (0, 10):
            row = select(self.points[:n], self.before[:n], self.after[:n], self.split[:n], self.shape, 1.)
            self.assertEqual(row['selected'], 'baseline')


if __name__ == '__main__':
    unittest.main()
