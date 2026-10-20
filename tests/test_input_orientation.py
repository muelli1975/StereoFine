"""End-to-end TIFF regressions for 1.1; these fail on the 1.0 loader.

The fixture writes the stored samples directly, so neither Pillow nor OpenCV can
silently rotate them while creating the test input. No customer images needed.
"""
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from stereofine.inputs import load_master_image


LAYOUTS = {
    1: [[0, 1, 2], [3, 4, 5]],
    2: [[2, 1, 0], [5, 4, 3]],
    3: [[5, 4, 3], [2, 1, 0]],
    4: [[3, 4, 5], [0, 1, 2]],
    5: [[0, 3], [1, 4], [2, 5]],
    6: [[3, 0], [4, 1], [5, 2]],
    7: [[5, 2], [4, 1], [3, 0]],
    8: [[2, 5], [1, 4], [0, 3]],
}


def _tag_orientation_after_encoding(path: Path, orientation: int) -> None:
    """Replace the first classic-TIFF IFD without rewriting stored samples."""
    data = bytearray(path.read_bytes())
    endian = "<" if data[:2] == b"II" else ">"
    assert struct.unpack_from(endian + "H", data, 2)[0] == 42
    offset = struct.unpack_from(endian + "I", data, 4)[0]
    count = struct.unpack_from(endian + "H", data, offset)[0]
    entries = {}
    for index in range(count):
        entry = data[offset + 2 + 12 * index:offset + 14 + 12 * index]
        tag = struct.unpack_from(endian + "H", entry)[0]
        entries[tag] = entry
    entries[274] = struct.pack(endian + "HHI", 274, 3, 1) + struct.pack(endian + "H", orientation) + b"\0\0"
    struct.pack_into(endian + "I", data, 4, len(data))
    data += struct.pack(endian + "H", len(entries))
    data += b"".join(bytes(entries[tag]) for tag in sorted(entries))
    data += struct.pack(endian + "I", 0)
    path.write_bytes(data)


def _write_rgb_tiff(path: Path, pixels: np.ndarray, orientation: int) -> None:
    height, width, _ = pixels.shape
    bits = pixels.dtype.itemsize * 8
    entry_count = 11
    bits_offset = 8 + 2 + 12 * entry_count + 4
    data_offset = bits_offset + 6
    samples = pixels.astype(f"<u{pixels.dtype.itemsize}").tobytes()
    entries = [
        (256, 4, 1, width),
        (257, 4, 1, height),
        (258, 3, 3, bits_offset),
        (259, 3, 1, 1),
        (262, 3, 1, 2),
        (273, 4, 1, data_offset),
        (274, 3, 1, orientation),
        (277, 3, 1, 3),
        (278, 4, 1, height),
        (279, 4, 1, len(samples)),
        (284, 3, 1, 1),
    ]
    directory = b"".join(struct.pack("<HHII", *entry) for entry in entries)
    path.write_bytes(
        struct.pack("<2sHIH", b"II", 42, 8, entry_count)
        + directory + struct.pack("<I3H", 0, bits, bits, bits) + samples
    )


class TiffOrientationTests(unittest.TestCase):
    def test_all_tiff_orientations_preserve_rgb_and_bit_depth(self):
        # Explicit coordinate maps for an asymmetric stored 2x3 image.
        # Letter order follows TIFF's documented eight orientation layouts.
        with tempfile.TemporaryDirectory() as directory:
            for dtype in (np.uint8, np.uint16):
                colors = np.array([
                    [1, 2, 3], [31, 42, 53], [61, 72, 83],
                    [91, 102, 113], [121, 132, 143], [151, 162, 173],
                ], dtype=dtype)
                if dtype == np.uint16:
                    colors = colors * 257 + 17
                for orientation, layout in LAYOUTS.items():
                    with self.subTest(dtype=str(dtype), orientation=orientation):
                        path = Path(directory) / "fixture.tif"
                        _write_rgb_tiff(path, colors.reshape(2, 3, 3), orientation)
                        actual = load_master_image(path)
                        expected = colors[np.array(layout)]
                        self.assertEqual(actual.dtype, expected.dtype)
                        np.testing.assert_array_equal(actual, expected)

    def test_tiff_orientation_across_compressions_channels_and_depths(self):
        with tempfile.TemporaryDirectory() as directory:
            for dtype in (np.uint8, np.uint16):
                # Exercise the decoder's grayscale, RGB and RGBA paths.
                for channels in (1, 3, 4):
                    samples = np.arange(6 * channels, dtype=dtype).reshape(2, 3, channels) * 7 + 3
                    if dtype == np.uint16:
                        samples = samples * 257 + 19
                    if channels == 1:
                        encoded_samples = samples[..., 0]
                        rgb = np.repeat(samples, 3, axis=2)
                    else:
                        encoded_samples = cv2.cvtColor(samples, cv2.COLOR_RGB2BGR if channels == 3 else cv2.COLOR_RGBA2BGRA)
                        rgb = samples[..., :3]
                    for compression in (1, 5, 8, 32773):
                        for orientation, layout in LAYOUTS.items():
                            with self.subTest(dtype=str(dtype), channels=channels, compression=compression, orientation=orientation):
                                path = Path(directory) / "compressed.tif"
                                self.assertTrue(cv2.imwrite(str(path), encoded_samples, [cv2.IMWRITE_TIFF_COMPRESSION, compression]))
                                _tag_orientation_after_encoding(path, orientation)
                                actual = load_master_image(path)
                                np.testing.assert_array_equal(actual, rgb.reshape(6, 3)[np.array(layout)])

    def test_tiff_format_is_detected_even_with_another_supported_extension(self):
        samples = np.arange(18, dtype=np.uint8).reshape(2, 3, 3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tiff_named_as_png.png"
            _write_rgb_tiff(path, samples, 6)
            np.testing.assert_array_equal(load_master_image(path), samples.reshape(6, 3)[np.array(LAYOUTS[6])])

    def test_legacy_tiff_sidecar_keeps_edits_but_invalidates_calculated_caches(self):
        from stereofine.models import FileStamp, SourceStamp
        from stereofine.processing import _state_from_sidecar
        from stereofine.session import browse_source
        from stereofine.sidecar import SidecarDocument, SidecarStatus, load_sidecar, save_sidecar, source_stamp_to_dict
        from stereofine.sources import source_from_pair

        samples = np.arange(18, dtype=np.uint8).reshape(2, 3, 3)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / "eye_l.tif", root / "eye_r.tif"]
            for path in paths:
                _write_rgb_tiff(path, samples, 6)
            old = SourceStamp(kind="pair", **{
                side: FileStamp.from_path(path, relative_to=root, width=3, height=2)
                for side, path in zip(("left", "right"), paths)
            })
            current = SourceStamp(kind="pair", **{
                side: FileStamp.from_path(path, relative_to=root, width=2, height=3)
                for side, path in zip(("left", "right"), paths)
            })
            doc = SidecarDocument(source=source_stamp_to_dict(old), favorite=True)
            doc.pipeline.pop("input")
            doc.manual = {"delta_x_px": 12, "delta_y_px": -3}
            doc.floating_window = {"left_permille": 4}
            doc.input_state = {"swap_eyes": True}
            doc.alignment = {"valid": True, "correction": {"rotation_deg": 10}}
            doc.disparity = {"valid": True, "stale": False}
            doc.framing = {"auto_near_offset_x_px": 20}
            source = source_from_pair(*paths, root)
            sidecar = source.sidecar_path
            save_sidecar(sidecar, doc)
            result = load_sidecar(sidecar, current)
            self.assertEqual(result.status, SidecarStatus.VALID)
            self.assertIn("input", result.pipeline_mismatches)
            self.assertFalse(result.alignment_cache_valid)
            self.assertFalse(result.disparity_cache_valid)
            self.assertFalse(result.color_cache_valid)
            state = _state_from_sidecar(result)
            self.assertTrue(state.favorite)
            self.assertTrue(state.input_transform.swap_eyes)
            self.assertEqual(state.manual.delta_x_px, 12)
            self.assertEqual(state.manual.delta_y_px, -3)
            self.assertEqual(state.floating_window.left_permille, 4)
            browsed = browse_source(source)
            self.assertFalse(browsed.state.alignment.valid)
            self.assertFalse(browsed.state.disparity.valid)
            self.assertIsNone(browsed.state.alignment.correction)
            self.assertIsNone(browsed.state.framing.auto_near_offset_x_px)
            self.assertEqual(browsed.state.effective_offset_x_px, 12)
            self.assertTrue(browsed.state.favorite)

            # An actual changed file must remain stale, even with the old
            # decoder version and otherwise compatible dimensions.
            paths[1].write_bytes(b"changed")
            changed = SourceStamp(
                kind="pair", left=current.left,
                right=FileStamp.from_path(paths[1], relative_to=root, width=2, height=3),
            )
            self.assertEqual(load_sidecar(sidecar, changed).status, SidecarStatus.STALE)


if __name__ == "__main__":
    unittest.main()
