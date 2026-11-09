"""Pixel references for the selected N/F measurement-cross palette."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from stereofine.preview import draw_measure_cross_overlay


def background(width, height):
    y, x = np.indices((height, width), dtype=np.int32)
    return Image.fromarray(np.stack([(x*17+y*23)%256, (x*7+y*19)%256,
                                    (x*29+y*11)%256], axis=2).astype(np.uint8))


class MeasurementOverlayTests(unittest.TestCase):
    def test_measurement_cross_matches_selected_style_at_center_and_edges(self):
        # Selected style B, with the scale clipped to the viewport at edges.
        cases = json.loads((Path(__file__).parent/'fixtures/measurement_overlay_reference.json').read_text())
        for case in cases:
            with self.subTest(case=case):
                source = background(*case['size'])
                before = source.tobytes()
                result = draw_measure_cross_overlay(source, *case['center'],
                                                     reference_width=case['reference_width'])
                self.assertEqual(hashlib.sha256(result.tobytes()).hexdigest(), case['sha256'])
                self.assertEqual(source.tobytes(), before)

    def test_offscreen_scale_marks_and_labels_are_clipped_at_fit_and_detail_sizes(self):
        width, height, padding = 200, 140, 400
        y = height // 2
        viewport = Image.new('RGB', (width, height))
        extended = Image.new('RGB', (width + 2 * padding, height))
        for reference_width, x in ((width, 2), (width, width - 3), (4000, 40), (4000, width - 41)):
            with self.subTest(reference_width=reference_width, x=x):
                actual = draw_measure_cross_overlay(viewport, x, y, reference_width=reference_width)
                full = draw_measure_cross_overlay(extended, x + padding, y, reference_width=reference_width)
                # Exclude the two-pixel antialiasing boundary of the horizontal axis.
                self.assertEqual(actual.crop((3, 0, width - 3, height)).tobytes(),
                                 full.crop((padding + 3, 0, padding + width - 3, height)).tobytes())

    def test_alpha_compositing_is_limited_to_the_small_measurement_region(self):
        source = background(1000, 700)
        clip = np.clip
        with patch('stereofine.preview.np.clip', wraps=clip) as blend:
            result = draw_measure_cross_overlay(source, 500, 350)
        self.assertEqual(result.size, source.size)
        self.assertEqual(blend.call_count, 1)
        self.assertLess(np.prod(blend.call_args.args[0].shape[:2]), 1000*700//8)
