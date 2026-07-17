import json
import tempfile
import unittest
from pathlib import Path

from printer_config import PrinterConfig


class ConfigFileEncodingTests(unittest.TestCase):
    def test_config_repository_reads_utf8_bom_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"managed_printers": [], "settings": {}, "network": {}, "printers": {}, "cloud": {}}), encoding="utf-8-sig")
            config = PrinterConfig(str(path))
            self.assertEqual([], config.get_managed_printers())

    def test_schema_v2_migration_clears_legacy_windows_printers_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps({
                    "managed_printers": [{
                        "id": "p1",
                        "name": "Windows Queue",
                        "uri": "legacy",
                        "device_uri": "legacy",
                        "print_readiness": {"verified": True},
                    }],
                    "printers": {"discovery_mode": "static", "static_list": []},
                    "settings": {},
                    "network": {},
                    "cloud": {},
                }),
                encoding="utf-8",
            )
            config = PrinterConfig(str(path)).get_full_config()
            self.assertNotIn("printers", config)
            self.assertEqual(2, config["printer_schema_version"])
            self.assertEqual([], config["managed_printers"])
            self.assertIsNone(config["default_printer_id"])

            # Loading schema v2 again must not repeat or alter the migration.
            reloaded = PrinterConfig(str(path)).get_full_config()
            self.assertEqual(2, reloaded["printer_schema_version"])
            self.assertEqual([], reloaded["managed_printers"])

    def test_removed_external_print_engine_settings_are_not_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({
                "printer_schema_version": 2,
                "managed_printers": [],
                "default_printer_id": None,
                "settings": {"pdf_printer_path": "old", "sumatra_path": "old"},
                "network": {},
                "cloud": {},
            }), encoding="utf-8")
            config = PrinterConfig(str(path)).get_full_config()
            self.assertNotIn("pdf_printer_path", config["settings"])
            self.assertNotIn("sumatra_path", config["settings"])


if __name__ == "__main__":
    unittest.main()
