"""Far-end confidence must reject unsupported range inflation."""
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from stereofine.disparity import analyze_horizontal_disparity, _rgb_to_luma_uint8
from stereofine.near_point import confirm_near_edge


class FarPointTests(unittest.TestCase):
    def test_recovered_far_marker_tracks_the_revised_measurement(self):
        near = dict(left=[.7, .8], right=[.703, .8], target_permille=-3.0, tentative=False)
        old_far = dict(left=[.04, .12], right=[.058, .12], target_permille=-18.0, tentative=True)
        verified_far = dict(left=[.2, .35], right=[.21612, .35], target_permille=-16.12, tentative=False)
        initial = dict(ready=True, uncertain_reasons=['far_edge_unconfirmed'],
                       near_confirmation=dict(confirmed=True, unsupported_extreme=False),
                       far_confirmation=dict(maximum_supported_px=None), analysis_width=1000,
                       analysis_height=500, low_edge_permille=-18.0, high_edge_permille=-3.0,
                       deviation_permille=15.0, endpoints=dict(markers={'near': near, 'far': old_far}))
        evidence = dict(endpoints_confirmed=True, observed_span_permille=12.82, endpoints={
            'near': dict(confirmed=True, edge_permille=-3.3),
            'far': dict(confirmed=True, edge_permille=-16.12, marker=verified_far),
        })
        pair = np.zeros((1000, 2000, 3), dtype=np.uint8)
        with patch('stereofine.disparity._analyze_horizontal_disparity',
                   side_effect=[initial, dict(ready=True)]), patch(
                       'stereofine.range_evidence.measure_range_evidence', side_effect=[evidence, evidence]):
            result = analyze_horizontal_disparity(pair, pair, 1000)
        self.assertTrue(result['range_recovery']['accepted'])
        self.assertAlmostEqual(result['low_edge_permille'], -16.62)
        self.assertEqual(result['endpoints']['markers']['near'], near)
        far = result['endpoints']['markers']['far']
        self.assertEqual(far['left'], verified_far['left'])
        self.assertEqual(far['target_permille'], result['low_edge_permille'])

    @staticmethod
    def scene():
        rng = np.random.default_rng(914)
        left = cv2.GaussianBlur(rng.integers(0, 256, (160, 320), dtype=np.uint8), (3, 3), 0)
        right = cv2.warpAffine(left, np.float32([[1, 0, 8], [0, 1, 0]]), (320, 160))
        return left, right

    def test_reflected_negative_disparity_plane_is_supported(self):
        left, right = self.scene()
        result = confirm_near_edge(left[:, ::-1].copy(), right[:, ::-1].copy(),
                                   np.full(left.shape, 8.), np.ones(left.shape, bool), 25.)
        self.assertTrue(result['confirmed'])
        self.assertAlmostEqual(result['maximum_supported_px'], 8., delta=.3)

    def test_spurious_far_plane_is_not_confirmed_by_nearer_texture(self):
        left, right = self.scene()
        # Dense output claims -20 px; real correspondence is only -8 px.
        result = confirm_near_edge(left[:, ::-1].copy(), right[:, ::-1].copy(),
                                   np.full(left.shape, 20.), np.ones(left.shape, bool), 62.5)
        self.assertFalse(result['confirmed'])

    def test_far_uncertainty_does_not_change_near_measurement(self):
        left, right = self.scene()
        rgb = lambda a: np.repeat(a[..., None], 3, axis=2)
        baseline = analyze_horizontal_disparity(rgb(left), rgb(right), 320)
        from stereofine.near_point import confirm_near_edge as original
        def unconfirmed_far(*args):
            result = original(*args)
            if np.array_equal(args[0], _rgb_to_luma_uint8(rgb(left))[:, ::-1]):
                result['confirmed'] = False
            return result
        with patch('stereofine.near_point.confirm_near_edge', side_effect=unconfirmed_far):
            result = analyze_horizontal_disparity(rgb(left), rgb(right), 320)
        self.assertIn('far_edge_unconfirmed', result['uncertain_reasons'])
        self.assertEqual(result['status'], 'uncertain')
        self.assertEqual(result['high_edge_permille'], baseline['high_edge_permille'])
        self.assertEqual(result['low_edge_permille'], baseline['low_edge_permille'])

    def test_supported_farther_surface_cannot_silently_pass_percentile_range(self):
        left, right = self.scene()
        rgb = lambda a: np.repeat(a[..., None], 3, axis=2)
        from stereofine.near_point import confirm_near_edge as original
        def farther_surface(*args):
            result = original(*args)
            if np.array_equal(args[0], _rgb_to_luma_uint8(rgb(left))[:, ::-1]):
                result['confirmed'] = True
                result['maximum_supported_px'] = args[4] * left.shape[1] / 1000 + 4
            return result
        with patch('stereofine.near_point.confirm_near_edge', side_effect=farther_surface):
            result = analyze_horizontal_disparity(rgb(left), rgb(right), 320)
        self.assertIn('far_edge_outside_estimate', result['uncertain_reasons'])
        self.assertEqual(result['status'], 'uncertain')


if __name__ == '__main__':
    unittest.main()
