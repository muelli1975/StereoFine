"""Run actual packaged input/session checks without creating a GUI or user state."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image

from .export import save_pair_outputs
from .render import render_final_pair
from .session import browse_source, save_browsed_state
from .sources import load_source, source_from_stereo_file


def check_inputs(destination: Path, fixtures: Path) -> None:
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
            for result in exported.metadata_results:
                if result.success:
                    for output in (exported.sbs_path, exported.anaglyph_path):
                        with Image.open(output) as image:
                            assert not image.info.get('icc_profile')
                            assert image.getexif().get_ifd(0x8769).get(0xA001) == 1
            checks.append({'source': name, 'entities': list(entities), 'eye_order': True,
                           'session_render_identical': True,
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
    import sys
    assert 'pillow_heif' not in sys.modules
    destination.write_text(json.dumps({'ok': True, 'codec_isolated': True, 'checks': checks}, indent=2)+'\n', 'utf-8')
