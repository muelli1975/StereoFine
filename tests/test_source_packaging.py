from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which("git"), "Git required for canonical source packaging")
class SourcePackagingTests(unittest.TestCase):
    def test_canonical_snapshot_ignores_windows_autocrlf(self):
        path = Path(__file__).resolve().parents[1] / "scripts/package_source.py"
        spec = importlib.util.spec_from_file_location("package_source_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="sf-source-") as temp:
            root = Path(temp)
            original = b"print('canonical source')\n# second line\n"
            (root / "StereoFine.py").write_bytes(original)
            research = root/'experiments/tests/test_known_geometry.py'
            research.parent.mkdir(parents=True)
            research.write_bytes(b'# source workflow also runs research regressions\n')
            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)
            git("init", "-q")
            git("-c", "core.autocrlf=false", "add", "StereoFine.py", "experiments")
            git("-c", "user.name=Packaging test", "-c", "user.email=test@example.invalid",
                "commit", "-qm", "Source fixture")
            git("config", "core.autocrlf", "true")
            module.ROOT = root.resolve()
            commit, files = module.committed_sources()
            self.assertEqual(files["StereoFine.py"], original)
            self.assertEqual(files['experiments/tests/test_known_geometry.py'], research.read_bytes())
            self.assertEqual(commit, git("rev-parse", "HEAD").decode().strip())


if __name__ == "__main__":
    unittest.main()
