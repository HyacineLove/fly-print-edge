import os
import sys
import asyncio
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main


class DummyConfig:
    def __init__(self):
        self.config = {
            "managed_printers": [],
            "default_printer_id": None,
            "cloud": {
                "base_url": "http://localhost:8012",
                "auth_url": "http://localhost:8012/auth/token",
                "client_id": "edge-default",
                "client_secret": "super-secret",
                "node_name": "edge-a",
                "location": "",
                "heartbeat_interval": 30,
                "node_id": "node-123",
            },
            "settings": {},
            "network": {"bind_address": "127.0.0.1", "port": 7860},
            "printers": {"discovery_mode": "auto", "static_list": []},
        }

    def get_full_config(self):
        return self.config

    def replace_full_config(self, new_config):
        self.config = new_config


class DummyPrinterManager:
    def __init__(self):
        self.config = DummyConfig()


class DummyCloudService:
    def __init__(self, connected=True, stale=False):
        self.node_id = "node-123"
        self.calls = []
        self.connected = connected
        self.stale = stale

    def reconfigure(self, new_config, preserve_node_id=True):
        self.calls.append({"config": new_config, "preserve_node_id": preserve_node_id})
        self.node_id = None if self.stale and not preserve_node_id else "node-123"
        return {"success": True, "node_id": self.node_id, "registered": True, "connected": self.connected}

    def ensure_registered(self, force_reregister=False):
        self.calls.append({"ensure_registered": force_reregister})
        self.node_id = "node-123"
        self.stale = False
        return {"success": True, "node_id": self.node_id, "registered": True, "connected": self.connected}

    def get_status(self):
        return {
            "configured": True,
            "registered": True,
            "node_id": self.node_id,
            "websocket": {"connected": self.connected},
        }

    def has_stale_node_registration(self):
        return self.stale


class DummyRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class AdminConfigApiTests(unittest.TestCase):
    def setUp(self):
        self.printer_manager = DummyPrinterManager()
        main.config_service = None

    def test_get_config_masks_secret(self):
        with patch.object(main, "printer_manager", self.printer_manager):
            result = asyncio.run(main.get_admin_config())

        self.assertTrue(result["success"])
        self.assertEqual(result["cloud"]["client_secret"], "")
        self.assertTrue(result["cloud"]["client_secret_configured"])

    def test_save_config_keeps_secret_when_blank(self):
        request = DummyRequest({
            "cloud": {
                "client_secret": "",
                "base_url": "http://example.com",
            }
        })
        dummy_cloud = DummyCloudService()
        with patch.object(main, "printer_manager", self.printer_manager), \
             patch.object(main, "cloud_service", dummy_cloud), \
             patch("main.ConfigService.test_cloud_connection", return_value={"success": True, "message": "ok"}):
            response = asyncio.run(main.save_admin_config(request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.printer_manager.config.config["cloud"]["client_secret"], "super-secret")
        self.assertEqual(self.printer_manager.config.config["cloud"]["base_url"], "http://example.com")
        self.assertEqual(dummy_cloud.calls[0]["preserve_node_id"], True)

    def test_save_config_marks_restart_required_fields(self):
        request = DummyRequest({
            "network": {"bind_address": "0.0.0.0", "port": 9000}
        })
        with patch.object(main, "printer_manager", self.printer_manager), \
             patch.object(main, "cloud_service", DummyCloudService()):
            response = asyncio.run(main.save_admin_config(request))
        payload = response.body.decode("utf-8")
        self.assertIn("network.bind_address", payload)
        self.assertIn("network.port", payload)

    def test_check_register_cloud_reuses_saved_secret_without_reregistering_existing_node(self):
        request = DummyRequest({
            "cloud": {
                "client_secret": "",
                "base_url": "http://example.com",
            }
        })
        dummy_cloud = DummyCloudService(connected=True)
        with patch.object(main, "printer_manager", self.printer_manager), \
             patch.object(main, "cloud_service", dummy_cloud), \
             patch("main.ConfigService.test_cloud_connection", return_value={"success": True, "message": "ok"}), \
             patch("main._wait_for_cloud_connected", return_value=True):
            response = asyncio.run(main.check_cloud_and_register_node(request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.printer_manager.config.config["cloud"]["client_secret"], "super-secret")
        self.assertEqual(self.printer_manager.config.config["cloud"]["base_url"], "http://example.com")
        self.assertEqual(dummy_cloud.calls[0]["preserve_node_id"], True)
        self.assertFalse(any("ensure_registered" in call for call in dummy_cloud.calls))

    def test_check_register_cloud_requires_connected_success(self):
        request = DummyRequest({
            "cloud": {
                "client_secret": "",
                "base_url": "http://example.com",
            }
        })
        dummy_cloud = DummyCloudService(connected=False)
        with patch.object(main, "printer_manager", self.printer_manager), \
             patch.object(main, "cloud_service", dummy_cloud), \
             patch("main.ConfigService.test_cloud_connection", return_value={"success": True, "message": "ok"}), \
             patch("main._wait_for_cloud_connected", return_value=False):
            response = asyncio.run(main.check_cloud_and_register_node(request))

        self.assertEqual(response.status_code, 409)

    def test_check_register_cloud_reregisters_when_local_node_is_stale(self):
        request = DummyRequest({
            "cloud": {
                "client_secret": "",
                "base_url": "http://example.com",
            }
        })
        dummy_cloud = DummyCloudService(connected=True, stale=True)
        with patch.object(main, "printer_manager", self.printer_manager), \
             patch.object(main, "cloud_service", dummy_cloud), \
             patch("main.ConfigService.test_cloud_connection", return_value={"success": True, "message": "ok"}), \
             patch("main._wait_for_cloud_connected", return_value=True):
            response = asyncio.run(main.check_cloud_and_register_node(request))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(dummy_cloud.calls[0]["preserve_node_id"])
        self.assertTrue(any("ensure_registered" in call for call in dummy_cloud.calls))

    def test_get_cloud_status_prefers_connected_message(self):
        with patch.object(main, "cloud_service", DummyCloudService(connected=True)):
            result = asyncio.run(main.get_cloud_status())

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "已连接")

    def test_get_cloud_status_uses_waiting_message_when_registered_only(self):
        with patch.object(main, "cloud_service", DummyCloudService(connected=False)):
            result = asyncio.run(main.get_cloud_status())

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "等待连接")


if __name__ == "__main__":
    unittest.main()
