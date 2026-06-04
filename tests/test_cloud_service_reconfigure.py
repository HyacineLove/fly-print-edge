import os
import sys
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cloud_service import CloudService, PrinterStatusReporter


class CloudServiceReconfigureTests(unittest.TestCase):
    def test_reconfigure_preserves_existing_node_id(self):
        service = CloudService(
            {
                "base_url": "http://old",
                "auth_url": "http://old/auth",
                "client_id": "edge",
                "client_secret": "secret",
                "node_id": "node-123",
            }
        )
        with patch.object(service, "stop", return_value=None), \
             patch.object(service, "_initialize_components", return_value={"success": True}), \
             patch.object(service, "start", return_value={"success": True, "node_id": "node-123", "registered": True, "connected": False}):
            result = service.reconfigure(
                {
                    "base_url": "http://new",
                    "auth_url": "http://new/auth",
                    "client_id": "edge",
                    "client_secret": "secret",
                },
                preserve_node_id=True,
            )

        self.assertTrue(result["success"])
        self.assertEqual(service.node_id, "node-123")
        self.assertEqual(service.config["node_id"], "node-123")

    def test_reconfigure_starts_even_without_node_registration(self):
        service = CloudService(
            {
                "base_url": "http://old",
                "auth_url": "http://old/auth",
                "client_id": "edge",
                "client_secret": "secret",
            }
        )
        with patch.object(service, "stop", return_value=None), \
             patch.object(service, "_initialize_components", return_value={"success": True}), \
             patch.object(service, "start", return_value={"success": True, "registered": False, "connected": False}) as mocked_start:
            result = service.reconfigure(
                {
                    "base_url": "http://new",
                    "auth_url": "http://new/auth",
                    "client_id": "edge",
                    "client_secret": "secret",
                },
                preserve_node_id=True,
            )

        self.assertTrue(result["success"])
        mocked_start.assert_called_once()

    def test_ensure_registered_registers_when_node_id_missing(self):
        service = CloudService(
            {
                "base_url": "http://old",
                "auth_url": "http://old/auth",
                "client_id": "edge",
                "client_secret": "secret",
            }
        )
        with patch.object(service, "_initialize_components", return_value={"success": True}), \
             patch.object(service, "_register_node", return_value={"success": True, "node_id": "node-123"}) as mocked_register, \
             patch.object(service, "start", return_value={"success": True, "registered": True, "connected": False}):
            result = service.ensure_registered()

        self.assertTrue(result["success"])
        mocked_register.assert_called_once()

    def test_mark_remote_node_missing_clears_stale_registration(self):
        printer_config = Mock()
        printer_config.config = {
            "cloud": {"node_id": "node-123"},
            "managed_printers": [],
        }
        printer_manager = Mock()
        printer_manager.config = printer_config

        service = CloudService(
            {
                "base_url": "http://old",
                "auth_url": "http://old/auth",
                "client_id": "edge",
                "client_secret": "secret",
                "node_id": "node-123",
            },
            printer_manager=printer_manager,
        )
        service.api_client = Mock()
        service.api_client.node_id = "node-123"
        service.print_job_handler = Mock()
        service.print_job_handler.node_id = "node-123"
        heartbeat_service = Mock()
        status_reporter = Mock()
        websocket_client = Mock()
        websocket_client.running = True
        websocket_client.connected = True
        service.heartbeat_service = heartbeat_service
        service.status_reporter = status_reporter
        service.websocket_client = websocket_client

        service._mark_remote_node_missing("websocket handshake returned 404")

        self.assertTrue(service.has_stale_node_registration())
        self.assertIsNone(service.node_id)
        self.assertFalse(service.registered)
        self.assertNotIn("node_id", service.config)
        self.assertNotIn("node_id", printer_config.config["cloud"])
        self.assertIsNone(service.api_client.node_id)
        self.assertIsNone(service.print_job_handler.node_id)
        heartbeat_service.stop.assert_called_once()
        status_reporter.stop.assert_called_once()
        self.assertFalse(websocket_client.running)
        self.assertFalse(websocket_client.connected)


class PrinterStatusReporterStatusMappingTests(unittest.TestCase):
    def make_reporter(self):
        return PrinterStatusReporter(
            websocket_client=None,
            printer_manager=None,
            node_id="node-1",
            api_client=None,
        )

    def test_convert_status_normalizes_english_case_and_whitespace(self):
        reporter = self.make_reporter()

        self.assertEqual("ready", reporter._convert_status_to_cloud_format(" idle "))
        self.assertEqual("printing", reporter._convert_status_to_cloud_format("PROCESSING"))
        self.assertEqual("error", reporter._convert_status_to_cloud_format("Paused"))
        self.assertEqual("offline", reporter._convert_status_to_cloud_format("OFFLINE"))

    def test_convert_status_maps_chinese_printer_states(self):
        reporter = self.make_reporter()

        self.assertEqual("ready", reporter._convert_status_to_cloud_format("准备就绪"))
        self.assertEqual("printing", reporter._convert_status_to_cloud_format("正在打印"))
        self.assertEqual("offline", reporter._convert_status_to_cloud_format("服务器未知"))
        self.assertEqual("error", reporter._convert_status_to_cloud_format("缺纸"))
        self.assertEqual("error", reporter._convert_status_to_cloud_format("被阻止"))

    def test_convert_status_defaults_unknown_to_offline(self):
        reporter = self.make_reporter()

        self.assertEqual("offline", reporter._convert_status_to_cloud_format(None))
        self.assertEqual("offline", reporter._convert_status_to_cloud_format(""))
        self.assertEqual("offline", reporter._convert_status_to_cloud_format("unexpected"))


if __name__ == "__main__":
    unittest.main()
