import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import windows_startup


class WindowsStartupTests(unittest.TestCase):
    def test_frozen_service_resolves_sibling_launcher(self):
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", r"C:\FlyPrint Edge\flyprint-edge.exe"):
            path = windows_startup.get_default_launcher_path()

        self.assertEqual(path, Path(r"C:\FlyPrint Edge\flyprint-launcher.exe"))

    def test_frozen_launcher_resolves_launcher_itself(self):
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", r"C:\FlyPrint Edge\flyprint-launcher.exe"):
            path = windows_startup.get_default_launcher_path()

        self.assertEqual(path, Path(r"C:\FlyPrint Edge\flyprint-launcher.exe"))


if __name__ == "__main__":
    unittest.main()
