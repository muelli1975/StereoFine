"""Keep prepared colour visible while a changed crop is waiting for its fit."""
from copy import deepcopy
import unittest

import numpy as np

from stereofine.preview_render import build_preview_base, render_preview_from_base
from stereofine.render import render_final_pair
from stereofine.state import PairState
from tests.test_final_corrections import loaded_pair


class InteractiveColourTests(unittest.TestCase):
    def prepared(self):
        loaded = loaded_pair()
        state = PairState()
        state.color.enabled = True
        render_final_pair(loaded, state)
        return loaded, state

    def test_pending_crop_keeps_the_last_colour_curves_without_marking_them_current(self):
        loaded, state = self.prepared()
        base = build_preview_base(loaded, state, max_width=320, max_height=230, apply_color=False)
        previous = deepcopy(state.color.parameters)
        state.framing.crop_zoom_index = 2
        state.invalidate_disparity_for_framing()
        self.assertFalse(state.color.valid)
        reference = deepcopy(state)
        reference.color.valid = True
        expected = render_preview_from_base(base, reference)
        raw = render_preview_from_base(base, state, apply_color=False)
        actual = render_preview_from_base(base, state)
        self.assertFalse(np.array_equal(expected.left, raw.left))
        np.testing.assert_array_equal(actual.left, expected.left)
        np.testing.assert_array_equal(actual.right, expected.right)
        self.assertFalse(state.color.valid)
        self.assertEqual(state.color.parameters, previous)
        render_final_pair(loaded, state)
        self.assertTrue(state.color.valid)
        self.assertEqual(state.color.basis['crop_zoom_index'], 2)

    def test_changed_eye_order_does_not_reuse_the_previous_eyes_curves(self):
        loaded, state = self.prepared()
        state.input_transform.swap_eyes = True
        state.invalidate_for_input_transform()
        base = build_preview_base(loaded, state, max_width=320, max_height=230, apply_color=False)
        actual = render_preview_from_base(base, state)
        raw = render_preview_from_base(base, state, apply_color=False)
        np.testing.assert_array_equal(actual.left, raw.left)
        np.testing.assert_array_equal(actual.right, raw.right)

    def test_pending_manual_offset_keeps_the_prepared_colour(self):
        loaded, state = self.prepared()
        base = build_preview_base(loaded, state, max_width=320, max_height=230, apply_color=False)
        state.manual.delta_x_px = 11
        state.manual.delta_y_px = 3
        state.color.valid = False
        reference = deepcopy(state)
        reference.color.valid = True
        expected = render_preview_from_base(base, reference)
        actual = render_preview_from_base(base, state)
        np.testing.assert_array_equal(actual.left, expected.left)
        np.testing.assert_array_equal(actual.right, expected.right)
        self.assertFalse(state.color.valid)

    def test_disabled_matching_stays_disabled_while_the_crop_is_pending(self):
        loaded, state = self.prepared()
        base = build_preview_base(loaded, state, max_width=320, max_height=230, apply_color=False)
        state.framing.crop_zoom_index = 2
        state.invalidate_disparity_for_framing()
        state.color.enabled = False
        actual = render_preview_from_base(base, state)
        raw = render_preview_from_base(base, state, apply_color=False)
        np.testing.assert_array_equal(actual.left, raw.left)
        np.testing.assert_array_equal(actual.right, raw.right)


if __name__ == '__main__':
    unittest.main()
