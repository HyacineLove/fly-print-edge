import logging
import os
import sys
import tempfile
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging_utils
import main
from logging_utils import (
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    configure_logging,
    redact_sensitive_text,
    resolve_log_settings,
)


class LoggingConfigurationTests(unittest.TestCase):
    def test_resolve_log_settings_defaults_to_info(self):
        resolved = resolve_log_settings({})
        self.assertEqual("INFO", resolved["level_name"])
        self.assertEqual(False, resolved["debug_logging"])
        self.assertEqual(False, resolved["access_log"])

    def test_resolve_log_settings_uses_config_values(self):
        resolved = resolve_log_settings(
            {"settings": {"log_level": "debug", "debug_logging": True}}
        )
        self.assertEqual("DEBUG", resolved["level_name"])
        self.assertEqual(True, resolved["debug_logging"])

    def test_resolve_log_settings_env_overrides_config(self):
        resolved = resolve_log_settings(
            {"settings": {"log_level": "INFO", "debug_logging": False}},
            env={
                "FLYPRINT_LOG_LEVEL": "WARNING",
                "FLYPRINT_DEBUG_LOGGING": "true",
            },
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


class ServiceLoggingTests(unittest.TestCase):
    def test_configure_logging_skips_stream_handler_when_stderr_missing(self):
        with patch.object(sys, "stderr", None):
            resolved = logging_utils.configure_logging({"settings": {}})

        self.assertEqual(resolved["level_name"], "INFO")

    def test_run_server_disables_uvicorn_default_log_config(self):
        class DummyPrinterConfig:
            def __init__(self):
                self.config = {
                    "network": {"bind_address": "127.0.0.1", "port": 7860}
                }

            def get_full_config(self):
                return self.config

        with (
            patch("main.configure_logging", return_value={"access_log": False}),
            patch("main.uvicorn.run") as run_mock,
            patch(
                "printer_config.PrinterConfig", return_value=DummyPrinterConfig()
            ),
        ):
            main.run_server()

        self.assertTrue(run_mock.called)
        _, kwargs = run_mock.call_args
        self.assertEqual(kwargs["log_config"], None)
        self.assertEqual(kwargs["use_colors"], False)


if __name__ == "__main__":
    unittest.main()
