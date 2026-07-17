import unittest
import logging
from logging.handlers import RotatingFileHandler
import tempfile
from pathlib import Path

from config_service import ConfigService
from logging_utils import (
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    configure_logging,
    redact_sensitive_text,
    resolve_log_settings,
)


class LoggingConfigTests(unittest.TestCase):
    def test_resolve_log_settings_defaults_to_info(self):
        resolved = resolve_log_settings({})
        self.assertEqual("INFO", resolved["level_name"])
        self.assertEqual(False, resolved["debug_logging"])
        self.assertEqual(False, resolved["access_log"])

    def test_resolve_log_settings_uses_config_values(self):
        resolved = resolve_log_settings(
            {
                "settings": {
                    "log_level": "debug",
                    "debug_logging": True,
                }
            }
        )
        self.assertEqual("DEBUG", resolved["level_name"])
        self.assertEqual(True, resolved["debug_logging"])

    def test_resolve_log_settings_env_overrides_config(self):
        resolved = resolve_log_settings(
            {"settings": {"log_level": "INFO", "debug_logging": False}},
            env={"FLYPRINT_LOG_LEVEL": "WARNING", "FLYPRINT_DEBUG_LOGGING": "true"},
        )
        self.assertEqual("DEBUG", resolved["level_name"])
        self.assertEqual(True, resolved["debug_logging"])
        self.assertEqual(True, resolved["access_log"])

    def test_resolve_log_settings_invalid_level_falls_back_to_info(self):
        resolved = resolve_log_settings(
            {"settings": {"log_level": "verbose", "debug_logging": False}}
        )
        self.assertEqual("INFO", resolved["level_name"])

    def test_configure_logging_keeps_noisy_dependencies_at_info_in_debug_mode(self):
        configure_logging({"settings": {"debug_logging": True}})
        self.assertEqual(logging.INFO, logging.getLogger("urllib3").level)
        self.assertEqual(logging.INFO, logging.getLogger("websockets").level)
        self.assertEqual(logging.INFO, logging.getLogger("asyncio").level)

    def test_file_logging_rotates_and_sensitive_values_are_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            rotating = RotatingFileHandler(
                Path(tmp) / "edge.log",
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            self.assertEqual(LOG_MAX_BYTES, rotating.maxBytes)
            self.assertEqual(LOG_BACKUP_COUNT, rotating.backupCount)
            rotating.close()
        redacted = redact_sensitive_text(
            "Authorization: Bearer abc token=one&access_token=two client_secret=three"
        )
        for secret in ("abc", "one", "two", "three"):
            self.assertNotIn(secret, redacted)


class ConfigServiceLoggingValidationTests(unittest.TestCase):
    def test_validate_rejects_invalid_log_level(self):
        service = ConfigService(config_repo=None)
        errors = service.validate(
            {
                "cloud": {"client_id": "edge"},
                "settings": {"log_level": "TRACE"},
                "network": {"bind_address": "127.0.0.1", "port": 7860},
            }
        )
        self.assertIn("settings.log_level must be DEBUG, INFO, WARNING, or ERROR", errors)


if __name__ == "__main__":
    unittest.main()
