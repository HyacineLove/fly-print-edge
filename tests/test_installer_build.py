"""
Tests for the PyInstaller + Inno Setup build pipeline.

These tests validate:
  - PyInstaller spec file structure and contents
  - Build output layout (after running PyInstaller)
  - Inno Setup script validity (syntax checks)
  - Launcher VBS script correctness
"""

import importlib.util
import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC_FILE = PROJECT_ROOT / "flyprint-edge.spec"
ISS_FILE = PROJECT_ROOT / "installer.iss"
LAUNCH_VBS = PROJECT_ROOT / "launch.vbs"
DIST_EXE_DIR = PROJECT_ROOT / "dist" / "flyprint-edge"
DIST_EXE = DIST_EXE_DIR / "flyprint-edge.exe"


class PyInstallerSpecTests(unittest.TestCase):
    """Validate the PyInstaller .spec file."""

    def test_spec_file_exists(self):
        self.assertTrue(SPEC_FILE.is_file(), f"Missing spec file: {SPEC_FILE}")

    def test_spec_file_is_valid_python_and_has_required_fields(self):
        spec_text = SPEC_FILE.read_text(encoding="utf-8")
        # Must reference main.py as the entry point
        self.assertIn("main.py", spec_text, "Spec must reference main.py as entry point")
        # Must include critical hidden imports
        self.assertIn("win32com", spec_text, "Spec must include pywin32 hidden imports")
        self.assertIn("win32timezone", spec_text, "Spec must include pywin32 timezone support")
        self.assertIn("fitz", spec_text, "Spec must include pymupdf (fitz) hidden imports")
        # Must collect static/ as data
        self.assertIn("static", spec_text, "Spec must reference static/ directory")
        # Must use onedir mode (Analysis + COLLECT, not just EXE)
        self.assertIn("COLLECT(", spec_text, "Spec must use COLLECT for onedir build")
        # Must exclude tests
        self.assertIn('"tests"', spec_text, "Spec must exclude tests/")

    def test_entry_point_main_py_exists(self):
        main_py = PROJECT_ROOT / "main.py"
        self.assertTrue(main_py.is_file(), "main.py must exist as the spec entry point")


class PyInstallerBuildOutputTests(unittest.TestCase):
    """Validate the PyInstaller output directory structure."""

    @classmethod
    def setUpClass(cls):
        if not DIST_EXE.is_file():
            raise unittest.SkipTest(
                "PyInstaller output not found. Run `pyinstaller flyprint-edge.spec --clean --noconfirm` first."
            )

    def test_exe_exists(self):
        self.assertTrue(DIST_EXE.is_file(), "flyprint-edge.exe must exist in dist output")

    def test_internal_dir_exists(self):
        internal = DIST_EXE_DIR / "_internal"
        self.assertTrue(internal.is_dir(), "_internal/ directory must exist in onedir build")

    def test_static_dir_bundled(self):
        static_in_internal = DIST_EXE_DIR / "_internal" / "static"
        self.assertTrue(static_in_internal.is_dir(), "static/ must be bundled as data files")
        # Verify key subdirectories
        self.assertTrue((static_in_internal / "user" / "Index.html").is_file(),
                        "User SPA entry must be bundled")
        self.assertTrue((static_in_internal / "admin" / "html" / "index.html").is_file(),
                        "Admin SPA entry must be bundled")

    def test_config_example_bundled(self):
        config_in_internal = DIST_EXE_DIR / "_internal" / "config.example.json"
        self.assertTrue(config_in_internal.is_file(),
                        "config.example.json must be bundled as a data file")

    def test_no_unwanted_directories_leaked(self):
        """Verify that dev-only directories do not leak into the build."""
        internal = DIST_EXE_DIR / "_internal"
        unwanted = {"tests", "docs", "release"}
        for name in unwanted:
            self.assertFalse(
                (internal / name).exists(),
                f"Dev directory '{name}' should not be bundled in the build output",
            )

    def test_build_size_reasonable(self):
        """Verify the total build is under a reasonable size threshold."""
        total_bytes = sum(
            f.stat().st_size for f in DIST_EXE_DIR.rglob("*") if f.is_file()
        )
        total_mb = total_bytes / (1024 * 1024)
        # Allow up to 250 MB (131 MB typical + margin)
        self.assertLess(total_mb, 250, f"Build size {total_mb:.0f} MB exceeds 250 MB threshold")


class InnoSetupScriptTests(unittest.TestCase):
    """Validate the Inno Setup .iss script."""

    def test_iss_file_exists(self):
        self.assertTrue(ISS_FILE.is_file(), f"Missing Inno Setup script: {ISS_FILE}")

    def test_iss_has_required_sections(self):
        text = ISS_FILE.read_text(encoding="utf-8")
        required = ["[Setup]", "[Files]", "[Icons]", "[Tasks]"]
        for section in required:
            self.assertIn(section, text, f".iss must contain {section} section")

    def test_iss_references_launcher(self):
        text = ISS_FILE.read_text(encoding="utf-8")
        self.assertIn("launch.vbs", text, ".iss must reference launch.vbs for shortcuts")

    def test_iss_references_correct_exe_name(self):
        text = ISS_FILE.read_text(encoding="utf-8")
        self.assertIn("flyprint-edge.exe", text, ".iss must reference the correct exe name")

    def test_iss_has_uninstall_info(self):
        text = ISS_FILE.read_text(encoding="utf-8")
        self.assertIn("[UninstallDelete]", text, ".iss should include uninstall cleanup")

    def test_iss_has_autostart_task(self):
        text = ISS_FILE.read_text(encoding="utf-8")
        self.assertIn("autostart", text, ".iss should include auto-start task option")


class VbsLauncherTests(unittest.TestCase):
    """Validate the launch.vbs launcher script."""

    def test_vbs_file_exists(self):
        self.assertTrue(LAUNCH_VBS.is_file(), f"Missing VBS launcher: {LAUNCH_VBS}")

    def test_vbs_references_exe_path(self):
        text = LAUNCH_VBS.read_text(encoding="utf-8")
        self.assertIn("flyprint-edge.exe", text, "VBS must reference the exe filename")

    def test_vbs_has_polling_loop(self):
        text = LAUNCH_VBS.read_text(encoding="utf-8")
        self.assertIn("/api/status", text, "VBS must poll the status endpoint for readiness")

    def test_vbs_returns_nonzero_on_missing_exe(self):
        """VBS should exit with code 1 if the exe is not found."""
        text = LAUNCH_VBS.read_text(encoding="utf-8")
        self.assertIn("Quit 1", text, "VBS should exit code 1 when exe not found")


if __name__ == "__main__":
    unittest.main()
