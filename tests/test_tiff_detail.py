"""Native depth, profile, final-crop colour and momentary-view regressions."""
from copy import deepcopy
import ctypes as C
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageCms, JpegImagePlugin
import tifffile

from stereofine.color_profiles import _library, promote_pair, transform_rgb
from stereofine.color_transfer import _sample_rgb
from stereofine.export import save_pair_outputs
from stereofine.inputs import load_pair, LoadedStereoPair
from stereofine.native_preview import detail_box, native_key, DETAIL_STEP_PX
from stereofine.preview_render import build_preview_base, render_preview_from_base
from stereofine.render import render_final_pair
from stereofine.settings import AppSettings
from stereofine.state import PairState
from tests.test_foundation import _import_gui_without_customtkinter_runtime


def linear_rgb_profile():
    """Generate a standard sRGB-primary profile with a linear tone curve."""
    lib = _library()
    class xyY(C.Structure):
        _fields_ = [('x', C.c_double), ('y', C.c_double), ('Y', C.c_double)]
    class Triple(C.Structure):
        _fields_ = [('red', xyY), ('green', xyY), ('blue', xyY)]
    lib.cmsBuildGamma.argtypes = [C.c_void_p, C.c_double]
    lib.cmsBuildGamma.restype = C.c_void_p
    lib.cmsFreeToneCurve.argtypes = [C.c_void_p]
    lib.cmsCreateRGBProfile.argtypes = [C.POINTER(xyY), C.POINTER(Triple), C.POINTER(C.c_void_p)]
    lib.cmsCreateRGBProfile.restype = C.c_void_p
    lib.cmsSaveProfileToMem.argtypes = [C.c_void_p, C.c_void_p, C.POINTER(C.c_uint32)]
    lib.cmsSaveProfileToMem.restype = C.c_int
    gamma = lib.cmsBuildGamma(None, 1.)
    curves = (C.c_void_p * 3)(gamma, gamma, gamma)
    white = xyY(.3127, .3290, 1.)
    primaries = Triple(xyY(.64, .33, 1.), xyY(.30, .60, 1.), xyY(.15, .06, 1.))
    profile = lib.cmsCreateRGBProfile(C.byref(white), C.byref(primaries), curves)
    try:
        size = C.c_uint32()
        assert lib.cmsSaveProfileToMem(profile, None, C.byref(size))
        buffer = C.create_string_buffer(size.value)
        assert lib.cmsSaveProfileToMem(profile, buffer, C.byref(size))
        return buffer.raw[:size.value]
    finally:
        lib.cmsCloseProfile(profile)
        lib.cmsFreeToneCurve(gamma)


class TiffDepthTests(unittest.TestCase):
    def test_lossless_tiff_samples_profiles_and_jpeg_choices(self):
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for dtype in (np.uint8, np.uint16):
                left = np.random.default_rng(4).integers(0, np.iinfo(dtype).max+1, (40, 80, 3), dtype=dtype)
                right = np.flip(left, axis=1).copy()
                result = save_pair_outputs(left, right, root/str(dtype), 'photo', tiff_sbs=True,
                                           icc_profile=profile, save_cross=True)
                np.testing.assert_array_equal(tifffile.imread(result.sbs_path), np.concatenate([left,right], axis=1))
                with tifffile.TiffFile(result.sbs_path) as image:
                    page = image.pages[0]
                    self.assertEqual(page.dtype, np.dtype(dtype))
                    self.assertEqual(page.tags[34675].value, profile)
                    self.assertEqual(page.compression.name, 'DEFLATE')
                with Image.open(result.cross_path) as image:
                    self.assertEqual(JpegImagePlugin.get_sampling(image), 0)
                    reference = root/'reference.jpg'
                    Image.new('RGB',(1,1)).save(reference, quality=90, subsampling=0)
                    with Image.open(reference) as expected:
                        self.assertEqual(image.quantization, expected.quantization)
                self.assertEqual(result.anaglyph_path.suffix, '.jpg')

    def test_mixed_depth_load_promotes_before_processing_and_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            a=np.arange(60, dtype=np.uint8).reshape(4,5,3)
            b=(a.astype(np.uint16)*251+17)
            tifffile.imwrite(root/'a.tif', a, photometric='rgb')
            tifffile.imwrite(root/'b.tif', b, photometric='rgb')
            pair=load_pair(root/'a.tif', root/'b.tif')
            self.assertEqual(pair.left.dtype, np.uint16)
            np.testing.assert_array_equal(pair.left, a.astype(np.uint16)*257)
            np.testing.assert_array_equal(pair.right, b)
            self.assertEqual(AppSettings.from_dict({'tiff_sbs':True}).tiff_sbs, True)
            self.assertFalse(AppSettings.from_dict({}).tiff_sbs)

    def test_profile_conversion_retains_more_than_256_levels(self):
        profile = linear_rgb_profile()
        ramp = np.arange(65536, dtype=np.uint16).reshape(256,256,1).repeat(3, axis=2)
        srgb=transform_rgb(ramp, profile)
        self.assertEqual(srgb.dtype,np.uint16)
        self.assertGreater(len(np.unique(srgb[:,:,0])), 20000)
        self.assertGreater(int(srgb[128,0,0]),int(ramp[128,0,0])+10000)
        self.assertIs(transform_rgb(ramp, profile, profile), ramp)
        with self.assertRaises(ValueError): transform_rgb(ramp, b'not an ICC profile')

    def test_sampling_covers_final_rows_and_preview_uses_master_crop_curves(self):
        ramp=np.arange(750000, dtype=np.float32).reshape(750,1000,1).repeat(3,axis=2)
        sample=_sample_rgb(ramp,500000)
        self.assertEqual(sample[0,0],0)
        self.assertEqual(sample[-1,0],749999)
        left=np.random.default_rng(4).integers(0,230,(80,120,3),dtype=np.uint8)
        right=left.copy(); right[40:]=np.clip(right[40:].astype(int)+25,0,255)
        loaded=LoadedStereoPair(left,right,Path('l'),Path('r'),'pair',120,80,120,80,120,80)
        state=PairState();state.color.enabled=True
        state.framing.aspect='1:1';state.framing.crop_zoom_index=2
        state.framing.pan_y_permille=700
        expected=deepcopy(state)
        final_a,final_b,_=render_final_pair(loaded,expected)
        base=build_preview_base(loaded,state,max_width=1000,max_height=1000)
        preview=render_preview_from_base(base,state)
        self.assertEqual(state.color.parameters,expected.color.parameters)
        self.assertEqual(state.color.basis,expected.color.basis)
        np.testing.assert_array_equal(preview.left,final_a)
        np.testing.assert_array_equal(preview.right,final_b)


class DetailAndSaveTests(unittest.TestCase):
    def app(self):
        gui=_import_gui_without_customtkinter_runtime()
        app=object.__new__(gui.StereoFineApp);app._init_native_preview()
        app.current=SimpleNamespace(state=PairState())
        from stereofine.i18n import Translator
        app.tr=Translator('en')
        app.busy_state='idle'
        return app

    def test_detail_pan_fixed_steps_preserves_entire_edit_state(self):
        app=self.app();app.detail_active=True;app._detail_center=(1000,800)
        app._native_cache=(native_key(app.current), np.zeros((1,1,3),np.uint8), None)
        app._show_detail_preview=lambda:None
        before=deepcopy(app.current.state)
        for _ in range(9):app._on_arrow('right')
        self.assertEqual(app._detail_center,(1000+9*DETAIL_STEP_PX,800))
        self.assertEqual(app.current.state,before)
        app._apply_native_preview=lambda:True
        app._end_detail_preview()
        self.assertTrue(app._handle_detail_arrow('right'))
        app.after_idle=lambda callback:callback()
        app._status_after_id=None
        app.measure_cross_active=False;app._measure_repeat_job=None
        app._on_arrow_release(SimpleNamespace(keysym='Right'))
        self.assertFalse(app._handle_detail_arrow('right'))
        self.assertEqual(detail_box((100,200,3),(400,300),None)[0],(0,0,200,100))

    def test_save_failure_retains_dirty_state_and_blocks_export(self):
        app=self.app();app._save_after_id=None
        app._state_dirty=True;app._state_dirty_can_create_sidecar=True
        app._state_save_error=None;app.current.sidecar=SimpleNamespace(status='valid')
        app._render_status=lambda:None
        gui=__import__('stereofine.gui',fromlist=['StereoFineApp'])
        with patch.object(gui,'save_browsed_state',side_effect=PermissionError('locked')):
            self.assertFalse(app._flush_state_save())
            self.assertTrue(app._state_dirty)
            self.assertTrue(app._state_dirty_can_create_sidecar)
            self.assertEqual(app._state_save_error,'locked')
        app.batch_mode=False
        with patch.object(gui.messagebox,'showerror'), patch.object(gui,'save_browsed_state',side_effect=PermissionError('locked')):
            app._start_worker=lambda *args:self.fail('Export must not read old settings')
            self.assertEqual(app.save_current_result(),'break')
