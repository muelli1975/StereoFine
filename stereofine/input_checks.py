"""Run actual packaged input/session checks without creating a GUI or user state."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image

from .export import save_pair_outputs
from .inputs import load_full_sbs, load_master_image
from .render import render_final_pair
from .resources import start_image_bytes
from .session import browse_source, save_browsed_state
from .sources import load_source, source_from_stereo_file


def check_inputs(destination: Path, fixtures: Path) -> None:
    jpeg = start_image_bytes()
    start_image = load_full_sbs(Path('stereofine.jpg'), jpeg_data=jpeg)
    branding = {'sha256': hashlib.sha256(jpeg).hexdigest(),
                'eye_size': [start_image.source_width, start_image.source_height]}
    del jpeg, start_image
    checks = []
    with tempfile.TemporaryDirectory(prefix='sf-package-input-check-') as td:
        root = Path(td)
        for name, blue_left, entities in [('stereo_pair.heic', False, (1, 2)),
                                          ('entity_groups.heic', True, (2, 1))]:
            path = root/name
            path.write_bytes((fixtures/name).read_bytes())
            source = source_from_stereo_file(path, root)
            first = browse_source(source)
            assert (first.source_stamp.left.entity, first.source_stamp.right.entity) == entities
            for index, image in enumerate((first.loaded_pair.left, first.loaded_pair.right)):
                assert image.shape == (64, 64, 3)
                blue = blue_left ^ bool(index)
                assert image[32, 32, 2 if blue else 0] > 240
                assert image[32, 32, 0 if blue else 2] < 10
            first.state.favorite = True
            first.state.input_transform.swap_eyes = True
            first.state.manual.delta_x_px = 7
            before = render_final_pair(first.loaded_pair, first.state)
            save_browsed_state(first)
            second = browse_source(source)
            assert second.state.favorite and second.state.input_transform.swap_eyes
            assert second.state.manual.delta_x_px == 7
            after = render_final_pair(second.loaded_pair, second.state)
            assert all(np.array_equal(a, b) for a, b in zip(before[:2], after[:2]))
            exported = save_pair_outputs(after[0], after[1], root/'output', source.base_name,
                                         metadata_source=path)
            assert exported.sbs_path.is_file() and exported.anaglyph_path.is_file()
            named = save_pair_outputs(after[0], after[1], root/'named-output', source.base_name,
                                      filename_deviation_permille=57.1)
            assert named.sbs_path.name == source.base_name+'_057_sbs.jpg'
            assert named.anaglyph_path.name == source.base_name+'_057_anaglyph.jpg'
            # Compare decoded pixels because only the normal export above
            # receives the original HEIF metadata.
            for plain, suffix in [(exported.sbs_path, named.sbs_path),
                                  (exported.anaglyph_path, named.anaglyph_path)]:
                with Image.open(plain) as a, Image.open(suffix) as b:
                    assert np.array_equal(np.asarray(a), np.asarray(b))
            for result in exported.metadata_results:
                if result.success:
                    for output in (exported.sbs_path, exported.anaglyph_path):
                        with Image.open(output) as image:
                            assert not image.info.get('icc_profile')
                            assert image.getexif().get_ifd(0x8769).get(0xA001) == 1
            checks.append({'source': name, 'entities': list(entities), 'eye_order': True,
                           'session_render_identical': True,
                           'deviation_filename_and_pixels': True,
                           'metadata_success': all(r.success for r in exported.metadata_results)})
        y, x = np.indices((48, 96))
        rgb = np.stack([(x*7+y)%256, (x+y*9)%256, (x*3+y*5)%256], axis=-1).astype(np.uint8)
        for ext in ('webp', 'bmp'):
            path = root/('pattern_'+ext+'.'+ext)
            Image.fromarray(rgb).save(path, **({'lossless': True} if ext == 'webp' else {}))
            loaded = load_source(source_from_stereo_file(path, root))
            assert np.array_equal(loaded.left, rgb[:, :48])
            assert np.array_equal(loaded.right, rgb[:, 48:])
            checks.append({'source': path.name, 'native_pixels_identical': True,
                           'rgb_sha256': hashlib.sha256(rgb.tobytes()).hexdigest()})
        if (fixtures/'spatial_photo.heic').is_file():
            path = fixtures/'spatial_photo.heic'
            loaded = load_source(source_from_stereo_file(path, fixtures))
            assert loaded.left.shape == loaded.right.shape == (2560, 2560, 3)
            assert (loaded.left_entity, loaded.right_entity) == (26, 52)
            hashes = [hashlib.sha256(x.tobytes()).hexdigest() for x in (loaded.left, loaded.right)]
            assert hashes[0] != hashes[1]
            checks.append({'source': path.name, 'entity_order': [26, 52],
                           'native_shape': [2560, 2560, 3], 'pixel_sha256': hashes})
        if (fixtures/'arrow.heic').is_file():
            image = load_master_image(fixtures/'arrow.heic')
            assert image.shape == (4032, 3024, 3)
            checks.append({'source': 'arrow.heic', 'oriented_shape': list(image.shape),
                           'pixel_sha256': hashlib.sha256(image.tobytes()).hexdigest()})
        # Exercise the frozen writer and the bundled native colour library.
        import tifffile
        from PIL import ImageCms, JpegImagePlugin
        from .color_profiles import transform_rgb
        profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        for dtype in (np.uint8,np.uint16):
            maximum=np.iinfo(dtype).max
            master=np.linspace(0,maximum,6000,dtype=dtype).reshape(40,50,3)
            converted=transform_rgb(master,profile)
            assert converted.dtype==dtype
            if dtype==np.uint16:
                assert len(np.unique(converted))>256
            result=save_pair_outputs(master,master,root/'native-output',np.dtype(dtype).name,
                                     tiff_sbs=True,icc_profile=profile,save_cross=True)
            np.testing.assert_array_equal(tifffile.imread(result.sbs_path),
                                          np.concatenate([master,master],axis=1))
            with tifffile.TiffFile(result.sbs_path) as image:
                assert image.pages[0].tags[34675].value==profile
            with Image.open(result.cross_path) as image:
                assert JpegImagePlugin.get_sampling(image)==0
            checks.append(dict(native_tiff=True,bits=np.dtype(dtype).itemsize*8,
                               icc_profile=True,native_cms=True,cross_jpeg=True))
    import sys
    assert 'pillow_heif' not in sys.modules
    destination.write_text(json.dumps({'ok': True, 'codec_isolated': True, 'start_image': branding,
                                       'checks': checks}, indent=2)+'\n', 'utf-8')

