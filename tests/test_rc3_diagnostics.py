"""Reproduce the seed-selection failure without altering application code."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from stereofine.near_point_recovery import stratified_tail_probe
from stereofine.near_point import confirm_near_edge


class RC3DiagnosticTests(unittest.TestCase):
    @staticmethod
    def scene():
        rng = np.random.default_rng(720)
        left = rng.integers(0, 256, (360, 640), dtype=np.uint8)
        right = cv2.warpAffine(left, np.float32([[1, 0, -20], [0, 1, 0]]), (640, 360))
        left[:50] = 100
        right[:50] = 100
        disparity = np.full(left.shape, 20., dtype=np.float32)
        # The largest values are in a flat strip. They occupy less than 2%
        # of the component and starve its eight production near-tail seeds.
        disparity[20, 30:610] = 25
        confidence = np.zeros(left.shape, bool)
        confidence[16:344, 30:610] = True
        return left, right, disparity, confidence

    def initial(self, left, right, disparity, confidence, baseline_px=20):
        # Isolate the dense-region seeding path. Descriptor/feature detection
        # must not accidentally rescue the deliberately starved component.
        # All image matching and all acceptance gates remain real.
        with patch("cv2.goodFeaturesToTrack", return_value=None):
            return confirm_near_edge(left, right, disparity, confidence, baseline_px*1000/left.shape[1])

    def test_starved_near_component_is_confirmed_with_unchanged_verifier(self):
        left, right, disparity, confidence = self.scene()
        baseline = self.initial(left, right, disparity, confidence)
        self.assertFalse(baseline["confirmed"])
        self.assertEqual(len(baseline["verified_points"]), 0)
        saved = deepcopy(baseline)
        result = stratified_tail_probe(left, right, disparity, confidence, baseline)
        self.assertTrue(result["confirmed"])
        self.assertLess(abs(result["maximum_supported_px"]-20), .1)
        self.assertEqual(result["edge_permille"], baseline["edge_permille"])
        self.assertLessEqual(result["additional_probes"], 128)
        self.assertEqual(baseline, saved)

    def test_already_confirmed_result_is_returned_without_new_probes(self):
        left, right, disparity, confidence = self.scene()
        baseline = {"confirmed": True}
        with patch("stereofine.near_point_recovery.verify_patch") as verifier:
            self.assertIs(stratified_tail_probe(left, right, disparity, confidence, baseline), baseline)
        verifier.assert_not_called()

    def test_unconfirmed_overestimated_percentile_is_not_lowered_or_blessed(self):
        left, right, disparity, confidence = self.scene()
        baseline = self.initial(left, right, disparity, confidence, baseline_px=25)
        result = stratified_tail_probe(left, right, disparity, confidence, baseline)
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["edge_permille"], baseline["edge_permille"])
        self.assertLess(result["maximum_supported_px"], 21)

    def test_flat_surface_remains_unconfirmed(self):
        left, right, disparity, confidence = self.scene()
        left.fill(100)
        right.fill(100)
        baseline = self.initial(left, right, disparity, confidence)
        result = stratified_tail_probe(left, right, disparity, confidence, baseline)
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["verified_points"], [])

    def test_repeating_surface_remains_unconfirmed(self):
        left, _, disparity, confidence = self.scene()
        repeated = np.tile(np.array([0,80,190,255,190,80,0,20], np.uint8), (360,80))
        baseline = self.initial(repeated, repeated, disparity, confidence)
        result = stratified_tail_probe(repeated, repeated, disparity, confidence, baseline)
        self.assertFalse(result["confirmed"])

    def test_no_confident_data_does_not_create_evidence(self):
        left, right, disparity, confidence = self.scene()
        confidence.fill(False)
        baseline = {"confirmed": False}
        self.assertIs(stratified_tail_probe(left, right, disparity, confidence, baseline), baseline)


if __name__ == "__main__":
    unittest.main()
