import os
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging_utils
import main


class ServiceLoggingTests(unittest.TestCase):
    def test_configure_logging_skips_stream_handler_when_stderr_missing(self):
        with patch.object(sys, "stderr", None):
            resolved = logging_utils.configure_logging({"settings": {}})

        self.assertEqual(resolved["level_name"], "INFO")

    def test_run_server_disables_uvicorn_default_log_config(self):
        class DummyPrinterConfig:
            def __init__(self):
                self.config = {"network": {"bind_address": "127.0.0.1", "port": 7860}}

            def get_full_config(self):
                return self.config

        with patch("main.configure_logging", return_value={"access_log": False}), \
             patch("main.uvicorn.run") as run_mock, \
             patch("printer_config.PrinterConfig", return_value=DummyPrinterConfig()):
            main.run_server()

        self.assertTrue(run_mock.called)
        _, kwargs = run_mock.call_args
        self.assertEqual(kwargs["log_config"], None)
        self.assertEqual(kwargs["use_colors"], False)


if __name__ == "__main__":
    unittest.main()
