"""The geometric reserve uses final output width; displayed values stay measured."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from stereofine.config import CROP_ZOOM_LEVELS
from stereofine.disparity import render_pair_for_disparity_analysis_from_arrays
from stereofine.framing import AutoNearGeometry, compute_auto_near_framing
from stereofine.geometry import crop_shifted_pair_to_overlap, crop_pair_to_aspect_and_framing
from stereofine.processing import ProcessingDefaults, ProcessingOptions, process_source
from stereofine.render import render_final_pair
from stereofine.session import browse_source, save_browsed_state
from stereofine.state import PairState
from tests.test_restart_alignment import RestartAlignmentTests


class FinalNearReserveTests(unittest.TestCase):
    def frame(self, geometry, near_px, **kw):
        initial_width = geometry.final_width(0)
        return compute_auto_near_framing(high_edge_permille=near_px*1000/initial_width,
            base_width_px=initial_width, ready=True, geometry=geometry, **kw)

    def test_known_counterexample_and_square_crop(self):
        original = AutoNearGeometry((4000, 6000), 'original', original_aspect=1.5)
        result = self.frame(original, 600)
        self.assertEqual(result.offset_x_px, 617)
        self.assertEqual(original.final_width(result.offset_x_px), 5383)
        self.assertAlmostEqual(result.near_after_permille, -17000/5383)
        square = AutoNearGeometry((4000, 6000), '1:1', original_aspect=1.5)
        result = self.frame(square, 600)
        self.assertEqual((result.offset_x_px, result.near_after_permille), (612, -3.))

    def test_integer_minimum_across_aspects_zoom_and_shift_signs(self):
        for shape in ((400, 600), (600, 400), (99, 151), (1000, 1500)):
            for aspect in ('original', 'maximum', '1:1', '16:9', '4:3'):
                for zoom in (1., 1.25, 2.):
                    geometry = AutoNearGeometry(shape, aspect, zoom, shape[1]/shape[0])
                    initial_width = geometry.final_width(0)
                    for near_px in (-.2*initial_width, 0., .1*initial_width, .35*initial_width):
                        with self.subTest(shape=shape, aspect=aspect, zoom=zoom, near=near_px):
                            frame = self.frame(geometry, near_px)
                            offset = frame.offset_x_px
                            width = geometry.final_width(offset)
                            reserve = (offset-near_px)*1000/width
                            self.assertGreaterEqual(reserve, 3.-1e-8)
                            previous = (offset-1-near_px)*1000/geometry.final_width(offset-1)
                            self.assertLess(previous, 3.+1e-8)
                            self.assertAlmostEqual(frame.near_after_permille, -reserve)

    def test_width_matches_actual_crop_pixels_including_pan(self):
        for shape in ((181, 320), (320, 181)):
            image = np.zeros((*shape, 3), np.uint8)
            for aspect in ('original', 'maximum', '1:1', '16:9'):
                for zoom in (1., 1.25, 2.):
                    geometry = AutoNearGeometry(shape, aspect, zoom, shape[1]/shape[0])
                    for offset in (-40, 0, 37):
                        for pan in (-1000, 0, 1000):
                            l, r, _ = crop_shifted_pair_to_overlap(image, image, offset, 0)
                            l, r, _ = crop_pair_to_aspect_and_framing(l,r,aspect,zoom,pan,-pan,shape[1]/shape[0])
                            self.assertEqual(geometry.final_width(offset), l.shape[1])

    def test_analysis_metadata_is_before_selected_crop_and_has_no_pixel_change(self):
        image = np.zeros((120, 180, 3), np.uint8)
        normal = render_pair_for_disparity_analysis_from_arrays(image,image,None,output_aspect='1:1')
        extended = render_pair_for_disparity_analysis_from_arrays(image,image,None,
            output_aspect='1:1', return_aligned_shape=True)
        self.assertEqual(extended[2], (120,180))
        for a,b in zip(normal,extended):
            np.testing.assert_array_equal(a,b)
        self.assertEqual(render_pair_for_disparity_analysis_from_arrays(None,None,None,
            return_aligned_shape=True), (None,None,None))

    def test_uncertainty_does_not_change_geometric_target(self):
        geometry=AutoNearGeometry((4000,6000),'original',original_aspect=1.5)
        sure=self.frame(geometry,600)
        uncertain=self.frame(geometry,600,uncertain=True)
        self.assertEqual(sure.offset_x_px, uncertain.offset_x_px)
        self.assertEqual(sure.near_after_permille, uncertain.near_after_permille)
        self.assertEqual((sure.status,uncertain.status), ('set','set_with_note'))

    def test_unreachable_target_respects_actual_overlap_limit(self):
        geometry=AutoNearGeometry((100,100),'maximum')
        result=self.frame(geometry,100.)
        self.assertEqual(result.offset_x_px,98)
        self.assertEqual(result.status,'set_with_note')
        self.assertGreater(result.near_after_permille,-3.)

    def test_processing_uses_actual_final_width_and_keeps_measured_minus_35(self):
        for uncertain in (False,True):
            with self.subTest(uncertain=uncertain), tempfile.TemporaryDirectory() as td:
                source=RestartAlignmentTests().source(Path(td))
                first=[]
                def measure(left,right,*args):
                    if not first:
                        width=left.shape[1]
                        near_px=round(width*.1)
                        first.append((width,near_px))
                        high=near_px*1000/width
                        return dict(ready=True,status='ok',low_edge_permille=high-20.,
                                    high_edge_permille=high,deviation_permille=20.,traffic='green')
                    return dict(ready=True,status='uncertain' if uncertain else 'ok',
                        low_edge_permille=-23.5,high_edge_permille=-3.5,deviation_permille=20.,
                        traffic='green',uncertain_reasons=['near_edge_unconfirmed'] if uncertain else [])
                with patch('stereofine.processing.analyze_horizontal_disparity',side_effect=measure) as analyze:
                    item=process_source(source,ProcessingOptions(keep_loaded_pair=True,
                        defaults=ProcessingDefaults(aspect='original',color_enabled=False)))
                self.assertEqual(analyze.call_count,2)
                rendered,_,_=render_final_pair(item.loaded_pair,deepcopy(item.state),
                                               apply_color=False,apply_floating_window=False)
                _,near_px=first[0]
                reserve=(item.state.auto_offset_x_px-near_px)*1000/rendered.shape[1]
                self.assertGreaterEqual(reserve,3.-1e-8)
                self.assertLess(reserve,3.+1000/rendered.shape[1]+1e-8)
                self.assertEqual(item.state.current_scene_positions_permille()[0],-3.5)
                self.assertEqual(item.state.disparity.uncertain,uncertain)
                # Saved framing/edits must not be silently replaced by the fix.
                saved=browse_source(source)
                saved.state.manual.delta_x_px=4
                saved.state.framing.crop_zoom_index=1
                saved.state.invalidate_disparity_for_framing()
                save_browsed_state(saved)
                framing=asdict(saved.state.framing)
                with patch('stereofine.processing.compute_auto_near_framing',
                           side_effect=AssertionError('Saved framing was replaced')), \
                     patch('stereofine.processing.analyze_horizontal_disparity',
                           return_value=dict(ready=True,status='ok',low_edge_permille=-25.,
                                             high_edge_permille=-5.,deviation_permille=20.,traffic='green')):
                    reused=process_source(source)
                self.assertEqual(asdict(reused.state.framing),framing)
                self.assertEqual(reused.state.manual.delta_x_px,4)


if __name__=='__main__':
    unittest.main()
