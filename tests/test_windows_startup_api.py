import os
import sys
import asyncio
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main


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


if __name__ == "__main__":
    unittest.main()
