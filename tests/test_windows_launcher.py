import os
import sys
import unittest
from pathlib import Path


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher


class LauncherHelpersTests(unittest.TestCase):
    def test_user_page_command_uses_edge_kiosk_mode(self):
        command = launcher.build_edge_command(
            edge_exe=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            url="http://127.0.0.1:7860",
            mode="user",
            profile_dir=Path(r"C:\FlyPrint\profiles\user"),
        )

        joined = " ".join(command)
        self.assertEqual(command[0], r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
        self.assertIn("--kiosk", joined)
        self.assertIn("--edge-kiosk-type=fullscreen", joined)
        self.assertIn("http://127.0.0.1:7860", joined)
        self.assertNotIn("/admin", joined)

    def test_admin_page_command_uses_normal_new_window(self):
        command = launcher.build_edge_command(
            edge_exe=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            url="http://127.0.0.1:7860/admin",
            mode="admin",
            profile_dir=Path(r"C:\FlyPrint\profiles\admin"),
        )

        joined = " ".join(command)
        self.assertIn("--new-window", joined)
        self.assertIn("http://127.0.0.1:7860/admin", joined)
        self.assertNotIn("--kiosk", joined)
        self.assertNotIn("--edge-kiosk-type=fullscreen", joined)

    def test_startup_command_points_to_launcher(self):
        command = launcher.build_startup_command(Path(r"C:\FlyPrint Edge\flyprint-launcher.exe"))
        self.assertEqual(command, r'"C:\FlyPrint Edge\flyprint-launcher.exe"')

    def test_control_command_defaults_to_open_user(self):
        self.assertEqual(launcher.normalize_launcher_action(None), launcher.ACTION_OPEN_USER)
        self.assertEqual(launcher.normalize_launcher_action(""), launcher.ACTION_OPEN_USER)
        self.assertEqual(launcher.normalize_launcher_action("--open-admin"), launcher.ACTION_OPEN_ADMIN)


if __name__ == "__main__":
    unittest.main()
