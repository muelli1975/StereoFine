"""Release candidates cannot silently relabel development builds."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from scripts.build_package import archive_spec, require_candidate_version
from scripts.release_checksums import ARCHIVES, write_manifest


class CandidatePackagingTests(unittest.TestCase):
    def test_version_guard_rejects_dev_and_inconsistent_windows_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'stereofine').mkdir()
            config = root/'stereofine/config.py'
            info = root/'version_info.txt'
            final = "flags=0x0,\nStringStruct('FileVersion', '1.1')\nStringStruct('ProductVersion', '1.1')"
            config.write_text("APP_VERSION = '1.1-dev'\n")
            info.write_text(final)
            with self.assertRaises(RuntimeError):
                require_candidate_version(root)
            config.write_text("APP_VERSION = '1.1'\n")
            info.write_text(final.replace('flags=0x0,', 'flags=0x2,'))
            with self.assertRaises(RuntimeError):
                require_candidate_version(root)
            info.write_text(final)
            require_candidate_version(root)

    def test_archives_cover_four_targets_and_preserve_unix_permissions(self):
        targets = [('Windows', 'AMD64'), ('Linux', 'x86_64'),
                   ('macOS', 'arm64'), ('macOS', 'x86_64')]
        names = []
        for system, machine in targets:
            name, kind = archive_spec(True, 'abcdef1234', system, machine)
            names.append(name+('.tar.gz' if kind == 'gztar' else '.zip'))
        self.assertEqual(tuple(names), ARCHIVES)
        self.assertEqual(archive_spec(False, 'abcdef1234', 'Linux', 'x86_64'),
                         ('StereoFine_1.1-dev_abcdef12_Linux_x86_64', 'zip'))
        with self.assertRaises(ValueError):
            archive_spec(True, 'abcdef1234', 'Linux', 'arm64')

    def test_manifest_requires_all_archives_and_checks_actual_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(FileNotFoundError):
                write_manifest(root)
            for name in ARCHIVES:
                data = name.encode()
                (root/name).write_bytes(data)
                (root/(name+'.sha256')).write_text(hashlib.sha256(data).hexdigest()+'  '+name+'\n')
            target = write_manifest(root)
            self.assertEqual(len(target.read_text().splitlines()), 4)
            (root/ARCHIVES[0]).write_bytes(b'changed')
            with self.assertRaises(RuntimeError):
                write_manifest(root)


if __name__ == '__main__':
    unittest.main()
