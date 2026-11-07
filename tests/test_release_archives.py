"""Check archive source identity, original assets and native executable headers."""
import struct
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from scripts.verify_release_packages import ASSETS, verify_archive


class ReleaseArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root/'assets').mkdir()
        self.expected = {'RELEASE_NOTES_1.3.md': b'Final notes\n', 'SOURCE_COMMIT.txt': b'test-commit\n'}
        self.public_lut = 'assets/luts/fixture.cube'
        self.expected[self.public_lut] = b'source LUT fixture'
        self.files = {'StereoFine/Source/'+name: data for name, data in self.expected.items()}
        self.files['StereoFine/_internal/'+self.public_lut] = self.expected[self.public_lut]
        for name in ASSETS:
            data = ('original '+name).encode()
            (self.root/'assets'/name).write_bytes(data)
            self.files['StereoFine/_internal/assets/'+name] = data
        self.files.update({
            'StereoFine/RELEASE_NOTES_1.3.md': b'Final notes\r\n',
            'StereoFine/tools/exiftool': b'perl',
            'StereoFine/tools/lcms/lcms2.dll': b'native',
            'StereoFine/tools/lcms/liblcms2.so': b'native',
            'StereoFine/tools/lcms/liblcms2.dylib': b'native',
            'StereoFine/tools/lib/Image/ExifTool.pm': b"$VERSION = '13.59'",
            'StereoFine/tools/heif/StereoFine-HEIF': b'helper',
        })

    def archive(self):
        target = self.root/'fixture.zip'
        with zipfile.ZipFile(target, 'w') as archive:
            for name, data in self.files.items():
                archive.writestr(name, data)
        return target

    def verify(self, platform='windows'):
        with patch('scripts.verify_release_packages.ROOT', self.root):
            return verify_archive(self.archive(), platform, self.expected)

    def windows(self, machine=0x8664):
        header = bytearray(4096)
        header[:2] = b'MZ'
        struct.pack_into('<I', header, 0x3c, 128)
        header[128:132] = b'PE\x00\x00'
        struct.pack_into('<H', header, 132, machine)
        self.files['StereoFine/StereoFine.exe'] = bytes(header)

    def test_windows_requires_x64_and_preserves_canonical_source_bytes(self):
        self.windows()
        self.assertTrue(self.verify()['passed'])
        self.files['StereoFine/Source/RELEASE_NOTES_1.3.md'] = b'Final notes\r\n'
        with self.assertRaisesRegex(RuntimeError, 'source mismatch'):
            self.verify()
        self.files['StereoFine/Source/RELEASE_NOTES_1.3.md'] = self.expected['RELEASE_NOTES_1.3.md']
        self.windows(machine=0x14c)
        with self.assertRaisesRegex(RuntimeError, 'architecture'):
            self.verify()

    def test_missing_helper_and_changed_original_asset_are_rejected(self):
        self.windows()
        helper = self.files.pop('StereoFine/tools/heif/StereoFine-HEIF')
        with self.assertRaises(RuntimeError):
            self.verify()
        self.files['StereoFine/tools/heif/StereoFine-HEIF'] = helper
        self.files['StereoFine/_internal/assets/stereofine.jpg'] = b'converted'
        with self.assertRaisesRegex(RuntimeError, 'Changed original asset'):
            self.verify()

    def test_packaged_presets_are_verified_and_private_assets_are_rejected(self):
        self.windows()
        private = 'StereoFine/_internal/private-build-assets/Autumn LUT #1.cube'
        self.files[private] = b'private LUT fixture'
        with self.assertRaisesRegex(RuntimeError, 'Unexpected private resource'):
            self.verify()
        del self.files[private]
        self.files['StereoFine/_internal/'+self.public_lut] = b'changed LUT'
        with self.assertRaisesRegex(RuntimeError, 'packaged LUT asset'):
            self.verify()

    def test_linux_and_both_mac_architectures_are_distinguished(self):
        header = bytearray(4096)
        header[:5] = b'\x7fELF\x02'
        struct.pack_into('<H', header, 18, 62)
        self.files['StereoFine/StereoFine'] = bytes(header)
        self.assertTrue(self.verify('linux')['passed'])
        del self.files['StereoFine/StereoFine']
        resources = 'StereoFine/StereoFine.app/Contents/Resources/'
        self.files[resources+self.public_lut] = self.files.pop('StereoFine/_internal/'+self.public_lut)
        for name, cpu in [('arm64', 0x100000c), ('intel', 0x1000007)]:
            self.files['StereoFine/StereoFine.app/Contents/MacOS/StereoFine'] = b'\xcf\xfa\xed\xfe'+struct.pack('<I', cpu)+b'\x00'*24
            self.assertTrue(self.verify(name)['passed'])
            with self.assertRaises(RuntimeError):
                self.verify('intel' if name == 'arm64' else 'arm64')


if __name__ == '__main__':
    unittest.main()

