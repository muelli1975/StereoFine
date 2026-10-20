"""End-to-end TIFF regressions for 1.1; intentionally red on the 1.0 loader.

The fixture writes the stored samples directly, so neither Pillow nor OpenCV can
silently rotate them while creating the test input. No customer images needed.
"""
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from stereofine.inputs import load_master_image


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
        layouts = {
            1: [[0, 1, 2], [3, 4, 5]],
            2: [[2, 1, 0], [5, 4, 3]],
            3: [[5, 4, 3], [2, 1, 0]],
            4: [[3, 4, 5], [0, 1, 2]],
            5: [[0, 3], [1, 4], [2, 5]],
            6: [[3, 0], [4, 1], [5, 2]],
            7: [[5, 2], [4, 1], [3, 0]],
            8: [[2, 5], [1, 4], [0, 3]],
        }
        with tempfile.TemporaryDirectory() as directory:
            for dtype in (np.uint8, np.uint16):
                colors = np.array([
                    [1, 2, 3], [31, 42, 53], [61, 72, 83],
                    [91, 102, 113], [121, 132, 143], [151, 162, 173],
                ], dtype=dtype)
                if dtype == np.uint16:
                    colors = colors * 257 + 17
                for orientation, layout in layouts.items():
                    with self.subTest(dtype=str(dtype), orientation=orientation):
                        path = Path(directory) / "fixture.tif"
                        _write_rgb_tiff(path, colors.reshape(2, 3, 3), orientation)
                        actual = load_master_image(path)
                        expected = colors[np.array(layout)]
                        self.assertEqual(actual.dtype, expected.dtype)
                        np.testing.assert_array_equal(actual, expected)


if __name__ == "__main__":
    unittest.main()
