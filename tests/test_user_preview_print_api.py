import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
from file_manager import FileManager
from printer_fault_state import PrinterFaultStateStore


class DummyConfig:
    def __init__(self):
        self.config = {
            "managed_printers": [
                {
                    "id": "printer-1",
                    "name": "HP",
                    "location": "http://169.254.12.234:3911",
                    "enabled": True,
                }
            ],
            "default_printer_id": "printer-1",
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
            "settings": {"copies_min": 1, "copies_max": 3},
            "network": {"bind_address": "127.0.0.1", "port": 7860},
            "printers": {"discovery_mode": "auto", "static_list": []},
        }

    def get_full_config(self):
        return self.config

    def get_default_printer_id(self):
        return self.config.get("default_printer_id")

    def set_default_printer_id(self, printer_id):
        self.config["default_printer_id"] = printer_id

    def clear_default_printer_id(self):
        self.config["default_printer_id"] = None

    def get_managed_printers(self):
        return self.config["managed_printers"]


class DummyPrinterManager:
    def __init__(self):
        self.config = DummyConfig()

    def get_printers(self):
        return self.config.get_managed_printers()

    def get_printer_capabilities(self, printer_name):
        return {"page_size": ["A4"], "color_model": ["RGB"], "duplex": ["None"]}


class DummyWebSocketClient:
    def __init__(self):
        self.sent_messages = []
        self.upload_token_requested = False

    async def send_message(self, message):
        self.sent_messages.append(message)
        return True

    def request_upload_token(self, node_id, printer_id):
        self.upload_token_requested = True
        return False


class DummyCloudService:
    def __init__(self):
        self.node_id = "node-123"
        self.websocket_client = DummyWebSocketClient()
        self.print_job_handler = None


class DummyRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class DummyBodyRequest:
    def __init__(self, payload):
        self.payload = payload

    async def body(self):
        return json.dumps(self.payload).encode("utf-8")


class UserPreviewPrintApiTests(unittest.TestCase):
    CONTENT_HASH = "a" * 64

    def setUp(self):
        self.printer_manager = DummyPrinterManager()
        self.cloud_service = DummyCloudService()
        self.session_manager = main.InteractiveSessionManager()
        self.temp_dir = tempfile.TemporaryDirectory()
        session = self.session_manager.start_session(upload_token="upload-token")
        self.session_id = session["session_id"]
        self.session_manager.accept_preview_event({
            "file_id": "file-1",
            "file_url": "https://example.com/file.pdf",
            "content_hash": self.CONTENT_HASH,
        })
        self.file_manager = FileManager(cleanup_interval=300, file_ttl=1800)

    def tearDown(self):
        self.temp_dir.cleanup()
        main.preview_cache = {}
        main.preview_page_cache = {}
        main.preview_page_meta = {}

    def test_submit_print_clamps_copies_to_configured_maximum(self):
        request = DummyRequest({
            "session_id": self.session_id,
            "file_id": "file-1",
            "options": {"copies": 99, "duplex": "simplex", "color_mode": "color"},
        })

        with patch.object(main, "printer_manager", self.printer_manager), \
             patch.object(main, "cloud_service", self.cloud_service), \
             patch.object(main, "interactive_session_manager", self.session_manager), \
             patch.object(main, "_ensure_default_printer", return_value="printer-1"), \
             patch.object(main, "get_file_manager", return_value=None):
            response = asyncio.run(main.submit_print(request))

        self.assertTrue(response["success"])
        sent = self.cloud_service.websocket_client.sent_messages[0]["data"]["options"]
        self.assertEqual(sent["copies"], 3)

    def test_submit_print_clamps_copies_to_configured_minimum(self):
        request = DummyRequest({
            "session_id": self.session_id,
            "file_id": "file-1",
            "options": {"copies": 0, "duplex": "simplex", "color_mode": "color"},
        })

        with patch.object(main, "printer_manager", self.printer_manager), \
             patch.object(main, "cloud_service", self.cloud_service), \
             patch.object(main, "interactive_session_manager", self.session_manager), \
             patch.object(main, "_ensure_default_printer", return_value="printer-1"), \
             patch.object(main, "get_file_manager", return_value=None):
            response = asyncio.run(main.submit_print(request))

        self.assertTrue(response["success"])
        sent = self.cloud_service.websocket_client.sent_messages[0]["data"]["options"]
        self.assertEqual(sent["copies"], 1)

    def test_submit_print_clears_preview_cache_but_preserves_hash_source(self):
        preview_cache = {'file-1:{"page_index": 0}': {"preview_url": "data", "timestamp": 1.0}}
        preview_page_cache = {"file-1": {0: object()}}
        preview_page_meta = {"file-1": {"page_count": 1}}
        main.preview_cache = preview_cache
        main.preview_page_cache = preview_page_cache
        main.preview_page_meta = preview_page_meta
        self.file_manager = FileManager(
            cleanup_interval=300,
            file_ttl=1800,
            preview_cache=preview_cache,
            preview_page_cache=preview_page_cache,
            preview_page_meta=preview_page_meta,
        )

        source_path = os.path.join(self.temp_dir.name, "preview.bin")
        with open(source_path, "wb") as fh:
            fh.write(b"preview")

        self.file_manager.register_preview_resource(
            "file-1",
            "/api/v1/files/file-1",
            source_path,
            content_hash=self.CONTENT_HASH,
        )

        request = DummyRequest({
            "session_id": self.session_id,
            "file_id": "file-1",
            "options": {"copies": 1, "duplex": "simplex", "color_mode": "mono"},
        })

        with patch.object(main, "printer_manager", self.printer_manager), \
             patch.object(main, "cloud_service", self.cloud_service), \
             patch.object(main, "interactive_session_manager", self.session_manager), \
             patch.object(main, "_ensure_default_printer", return_value="printer-1"), \
             patch.object(main, "get_file_manager", return_value=self.file_manager):
            response = asyncio.run(main.submit_print(request))

        self.assertTrue(response["success"])
        self.assertTrue(os.path.exists(source_path))
        self.assertEqual({}, main.preview_cache)
        self.assertEqual({}, main.preview_page_cache)
        self.assertEqual({}, main.preview_page_meta)
        self.assertEqual(source_path, self.file_manager.get_cached_path(self.CONTENT_HASH))

    def test_preview_rejects_missing_content_hash(self):
        request = DummyBodyRequest({
            "session_id": self.session_id,
            "file_id": "file-1",
            "file_url": "https://example.com/file.pdf",
            "file_name": "file.pdf",
            "file_type": "application/pdf",
            "options": {"page_index": 0},
        })

        with patch.object(main, "printer_manager", self.printer_manager), \
             patch.object(main, "interactive_session_manager", self.session_manager), \
             patch.object(main, "get_file_manager", return_value=self.file_manager):
            response = asyncio.run(main.preview(request))

        self.assertEqual(400, response.status_code)
        self.assertIn("content_hash", response.body.decode("utf-8"))

    def test_preview_reuses_cached_hash_without_download(self):
        source_path = os.path.join(self.temp_dir.name, "preview.pdf")
        with open(source_path, "wb") as fh:
            fh.write(b"%PDF-1.4\n")

        self.file_manager.register_preview_resource(
            "file-existing",
            "/api/v1/files/file-existing",
            source_path,
            content_hash=self.CONTENT_HASH,
        )
        request = DummyBodyRequest({
            "session_id": self.session_id,
            "file_id": "file-1",
            "file_url": "/api/v1/files/file-1",
            "file_name": "file.pdf",
            "file_type": "application/pdf",
            "content_hash": self.CONTENT_HASH,
            "options": {"page_index": 0},
        })

        with patch.object(main, "printer_manager", self.printer_manager), \
             patch.object(main, "interactive_session_manager", self.session_manager), \
             patch.object(main, "get_file_manager", return_value=self.file_manager), \
             patch.object(main, "_download_preview_file") as download_mock, \
             patch.object(main, "_generate_preview_image", return_value=(None, 0, 0, "render skipped")):
            response = asyncio.run(main.preview(request))

        self.assertEqual(500, response.status_code)
        download_mock.assert_not_called()
        self.assertEqual(source_path, self.file_manager.get_preview_resource("file-1")["source_path"])

    def test_printer_availability_reports_fault_from_probe_and_mapping(self):
        fault_store = PrinterFaultStateStore()
        fault_probe = type(
            "FaultProbe",
            (),
            {
                "probe": lambda self, host: type(
                    "FaultResult",
                    (),
                    {
                        "available": True,
                        "faulted": True,
                        "fault_reasons": ["media-empty-error", "media-needed-error"],
                        "printer_state": 5,
                        "printer_state_name": "stopped",
                    },
                )()
            },
        )()

        with patch.object(main, "printer_manager", self.printer_manager), \
             patch.object(main, "printer_fault_state_store", fault_store), \
             patch.object(main, "printer_fault_probe", fault_probe):
            response = asyncio.run(main.get_printer_availability())

        self.assertFalse(response["available"])
        self.assertTrue(response["faulted"])
        self.assertEqual("printer_fault", response["error_code"])
        self.assertEqual("缺纸", response["reason_label"])
        self.assertEqual("打印机缺纸，请联系管理员补纸", response["message"])
        self.assertEqual(["media-empty-error", "media-needed-error"], response["raw_reasons"])

    def test_qr_code_does_not_request_upload_token_while_default_printer_faulted(self):
        fault_store = PrinterFaultStateStore()
        fault_store.set_fault(
            printer_id="printer-1",
            printer_name="HP",
            raw_reasons=["media-empty-error"],
        )

        with patch.object(main, "printer_manager", self.printer_manager), \
             patch.object(main, "cloud_service", self.cloud_service), \
             patch.object(main, "printer_fault_state_store", fault_store), \
             patch.object(main, "printer_fault_probe", None), \
             patch.object(main, "node_id", "node-123"):
            response = asyncio.run(main.get_qr_code())

        self.assertEqual(False, response["success"])
        self.assertEqual(True, response["standby"])
        self.assertEqual("printer_fault", response["error_code"])
        self.assertEqual("打印机缺纸，请联系管理员补纸", response["message"])
        self.assertFalse(self.cloud_service.websocket_client.upload_token_requested)


if __name__ == "__main__":
    unittest.main()
