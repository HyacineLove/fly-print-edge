import os
import sys
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cloud_service import CloudService


class CloudServiceReconfigureTests(unittest.TestCase):
    def test_managed_printer_registration_sends_string_port_info(self):
        config = Mock()
        config.update_printer_id.return_value = True
        manager = Mock()
        manager.config = config
        manager.get_printer_capabilities.return_value = {
            "page_size": ["A4"],
            "color_model": ["color"],
            "duplex": ["simplex", "longedge"],
            "resolution": ["600dpi"],
            "media_type": ["Plain"],
        }
        manager.get_printer_port_info.return_value = {
            "name": "Office",
            "protocol": "ipp",
            "host": "192.168.50.2",
            "port": "631",
            "resource": "/ipp/print",
        }
        service = CloudService({"node_id": "node-1"}, printer_manager=manager)
        service.api_client = Mock()
        service.api_client.register_printers.return_value = {
            "success": True,
            "failed_printers": [],
            "registered_printers": {"Office": "cloud-printer-1"},
        }

        result = service.register_managed_printer({"name": "Office", "make_model": "HP"})

        self.assertTrue(result["success"])
        payload = service.api_client.register_printers.call_args.args[0][0]
        self.assertEqual("631", payload["port_info"])
        self.assertIsInstance(payload["port_info"], str)

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


if __name__ == "__main__":
    unittest.main()
