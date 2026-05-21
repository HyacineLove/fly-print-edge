import os
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cloud_service import CloudService


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


if __name__ == "__main__":
    unittest.main()
