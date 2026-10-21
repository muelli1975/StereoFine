"""Admit real native correspondences without certifying unseen scene surfaces."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2

from stereofine.disparity import analyze_horizontal_disparity, _analyze_horizontal_disparity
from stereofine.framing import compute_auto_near_framing
from stereofine.range_evidence import measure_range_evidence
from tests.stereo_fixtures import scene


def sky_outlier(left, right, width):
    result = _analyze_horizontal_disparity(left, right, width)
    if width == 720:
        # Inject a dense far-tail failure only. All point searches still use
        # the real pixels, including the separate control resolution.
        result['low_edge_permille'] = -80.
        result['deviation_permille'] = result['high_edge_permille']+80.
        result['far_confirmation'] = dict(result['far_confirmation'], confirmed=False,
                                          maximum_supported_px=None)
        result['uncertain_reasons'] = ['far_edge_unconfirmed']
        result.update(status='uncertain', traffic='gray')
    return result


class ObservedRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cv2.setNumThreads(2)
        cls.left, cls.right = scene(sky=True)

    def run_recovery(self):
        with patch('stereofine.disparity._analyze_horizontal_disparity', side_effect=sky_outlier):
            return analyze_horizontal_disparity(self.left, self.right, 720)

    def test_real_pixels_recover_known_span_without_false_completeness(self):
        result = self.run_recovery()
        self.assertTrue(result['range_recovery']['accepted'])
        self.assertAlmostEqual(result['deviation_permille'], 50., delta=2.)
        self.assertIn('range_completeness_unconfirmed', result['uncertain_reasons'])
        self.assertEqual(result['traffic'], 'gray')
        self.assertEqual(result['status'], 'uncertain')
        frame = compute_auto_near_framing(high_edge_permille=result['high_edge_permille'],
                                          base_width_px=1440, ready=True)
        self.assertLessEqual(48*1000/1440-frame.shift_permille, -3.)

    def test_confirmed_result_bypasses_recovery_unchanged(self):
        reference = _analyze_horizontal_disparity(self.left, self.right, 720)
        reference['uncertain_reasons'] = []
        with patch('stereofine.disparity._analyze_horizontal_disparity', return_value=reference), \
             patch('stereofine.range_evidence.measure_range_evidence', side_effect=AssertionError('Unexpected recovery')):
            self.assertIs(analyze_horizontal_disparity(self.left, self.right, 720), reference)

    def test_conflicting_control_cannot_shrink_range(self):
        def conflict(*args, **kwargs):
            value = measure_range_evidence(*args, **kwargs)
            if args[2] != 720:
                value['endpoints']['near']['edge_permille'] += 10
            return value
        with patch('stereofine.range_evidence.measure_range_evidence', side_effect=conflict):
            result = self.run_recovery()
        self.assertFalse(result['range_recovery']['accepted'])
        self.assertEqual(result['range_recovery']['reason'], 'control_endpoints_disagree')
        self.assertEqual(result['low_edge_permille'], -80.)

    def test_original_supported_farther_surface_is_not_discarded(self):
        def original_support(*args):
            result = sky_outlier(*args)
            if args[2] == 720:
                result['far_confirmation']['maximum_supported_px'] = 60.
            return result
        with patch('stereofine.disparity._analyze_horizontal_disparity', side_effect=original_support):
            result = analyze_horizontal_disparity(self.left, self.right, 720)
        self.assertFalse(result['range_recovery']['accepted'])
        self.assertEqual(result['range_recovery']['reason'], 'unresolved_original_far_support')
        self.assertEqual(result['low_edge_permille'], -80.)

    def test_old_sidecar_recomputes_and_retains_manual_edits(self):
        from stereofine.processing import process_source
        from stereofine.sources import source_from_pair
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root/'scene_l.png', root/'scene_r.png']
            for p, pixels in zip(paths, [self.left, self.right]):
                cv2.imwrite(str(p), pixels)
            source = source_from_pair(*paths, root)
            with patch('stereofine.processing.DISPARITY_ANALYSIS_MAX_WIDTH', 720), \
                 patch('stereofine.disparity._analyze_horizontal_disparity', side_effect=sky_outlier):
                first = process_source(source)
                payload = json.loads(source.sidecar_path.read_text())
                payload['pipeline']['disparity'] = 'sf-disparity-4'
                payload['disparity']['total_permille'] = 999.
                payload['favorite'] = True
                payload['manual']['delta_x_px'] = 7
                source.sidecar_path.write_text(json.dumps(payload))
                second = process_source(source)
                self.assertTrue(second.alignment_from_cache)
                self.assertFalse(second.disparity_from_cache)
                self.assertLess(second.state.disparity.total_permille, 60)
                self.assertTrue(second.state.favorite)
                self.assertEqual(second.state.manual.delta_x_px, 7)
                self.assertEqual(second.state.framing.auto_near_offset_x_px, first.state.framing.auto_near_offset_x_px)
                third = process_source(source)
                self.assertTrue(third.disparity_from_cache)
                self.assertEqual(third.state.disparity.total_permille, second.state.disparity.total_permille)
                self.assertEqual(third.state.disparity.method, second.state.disparity.method)
                self.assertEqual(third.state.disparity.measurement_scope, second.state.disparity.measurement_scope)
                self.assertEqual(third.state.disparity.uncertain_reasons, second.state.disparity.uncertain_reasons)


if __name__ == '__main__':
    unittest.main()
