"""Alt-arrow framing must move the crop in small steps, rather than to an edge."""
import types
import unittest
from copy import deepcopy

import numpy as np

from stereofine.preview_render import PreviewBasePair, render_preview_from_base
from stereofine.state import PairState
from tests.test_foundation import _import_gui_without_customtkinter_runtime


class CropPanTests(unittest.TestCase):
    def app(self, width=1600, height=900, scale=1., original_aspect=None):
        pixels = np.zeros((height, width, 3), dtype=np.uint16)
        pixels[:, :, 0] = np.arange(width)
        pixels[:, :, 1] = np.arange(height)[:, None]
        base = PreviewBasePair(pixels, pixels, scale,
                               original_aspect or width / height, color_applied=True)
        state = PairState()
        state.framing.aspect = '1:1'
        gui = _import_gui_without_customtkinter_runtime()
        app = object.__new__(gui.StereoFineApp)
        app.current = types.SimpleNamespace(state=state)
        app.busy_state = 'idle'
        app._ensure_preview_base = lambda _session: base
        # Reproduce the actual GUI: this shape is AFTER the square crop.
        app._preview_pair_shape = (min(width, height), min(width, height))
        self.scheduled = []
        app._schedule_disparity_refresh = lambda: self.scheduled.append(True)
        app._schedule_state_save = lambda: None
        app._refresh_preview = lambda: None
        app._schedule_status_refresh = lambda: None
        return app, state, base

    def position(self, state, base):
        pair = render_preview_from_base(base, state, apply_color=False, apply_floating_window=False)
        return tuple(int(x) for x in pair.left[0, 0, :2])

    def test_widescreen_to_square_moves_five_pixels_per_key(self):
        app, state, base = self.app()
        initial = self.position(state, base)
        for _ in range(10):
            before = self.position(state, base)
            app._on_alt_arrow('right')
            after = self.position(state, base)
            self.assertIn(after[0] - before[0], (4, 5, 6))
            self.assertEqual(after[1], before[1])
        self.assertLess(abs(state.framing.pan_x_permille), 1000)
        for _ in range(10):
            app._on_alt_arrow('left')
        self.assertEqual(self.position(state, base), initial)

    def test_portrait_to_square_moves_in_small_vertical_steps(self):
        app, state, base = self.app(900, 1600)
        before = self.position(state, base)
        app._on_alt_arrow('down')
        after = self.position(state, base)
        self.assertEqual(after[0], before[0])
        self.assertIn(after[1] - before[1], (4, 5, 6))

    def test_unavailable_axis_does_not_change_pan_or_schedule_measurement(self):
        app, state, base = self.app()
        before = self.position(state, base)
        app._on_alt_arrow('up')
        app._on_alt_arrow('down')
        self.assertEqual(state.framing.pan_y_permille, 0)
        self.assertEqual(self.position(state, base), before)
        self.assertEqual(self.scheduled, [])

    def test_zoom_and_manual_overlap_keep_small_steps_in_both_axes(self):
        app, state, base = self.app(scale=.25)
        state.manual.delta_x_px, state.manual.delta_y_px = 120, -80
        state.framing.crop_zoom_index = 4
        for direction, axis in [('right', 0), ('down', 1)]:
            before = self.position(state, base)
            app._on_alt_arrow(direction)
            after = self.position(state, base)
            self.assertIn(after[axis] - before[axis], (4, 5, 6))
            self.assertEqual(after[1-axis], before[1-axis])

    def test_original_aspect_uses_source_ratio_before_framing(self):
        app, state, base = self.app(1500, 900, original_aspect=16/9)
        state.framing.aspect = 'original'
        state.framing.crop_zoom_index = 2
        for direction, axis in [('right', 0), ('down', 1)]:
            before = self.position(state, base)
            app._on_alt_arrow(direction)
            after = self.position(state, base)
            self.assertIn(after[axis] - before[axis], (4, 5, 6))

    def test_all_aspects_and_zoom_levels_have_bounded_steps(self):
        for width, height in [(640, 360), (360, 640), (600, 400), (400, 600), (500, 500)]:
            app, state, base = self.app(width, height, scale=.5)
            app._preview_pair_shape = (1, 1)  # A rendered shape must never set the step.
            for aspect in ('maximum', 'original', '1:1', '4:3', '3:2', '16:9'):
                for zoom in (0, 2, 8):
                    for offsets in [(0, 0), (20, -12)]:
                        with self.subTest(size=(width, height), aspect=aspect, zoom=zoom, offsets=offsets):
                            state.framing.aspect = aspect
                            state.framing.crop_zoom_index = zoom
                            state.framing.pan_x_permille = state.framing.pan_y_permille = 0
                            state.manual.delta_x_px, state.manual.delta_y_px = offsets
                            for direction, axis in [('right', 0), ('down', 1)]:
                                before = self.position(state, base)
                                edge = deepcopy(state)
                                setattr(edge.framing, 'pan_x_permille' if axis == 0 else 'pan_y_permille', 1000)
                                available = self.position(edge, base)[axis] - before[axis]
                                app._on_alt_arrow(direction)
                                after = self.position(state, base)
                                delta = after[axis] - before[axis]
                                self.assertGreaterEqual(delta, 0)
                                self.assertLessEqual(delta, 6)
                                if available >= 6:
                                    self.assertGreaterEqual(delta, 4)
                                self.assertEqual(after[1-axis], before[1-axis])


if __name__ == '__main__':
    unittest.main()
