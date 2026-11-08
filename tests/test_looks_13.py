from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from stereofine.looks import ColorLUT, load_lut, read_cube, read_hald, builtin_looks
from stereofine.render import render_final_pair
from stereofine.native_preview import native_key, prepare_native_preview, prepare_detail_texture
from stereofine.state import PairState, LookState
from stereofine.sidecar import SidecarDocument
from stereofine.settings import AppSettings
from stereofine.worker import CancellationToken
from stereofine.anaglyph import make_anaglyph
from tests.test_final_corrections import loaded_pair
from types import SimpleNamespace


def identity_table(n):
    b,g,r=np.meshgrid(*([np.linspace(0,1,n,dtype=np.float32)]*3),indexing='ij')
    return np.stack([r,g,b],axis=-1)


class LookTests(unittest.TestCase):
    def test_identity_preserves_both_master_depths(self):
        lut=ColorLUT(identity_table(4))
        for dtype,maximum in ((np.uint8,256),(np.uint16,65536)):
            source=np.random.default_rng(71).integers(0,maximum,(79,83,3),dtype=dtype)
            np.testing.assert_array_equal(lut.apply(source),source)
            self.assertIs(lut.apply(source,0),source)

    def test_partial_strength_blends_before_clipping_negative_outputs(self):
        lut=ColorLUT(np.full((2,2,2,3),-.2,np.float32))
        actual=lut.apply(np.full((1,1,3),128,np.uint8),.5)
        np.testing.assert_allclose(actual,38.5,atol=1)

    def test_fast_display_and_native_precision_agree(self):
        rng=np.random.default_rng(7)
        lut=ColorLUT(rng.uniform(-.12,1.15,(9,9,9,3)).astype(np.float32))
        source=rng.integers(0,256,(37,59,3),dtype=np.uint8)
        exact=lut.apply(source.astype(np.float32)/255,.37)*255
        np.testing.assert_allclose(lut.apply(source,.37),exact,atol=1)

    def test_cube_domains_and_red_fast_channel_order(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'test.cube'
            rows='\n'.join(' '.join(map(str,r)) for r in identity_table(2).reshape(-1,3))
            p.write_text('TITLE "a # title"\nLUT_3D_SIZE 2\nDOMAIN_MIN .25 .25 .25\nDOMAIN_MAX .75 .75 .75\n'+rows)
            lut=read_cube(p)
            source=np.array([[[.25,.5,.75],[1,0,.5]]],np.float32)
            np.testing.assert_allclose(lut.apply(source),[[[0,.5,1],[1,0,.5]]],atol=1e-6)

    def test_hald_16bit_is_read_without_quantizing_to_eight_bits(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'identity.png'
            table=identity_table(4)
            rgb=np.rint(table.reshape(8,8,3)*65535).astype(np.uint16)
            ok,encoded=cv2.imencode('.png',rgb[...,::-1]);self.assertTrue(ok)
            p.write_bytes(encoded.tobytes())
            lut=read_hald(p)
            samples=np.array([[[123,11777,50119],[64001,1,9999]]],np.uint16)
            np.testing.assert_allclose(lut.apply(samples),samples,atol=1)

    def test_invalid_cube_does_not_silently_become_identity(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'bad.cube'
            for content in ('LUT_3D_SIZE 2\n0 0 0', 'LUT_1D_SIZE 2\n0 0 0\n1 1 1'):
                p.write_text(content)
                with self.assertRaises(ValueError):read_cube(p)

    def test_look_and_strength_roundtrip_with_legacy_sidecars(self):
        state=PairState();state.look=LookState(True,'',r'C:\looks\my look.cube',.42)
        document=state.to_sidecar(source={})
        restored=PairState.from_sidecar(SidecarDocument.from_dict(document.to_dict()))
        self.assertEqual(restored.look,state.look)
        legacy=document.to_dict();legacy.pop('look')
        self.assertFalse(PairState.from_sidecar(SidecarDocument.from_dict(legacy)).look.enabled)

    def test_program_defaults_retain_output_destination_and_language(self):
        settings=AppSettings(language='en',custom_output_folder='X:/stereo',
                             use_input_output_subfolder=False,look_enabled=True,look_strength=.25)
        fresh=settings.restored_defaults()
        self.assertEqual(fresh.custom_output_folder,'X:/stereo')
        self.assertFalse(fresh.use_input_output_subfolder)
        self.assertEqual(fresh.language,'en')
        self.assertFalse(fresh.look_enabled)
        self.assertEqual(fresh.look_preset_id, 'velvia50')
        self.assertEqual(fresh.look_strength,1)
        saved = AppSettings.from_dict({'look_preset_id': 'portra160nc'})
        self.assertEqual(saved.look_preset_id, 'portra160nc')

    def test_every_bundled_preset_is_loadable_and_order_is_stable(self):
        entries=builtin_looks()
        self.assertEqual([entry['id'] for entry in entries], [
            'portra160nc', 'vista200', 'provia100f', 'kodachrome64', 'velvia50', 'fp100c', 'polaroid669',
            'classic_chrome',
            'delta100', 'retro80s', 'cinema_noir', 'ortho25', 'acros_red', 'rollei_ir_400', 'barnack',
            'cyanotype',
            'classic_cinema', 'teal_orange', 'cinema', 'cinema_2', 'cinema_3', 'cinema_4', 'cinema_5',
            'cinematic_lady_bird', 'city_neon_cinema', 'old_west', 'bleachbypass_2', 'matrix',
            'foggy_night', 'nightfromday', 'bleak_future', 'false_color_infrared',
            'faded_film', 'cross_process', 'redscale', 'two_strip_color', 'era',
            'gentle_contrast', 'taiga', 'fall_colors', 'crispwarm', 'operation_yellow', 'rosegold',
            'prussian_blue', 'blue_house', 'blue_ice', 'goldengate', 'caribe', 'lia_color', 'sam_kolder',
        ])
        self.assertEqual({i: e['section'] for i, e in enumerate(entries) if 'section' in e},
                         {0: 'film', 8: 'monochrome', 16: 'cinema', 28: 'night', 32: 'retro', 37: 'mood'})
        self.assertEqual(entries[14]['name'], 'Vintage 35 mm')
        from hashlib import sha256
        from stereofine.resources import asset_path
        for entry in entries:
            with self.subTest(entry=entry['name']):
                path = asset_path('luts/' + entry['file'])
                self.assertEqual(sha256(path.read_bytes()).hexdigest(), entry['sha256'])
                load_lut(path)

    def test_preview_texture_and_export_use_same_look_before_masks(self):
        loaded=loaded_pair()
        state=PairState();state.color.enabled=False
        state.look=LookState(True,'blue_house','',.65)
        state.floating_window.left_permille=10
        expected_l,expected_r,info=render_final_pair(loaded,deepcopy(state))
        self.assertIsNone(info.output_icc_profile)
        self.assertTrue(np.all(expected_l[:,0]==0))
        session=SimpleNamespace(state=state,loaded_pair=loaded)
        key=native_key(session)
        native=prepare_native_preview(loaded,deepcopy(state),key,(320,240),CancellationToken())
        texture=prepare_detail_texture(key,native[1],native[2],state.floating_window,
                                       'Farbig',CancellationToken(),state.look)[1]
        np.testing.assert_array_equal(np.asarray(texture),make_anaglyph(expected_l,expected_r))

if __name__=='__main__':unittest.main()
