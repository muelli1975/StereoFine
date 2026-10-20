"""JPS/PNS use existing image and source contracts without layout guessing."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image, ImageOps

from stereofine.config import SUPPORTED_IMAGE_EXTENSIONS, SUPPORTED_STEREO_SINGLE_EXTENSIONS
from stereofine.gui import StereoFineApp
from stereofine.inputs import InputError, load_master_image
from stereofine.session import browse_source, save_browsed_state
from stereofine.sources import discover_pair_sources, discover_stereo_file_sources, load_source, source_from_stereo_file


class StereoImageAliasTests(unittest.TestCase):
    def pattern(self):
        y, x = np.indices((48, 96))
        return np.stack([(x*7+y)%256, (x+y*9)%256, (x*3+y*5)%256], axis=-1).astype(np.uint8)

    def test_jps_uses_identical_jpeg_pixels_and_explicit_eye_order(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            jpeg, alias = root/'reference.jpg', root/'stereo.JPS'
            Image.fromarray(self.pattern()).save(jpeg, quality=95, subsampling=0)
            alias.write_bytes(jpeg.read_bytes())
            rgb = load_master_image(jpeg)
            loaded = load_source(source_from_stereo_file(alias, root))
            self.assertEqual(loaded.kind, 'full_sbs')
            np.testing.assert_array_equal(loaded.left, rgb[:, :48])
            np.testing.assert_array_equal(loaded.right, rgb[:, 48:])
            state = browse_source(source_from_stereo_file(alias, root)).state
            self.assertFalse(state.input_transform.swap_eyes)

    def test_all_jps_exif_orientations_match_jpeg_reference(self):
        with tempfile.TemporaryDirectory() as td:
            for orientation in range(1, 9):
                with self.subTest(orientation=orientation):
                    path = Path(td)/f'view{orientation}.jps'
                    exif = Image.Exif()
                    exif[274] = orientation
                    Image.fromarray(self.pattern()).save(path, format='JPEG', exif=exif)
                    with Image.open(path) as image:
                        expected = np.asarray(ImageOps.exif_transpose(image).convert('RGB'))
                    np.testing.assert_array_equal(load_master_image(path), expected)

    def test_pns_16bit_full_sbs_keeps_native_samples(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'sixteen.PNS'
            expected = self.pattern().astype(np.uint16)*257
            ok, data = cv2.imencode('.png', cv2.cvtColor(expected, cv2.COLOR_RGB2BGR))
            self.assertTrue(ok)
            path.write_bytes(data.tobytes())
            loaded = load_source(source_from_stereo_file(path, path.parent))
            self.assertEqual(loaded.left.dtype, np.uint16)
            np.testing.assert_array_equal(loaded.left, expected[:, :48])
            np.testing.assert_array_equal(loaded.right, expected[:, 48:])

    def test_pns_suffix_pairs_are_discovered_and_keep_eye_assignment(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pixels = self.pattern()
            for suffix, half in [('l', pixels[:, :48]), ('r', pixels[:, 48:])]:
                Image.fromarray(half).save(root/f'scene_{suffix}.pns', format='PNG')
            sources = discover_pair_sources(root)
            self.assertEqual(len(sources), 1)
            pair = load_source(sources[0])
            self.assertEqual(pair.kind, 'pair')
            np.testing.assert_array_equal(pair.left, pixels[:, :48])
            np.testing.assert_array_equal(pair.right, pixels[:, 48:])

    def test_new_extensions_participate_in_collision_protection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            Image.fromarray(self.pattern()).save(root/'scene.png')
            (root/'scene.pns').write_bytes((root/'scene.png').read_bytes())
            with self.assertRaises(InputError):
                discover_stereo_file_sources(root)

    def test_pns_sidecar_preserves_explicit_eye_swap_and_user_state(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'scene.pns'
            Image.fromarray(self.pattern()).save(path, format='PNG')
            source = source_from_stereo_file(path, path.parent)
            first = browse_source(source)
            first.state.input_transform.swap_eyes = True
            first.state.manual.delta_x_px = 7
            first.state.favorite = True
            save_browsed_state(first)
            second = browse_source(source)
            self.assertTrue(second.state.input_transform.swap_eyes)
            self.assertEqual(second.state.manual.delta_x_px, 7)
            self.assertTrue(second.state.favorite)
            self.assertEqual(second.source_stamp.left.frame, 0)
            self.assertEqual(second.source_stamp.right.frame, 1)
            np.testing.assert_array_equal(second.loaded_pair.left, first.loaded_pair.left)

    def test_both_localized_dialogs_offer_every_supported_extension(self):
        for language in ('de', 'en'):
            app = SimpleNamespace(settings=SimpleNamespace(language=language))
            for function, extensions in [(StereoFineApp._image_filetypes, SUPPORTED_IMAGE_EXTENSIONS),
                                        (StereoFineApp._stereo_filetypes, SUPPORTED_STEREO_SINGLE_EXTENSIONS)]:
                with self.subTest(language=language, dialog=function.__name__):
                    globs = set(function(app)[0][1].split())
                    self.assertEqual(globs, {f'*{ext}' for ext in extensions})


if __name__ == '__main__':
    unittest.main()
