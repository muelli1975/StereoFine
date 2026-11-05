"""Pixel references captured from the original full-frame measurement overlay."""
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
    def test_optimized_overlay_matches_original_pixels_at_center_and_edges(self):
        # Recorded before optimizing the renderer at 99924196ba56345c404c9b052487c1de9e432130.
        cases = json.loads((Path(__file__).parent/'fixtures/measurement_overlay_reference.json').read_text())
        for case in cases:
            with self.subTest(case=case):
                source = background(*case['size'])
                before = source.tobytes()
                result = draw_measure_cross_overlay(source, *case['center'],
                                                     reference_width=case['reference_width'])
                self.assertEqual(hashlib.sha256(result.tobytes()).hexdigest(), case['sha256'])
                self.assertEqual(source.tobytes(), before)

    def test_alpha_compositing_is_limited_to_the_small_measurement_region(self):
        source = background(1000, 700)
        clip = np.clip
        with patch('stereofine.preview.np.clip', wraps=clip) as blend:
            result = draw_measure_cross_overlay(source, 500, 350)
        self.assertEqual(result.size, source.size)
        self.assertEqual(blend.call_count, 1)
        self.assertLess(np.prod(blend.call_args.args[0].shape[:2]), 1000*700//8)
