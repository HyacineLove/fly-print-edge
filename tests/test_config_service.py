import os
import sys
import unittest
from unittest.mock import MagicMock, patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_service import ConfigService


class ConfigServiceTests(unittest.TestCase):
    def setUp(self):
        self.raw_config = {
            "managed_printers": [],
            "default_printer_id": None,
            "cloud": {
                "base_url": "http://localhost:8012",
                "auth_url": "http://localhost:8012/auth/token",
                "client_id": "edge-default",
                "client_secret": "top-secret",
                "node_name": "edge-a",
                "location": "",
                "heartbeat_interval": 30,
                "node_id": "node-123",
            },
            "settings": {},
            "network": {"bind_address": "127.0.0.1", "port": 7860},
        }
        self.service = ConfigService(config_repo=None)

    def test_build_public_config_masks_secret(self):
        payload = self.service.build_public_config(self.raw_config)
        self.assertEqual(payload["cloud"]["client_secret"], "")
        self.assertTrue(payload["cloud"]["client_secret_configured"])
        self.assertEqual(self.raw_config["cloud"]["client_secret"], "top-secret")

    def test_build_public_config_normalizes_legacy_zero_max_upscale(self):
        raw = {
            **self.raw_config,
            "settings": {"default_max_upscale": 0},
        }
        payload = self.service.build_public_config(raw)
        self.assertEqual(payload["settings"]["default_max_upscale"], "")

    def test_build_public_config_supplies_default_copy_limits(self):
        payload = self.service.build_public_config(self.raw_config)
        self.assertEqual(payload["settings"]["copies_min"], 1)
        self.assertEqual(payload["settings"]["copies_max"], 3)

    def test_merge_update_keeps_existing_secret_when_blank(self):
        merged = self.service.merge_update(
            self.raw_config,
            {"cloud": {"client_secret": "", "base_url": "http://example.com"}},
        )
        self.assertEqual(merged["cloud"]["client_secret"], "top-secret")
        self.assertEqual(merged["cloud"]["base_url"], "http://example.com")

    def test_restart_required_fields_are_classified(self):
        changed = {
            **self.raw_config,
            "network": {"bind_address": "0.0.0.0", "port": 9000},
        }
        result = self.service.classify_changes(before=self.raw_config, after=changed)
        self.assertIn("network.bind_address", result["restart_required"])
        self.assertIn("network.port", result["restart_required"])

    def test_validate_allows_blank_default_max_upscale(self):
        changed = {
            **self.raw_config,
            "settings": {"default_max_upscale": ""},
        }
        errors = self.service.validate(changed)
        self.assertNotIn("settings.default_max_upscale must be a positive number", errors)

    def test_validate_rejects_copy_limit_range_with_max_less_than_min(self):
        changed = {
            **self.raw_config,
            "settings": {"copies_min": 4, "copies_max": 2},
        }
        errors = self.service.validate(changed)
        self.assertIn("settings.copies_max must be an integer and >= settings.copies_min", errors)

    def test_validate_rejects_copy_limit_min_less_than_one(self):
        changed = {
            **self.raw_config,
            "settings": {"copies_min": 0, "copies_max": 2},
        }
        errors = self.service.validate(changed)
        self.assertIn("settings.copies_min must be an integer >= 1", errors)

    def test_save_and_apply_reports_cloud_preflight_failure(self):
        class Repo:
            def __init__(self, config):
                self.config = config

            def get_full_config(self):
                return self.config

            def replace_full_config(self, new_config):
                self.config = new_config

        repo = Repo(self.raw_config)
        service = ConfigService(config_repo=repo)
        cloud_service = object()

        with patch.object(service, "test_cloud_connection", return_value={"success": False, "message": "auth failed"}):
            result = service.save_and_apply(
                {"cloud": {"auth_url": "http://127.0.0.1:65534/auth/token", "client_secret": ""}},
                cloud_service=cloud_service,
            )

        self.assertTrue(result["success"])
        self.assertTrue(result["saved"])
        self.assertFalse(result["cloud_reconnected"])
        self.assertIn("auth failed", result["warnings"])

    def test_test_cloud_connection_keeps_existing_secret_when_blank(self):
        class Repo:
            def __init__(self, config):
                self.config = config

            def get_full_config(self):
                return self.config

        repo = Repo(self.raw_config)
        service = ConfigService(config_repo=repo)

        auth_client = MagicMock()
        auth_client.get_access_token.return_value = "token-123"

        with patch("config_service.CloudAuthClient", return_value=auth_client) as auth_cls, \
             patch("config_service.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            result = service.test_cloud_connection({
                "cloud": {
                    "base_url": "http://localhost:8012",
                    "auth_url": "http://localhost:8012/auth/token",
                    "client_id": "edge-default",
                    "client_secret": "",
                }
            })

        self.assertTrue(result["success"])
        auth_cls.assert_called_once_with(
            auth_url="http://localhost:8012/auth/token",
            client_id="edge-default",
            client_secret="top-secret",
        )


if __name__ == "__main__":
    unittest.main()
