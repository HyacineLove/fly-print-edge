import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
from file_manager import FileManager


class DummyConfig:
    def __init__(self):
        self.config = {
            "managed_printers": [],
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


class DummyPrinterManager:
    def __init__(self):
        self.config = DummyConfig()


class DummyWebSocketClient:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, message):
        self.sent_messages.append(message)
        return True


class DummyCloudService:
    def __init__(self):
        self.node_id = "node-123"
        self.websocket_client = DummyWebSocketClient()


class DummyRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class UserPreviewPrintApiTests(unittest.TestCase):
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

    def test_submit_print_clears_registered_preview_resource(self):
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

        self.file_manager.register_preview_resource("file-1", "/api/v1/files/file-1", source_path)

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
        self.assertFalse(os.path.exists(source_path))
        self.assertEqual({}, main.preview_cache)
        self.assertEqual({}, main.preview_page_cache)
        self.assertEqual({}, main.preview_page_meta)


if __name__ == "__main__":
    unittest.main()
