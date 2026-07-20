import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config_service import ConfigService


class ConfigServiceTests(unittest.TestCase):
    def setUp(self):
        self.raw = {"cloud": {"base_url": "http://cloud.example.com", "credential_blob": "opaque", "node_id": "node-1", "client_secret": "legacy-secret"}, "settings": {}, "network": {"bind_address": "127.0.0.1", "port": 7860}}
        self.service = ConfigService(None)

    def test_public_config_never_exposes_credential_material(self):
        payload = self.service.build_public_config(self.raw)
        self.assertTrue(payload["cloud"]["activated"])
        self.assertNotIn("credential_blob", payload["cloud"])
        self.assertNotIn("client_secret", payload["cloud"])

    def test_merge_ignores_manual_credential_fields(self):
        merged = self.service.merge_update(self.raw, {"cloud": {"client_secret": "attacker", "base_url": "http://new.example.com"}})
        self.assertEqual(merged["cloud"]["credential_blob"], "opaque")
        self.assertNotIn("client_secret", merged["cloud"])
        self.assertEqual(merged["cloud"]["base_url"], "http://new.example.com")

    def test_cloud_health_preflight_uses_base_url_only(self):
        with patch("config_service.requests.get") as get:
            get.return_value.status_code = 200
            result = self.service.test_cloud_connection({"cloud": {"base_url": "http://cloud.example.com"}})
        self.assertTrue(result["success"])
        get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
