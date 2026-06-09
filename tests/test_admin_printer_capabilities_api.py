import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main


class DummyConfig:
    def __init__(self):
        self.default_printer_id = "printer-1"

    def get_default_printer_id(self):
        return self.default_printer_id

    def clear_default_printer_id(self):
        self.default_printer_id = None

    def set_default_printer_id(self, printer_id):
        self.default_printer_id = printer_id


class DummyDiscovery:
    def discover_local_printers(self):
        return [
            {"name": "Office Printer", "id": "printer-2", "type": "local", "ip": "-", "port": "-"}
        ]

    def discover_network_printers(self):
        return []


class DummyPrinterManager:
    def __init__(self):
        self.config = DummyConfig()
        self.discovery = DummyDiscovery()
        self._printers = [
            {"name": "Main Printer", "id": "printer-1", "ip": "127.0.0.1", "port": 631, "enabled": True}
        ]
        self.get_admin_printer_summary = MagicMock()

    def get_printers(self):
        return [dict(item) for item in self._printers]


class AdminPrinterCapabilitiesApiTests(unittest.TestCase):
    def setUp(self):
        self.printer_manager = DummyPrinterManager()

    def test_managed_printers_include_capability_summary(self):
        self.printer_manager.get_admin_printer_summary.return_value = {
            "duplex_supported": True,
            "color_supported": True,
            "capability_summary": "单双面: 支持, 彩色: 支持",
        }

        with patch.object(main, "printer_manager", self.printer_manager):
            result = asyncio.run(main.get_managed_printers())

        self.assertTrue(result["success"])
        item = result["items"][0]
        self.assertEqual(item["duplex_supported"], True)
        self.assertEqual(item["color_supported"], True)
        self.assertIn("单双面: 支持", item["capability_summary"])
        self.assertIn("彩色: 支持", item["capability_summary"])
        self.printer_manager.get_admin_printer_summary.assert_called_once_with("Main Printer")

    def test_discovered_printers_report_unknown_capabilities(self):
        self.printer_manager.get_admin_printer_summary.return_value = {
            "duplex_supported": None,
            "color_supported": None,
            "capability_summary": "单双面: 未知, 彩色: 未知",
        }

        with patch.object(main, "printer_manager", self.printer_manager):
            result = asyncio.run(main.get_discovered_printers())

        self.assertTrue(result["success"])
        item = result["items"][0]
        self.assertIsNone(item["duplex_supported"])
        self.assertIsNone(item["color_supported"])
        self.assertIn("单双面: 未知", item["capability_summary"])
        self.assertIn("彩色: 未知", item["capability_summary"])
        self.printer_manager.get_admin_printer_summary.assert_called_once_with("Office Printer")


if __name__ == "__main__":
    unittest.main()
