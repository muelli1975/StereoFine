from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
import cv2
import numpy as np

from stereofine.disparity import analyze_horizontal_disparity
from stereofine.framing import compute_auto_near_framing
from stereofine.geometry import crop_shifted_pair_to_overlap
from stereofine.near_point import supported_near_edge, verify_patch


class NearPointTests(unittest.TestCase):
    def test_single_extreme_does_not_override_corroborated_surface(self):
        points = [dict(x=100, y=100, disparity_px=10.), dict(x=110, y=100, disparity_px=10.),
                  dict(x=400, y=300, disparity_px=100.)]
        result = supported_near_edge(points, 10, 1000)
        self.assertEqual(result["edge_permille"], 10)
        self.assertTrue(result["unsupported_extreme"])

    def test_small_confirmed_surface_gets_measurement_margin(self):
        result = supported_near_edge([dict(x=100, y=100, disparity_px=30.),
                                      dict(x=110, y=100, disparity_px=30.)], 10, 1000)
        self.assertEqual(result["edge_permille"], 30.5)

    def test_flat_or_repeating_ambiguous_patch_is_rejected(self):
        flat = np.zeros((80, 160), np.uint8)
        self.assertIsNone(verify_patch(flat, flat, 80, 40))
        repeated = np.tile(np.array([0, 80, 190, 255, 190, 80, 0, 20], np.uint8), (80, 20))
        self.assertIsNone(verify_patch(repeated, repeated, 80, 40))

    @staticmethod
    def scene(near_disparity=30):
        rng = np.random.default_rng(236)
        h, w = 480, 720
        left = cv2.GaussianBlur(rng.integers(0, 256, (h, w), dtype=np.uint8), (3, 3), 0)
        right = cv2.warpAffine(left, np.float32([[1, 0, -8], [0, 1, 0]]), (w, h))
        patch = rng.integers(0, 256, (32, 34), dtype=np.uint8)
        left[420:452, 650:684] = patch
        right[420:452, 650-near_disparity:684-near_disparity] = patch
        return left, right

    def test_tiny_near_object_in_former_search_rim_is_framed_behind_window(self):
        # This object occupies 0.32% of the image: a global P99 cannot select it.
        left, right = self.scene()
        result = analyze_horizontal_disparity(np.repeat(left[..., None], 3, axis=2),
                                              np.repeat(right[..., None], 3, axis=2), 720)
        self.assertTrue(result["ready"])
        self.assertGreater(result["high_edge_permille"], 40)
        self.assertLess(result["high_edge_permille"], 44)
        near = compute_auto_near_framing(high_edge_permille=result["high_edge_permille"],
                                         base_width_px=720, ready=True)
        l, r, _ = crop_shifted_pair_to_overlap(left, right, near.offset_x_px, 0)
        point = verify_patch(l, r, 666-near.offset_x_px, 436)
        self.assertIsNotNone(point)
        self.assertLessEqual(point["disparity_px"] * 1000 / l.shape[1], -3.)

    def test_large_verified_disparity_exposes_search_limit(self):
        left, right = self.scene(80)
        result = analyze_horizontal_disparity(np.repeat(left[..., None], 3, axis=2),
                                              np.repeat(right[..., None], 3, axis=2), 720)
        self.assertIn("disparity_search_limit", result["uncertain_reasons"])
        self.assertGreater(result["high_edge_permille"], 100)

    def test_confirmed_near_framing_survives_real_sidecar_cache_roundtrip(self):
        from stereofine.processing import process_source
        from stereofine.sources import source_from_pair
        left, right = self.scene()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / "scene_l.png", root / "scene_r.png"]
            for path, pixels in zip(paths, (left, right)):
                cv2.imwrite(str(path), pixels)
            source = source_from_pair(*paths, root)
            first = process_source(source)
            second = process_source(source)
            self.assertTrue(second.alignment_from_cache)
            self.assertTrue(second.disparity_from_cache)
            self.assertGreater(second.state.disparity.high_edge_permille, 40)
            self.assertEqual(first.state.framing.auto_near_offset_x_px, second.state.framing.auto_near_offset_x_px)

    def test_disparity_pipeline_change_discards_old_auto_shift_but_keeps_edits(self):
        from stereofine.processing import process_source
        from stereofine.sources import source_from_pair
        from stereofine.session import browse_source
        import json
        left, right = self.scene()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / "scene_l.png", root / "scene_r.png"]
            for path, pixels in zip(paths, (left, right)):
                cv2.imwrite(str(path), pixels)
            source = source_from_pair(*paths, root)
            process_source(source)
            payload = json.loads(source.sidecar_path.read_text())
            payload["pipeline"]["disparity"] = "sf-disparity-2"
            payload["manual"]["delta_x_px"] = 7
            payload["favorite"] = True
            payload["floating_window"]["right_permille"] = 4
            payload["framing"]["auto_near_offset_x_px"] = 9999
            source.sidecar_path.write_text(json.dumps(payload))
            browsed = browse_source(source)
            self.assertTrue(browsed.state.alignment.valid)
            self.assertFalse(browsed.state.disparity.valid)
            self.assertIsNone(browsed.state.framing.auto_near_offset_x_px)
            self.assertEqual(browsed.state.manual.delta_x_px, 7)
            self.assertTrue(browsed.state.favorite)
            refreshed = process_source(source)
            self.assertTrue(refreshed.alignment_from_cache)
            self.assertFalse(refreshed.disparity_from_cache)
            self.assertTrue(refreshed.state.favorite)
            self.assertEqual(refreshed.state.manual.delta_x_px, 7)
            self.assertEqual(refreshed.state.floating_window.right_permille, 4)
            self.assertNotEqual(refreshed.state.framing.auto_near_offset_x_px, 9999)
            cached = process_source(source)
            self.assertTrue(cached.alignment_from_cache)
            self.assertTrue(cached.disparity_from_cache)


if __name__ == "__main__":
    unittest.main()
