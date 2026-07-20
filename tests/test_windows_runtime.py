import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher
import main
import windows_startup


class WindowsStartupTests(unittest.TestCase):
    def test_frozen_service_resolves_sibling_launcher(self):
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(
                sys, "executable", r"C:\FlyPrint Edge\flyprint-edge.exe"
            ),
        ):
            path = windows_startup.get_default_launcher_path()

        self.assertEqual(path, Path(r"C:\FlyPrint Edge\flyprint-launcher.exe"))

    def test_frozen_launcher_resolves_launcher_itself(self):
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(
                sys, "executable", r"C:\FlyPrint Edge\flyprint-launcher.exe"
            ),
        ):
            path = windows_startup.get_default_launcher_path()

        self.assertEqual(path, Path(r"C:\FlyPrint Edge\flyprint-launcher.exe"))


class DummyStartupRequest:
    def __init__(self, enabled):
        self._enabled = enabled

    async def json(self):
        return {"enabled": self._enabled}


class WindowsStartupApiTests(unittest.TestCase):
    def test_get_startup_state_returns_registry_status(self):
        with patch("main.get_windows_startup_enabled", return_value=True):
            result = asyncio.run(main.get_admin_startup_state())

        self.assertTrue(result["success"])
        self.assertTrue(result["enabled"])

    def test_post_startup_state_updates_registry(self):
        request = DummyStartupRequest(enabled=False)
        with patch("main.set_windows_startup_enabled") as set_enabled:
            result = asyncio.run(main.update_admin_startup_state(request))

        self.assertTrue(result["success"])
        self.assertFalse(result["enabled"])
        set_enabled.assert_called_once_with(False)


class LauncherHelpersTests(unittest.TestCase):
    def test_user_page_command_uses_edge_kiosk_mode(self):
        command = launcher.build_edge_command(
            edge_exe=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            url="http://127.0.0.1:7860",
            mode="user",
            profile_dir=Path(r"C:\FlyPrint\profiles\user"),
        )

        joined = " ".join(command)
        self.assertEqual(
            command[0],
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        )
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
        command = launcher.build_startup_command(
            Path(r"C:\FlyPrint Edge\flyprint-launcher.exe")
        )
        self.assertEqual(command, r'"C:\FlyPrint Edge\flyprint-launcher.exe"')

    def test_control_command_defaults_to_open_user(self):
        self.assertEqual(
            launcher.normalize_launcher_action(None), launcher.ACTION_OPEN_USER
        )
        self.assertEqual(
            launcher.normalize_launcher_action(""), launcher.ACTION_OPEN_USER
        )
        self.assertEqual(
            launcher.normalize_launcher_action("--open-admin"),
            launcher.ACTION_OPEN_ADMIN,
        )

    def test_runtime_profile_matches_only_flyprint_edge_processes(self):
        runtime_dir = Path(r"C:\FlyPrint Edge\runtime")
        self.assertTrue(
            launcher.command_uses_runtime_profile(
                [
                    "msedge.exe",
                    r"--user-data-dir=C:\FlyPrint Edge\runtime\user-browser-profile",
                ],
                runtime_dir,
            )
        )
        self.assertFalse(
            launcher.command_uses_runtime_profile(
                ["msedge.exe", r"--user-data-dir=C:\Users\PC\EdgeProfile"],
                runtime_dir,
            )
        )


if __name__ == "__main__":
    unittest.main()
