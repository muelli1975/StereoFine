"""Known geometry, composited export and sidecar round-trip for the H mode."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from stereofine.alignment import warp_pair_symmetric
from stereofine.manual_geometry import GeometryAdjustment, geometry_matrix
from stereofine.processing import ProcessingOptions, process_source
from stereofine.render import render_final_pair
from stereofine.sidecar import load_sidecar
from stereofine.sources import source_from_pair
from tests.stereo_fixtures import scene


class ManualGeometryTests(unittest.TestCase):
    def test_perspective_has_the_expected_edge_magnification(self):
        points = np.array([[[100., 0.], [500., 0.], [100., 400.], [500., 400.]]])
        for value, ratio in [(20, 1.2), (0, 1.), (-20, 1 / 1.2)]:
            corrected = cv2.perspectiveTransform(points, geometry_matrix((401, 601), GeometryAdjustment(0, value)))[0]
            self.assertAlmostEqual((corrected[1, 0] - corrected[0, 0]) /
                                   (corrected[3, 0] - corrected[2, 0]), ratio)
        self.assertEqual(GeometryAdjustment().step(100, -40), GeometryAdjustment(50, -20))

    def test_manual_and_stereo_geometry_sample_each_master_once(self):
        eye = np.full((260, 380, 3), 32000, np.uint16)
        correction = {'rotation_deg': 1.3, 'scale': 1.002, 'vertical_shift_px': 4.5}
        with patch('cv2.remap', wraps=cv2.remap) as remap:
            left, right = warp_pair_symmetric(eye, eye, correction, geometry=GeometryAdjustment(50, 20))
        self.assertEqual(remap.call_count, 2)
        self.assertEqual(left.shape, right.shape)
        self.assertLess(left.shape[0] * left.shape[1], eye.shape[0] * eye.shape[1])
        self.assertTrue((left == 32000).all() and (right == 32000).all())

    def test_realign_save_and_reload_a_known_stereo_pair(self):
        adjustment = GeometryAdjustment(32, 16)
        w, h = 720, 480
        inverse = np.linalg.inv(geometry_matrix((h, w), adjustment))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            files = [root / 'left.png', root / 'right.png']
            for file, eye in zip(files, scene()):
                pixels = cv2.resize(eye, (w, h), interpolation=cv2.INTER_AREA)
                pixels = cv2.warpPerspective(pixels, inverse, (w, h), borderMode=cv2.BORDER_REFLECT_101)
                Image.fromarray(pixels).save(file)
            source = source_from_pair(*files, root)
            first = process_source(source, ProcessingOptions(analysis_method='SIFT', keep_loaded_pair=True,
                                                            geometry=adjustment))
            self.assertTrue(first.state.alignment.valid)
            self.assertLess(first.state.alignment.vertical_error_mean_px, 1.)
            self.assertEqual(first.state.geometry, adjustment)
            self.assertTrue(load_sidecar(source.sidecar_path, first.source_stamp).alignment_cache_valid)
            reopened = process_source(source, ProcessingOptions(analysis_method='SIFT', keep_loaded_pair=True,
                                                               save_sidecar=False))
            self.assertTrue(reopened.alignment_from_cache)
            self.assertEqual(reopened.state.geometry, adjustment)
            a = render_final_pair(first.loaded_pair, deepcopy(first.state), apply_color=False)
            b = render_final_pair(reopened.loaded_pair, deepcopy(reopened.state), apply_color=False)
            for x, y in zip(a[:2], b[:2]):
                np.testing.assert_array_equal(x, y)
