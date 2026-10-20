"""Real codecs, tagged eye selection and source/session identity for 1.1 imports."""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageCms, ImageOps

from stereofine.inputs import InputError, load_master_image, load_stereo_single_file
from stereofine.models import SourceStamp
from stereofine.render import render_final_pair
from stereofine.session import browse_source, save_browsed_state
from stereofine.sidecar import load_sidecar, source_matches, source_stamp_to_dict
from stereofine.sources import (source_from_stereo_file, load_source,
    discover_pair_sources, discover_stereo_file_sources)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/heif'
spec = importlib.util.spec_from_file_location('sf_heif_reader_test', ROOT/'native/heif/read_heif.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


class NewImageFormatTests(unittest.TestCase):
    def pattern(self):
        y, x = np.indices((48, 96))
        return np.stack([(x*7+y)%256, (x+y*9)%256, (x*3+y*5)%256], axis=-1).astype(np.uint8)

    def test_lossless_webp_bmp_full_sbs_and_lr_discovery(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for extension in ('webp', 'bmp'):
                with self.subTest(extension=extension):
                    folder = root/extension; folder.mkdir()
                    pixels = self.pattern()
                    options = {'lossless': True} if extension == 'webp' else {}
                    path = folder/f'packed.{extension}'
                    Image.fromarray(pixels).save(path, **options)
                    loaded = load_source(source_from_stereo_file(path, folder))
                    np.testing.assert_array_equal(loaded.left, pixels[:, :48])
                    np.testing.assert_array_equal(loaded.right, pixels[:, 48:])
                    for eye, half in [('l', pixels[:, :48]), ('r', pixels[:, 48:])]:
                        Image.fromarray(half).save(folder/f'scene_{eye}.{extension}', **options)
                    pairs = discover_pair_sources(folder)
                    self.assertEqual(len(pairs), 1)
                    np.testing.assert_array_equal(load_source(pairs[0]).right, pixels[:, 48:])

    def test_webp_orientation_profile_and_alpha_follow_explicit_import_contract(self):
        pixels = self.pattern()
        rgba = np.dstack((pixels, np.full(pixels.shape[:2], 100, np.uint8)))
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'profile.webp'
            for orientation in range(1, 9):
                exif = Image.Exif(); exif[274] = orientation
                Image.fromarray(rgba).save(path, lossless=True, exif=exif, icc_profile=profile)
                with Image.open(path) as original:
                    image = ImageOps.exif_transpose(original)
                    expected = np.asarray(ImageCms.profileToProfile(image.convert('RGB'),
                        ImageCms.ImageCmsProfile(io.BytesIO(profile)), ImageCms.createProfile('sRGB'), outputMode='RGB'))
                np.testing.assert_array_equal(load_master_image(path), expected)

    def test_animated_webp_and_broken_profile_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'animated.webp'
            image = Image.fromarray(self.pattern())
            image.save(path, save_all=True, append_images=[image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)], duration=50)
            with self.assertRaisesRegex(InputError, 'Animierte'):
                load_stereo_single_file(path)
            image.save(path, lossless=True, icc_profile=b'not an ICC profile')
            with self.assertRaises(InputError):
                load_master_image(path)

    def test_bmp_v5_embedded_profile_is_used_and_unsupported_colour_is_rejected(self):
        import struct
        buffer = io.BytesIO()
        pixels = self.pattern()
        Image.fromarray(pixels).save(buffer, format='BMP')
        basic = buffer.getvalue()
        raster = basic[54:]
        def bitmap(profile, color_space=0x4D424544):
            dib = bytearray(basic[14:54]+bytes(84))
            struct.pack_into('<I', dib, 0, 124)
            struct.pack_into('<I', dib, 56, color_space)
            struct.pack_into('<II', dib, 112, 124+len(raster), len(profile))
            header = bytearray(basic[:14])
            struct.pack_into('<I', header, 2, 14+len(dib)+len(raster)+len(profile))
            struct.pack_into('<I', header, 10, 14+len(dib))
            return bytes(header+dib)+raster+profile
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'profile.bmp'
            srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
            path.write_bytes(bitmap(srgb))
            np.testing.assert_array_equal(load_master_image(path), pixels)
            # A malformed profile must fail, rather than being silently ignored
            # by Pillow's otherwise successful BMP pixel decoder.
            for profile, color_space in [(b'not ICC', 0x4D424544), (srgb, 0x4C494E4B), (srgb, 0)]:
                path.write_bytes(bitmap(profile, color_space))
                with self.assertRaises(InputError):
                    load_master_image(path)

    def test_new_extensions_reject_duplicate_stems(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for ext in ('bmp', 'webp'):
                Image.fromarray(self.pattern()).save(root/f'scene.{ext}')
            with self.assertRaises(InputError):
                discover_stereo_file_sources(root)

    def test_reader_does_not_guess_untagged_images_or_ambiguous_groups(self):
        class Container(list):
            primary_index = 0
        def image(**info):
            return SimpleNamespace(info=info, size=(64, 64), mode='RGB')
        container = Container([image(aux={'depth': [11]}), image()])
        self.assertEqual(reader.selected_images(container), ([container[0]], []))
        container[0].info['entity_groups'] = [
            {'type': 'ster', 'entities': [10, 11], 'images': [0, 1]},
            {'type': 'ster', 'entities': [10, 12], 'images': [0, 2]}]
        container.append(image())
        with self.assertRaisesRegex(ValueError, 'more than one'):
            reader.selected_images(container)
        container[0].info['entity_groups'] = [{'type': 'ster', 'entities': [10, 11], 'images': [0, 9]}]
        with self.assertRaisesRegex(ValueError, 'readable'):
            reader.selected_images(container)

    def test_reader_rejects_hdr_non_square_pixels_and_incompatible_eye_sizes(self):
        image = SimpleNamespace(info={}, size=(64, 64), mode='RGB')
        for transfer in (16, 18):
            image.info = {'nclx_profile': {'transfer_characteristics': transfer}}
            with self.assertRaisesRegex(ValueError, 'HDR'):
                reader.describe([image], [])
        image.info = {'pixel_aspect_ratio': (2, 1)}
        with self.assertRaisesRegex(ValueError, 'non-square'):
            reader.describe([image], [])
        image.info = {}
        other = SimpleNamespace(info={}, size=(32, 64), mode='RGB')
        with self.assertRaisesRegex(ValueError, 'different dimensions'):
            reader.describe([image, other], [1, 2])

    def test_unsupported_nclx_requires_conversion_and_is_not_called_srgb(self):
        class Source:
            info = {'nclx_profile': {'color_primaries': 12, 'transfer_characteristics': 13}}
            def to_pillow(self):
                return Image.new('RGB', (8, 8))
        if importlib.util.find_spec('pillow_heif'):
            with self.assertRaisesRegex(ValueError, 'unsupported colour conversion'):
                reader.pixels(Source(), None)

    @unittest.skipUnless(importlib.util.find_spec('pillow_heif'), 'Separate HEIF development dependency required')
    def test_real_heif_groups_determine_eyes_and_reject_pair_half_misinterpretation(self):
        for name, entities, blue_left in [('stereo_pair.heic', (1, 2), False),
                                           ('entity_groups.heic', (2, 1), True)]:
            with self.subTest(name=name):
                path = FIXTURES/name
                source = source_from_stereo_file(path, path.parent)
                loaded = load_source(source)
                self.assertEqual(source.kind, 'heif')
                self.assertEqual((loaded.left_entity, loaded.right_entity), entities)
                self.assertEqual(loaded.left.shape, (64, 64, 3))
                for index, half in enumerate((loaded.left, loaded.right)):
                    blue = blue_left ^ bool(index)
                    pixel = half[32, 32]
                    self.assertGreater(pixel[2 if blue else 0], 240)
                    self.assertLess(pixel[0 if blue else 2], 10)
                with self.assertRaisesRegex(InputError, 'kein einzelnes Halbbild'):
                    load_master_image(path)

    @unittest.skipUnless(importlib.util.find_spec('pillow_heif'), 'Separate HEIF development dependency required')
    def test_real_heif_sidecar_keeps_entities_swap_manual_edits_and_native_render(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'scene.heif'
            path.write_bytes((FIXTURES/'entity_groups.heic').read_bytes())
            source = source_from_stereo_file(path, path.parent)
            first = browse_source(source)
            first.state.input_transform.swap_eyes = True
            first.state.manual.delta_x_px = 7
            first.state.favorite = True
            first.state.floating_window.left_permille = 10
            before = render_final_pair(first.loaded_pair, first.state)
            save_browsed_state(first)
            second = browse_source(source)
            self.assertTrue(second.state.favorite)
            self.assertTrue(second.state.input_transform.swap_eyes)
            self.assertEqual(second.state.manual.delta_x_px, 7)
            self.assertEqual(second.state.floating_window.left_permille, 10)
            self.assertEqual(second.source_stamp.left.entity, 2)
            self.assertEqual(second.source_stamp.right.entity, 1)
            self.assertIsNone(second.source_stamp.left.frame)
            after = render_final_pair(second.loaded_pair, second.state)
            for a, b in zip(before[:2], after[:2]):
                np.testing.assert_array_equal(a, b)
            saved = source_stamp_to_dict(first.source_stamp)
            saved['left']['entity'] = 1
            self.assertFalse(source_matches(saved, second.source_stamp))

    def test_gui_import_does_not_load_heif_codec(self):
        import subprocess, sys
        subprocess.run([sys.executable, '-c',
            "import sys, stereofine.gui; assert 'pillow_heif' not in sys.modules"], cwd=ROOT, check=True)

    @unittest.skipUnless(importlib.util.find_spec('pillow_heif'), 'Separate HEIF development dependency required')
    def test_real_untagged_heif_uses_primary_for_full_sbs_or_separate_eyes(self):
        import pillow_heif
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root/'packed.heic'
            image = Image.fromarray(self.pattern())
            pillow_heif.from_pillow(image).save(path, quality=100)
            primary = load_master_image(path)
            loaded = load_source(source_from_stereo_file(path, root))
            np.testing.assert_array_equal(loaded.left, primary[:, :48])
            np.testing.assert_array_equal(loaded.right, primary[:, 48:])
            self.assertIsNone(loaded.left_entity)
            for eye in ('l', 'r'):
                (root/f'scene_{eye}.heif').write_bytes(path.read_bytes())
            pair = load_source(discover_pair_sources(root)[0])
            np.testing.assert_array_equal(pair.left, primary)
            np.testing.assert_array_equal(pair.right, primary)


if __name__ == '__main__':
    unittest.main()
