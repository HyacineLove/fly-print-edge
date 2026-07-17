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
        return []

    def discover_network_printers(self):
        return [{
            "name": "Office Printer",
            "type": "ipp",
            "printer_uuid": "urn:uuid:printer-2",
            "ipp_uri": "ipp://192.168.50.2:631/ipp/print",
            "compatible": True,
            "duplex_supported": None,
            "color_supported": None,
            "capability_summary": "unknown",
        }]


class DummyPrinterManager:
    def __init__(self):
        self.config = DummyConfig()
        self.discovery = DummyDiscovery()
        self._printers = [
            {
                "name": "Main Printer", "id": "printer-1", "type": "ipp",
                "printer_uuid": "urn:uuid:printer-1",
                "ipp_uri": "ipp://127.0.0.1:631/ipp/print", "enabled": True,
            }
        ]
        self.get_admin_printer_summary = MagicMock()
        self.get_printer_status_detail = MagicMock(return_value={"status_text": "idle", "uncertain": False})

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
        with patch.object(main, "printer_manager", self.printer_manager):
            result = asyncio.run(main.get_discovered_printers())
        self.assertTrue(result["success"])
        item = result["items"][0]
        self.assertEqual("ipp", item["type"])
        self.assertEqual("urn:uuid:printer-2", item["printer_uuid"])
        self.assertEqual("unknown", item["capability_summary"])
        self.printer_manager.get_admin_printer_summary.assert_not_called()
        return
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

    def test_duplicate_test_print_is_rejected_for_same_printer(self):
        main.active_printer_tests["printer-1"] = "task-1"
        main.printer_test_tasks["task-1"] = {"status": "running"}
        try:
            with patch.object(main, "printer_manager", self.printer_manager):
                response = asyncio.run(main.start_printer_test("printer-1"))
            self.assertEqual(409, response.status_code)
            self.assertIn("请勿重复提交", response.body.decode("utf-8"))
        finally:
            main.active_printer_tests.clear()
            main.printer_test_tasks.clear()


if __name__ == "__main__":
    unittest.main()
