"""Native evidence, seed starvation and contradictory near-surface guards."""
from copy import deepcopy
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from stereofine.near_point_recovery import recover_near_edge
from stereofine.near_point import confirm_near_edge, supported_near_edge


class NativeNearConfirmationTests(unittest.TestCase):
    def scene(self,baseline_px=20.):
        rng=np.random.default_rng(720)
        a=rng.integers(0,256,(360,640),dtype=np.uint8)
        b=cv2.warpAffine(a,np.float32([[1,0,-20],[0,1,0]]),(640,360))
        a[:50]=100;b[:50]=100
        disparity=np.full(a.shape,20.,dtype=np.float32);disparity[20,30:610]=25.
        confidence=np.zeros(a.shape,bool);confidence[16:344,30:610]=True
        with patch('cv2.goodFeaturesToTrack',return_value=None):
            old=confirm_near_edge(a,b,disparity,confidence,baseline_px*1000/640)
        native=[cv2.resize(x,None,fx=2,fy=2,interpolation=cv2.INTER_LANCZOS4) for x in (a,b)]
        return a,b,disparity,confidence,old,*native

    def test_real_patches_recover_starved_component_at_both_scales(self):
        args=self.scene();old=deepcopy(args[4])
        result,audit=recover_near_edge(*args)
        self.assertFalse(old['confirmed']);self.assertTrue(result['confirmed'])
        self.assertTrue(audit['accepted']);self.assertGreaterEqual(audit['native_support']['supported_points'],2)
        self.assertLessEqual(audit['additional_probes'],128);self.assertLessEqual(audit['native_checked'],24)
        self.assertEqual(args[4],old)
        self.assertAlmostEqual(result['edge_permille'],20.*1000/640,places=5)

    def test_farther_native_matches_cannot_hide_a_nearer_analysis_surface(self):
        args=list(self.scene(baseline_px=10.))
        old=args[4];old.update(verified_points=[],confirmed=False)
        points=[dict(x=x,y=y,disparity_px=d) for x,y,d in [(100,100,30.),(110,100,30.),(200,200,10.),(210,200,10.)]]
        proposed=supported_near_edge(points,10.,640)
        proposed.update(additional_probes=4,probed_points=4,baseline_percentile_permille=1000*10/640)
        checks=[dict(x=round((p['x']+.5)*2-.5),y=round((p['y']+.5)*2-.5),
                     disparity_permille=1000*p['disparity_px']/640) for p in points[2:]]
        with patch('stereofine.near_point_recovery.stratified_tail_probe',return_value=proposed), \
             patch('stereofine.near_point_recovery.native_patch_checks',return_value=checks):
            result,audit=recover_near_edge(*args)
        self.assertIs(result,old)
        self.assertFalse(audit['accepted'])
        self.assertEqual(audit['reason'],'unresolved_nearer_analysis_surface')

    def test_unsupported_original_extreme_is_not_dropped(self):
        args=list(self.scene());old=args[4]
        old['verified_points']=[dict(x=600,y=300,disparity_px=80.)]
        result,audit=recover_near_edge(*args)
        self.assertIs(result,old);self.assertFalse(audit['accepted'])
        self.assertEqual(old['verified_points'][0]['disparity_px'],80.)

    def test_native_near_measurement_retains_the_existing_half_pixel_reserve(self):
        args=list(self.scene(baseline_px=10.));old=args[4]
        points=[dict(x=100,y=100,disparity_px=30.),dict(x=110,y=100,disparity_px=30.)]
        proposed=supported_near_edge(points,10.,640)
        proposed.update(additional_probes=2,probed_points=2,baseline_percentile_permille=1000*10/640)
        checks=[dict(x=round((p['x']+.5)*2-.5),y=round((p['y']+.5)*2-.5),
                     disparity_permille=1000*30.8/640) for p in points]
        with patch('stereofine.near_point_recovery.stratified_tail_probe',return_value=proposed), \
             patch('stereofine.near_point_recovery.native_patch_checks',return_value=checks):
            result,audit=recover_near_edge(*args)
        self.assertTrue(audit['accepted'])
        self.assertAlmostEqual(result['maximum_supported_px'],30.8)
        self.assertAlmostEqual(result['edge_permille'],1000*31.3/640)

    def test_supported_analysis_envelope_is_not_lowered_by_native_filtering(self):
        args=list(self.scene(baseline_px=10.))
        points=[dict(x=x,y=y,disparity_px=d) for x,y,d in [(100,100,30.),(110,100,30.),(200,200,29.2),(210,200,29.2)]]
        proposed=supported_near_edge(points,10.,640)
        proposed.update(additional_probes=4,probed_points=4,baseline_percentile_permille=1000*10/640)
        checks=[dict(x=round((p['x']+.5)*2-.5),y=round((p['y']+.5)*2-.5),
                     disparity_permille=1000*p['disparity_px']/640) for p in points[2:]]
        with patch('stereofine.near_point_recovery.stratified_tail_probe',return_value=proposed), \
             patch('stereofine.near_point_recovery.native_patch_checks',return_value=checks):
            result,audit=recover_near_edge(*args)
        self.assertTrue(audit['accepted'])
        self.assertEqual(result['edge_permille'],proposed['edge_permille'])

    def test_overestimated_percentile_is_not_lowered_or_blessed(self):
        args=self.scene(baseline_px=25.)
        result,audit=recover_near_edge(*args)
        self.assertIs(result,args[4]);self.assertFalse(result['confirmed'])
        self.assertFalse(audit['accepted'])

    def test_unconfirmed_native_pixels_cannot_override_analysis(self):
        args=list(self.scene());args[5].fill(100);args[6].fill(100)
        result,audit=recover_near_edge(*args)
        self.assertIs(result,args[4]);self.assertFalse(audit['accepted'])
        self.assertEqual(audit['reason'],'native_confirmation_failed')

    def test_already_confirmed_result_is_returned_without_any_probe(self):
        old={'confirmed':True}
        with patch('stereofine.near_point_recovery.stratified_tail_probe') as probe:
            result,audit=recover_near_edge(None,None,None,None,old,None,None)
        self.assertIs(result,old);probe.assert_not_called()
        self.assertEqual(audit['reason'],'already_confirmed')

    def test_empty_confidence_does_not_create_evidence(self):
        args=list(self.scene());args[3].fill(False)
        result,audit=recover_near_edge(*args)
        self.assertIs(result,args[4]);self.assertEqual(audit['reason'],'no_confident_data')

    def test_missing_finer_native_scale_keeps_original_uncertainty(self):
        args=list(self.scene());args[5],args[6]=args[0],args[1]
        result,audit=recover_near_edge(*args)
        self.assertIs(result,args[4]);self.assertEqual(audit['reason'],'no_finer_native_measurement')

    def test_processing_recovery_frames_real_pixels_and_reuses_sidecar(self):
        from stereofine.processing import process_source
        from stereofine.sources import source_from_pair, load_source
        from stereofine.render import render_final_pair
        from stereofine.disparity import _rgb_to_luma_uint8
        from stereofine.near_point import verify_patch
        import json
        *_,native_left,native_right=self.scene()
        # Isolate a missing initial seed. Dense matching, extra patch searches,
        # native confirmation, framing, disk persistence and cache are real.
        def missing_initial_seed(l,r,d,c,baseline):
            result=supported_near_edge([],baseline*l.shape[1]/1000.,l.shape[1])
            result.update(probed_points=0,baseline_percentile_permille=baseline)
            return result
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);paths=[root/'scene_l.png',root/'scene_r.png']
            for path,pixels in zip(paths,(native_left,native_right)):cv2.imwrite(str(path),pixels)
            source=source_from_pair(*paths,root)
            with patch('stereofine.processing.DISPARITY_ANALYSIS_MAX_WIDTH',640), \
                 patch('stereofine.near_point.confirm_near_edge',side_effect=missing_initial_seed) as initial:
                first=process_source(source)
                self.assertTrue(first.state.disparity.valid)
                self.assertNotIn('near_edge_unconfirmed',first.state.disparity.uncertain_reasons)
                self.assertIn('disparity_range_unreliable',first.state.disparity.uncertain_reasons)
                near=first.state.disparity.diagnostics['near_confirmation']
                self.assertTrue(near['recovery_validation']['accepted'])
                left,right,_=render_final_pair(load_source(source),first.state,apply_color=False)
                offset=first.state.effective_offset_x_px
                point=verify_patch(_rgb_to_luma_uint8(left),_rgb_to_luma_uint8(right),640-offset,360)
                self.assertIsNotNone(point)
                self.assertLessEqual(point['disparity_px']*1000/left.shape[1],-3.)
                payload=json.loads(source.sidecar_path.read_text())
                payload['favorite']=True;payload['manual']['delta_x_px']=7
                source.sidecar_path.write_text(json.dumps(payload))
                second=process_source(source)
                self.assertTrue(second.alignment_from_cache)
                self.assertTrue(second.disparity_from_cache)
                self.assertTrue(second.state.favorite)
                self.assertEqual(second.state.manual.delta_x_px,7)
                self.assertEqual(first.state.framing.auto_near_offset_x_px,second.state.framing.auto_near_offset_x_px)
                self.assertEqual(initial.call_count,1)

    def test_native_uint16_uses_full_range_proxy_without_clipping(self):
        from stereofine.near_point_recovery import native_patch_checks
        *_,left,right=self.scene()
        points=[dict(x=200,y=150,disparity_px=20.),dict(x=210,y=150,disparity_px=20.)]
        expected=native_patch_checks(left,right,(360,640),points)
        actual=native_patch_checks(left.astype(np.uint16)*257,right.astype(np.uint16)*257,(360,640),points)
        self.assertGreaterEqual(len(expected),1)
        self.assertEqual(actual,expected)


if __name__=='__main__':unittest.main()
