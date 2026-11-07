import unittest
from copy import deepcopy
import numpy as np

from stereofine.inspection import InspectionView,image_point,measured_deviation
from stereofine.endpoints import locate_endpoints,to_master,current_markers
from stereofine.state import PairState


class InspectionTests(unittest.TestCase):
    def test_zoom_keeps_pointer_anchor_and_does_not_change_crop(self):
        state=PairState();before=deepcopy(state.to_sidecar(source={}).to_dict())
        view=InspectionView()
        view.zoom(2,(2000,1000),(800,400),(.4,.4))
        box,size=view.layout((2000,1000),(800,400))
        np.testing.assert_allclose(image_point((size[0]*.4,size[1]*.4),size,box),(800,400))
        view.pan(30,20,(2000,1000),(800,400));view.reset()
        self.assertFalse(view.active)
        self.assertEqual(state.to_sidecar(source={}).to_dict(),before)

    def test_measurement_is_invariant_under_zoom_and_pan(self):
        for box,size in [((0,0,2000,1000),(800,400)),((400,200,1400,700),(1000,500))]:
            native=[(600,400),(630,400)]
            points=[((x-box[0])/(box[2]-box[0])*size[0],(y-box[1])/(box[3]-box[1])*size[1]) for x,y in native]
            restored=[image_point(p,size,box) for p in points]
            self.assertAlmostEqual(measured_deviation(*restored,2000),15)

    def test_pan_clamps_to_image_and_zoom_out_returns_to_fit(self):
        view=InspectionView()
        view.zoom(4,(2000,1000),(800,400))
        view.pan(1e6,-1e6,(2000,1000),(800,400))
        box,_=view.layout((2000,1000),(800,400))
        self.assertEqual(box[0],0)
        self.assertEqual(box[3],1000)
        view.zoom(.001,(2000,1000),(800,400))
        self.assertFalse(view.active)

    def test_endpoint_projection_tracks_real_source_points_after_manual_shift(self):
        state=PairState();state.disparity.valid=True
        evidence=dict(markers={'near':dict(left=[.8,.5],right=[.76,.5],tentative=False)})
        state.disparity.endpoints=to_master(evidence,state,(600,1000),1000/600)
        markers=current_markers(state)
        self.assertAlmostEqual(markers['near']['point_permille'],40)
        state.manual.delta_x_px=10
        self.assertAlmostEqual(current_markers(state)['near']['point_permille'],1000*30/990)
        state.disparity.stale=True
        self.assertEqual(current_markers(state),{})

    def test_far_evidence_is_unreflected_before_drawing(self):
        disparity=np.full((60,100),4,np.float32)
        # Give the unverified point an equal disparity error and an earlier
        # x-coordinate than either verified point.
        confidence=np.zeros_like(disparity,bool)
        confidence[20,55]=True
        near=dict(confirmed=True,verified_points=[dict(x=70,y=20,disparity_px=4)])
        far=dict(confirmed=True,verified_points=[dict(x=20,y=20,disparity_px=-4)])
        data=locate_endpoints(disparity,confidence,near,far,40,40)
        self.assertAlmostEqual(data['markers']['far']['left'][0],.795)
        self.assertAlmostEqual(data['markers']['far']['right'][0],.755)
        self.assertFalse(data['markers']['far']['tentative'])


if __name__=='__main__':unittest.main()
