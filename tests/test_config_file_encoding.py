import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from printer_config import PrinterConfig
from printer_windows import WindowsEnterprisePrinter


class ConfigFileEncodingTests(unittest.TestCase):
    def test_printer_config_reads_utf8_bom_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.json")
            payload = {
                "managed_printers": [],
                "settings": {"default_paper_size": "A4"},
                "cloud": {"client_id": "edge"},
            }
            with open(config_path, "w", encoding="utf-8-sig") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)

            config = PrinterConfig(config_file=config_path).config

        self.assertEqual(config["settings"]["default_paper_size"], "A4")
        self.assertEqual(config["cloud"]["client_id"], "edge")

    def test_windows_settings_loader_reads_utf8_bom_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.json")
            payload = {
                "settings": {"default_scale_mode": "fit"},
            }
            with open(config_path, "w", encoding="utf-8-sig") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)

            printer = WindowsEnterprisePrinter()
            with patch("printer_windows.os.getcwd", return_value=tmpdir), \
                 patch("printer_windows.os.path.dirname", return_value=tmpdir):
                settings = printer._load_settings()

        self.assertEqual(settings["default_scale_mode"], "fit")


if __name__ == "__main__":
    unittest.main()
