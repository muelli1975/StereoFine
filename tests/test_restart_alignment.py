"""Explicit Start replaces manual nudges, while save/batch retain user edits."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from stereofine.processing import ProcessingOptions, process_source
from stereofine.render import render_final_pair
from stereofine.session import browse_source, save_browsed_state
from stereofine.sources import discover_pair_sources
from stereofine.worker import CancellationToken, JobCancelled


class RestartAlignmentTests(unittest.TestCase):
    def source(self, root: Path):
        rng = np.random.default_rng(42)
        left = cv2.GaussianBlur(rng.integers(0, 256, (240, 360, 3), dtype=np.uint8), (3, 3), 0)
        for _ in range(80):
            x, y = int(rng.integers(10, 350)), int(rng.integers(10, 230))
            cv2.circle(left, (x, y), int(rng.integers(2, 6)),
                       tuple(int(v) for v in rng.integers(0, 256, 3)), -1)
        right = cv2.warpAffine(left, np.float32([[1, 0, 8], [0, 1, 1]]), (360, 240),
                               borderMode=cv2.BORDER_REFLECT)
        for eye, array in [('l', left), ('r', right)]:
            cv2.imwrite(str(root/f'scene_{eye}.png'), cv2.cvtColor(array, cv2.COLOR_RGB2BGR))
        return discover_pair_sources(root)[0]

    def edited(self, source):
        process_source(source)
        session = browse_source(source)
        session.state.framing.aspect = '4:3'
        session.state.framing.crop_zoom_index = 3
        session.state.framing.pan_x_permille = 210
        session.state.framing.pan_y_permille = -170
        session.state.manual.delta_x_px = 15
        session.state.manual.delta_y_px = -7
        session.state.favorite = True
        session.state.floating_window.left_permille = 10
        session.state.invalidate_disparity_for_framing()
        save_browsed_state(session)
        return session

    def test_restart_matches_clean_crop_analysis_and_persists_zero_nudges(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            edited_root, clean_root = root/'edited', root/'clean'
            edited_root.mkdir(); clean_root.mkdir()
            source = self.source(edited_root)
            session = self.edited(source)
            # Normal processing remains the save/batch path and keeps nudges.
            retained = process_source(source)
            self.assertEqual((retained.state.manual.delta_x_px, retained.state.manual.delta_y_px), (15, -7))
            self.assertTrue(retained.alignment_from_cache)

            reference_source = self.source(clean_root)
            reference = browse_source(reference_source)
            reference.state.framing = deepcopy(session.state.framing)
            reference.state.favorite = True
            reference.state.floating_window.left_permille = 10
            save_browsed_state(reference)
            clean = process_source(reference_source, ProcessingOptions(keep_loaded_pair=True))

            restarted = process_source(source, ProcessingOptions(restart_alignment=True, keep_loaded_pair=True))
            self.assertFalse(restarted.alignment_from_cache)
            self.assertFalse(restarted.disparity_from_cache)
            self.assertEqual((restarted.state.manual.delta_x_px, restarted.state.manual.delta_y_px), (0, 0))
            self.assertEqual(restarted.state.disparity.basis, clean.state.disparity.basis)
            self.assertEqual(restarted.state.framing.auto_near_offset_x_px, clean.state.framing.auto_near_offset_x_px)
            self.assertEqual(restarted.state.framing.auto_near_back_permille, 3.0)
            self.assertLessEqual(restarted.state.current_scene_positions_permille()[0], -3.0+1e-9)
            self.assertEqual((restarted.state.framing.aspect, restarted.state.framing.crop_zoom_index,
                              restarted.state.framing.pan_x_permille, restarted.state.framing.pan_y_permille),
                             ('4:3', 3, 210, -170))
            self.assertTrue(restarted.state.favorite)
            self.assertEqual(restarted.state.floating_window.left_permille, 10)
            for actual, expected in zip(render_final_pair(restarted.loaded_pair, restarted.state)[:2],
                                        render_final_pair(clean.loaded_pair, clean.state)[:2]):
                np.testing.assert_array_equal(actual, expected)
            reopened = browse_source(source)
            self.assertEqual((reopened.state.manual.delta_x_px, reopened.state.manual.delta_y_px), (0, 0))
            cached = process_source(source)
            self.assertTrue(cached.alignment_from_cache)
            self.assertTrue(cached.disparity_from_cache)
            # Even a second explicit Start must recompute the valid caches.
            again = process_source(source, ProcessingOptions(restart_alignment=True))
            self.assertFalse(again.alignment_from_cache)
            self.assertFalse(again.disparity_from_cache)

    def test_cancelled_restart_does_not_commit_the_reset(self):
        with tempfile.TemporaryDirectory() as td:
            source = self.source(Path(td))
            self.edited(source)
            before = source.sidecar_path.read_bytes()
            token = CancellationToken()
            from stereofine.processing import analyze_pair_features
            def cancel_after_alignment(*args, **kwargs):
                result = analyze_pair_features(*args, **kwargs)
                token.cancel()
                return result
            with patch('stereofine.processing.analyze_pair_features', side_effect=cancel_after_alignment):
                with self.assertRaises(JobCancelled):
                    process_source(source, ProcessingOptions(restart_alignment=True), cancellation=token)
            self.assertEqual(source.sidecar_path.read_bytes(), before)
            reopened = browse_source(source)
            self.assertEqual((reopened.state.manual.delta_x_px, reopened.state.manual.delta_y_px), (15, -7))
            self.assertEqual(reopened.state.framing.crop_zoom_index, 3)


if __name__ == '__main__': unittest.main()
