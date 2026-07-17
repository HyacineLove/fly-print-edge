"""
Tests for the PyInstaller + Inno Setup build pipeline.

These tests validate:
  - PyInstaller spec file structure and contents
  - Build output layout (after running PyInstaller)
  - Inno Setup script validity (syntax checks)
  - Launcher packaging rules for the rewritten Windows shell
"""

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC_FILE = PROJECT_ROOT / "flyprint-edge.spec"
ISS_FILE = PROJECT_ROOT / "installer.iss"
DIST_EXE_DIR = PROJECT_ROOT / "dist" / "flyprint-edge"
DIST_SERVICE_EXE = DIST_EXE_DIR / "flyprint-edge.exe"
DIST_LAUNCHER_EXE = DIST_EXE_DIR / "flyprint-launcher.exe"


class PyInstallerSpecTests(unittest.TestCase):
    def test_spec_file_exists(self):
        self.assertTrue(SPEC_FILE.is_file(), f"Missing spec file: {SPEC_FILE}")

    def test_spec_file_is_valid_python_and_has_required_fields(self):
        spec_text = SPEC_FILE.read_text(encoding="utf-8")
        self.assertIn("service_main.py", spec_text)
        self.assertIn("launcher.py", spec_text)
        self.assertIn('name="flyprint-edge"', spec_text)
        self.assertIn('name="flyprint-launcher"', spec_text)
        self.assertIn("zeroconf", spec_text)
        self.assertNotIn("win32com.client", spec_text)
        self.assertNotIn("win32print", spec_text)
        self.assertNotIn("win32ui", spec_text)
        self.assertNotIn("mfc140u", spec_text)
        self.assertIn("fitz", spec_text)
        self.assertIn("static", spec_text)
        self.assertIn("ipp-printing-architecture.md", spec_text)
        self.assertIn("ipp-printing-operations.md", spec_text)
        self.assertIn("COLLECT(", spec_text)
        self.assertIn('"tests"', spec_text)
        self.assertNotIn("launch.vbs", spec_text)

    def test_entry_points_exist(self):
        self.assertTrue((PROJECT_ROOT / "service_main.py").is_file())
        self.assertTrue((PROJECT_ROOT / "launcher.py").is_file())


class PyInstallerBuildOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DIST_SERVICE_EXE.is_file():
            raise unittest.SkipTest(
                "PyInstaller output not found. Run `pyinstaller flyprint-edge.spec --clean --noconfirm` first."
            )

    def test_service_exe_exists(self):
        self.assertTrue(DIST_SERVICE_EXE.is_file())

    def test_launcher_exe_exists(self):
        self.assertTrue(DIST_LAUNCHER_EXE.is_file())

    def test_internal_dir_exists(self):
        internal = DIST_EXE_DIR / "_internal"
        self.assertTrue(internal.is_dir())

    def test_static_dir_bundled(self):
        static_in_internal = DIST_EXE_DIR / "_internal" / "static"
        self.assertTrue(static_in_internal.is_dir())
        self.assertTrue((static_in_internal / "user" / "Index.html").is_file())
        self.assertTrue((static_in_internal / "admin" / "html" / "index.html").is_file())

    def test_config_example_bundled(self):
        config_in_internal = DIST_EXE_DIR / "_internal" / "config.example.json"
        self.assertTrue(config_in_internal.is_file())


class InnoSetupScriptTests(unittest.TestCase):
    def test_iss_file_exists(self):
        self.assertTrue(ISS_FILE.is_file(), f"Missing Inno Setup script: {ISS_FILE}")

    def test_iss_has_required_sections(self):
        text = ISS_FILE.read_text(encoding="utf-8")
        for section in ["[Setup]", "[Files]", "[Icons]", "[Tasks]", "[Registry]"]:
            self.assertIn(section, text)

    def test_iss_references_rewritten_launcher(self):
        text = ISS_FILE.read_text(encoding="utf-8")
        self.assertIn("flyprint-launcher.exe", text)
        self.assertNotIn("launch.vbs", text)
        self.assertNotIn("start-edge.bat", text)

    def test_iss_uses_single_desktop_shortcut(self):
        text = ISS_FILE.read_text(encoding="utf-8")
        self.assertIn('Name: "{userdesktop}\\{#MyAppName}"', text)
        self.assertNotIn("desktopicon_admin", text)
        self.assertNotIn("{#MyAppName} Admin", text)

    def test_iss_has_autostart_task(self):
        text = ISS_FILE.read_text(encoding="utf-8")
        self.assertIn("autostart", text)
        self.assertIn("flyprint-launcher.exe", text)

    def test_uninstaller_stops_runtime_before_deleting_files(self):
        text = ISS_FILE.read_text(encoding="utf-8")
        self.assertIn("[UninstallRun]", text)
        self.assertIn('Parameters: "--exit"', text)
        self.assertIn('RunOnceId: "StopFlyPrintEdge"', text)
        self.assertIn("CloseApplications=yes", text)
        self.assertIn("RestartApplications=no", text)


if __name__ == "__main__":
    unittest.main()
