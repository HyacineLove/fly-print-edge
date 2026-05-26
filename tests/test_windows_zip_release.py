import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "release" / "windows_zip" / "build_release.py"


class WindowsZipReleaseTests(unittest.TestCase):
    def _load_module(self):
        self.assertTrue(MODULE_PATH.is_file(), f"missing build script: {MODULE_PATH}")
        spec = importlib.util.spec_from_file_location("windows_zip_build_release", MODULE_PATH)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_build_release_creates_expected_layout_and_zip(self):
        module = self._load_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            release_dir, zip_path = module.build_release(PROJECT_ROOT, output_root)

            self.assertTrue((release_dir / "app" / "main.py").is_file())
            self.assertTrue((release_dir / "app" / "requirements.txt").is_file())
            self.assertTrue((release_dir / "app" / "config.example.json").is_file())
            self.assertTrue((release_dir / "app" / "static" / "index.html").is_file())
            self.assertTrue((release_dir / "scripts" / "bootstrap.ps1").is_file())
            self.assertTrue((release_dir / "scripts" / "launch.ps1").is_file())
            self.assertTrue((release_dir / "start-edge.cmd").is_file())
            self.assertTrue((release_dir / "start-edge-debug.cmd").is_file())
            self.assertTrue((release_dir / "README-runtime.md").is_file())
            self.assertTrue((release_dir / "logs").is_dir())
            self.assertTrue((release_dir / "temp").is_dir())
            self.assertFalse((release_dir / "tests").exists())
            self.assertFalse((release_dir / "venv").exists())

            self.assertTrue(zip_path.is_file())
            with zipfile.ZipFile(zip_path) as archive:
                members = set(archive.namelist())

            prefix = f"{release_dir.name}/"
            self.assertIn(prefix + "app/main.py", members)
            self.assertIn(prefix + "app/static/index.html", members)
            self.assertIn(prefix + "scripts/bootstrap.ps1", members)
            self.assertIn(prefix + "start-edge.cmd", members)
            self.assertIn(prefix + "README-runtime.md", members)


if __name__ == "__main__":
    unittest.main()
